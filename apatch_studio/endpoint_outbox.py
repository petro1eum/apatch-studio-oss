"""Durable outbox for fixed-purpose Cowork connector work (RFP-019).

Nothing is delivered twice and nothing is dropped in silence. Each item is
given one identifier when it is queued and keeps it across every retry, so the
control plane's own idempotency recognises a repeat instead of applying it
again. An item the control plane refuses outright is kept and marked so a
person can see it, rather than being discarded.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from apatch_studio.endpoint_transport import TransportRejected, TransportUnavailable
from apatch_studio.projection import assert_projection_safe

OUTBOX_SCHEMA = "apatch.studio.endpoint-outbox.v1"
MAX_PENDING = 1000
MAX_ATTEMPTS = 8
MAX_PAYLOAD_BYTES = 262_144
BASE_BACKOFF_SECONDS = 5
MAX_BACKOFF_SECONDS = 3600
_DELIVERED_RETENTION = 200

_SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL UNIQUE,
    command TEXT NOT NULL,
    path TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    next_attempt_at TEXT NOT NULL,
    last_reason TEXT
);
CREATE INDEX IF NOT EXISTS outbox_status ON outbox (status, next_attempt_at);
"""


class OutboxFull(RuntimeError):
    """The queue is at its bound; the control plane has been unreachable too long."""


