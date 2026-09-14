"""Safe aggregate workspace observations for local run review."""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from apatch_studio.projection import assert_projection_safe

OBSERVATION_SCHEMA = "apatch.studio.workspace-observation.v1"
REVIEW_SCHEMA = "apatch.studio.run-review.v1"
_NUMERIC_FIELDS = (
    "dirty_files",
    "insertions",
    "deletions",
    "attested_requirements",
    "stale_requirements",
    "evidence_events",
    "work_assets",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git(root: Path, *args: str) -> tuple[int, str]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return completed.returncode, completed.stdout.strip()


def _tracked_delta(root: Path) -> tuple[int, int]:
    code, output = _git(root, "diff", "--numstat", "HEAD", "--")
    if code != 0:
        _code, output = _git(root, "diff", "--numstat", "--")
    insertions = 0
    deletions = 0
    for line in output.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 2:
            continue
        if parts[0].isdigit():
            insertions += int(parts[0])
        if parts[1].isdigit():
            deletions += int(parts[1])
    return insertions, deletions


class WorkspaceReviewCollector:
    """Collect counts and hashes without retaining files, paths or diff content."""

    def __init__(
        self,
        workspace: str | Path,
        *,
        overview_supplier: Callable[[], dict[str, Any]] | None = None,
    ):
        self.root = Path(workspace).expanduser().resolve()
        self.overview_supplier = overview_supplier

    def capture(self) -> dict[str, Any]:
        _code, porcelain = _git(self.root, "status", "--porcelain=v1")
        _code, branch = _git(self.root, "branch", "--show-current")
        _code, head = _git(self.root, "rev-parse", "--short=12", "HEAD")
        insertions, deletions = _tracked_delta(self.root)
        overview: dict[str, Any] = {}
        if self.overview_supplier is not None:
            try:
                overview = self.overview_supplier() or {}
            except Exception:
                overview = {}
        summary = overview.get("summary") or {}
        work_assets = overview.get("work_assets") or {}
        observation = {
            "schema": OBSERVATION_SCHEMA,
            "captured_at": _now(),
            "branch": branch or "detached",
            "head": head or None,
            "dirty_files": len([line for line in porcelain.splitlines() if line.strip()]),
            "insertions": insertions,
            "deletions": deletions,
            "attested_requirements": int(summary.get("attested") or 0),
            "stale_requirements": int(summary.get("stale_count") or 0),
            "evidence_events": len(overview.get("evidence") or []),
            "work_assets": int(work_assets.get("count") or 0),
        }
        assert_projection_safe(observation)
        return observation


def build_review(
    baseline: dict[str, Any] | None,
    result: dict[str, Any] | None,
) -> dict[str, Any] | None:
    if baseline is None and result is None:
        return None
    delta = None
    if baseline is not None and result is not None:
        delta = {
            field: int(result.get(field) or 0) - int(baseline.get(field) or 0)
            for field in _NUMERIC_FIELDS
        }
        delta["head_changed"] = baseline.get("head") != result.get("head")
        delta["branch_changed"] = baseline.get("branch") != result.get("branch")
    review = {
        "schema": REVIEW_SCHEMA,
        "baseline": baseline,
        "result": result,
        "delta": delta,
        "attribution": "workspace_observation_only",
    }
    assert_projection_safe(review)
    return review
