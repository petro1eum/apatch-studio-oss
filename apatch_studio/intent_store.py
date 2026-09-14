"""Owner-private durable ledger for imported execution intents."""

from __future__ import annotations

import json
import os
import re
import stat
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterator, TypeVar

from apatch_studio.projection import UnsafeProjectionError, assert_projection_safe
from apatch_studio.run_store import default_state_root, workspace_identity

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback
    fcntl = None

INTENT_JOURNAL_SCHEMA = "apatch.studio.execution-intent-journal.v1"
INTENT_RECORD_SCHEMA = "apatch.studio.execution-intent-record.v1"
MAX_INTENT_JOURNAL_BYTES = 2 * 1024 * 1024
MAX_EXECUTION_INTENT_ENVELOPE_BYTES = 16 * 1024
MAX_INTENT_RECORDS = 256

_INTENT_STATUSES = {
    "awaiting_local_confirmation",
    "consuming",
    "consumed",
    "cancelled",
    "expired",
    "manual_review",
}
_COWORK_STATUSES = {
    "not_connected",
    "awaiting_local_acceptance",
    "accepting",
    "acceptance_failed",
    "source_bound",
}
_INTENT_ID_PATTERN = re.compile(r"^tcapsei_[0-9a-f]{32}$")
_CHANGE_ID_PATTERN = re.compile(r"^apchg_[0-9a-f]{32}$")
_SOURCE_BINDING_ID_PATTERN = re.compile(r"^(?:tcpsb|tcawieb)_[0-9a-f]{32}$")
_LEGACY_RECORD_FIELDS = {
    "schema",
    "intent_id",
    "tenant_id",
    "project_group_id",
    "work_item_id",
    "work_item_hash",
    "authority_version",
    "work_program_id",
    "work_program_hash",
    "objective",
    "acceptance_criteria",
    "issued_at",
    "expires_at",
    "received_at",
    "updated_at",
    "status",
    "document_hash",
    "envelope_hash",
    "nonce_digest",
    "run_id",
    "consumed_at",
}
_RECORD_FIELDS = _LEGACY_RECORD_FIELDS | {
    "cowork_status",
    "cowork_change_id",
    "cowork_source_binding_id",
}
T = TypeVar("T")


