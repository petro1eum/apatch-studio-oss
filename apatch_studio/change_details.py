"""Local-only full-fidelity detail for one signed APatch change."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping
from pathlib import PurePosixPath
from typing import Any

from apatch_studio.change_history import (
    _iso_timestamp,
    _line_delta,
    _session_id,
    project_signed_changes,
)

_CHANGE_ID = re.compile(r"^apchg_[0-9a-f]{32}$")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\\\/]")
_MODE = re.compile(r"^[0-7]{3,6}$")
_DIGEST = re.compile(r"^(?:sha256:)?[0-9a-f]{64}$")
_MAX_FILES = 200
_MAX_PATH_CHARS = 512
_MAX_FILE_PATCH_BYTES = 256 * 1024
_MAX_TOTAL_PATCH_BYTES = 2 * 1024 * 1024
_MAX_EVENTS = 96


class InvalidChangeId(ValueError):
    """The requested public change identifier is malformed."""


class ChangeDetailNotFound(LookupError):
    """No signed APatch session maps to the requested change."""


def change_id_for_session(session_id: str) -> str:
    return "apchg_" + hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32]


def _safe_relative_path(value: Any) -> str | None:
    text = str(value or "").strip()
    if (
        not text
        or len(text) > _MAX_PATH_CHARS
        or "\x00" in text
        or text.startswith(("/", "~"))
        or _WINDOWS_ABSOLUTE.match(text)
    ):
        return None
    normalized = text.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        return None
    if path.parts[0] == ".git":
        return None
    return str(path)


def _safe_identifier(value: Any, *, limit: int = 192) -> str | None:
    text = " ".join(str(value or "").split())
    return text[:limit] or None


def _safe_project(project: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "name": _safe_identifier(project.get("name"), limit=160) or "Local project",
        "identity": _safe_identifier(project.get("identity"), limit=64),
        "repository": _safe_identifier(project.get("repository"), limit=220),
        "branch": _safe_identifier(project.get("branch"), limit=220),
        "upstream": _safe_identifier(project.get("upstream"), limit=220),
        "head": _safe_identifier(project.get("head"), limit=64),
        "operator": _safe_identifier(project.get("operator"), limit=160) or "Local user",
    }


def _target_entries(
    entries: Iterable[Mapping[str, Any]],
    change_id: str,
) -> tuple[str, list[Mapping[str, Any]]]:
    if _CHANGE_ID.fullmatch(change_id) is None:
        raise InvalidChangeId("invalid change id")
    selected_session: str | None = None
    selected: list[Mapping[str, Any]] = []
    for entry in entries:
        payload = entry.get("payload")
        if not isinstance(payload, Mapping):
            continue
        session_id = _session_id(payload)
        if session_id is None or change_id_for_session(session_id) != change_id:
            continue
        selected_session = session_id
        selected.append(entry)
    if selected_session is None:
        raise ChangeDetailNotFound(change_id)
    return selected_session, selected


def _file_rows(
    entries: Iterable[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], int, int, bool]:
    retained: dict[str, dict[str, Any]] = {}
    omitted = 0
    for entry in entries:
        payload = entry.get("payload")
        if not isinstance(payload, Mapping):
            continue
        files = payload.get("files")
        if not isinstance(files, Mapping):
            continue
        for raw_path, raw_value in files.items():
            path = _safe_relative_path(raw_path)
            if path is None or not isinstance(raw_value, Mapping):
                omitted += 1
                continue
            if path not in retained and len(retained) >= _MAX_FILES:
                omitted += 1
                continue
            row = retained.setdefault(
                path,
                {
                    "path": path,
                    "mode": None,
                    "sha256": None,
                    "patches": [],
                    "binary": False,
                    "record_ids": [],
                },
            )
            mode = str(raw_value.get("mode") or "")
            digest = str(raw_value.get("sha256") or "")
            if _MODE.fullmatch(mode):
                row["mode"] = mode
            if _DIGEST.fullmatch(digest):
                row["sha256"] = digest
            record_id = _safe_identifier(entry.get("id"))
            if record_id:
                row["record_ids"].append(record_id)
            patch = raw_value.get("diff")
            if not isinstance(patch, str) or not patch:
                continue
            if "\x00" in patch or patch.startswith("Binary files "):
                row["binary"] = True
                continue
            row["patches"].append(patch)

    remaining = _MAX_TOTAL_PATCH_BYTES
    result: list[dict[str, Any]] = []
    total_bytes = 0
    any_truncated = False
    for path in sorted(retained):
        raw = retained[path]
        full_patch = "\n\n".join(raw.pop("patches"))
        insertions, deletions = _line_delta({path: {"diff": full_patch}})
        encoded = full_patch.encode("utf-8")
        allowed = min(_MAX_FILE_PATCH_BYTES, remaining)
        truncated = len(encoded) > allowed
        if encoded and allowed:
            emitted = encoded[:allowed]
            patch = emitted.decode("utf-8", errors="ignore")
            emitted_bytes = len(patch.encode("utf-8"))
        else:
            patch = None
            emitted_bytes = 0
        remaining -= emitted_bytes
        total_bytes += emitted_bytes
        any_truncated = any_truncated or truncated
        if raw["binary"]:
            patch_status = "binary"
            patch = None
        elif truncated:
            patch_status = "truncated"
        elif patch:
            patch_status = "available"
        else:
            patch_status = "not_recorded"
        result.append(
            {
                **raw,
                "patch": patch,
                "patch_status": patch_status,
                "patch_bytes": emitted_bytes,
                "insertions": insertions,
                "deletions": deletions,
                "truncated": truncated,
            }
        )
    return result, omitted, total_bytes, any_truncated


def project_signed_change_detail(
    entries: Iterable[Mapping[str, Any]],
    change_id: str,
    *,
    project: Mapping[str, Any],
) -> dict[str, Any]:
    """Derive one local full-fidelity detail without persisting a second truth."""

    session_id, selected = _target_entries(list(entries), change_id)
    summary_rows = project_signed_changes(selected, limit=1)
    if not summary_rows:
        raise ChangeDetailNotFound(change_id)
    summary = summary_rows[0]
    files, omitted, patch_bytes, patch_truncated = _file_rows(selected)
    events = []
    for entry in sorted(selected, key=lambda row: float(row.get("timestamp") or 0)):
        payload = entry.get("payload")
        if not isinstance(payload, Mapping):
            continue
        events.append(
            {
                "record_id": _safe_identifier(entry.get("id")),
                "at": _iso_timestamp(entry.get("timestamp")),
                "tool": _safe_identifier(entry.get("tool_id"), limit=96) or "apatch",
                "action": _safe_identifier(payload.get("action"), limit=96),
                "signer_key_id": _safe_identifier(entry.get("key_id")),
            }
        )
    events = events[-_MAX_EVENTS:]
    result_kind = (
        "code_change"
        if int(summary.get("mutation_count") or 0) > 0
        else "verification_checkpoint"
    )
    has_patch = any(row["patch_status"] in ("available", "truncated") for row in files)
    actions = ["back_to_changes"]
    if has_patch:
        actions.append("open_recorded_patch")
    if summary.get("spec_id"):
        actions.append("open_backlog")
    if result_kind == "verification_checkpoint":
        result_message = "No files were changed. This record verifies existing project state."
    elif files:
        result_message = f"{len(files)} changed file{'s' if len(files) != 1 else ''} recorded."
    else:
        result_message = "Files changed, but this ledger record does not retain file detail."

    return {
        "schema": "apatch.studio.imported-change-detail.v1",
        "privacy_band": "local_source",
        "change_id": change_id,
        "governed_session_id": session_id,
        "result_kind": result_kind,
        "result_message": result_message,
        "objective": summary["objective"],
        "status": summary["status"],
        "created_at": summary["created_at"],
        "updated_at": summary["updated_at"],
        "spec_id": summary.get("spec_id"),
        "requirement_id": summary.get("requirement_id"),
        "project": _safe_project(project),
        "actor": {
            "type": "apatch_signing_identity",
            "label": "Local APatch signing identity",
            "key_id": summary.get("latest_signer"),
        },
        "summary": {
            "file_count": len(files),
            "omitted_file_count": omitted,
            "insertions": int(summary.get("insertions") or 0),
            "deletions": int(summary.get("deletions") or 0),
            "mutation_count": int(summary.get("mutation_count") or 0),
            "attestation_count": int(summary.get("attestation_count") or 0),
            "signed_event_count": int(summary.get("signed_event_count") or 0),
            "patch_bytes": patch_bytes,
            "patch_truncated": patch_truncated,
        },
        "files": files,
        "events": events,
        "verification": {
            "status": "proven" if summary.get("attestation_count") else "recorded",
            "attestation_count": int(summary.get("attestation_count") or 0),
            "latest_record_id": summary.get("latest_record_id"),
            "latest_signer": summary.get("latest_signer"),
        },
        "available_actions": actions,
    }


def recorded_change_patch(detail: Mapping[str, Any]) -> bytes:
    chunks = []
    for file_row in detail.get("files") or []:
        if not isinstance(file_row, Mapping):
            continue
        patch = file_row.get("patch")
        if isinstance(patch, str) and patch:
            chunks.append(patch)
    return ("\n\n".join(chunks) + ("\n" if chunks else "")).encode("utf-8")
