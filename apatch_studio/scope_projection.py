"""Content-safe APatch scope outcomes for Studio change cards."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_SCOPE_SCHEMA = "apatch.studio.scope-outcome.v1"
_AREA_ORDER = ("frontend", "backend", "tests", "docs", "configuration", "other")
_MUTATION_TOOL_FRAGMENTS = (
    "execute_next",
    "apply",
    "generate",
    "spec_run",
    "session_start",
)


def empty_scope_outcome() -> dict[str, Any]:
    """Return a conservative projection before an explicit sandbox audit."""

    return {
        "schema": _SCOPE_SCHEMA,
        "status": "pending",
        "audit_observed": False,
        "planned_file_count": 0,
        "logical_areas": [],
        "blocked_out_of_scope": 0,
        "reverted_out_of_scope": 0,
        "unresolved_out_of_scope": 0,
    }


def _walk(value: Any):
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for child in value[:512]:
            yield from _walk(child)


def _tool_names(event: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    for item in _walk(event):
        for key in ("name", "tool", "tool_name"):
            value = item.get(key)
            if isinstance(value, str) and "apatch" in value.lower():
                names.add(value.lower())
    return names


def _bounded_count(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return min(max(value, 0), 100_000)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return min(len(value), 100_000)
    return 0


def _logical_area(raw: str) -> str:
    normalized = raw.replace("\\", "/").strip().lower().lstrip("./")
    first = normalized.split("/", 1)[0]
    if first in {"frontend", "web", "ui", "client"}:
        return "frontend"
    if first in {"backend", "server", "api", "apatch_studio", "src"}:
        return "backend"
    if first in {"test", "tests", "e2e"}:
        return "tests"
    if first in {"doc", "docs"} or normalized.startswith(("readme", "license", "changelog")):
        return "docs"
    if first in {
        ".github",
        ".gitlab",
        ".vscode",
        "config",
        "configs",
        "scripts",
        "pyproject.toml",
        "package.json",
        "package-lock.json",
        "vite.config.ts",
        "tsconfig.json",
    }:
        return "configuration"
    return "other"


def _path_values(event: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for item in _walk(event):
        for key in ("planned_paths", "target_files", "files_touched", "paths"):
            raw = item.get(key)
            if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes, bytearray)):
                continue
            for candidate in raw[:512]:
                if isinstance(candidate, str) and candidate and candidate != ".":
                    values.append(candidate)
    return values


def _violation_fingerprint(value: Mapping[str, Any]) -> str | None:
    path = value.get("path")
    digest = value.get("sha256")
    reason = value.get("reason")
    if not all(isinstance(item, str) and item for item in (path, digest, reason)):
        return None
    return "\0".join((path, digest, reason))


def scope_violation_fingerprints(values: Any) -> frozenset[str]:
    """Return private exact identities for sandbox findings without projecting them."""

    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return frozenset()
    fingerprints = (
        _violation_fingerprint(value)
        for value in values
        if isinstance(value, Mapping)
    )
    return frozenset(value for value in fingerprints if value is not None)


def capture_scope_violation_fingerprints(workspace: str) -> frozenset[str]:
    """Snapshot pre-existing sandbox findings for run-local attribution."""

    try:
        from apatch.sandbox_watch import scan_unleased_violations

        return scope_violation_fingerprints(scan_unleased_violations(workspace))
    except Exception:
        return frozenset()


def _audit_payload(event: Mapping[str, Any]) -> Mapping[str, Any] | None:
    recognized = {
        "scanned_violations",
        "violations",
        "reverted_tracked",
        "removed_untracked",
        "revert_failed",
        "reverted_count",
    }
    candidates = [item for item in _walk(event) if recognized.intersection(item)]
    if not candidates:
        return None
    return max(candidates, key=lambda item: len(recognized.intersection(item)))


def update_scope_outcome(
    current: Mapping[str, Any] | None,
    event: Mapping[str, Any],
    *,
    baseline_violations: frozenset[str] | set[str] | None = None,
) -> dict[str, Any]:
    """Merge one structured runner event without exposing source or repository paths."""

    projection = empty_scope_outcome()
    if current is not None:
        projection.update({key: current[key] for key in projection if key in current})

    tool_names = _tool_names(event)
    if any(
        fragment in name
        for name in tool_names
        for fragment in _MUTATION_TOOL_FRAGMENTS
    ):
        raw_paths = _path_values(event)
        if raw_paths:
            areas = set(projection["logical_areas"])
            areas.update(_logical_area(value) for value in raw_paths)
            projection["logical_areas"] = [
                area for area in _AREA_ORDER if area in areas
            ]
            projection["planned_file_count"] = max(
                int(projection["planned_file_count"]),
                len(set(raw_paths)),
            )

    if not any("apatch_sandbox_audit" in name for name in tool_names):
        return projection

    audit = _audit_payload(event)
    if audit is None:
        return projection

    scanned = _bounded_count(audit.get("scanned_violations"))
    raw_rows = audit.get("violations")
    rows = (
        [value for value in raw_rows if isinstance(value, Mapping)]
        if isinstance(raw_rows, Sequence)
        and not isinstance(raw_rows, (str, bytes, bytearray))
        else []
    )
    if baseline_violations is None:
        blocked = max(scanned, len(rows))
    else:
        novel_rows = [
            value
            for value in rows
            if _violation_fingerprint(value) not in baseline_violations
        ]
        blocked = len(novel_rows)
        if scanned > len(rows):
            blocked = max(blocked, max(0, scanned - len(baseline_violations)))

    reverted_components = (
        _bounded_count(audit.get("reverted_tracked"))
        + _bounded_count(audit.get("removed_untracked"))
    )
    reverted = min(
        blocked,
        max(_bounded_count(audit.get("reverted_count")), reverted_components),
    )
    unresolved = min(
        max(0, blocked - reverted),
        _bounded_count(audit.get("revert_failed")),
    )
    explicit_ok = audit.get("ok") is True
    if not explicit_ok and blocked > reverted + unresolved:
        unresolved = blocked - reverted

    projection.update(
        {
            "audit_observed": True,
            "blocked_out_of_scope": blocked,
            "reverted_out_of_scope": reverted,
            "unresolved_out_of_scope": unresolved,
        }
    )
    if unresolved:
        projection["status"] = "attention"
    elif blocked or reverted:
        projection["status"] = "protected"
    elif explicit_ok or baseline_violations is not None:
        projection["status"] = "clean"
    else:
        projection["status"] = "attention"
    return projection