class IntentJournalError(RuntimeError):
    """The replay ledger cannot be trusted or updated."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lock(handle: BinaryIO) -> None:
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        return
    import msvcrt  # pragma: no cover - Windows fallback

    handle.seek(0)
    if handle.read(1) == b"":
        handle.seek(0)
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)


def _unlock(handle: BinaryIO) -> None:
    if fcntl is not None:
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        return
    import msvcrt  # pragma: no cover - Windows fallback

    handle.seek(0)
    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)


class IntentStore:
    """Workspace-scoped journal with atomic cross-process updates."""

    def __init__(
        self,
        workspace: str | os.PathLike[str],
        *,
        state_root: str | os.PathLike[str] | None = None,
    ):
        self.workspace = Path(workspace).expanduser().resolve()
        if not self.workspace.is_dir():
            raise ValueError(f"workspace does not exist: {self.workspace}")
        root = Path(state_root).expanduser().resolve() if state_root else default_state_root()
        self.workspace_identity = workspace_identity(self.workspace)
        self.state_root = root
        self.directory = root / "workspaces" / self.workspace_identity
        try:
            self.directory.relative_to(self.workspace)
        except ValueError:
            pass
        else:
            raise ValueError("execution-intent ledger must be outside the Git workspace")
        self.journal_path = self.directory / "execution-intents.json"
        self.lock_path = self.directory / "execution-intents.lock"
        self.envelope_directory = self.directory / "execution-intent-envelopes"

    def load(self) -> list[dict[str, Any]]:
        with self._transaction():
            return self._load_unlocked()

    def update(self, mutate: Callable[[list[dict[str, Any]]], T]) -> T:
        with self._transaction():
            records = self._load_unlocked()
            result = mutate(records)
            self._write_unlocked(records)
            return result

    def update_with_envelope(
        self,
        intent_id: str,
        raw: bytes,
        mutate: Callable[[list[dict[str, Any]]], T],
    ) -> T:
        """Admit journal metadata and its private exact envelope under one lock."""
        with self._transaction():
            records = self._load_unlocked()
            result = mutate(records)
            created = self._write_envelope_unlocked(intent_id, raw)
            try:
                self._write_unlocked(records)
            except Exception:
                if created:
                    self.envelope_path(intent_id).unlink(missing_ok=True)
                raise
            return result

    def envelope_path(self, intent_id: str) -> Path:
        if not isinstance(intent_id, str) or not _INTENT_ID_PATTERN.fullmatch(intent_id):
            raise IntentJournalError("invalid execution-intent envelope identity")
        return self.envelope_directory / f"{intent_id}.json"

    def load_envelope(self, intent_id: str) -> bytes:
        with self._transaction():
            return self._read_envelope_unlocked(intent_id)

    def delete_envelope(self, intent_id: str) -> None:
        with self._transaction():
            path = self.envelope_path(intent_id)
            if path.is_symlink():
                raise IntentJournalError("execution-intent envelope cannot be a symlink")
            path.unlink(missing_ok=True)

    def _write_envelope_unlocked(self, intent_id: str, raw: bytes) -> bool:
        if (
            not isinstance(raw, bytes)
            or not 0 < len(raw) <= MAX_EXECUTION_INTENT_ENVELOPE_BYTES
        ):
            raise IntentJournalError("execution-intent envelope size is invalid")
        path = self.envelope_path(intent_id)
        if path.exists() or path.is_symlink():
            if self._read_envelope_unlocked(intent_id) != raw:
                raise IntentJournalError("execution-intent envelope conflicts with stored bytes")
            return False
        temporary = self.envelope_directory / f".{intent_id}.{uuid.uuid4().hex}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            os.chmod(path, 0o600)
            directory_fd = os.open(self.envelope_directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)
        return True

    def _read_envelope_unlocked(self, intent_id: str) -> bytes:
        path = self.envelope_path(intent_id)
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except (FileNotFoundError, OSError) as exc:
            raise IntentJournalError("private execution-intent envelope is unavailable") from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= 16 * 1024:
                raise IntentJournalError("private execution-intent envelope is invalid")
            with os.fdopen(descriptor, "rb") as handle:
                descriptor = -1
                raw = handle.read(MAX_EXECUTION_INTENT_ENVELOPE_BYTES + 1)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if not raw or len(raw) > MAX_EXECUTION_INTENT_ENVELOPE_BYTES:
            raise IntentJournalError("private execution-intent envelope is invalid")
        return raw

    def _load_unlocked(self) -> list[dict[str, Any]]:
        if not self.journal_path.exists():
            return []
        try:
            if self.journal_path.stat().st_size > MAX_INTENT_JOURNAL_BYTES:
                raise IntentJournalError("execution-intent journal exceeds the storage limit")
            document = json.loads(self.journal_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise IntentJournalError("execution-intent journal is corrupt") from exc
        if not isinstance(document, dict):
            raise IntentJournalError("execution-intent journal must be an object")
        if set(document) != {"schema", "workspace_identity", "updated_at", "records"}:
            raise IntentJournalError("execution-intent journal shape is invalid")
        if document["schema"] != INTENT_JOURNAL_SCHEMA:
            raise IntentJournalError("unsupported execution-intent journal schema")
        if document["workspace_identity"] != self.workspace_identity:
            raise IntentJournalError("execution-intent workspace identity mismatch")
        raw_records = document["records"]
        if not isinstance(raw_records, list) or len(raw_records) > MAX_INTENT_RECORDS:
            raise IntentJournalError("execution-intent record limit exceeded")
        return [self._validated_copy(record) for record in raw_records]

    def _write_unlocked(self, records: list[dict[str, Any]]) -> None:
        accepted = [self._validated_copy(record) for record in records]
        if len(accepted) > MAX_INTENT_RECORDS:
            terminal = [row for row in accepted if row["status"] != "awaiting_local_confirmation"]
            pending = [row for row in accepted if row["status"] == "awaiting_local_confirmation"]
            keep_terminal = terminal[-max(0, MAX_INTENT_RECORDS - len(pending)) :]
            accepted = [*keep_terminal, *pending]
        if len(accepted) > MAX_INTENT_RECORDS:
            raise IntentJournalError("too many pending execution intents")
        document = {
            "schema": INTENT_JOURNAL_SCHEMA,
            "workspace_identity": self.workspace_identity,
            "updated_at": _now(),
            "records": accepted,
        }
        try:
            assert_projection_safe(document)
        except UnsafeProjectionError as exc:
            raise IntentJournalError(str(exc)) from exc
        payload = json.dumps(
            document, ensure_ascii=True, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if len(payload) > MAX_INTENT_JOURNAL_BYTES:
            raise IntentJournalError("execution-intent journal exceeds the storage limit")
        temporary = self.directory / f".execution-intents.{uuid.uuid4().hex}.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.journal_path)
            os.chmod(self.journal_path, 0o600)
            directory_fd = os.open(self.directory, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _validated_copy(record: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(record, dict):
            raise IntentJournalError("execution-intent record shape is invalid")
        candidate = dict(record)
        if set(candidate) == _LEGACY_RECORD_FIELDS:
            candidate.update(
                {
                    "cowork_status": "local_only"
                    if candidate.get("status") == "consumed"
                    else "not_connected",
                    "cowork_change_id": None,
                    "cowork_source_binding_id": None,
                }
            )
        if set(candidate) != _RECORD_FIELDS:
            raise IntentJournalError("execution-intent record shape is invalid")
        if candidate.get("schema") != INTENT_RECORD_SCHEMA:
            raise IntentJournalError("unsupported execution-intent record schema")
        if candidate.get("status") not in _INTENT_STATUSES:
            raise IntentJournalError("invalid execution-intent status")
        if candidate.get("cowork_status") not in _COWORK_STATUSES | {"local_only"}:
            raise IntentJournalError("invalid Cowork execution-intent status")
        if not isinstance(candidate.get("acceptance_criteria"), list):
            raise IntentJournalError("execution-intent criteria must be a list")
        if not isinstance(candidate.get("authority_version"), int):
            raise IntentJournalError("execution-intent authority version must be an integer")
        change_id = candidate.get("cowork_change_id")
        source_binding_id = candidate.get("cowork_source_binding_id")
        if candidate["cowork_status"] == "source_bound":
            if (
                not isinstance(change_id, str)
                or not _CHANGE_ID_PATTERN.fullmatch(change_id)
                or not isinstance(source_binding_id, str)
                or not _SOURCE_BINDING_ID_PATTERN.fullmatch(source_binding_id)
            ):
                raise IntentJournalError("source-bound intent is missing exact identifiers")
        elif change_id is not None or source_binding_id is not None:
            raise IntentJournalError("unbound intent cannot carry Cowork identifiers")
        try:
            assert_projection_safe(candidate)
            return json.loads(json.dumps(candidate, ensure_ascii=True))
        except (UnsafeProjectionError, TypeError, ValueError) as exc:
            raise IntentJournalError("unsafe execution-intent record") from exc

    def _ensure_directory(self) -> None:
        for directory in (
            self.state_root,
            self.state_root / "workspaces",
            self.directory,
            self.envelope_directory,
        ):
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            os.chmod(directory, 0o700)

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._ensure_directory()
        handle = self.lock_path.open("a+b")
        os.chmod(self.lock_path, 0o600)
        try:
            _lock(handle)
            yield
        finally:
            _unlock(handle)
            handle.close()
