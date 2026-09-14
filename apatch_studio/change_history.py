"""Content-safe projection of existing signed APatch sessions for Studio."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from apatch_studio.projection import assert_projection_safe
from apatch_studio.scope_projection import _logical_area

_SESSION = re.compile(r"^apatch_sess_[A-Za-z0-9_-]{8,160}$")
_SPEC_REQUIREMENT = re.compile(r"^(SPEC-[A-Za-z0-9_-]+)#([A-Za-z]+-?\d+)")
_POSIX_PATH = re.compile(r"(?<![A-Za-z0-9])/(?:Users|home|private|tmp|var|opt|etc)/[^\s,;)}\]]+")
_WINDOWS_PATH = re.compile(r"(?i)(?<![A-Za-z0-9])[A-Z]:\\[^\s,;)}\]]+")


def _iso_timestamp(value: Any) -> str:
    try:
        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return datetime.fromtimestamp(0, timezone.utc).isoformat()


def _safe_objective(value: Any) -> str:
    text = " ".join(str(value or "").split())
    text = _POSIX_PATH.sub("[local path]", text)
    text = _WINDOWS_PATH.sub("[local path]", text)
    return text[:1000] or "Recorded protected change"


def _session_id(payload: Mapping[str, Any]) -> str | None:
    for key in ("governed_session_id", "session_id"):
        candidate = str(payload.get(key) or "")
        if _SESSION.fullmatch(candidate):
            return candidate
    return None


def _requirement(payload: Mapping[str, Any]) -> tuple[str | None, str | None]:
    for artifact in list(payload.get("artifacts") or [])[:32]:
        if not isinstance(artifact, Mapping) or artifact.get("kind") != "spec":
            continue
        match = _SPEC_REQUIREMENT.match(str(artifact.get("id") or ""))
        if match:
            return match.group(1), match.group(2)
    match = _SPEC_REQUIREMENT.match(str(payload.get("intent") or ""))
    return (match.group(1), match.group(2)) if match else (None, None)


def _line_delta(files: Mapping[str, Any]) -> tuple[int, int]:
    insertions = 0
    deletions = 0
    for value in files.values():
        if not isinstance(value, Mapping):
            continue
        patch_text = value.get("diff")
        if not isinstance(patch_text, str):
            continue
        for line in patch_text.splitlines():
            if line.startswith("+") and not line.startswith("+++"):
                insertions += 1
            elif line.startswith("-") and not line.startswith("---"):
                deletions += 1
    return insertions, deletions


def project_signed_changes(
    entries: Iterable[Mapping[str, Any]],
    *,
    limit: int = 80,
) -> list[dict[str, Any]]:
    """Group exact signed ledger records by governed session without persisting a copy."""

    sessions: dict[str, dict[str, Any]] = {}
    file_sets: dict[str, set[str]] = {}
    area_sets: dict[str, set[str]] = {}

    for entry in entries:
        payload = entry.get("payload")
        if not isinstance(payload, Mapping):
            continue
        session_id = _session_id(payload)
        if session_id is None:
            continue
        timestamp = _iso_timestamp(entry.get("timestamp"))
        row = sessions.setdefault(
            session_id,
            {
                "schema": "apatch.studio.imported-change.v1",
                "change_id": "apchg_" + hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32],
                "governed_session_id": session_id,
                "objective": _safe_objective(payload.get("intent")),
                "status": "recorded",
                "created_at": timestamp,
                "updated_at": timestamp,
                "spec_id": None,
                "requirement_id": None,
                "file_count": 0,
                "logical_areas": [],
                "insertions": 0,
                "deletions": 0,
                "mutation_count": 0,
                "attestation_count": 0,
                "signed_event_count": 0,
                "latest_record_id": None,
                "latest_signer": None,
            },
        )
        row["created_at"] = min(str(row["created_at"]), timestamp)
        if timestamp >= str(row["updated_at"]):
            row["updated_at"] = timestamp
            row["latest_record_id"] = str(entry.get("id") or "")[:192] or None
            row["latest_signer"] = str(entry.get("key_id") or "")[:192] or None
        if payload.get("intent"):
            row["objective"] = _safe_objective(payload.get("intent"))
        spec_id, requirement_id = _requirement(payload)
        row["spec_id"] = row["spec_id"] or spec_id
        row["requirement_id"] = row["requirement_id"] or requirement_id
        row["signed_event_count"] += 1

        tool_id = str(entry.get("tool_id") or "")
        action = str(payload.get("action") or "")
        if "rollback" in tool_id or action == "rollback":
            row["status"] = "rolled_back"
        elif tool_id == "apatch_attest":
            row["attestation_count"] += 1
            if row["status"] != "rolled_back":
                row["status"] = "proven"
        elif isinstance(payload.get("files"), Mapping) or payload.get("applied_patches"):
            row["mutation_count"] += 1
            files = payload.get("files")
            if isinstance(files, Mapping):
                file_sets.setdefault(session_id, set()).update(str(path) for path in files)
                area_sets.setdefault(session_id, set()).update(
                    _logical_area(str(path)) for path in files
                )
                added, removed = _line_delta(files)
                row["insertions"] += added
                row["deletions"] += removed

    area_order = ("frontend", "backend", "tests", "docs", "configuration", "other")
    for session_id, row in sessions.items():
        row["file_count"] = len(file_sets.get(session_id, set()))
        areas = area_sets.get(session_id, set())
        row["logical_areas"] = [area for area in area_order if area in areas]
        assert_projection_safe(row)

    ordered = sorted(
        sessions.values(),
        key=lambda item: (str(item["updated_at"]), str(item["change_id"])),
        reverse=True,
    )
    return ordered[: max(1, min(int(limit), 200))]