def _utc(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat(timespec="seconds")


class EndpointOutbox:
    """Work queued for one control plane, surviving restarts."""

    def __init__(
        self,
        state_root: str | os.PathLike[str],
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._now = now or (lambda: datetime.now(timezone.utc))
        directory = Path(state_root).expanduser().resolve()
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "endpoint-outbox.sqlite3"
        with closing(self._connect()) as connection:
            connection.executescript(_SCHEMA)
            connection.commit()
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, isolation_level=None, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        return connection

    def enqueue(
        self, command: str, path: str, payload: Mapping[str, Any], *,
        request_id: str | None = None,
    ) -> str:
        """Queue one operation, retaining the first payload for a stable identifier."""

        if not isinstance(command, str) or not 1 <= len(command) <= 64:
            raise ValueError("command must be a short name")
        if not isinstance(payload, Mapping):
            raise ValueError("payload must be a mapping")
        assert_projection_safe(payload)
        selected = request_id or ("apsreq_" + uuid.uuid4().hex)
        if re.fullmatch(r"[A-Za-z0-9_.:-]{16,128}", selected) is None:
            raise ValueError("request id must be a bounded canonical identifier")
        body = dict(payload)
        body["request_id"] = selected
        encoded = json.dumps(body, ensure_ascii=False, sort_keys=True)
        if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
            raise ValueError("payload is larger than the control plane accepts")
        stamp = _utc(self._now())
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                existing = connection.execute(
                    "SELECT command, path FROM outbox WHERE request_id=?",
                    (selected,),
                ).fetchone()
                if existing is not None:
                    if existing["command"] != command or existing["path"] != path:
                        raise ValueError("request id belongs to another queued operation")
                    connection.commit()
                    return selected
                pending = connection.execute(
                    "SELECT COUNT(*) FROM outbox WHERE status='pending'"
                ).fetchone()[0]
                if pending >= MAX_PENDING:
                    raise OutboxFull(
                        "the queue is full; the control plane is unreachable"
                    )
                connection.execute(
                    "INSERT INTO outbox (request_id, command, path, payload_json, status, "
                    "attempts, created_at, next_attempt_at, last_reason) "
                    "VALUES (?, ?, ?, ?, 'pending', 0, ?, ?, NULL)",
                    (selected, command, path, encoded, stamp, stamp),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return selected

    def retry(self, request_id: str) -> str:
        """Make one retained item due without replacing its identity or payload."""

        stamp = _utc(self._now())
        with closing(self._connect()) as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT status, attempts FROM outbox WHERE request_id=?",
                    (request_id,),
                ).fetchone()
                if row is None:
                    raise ValueError("The retained endpoint operation does not exist.")
                if row["status"] == "delivered":
                    connection.commit()
                    return "delivered"
                if row["status"] not in {"pending", "blocked"}:
                    raise ValueError("The retained endpoint operation has an invalid state.")
                attempts = 0 if row["status"] == "blocked" else int(row["attempts"])
                connection.execute(
                    "UPDATE outbox SET status='pending', attempts=?, next_attempt_at=?, "
                    "last_reason=NULL WHERE request_id=?",
                    (attempts, stamp, request_id),
                )
                connection.commit()
                return "pending"
            except Exception:
                connection.rollback()
                raise

    def drain(self, send: Callable[[str, Mapping[str, Any]], Any]) -> dict[str, Any]:
        """Deliver what is due, in order, stopping at the first unreachable answer."""

        delivered = 0
        blocked = 0
        stopped = None
        now = self._now()
        with closing(self._connect()) as connection:
            due = connection.execute(
                "SELECT * FROM outbox WHERE status='pending' AND next_attempt_at<=? "
                "ORDER BY sequence",
                (_utc(now),),
            ).fetchall()
            for row in due:
                payload = json.loads(row["payload_json"])
                try:
                    send(row["path"], payload)
                except TransportUnavailable as exc:
                    attempts = int(row["attempts"]) + 1
                    if attempts >= MAX_ATTEMPTS:
                        connection.execute(
                            "UPDATE outbox SET status='blocked', attempts=?, last_reason=? "
                            "WHERE sequence=?",
                            (attempts, str(exc)[:200], row["sequence"]),
                        )
                        blocked += 1
                        continue
                    delay = min(
                        MAX_BACKOFF_SECONDS, BASE_BACKOFF_SECONDS * (2 ** (attempts - 1))
                    )
                    connection.execute(
                        "UPDATE outbox SET attempts=?, next_attempt_at=?, last_reason=? "
                        "WHERE sequence=?",
                        (
                            attempts,
                            _utc(now + timedelta(seconds=delay)),
                            str(exc)[:200],
                            row["sequence"],
                        ),
                    )
                    stopped = "unreachable"
                    break
                except TransportRejected as exc:
                    connection.execute(
                        "UPDATE outbox SET status='blocked', attempts=attempts+1, "
                        "last_reason=? WHERE sequence=?",
                        (str(exc)[:200], row["sequence"]),
                    )
                    blocked += 1
                    continue
                connection.execute(
                    "UPDATE outbox SET status='delivered', attempts=attempts+1, "
                    "last_reason=NULL WHERE sequence=?",
                    (row["sequence"],),
                )
                delivered += 1
            self._prune(connection)
            counts = self._counts(connection)
        return {
            "schema": OUTBOX_SCHEMA,
            "delivered": delivered,
            "blocked": blocked,
            "stopped": stopped,
            **counts,
        }

    def summary(self) -> dict[str, Any]:
        """Report what is still owed, safe to project to a person."""

        with closing(self._connect()) as connection:
            counts = self._counts(connection)
            oldest = connection.execute(
                "SELECT created_at FROM outbox WHERE status='pending' "
                "ORDER BY sequence LIMIT 1"
            ).fetchone()
        return {
            "schema": OUTBOX_SCHEMA,
            "oldest_pending_at": oldest["created_at"] if oldest else None,
            **counts,
        }

    @staticmethod
    def _counts(connection: sqlite3.Connection) -> dict[str, int]:
        rows = connection.execute(
            "SELECT status, COUNT(*) AS total FROM outbox GROUP BY status"
        ).fetchall()
        totals = {row["status"]: int(row["total"]) for row in rows}
        return {
            "pending": totals.get("pending", 0),
            "blocked": totals.get("blocked", 0),
        }

    @staticmethod
    def _prune(connection: sqlite3.Connection) -> None:
        connection.execute(
            "DELETE FROM outbox WHERE status='delivered' AND sequence NOT IN ("
            "SELECT sequence FROM outbox WHERE status='delivered' "
            "ORDER BY sequence DESC LIMIT ?)",
            (_DELIVERED_RETENTION,),
        )
