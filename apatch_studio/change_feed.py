"""One ordered Studio changes feed over local runs and signed APatch history."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from apatch_studio.projection import assert_projection_safe


def _run_time(run: Mapping[str, Any]) -> str:
    return str(run.get("ended_at") or run.get("started_at") or run.get("created_at") or "")


def _meaningful_key(item: Mapping[str, Any]) -> str | None:
    if item.get("kind") == "studio_run":
        run = item.get("run") or {}
        return f"run:{run.get('run_id') or item.get('id')}"

    change = item.get("change") or {}
    meaningful = (
        int(change.get("mutation_count") or 0) > 0
        or int(change.get("file_count") or 0) > 0
        or str(change.get("status") or "") == "rolled_back"
    )
    if not meaningful:
        return None
    spec_id = str(change.get("spec_id") or "").strip()
    requirement_id = str(change.get("requirement_id") or "").strip()
    if spec_id:
        return f"spec:{spec_id}"
    if requirement_id:
        return f"requirement:{requirement_id}"
    return f"change:{change.get('change_id') or item.get('id')}"


def _recent_result_projection(
    items: Sequence[Mapping[str, Any]],
    *,
    limit: int = 6,
) -> tuple[list[str], dict[str, int]]:
    counts: dict[str, int] = {}
    for item in items:
        key = _meaningful_key(item)
        if key is not None:
            counts[key] = counts.get(key, 0) + 1

    recent: list[str] = []
    group_sizes: dict[str, int] = {}
    seen: set[str] = set()
    for item in items:
        key = _meaningful_key(item)
        if key is None or key in seen:
            continue
        seen.add(key)
        item_id = str(item.get("id") or "")
        recent.append(item_id)
        group_sizes[item_id] = counts[key]
        if len(recent) >= limit:
            break
    return recent, group_sizes


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _current_state(items: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """Return the project state with a cause and one next step in product language (RFP-009)."""

    runs = [
        item.get("run") or {}
        for item in items
        if item.get("kind") == "studio_run"
    ]
    working = sum(run.get("status") in {"queued", "running"} for run in runs)
    if working:
        return {
            "id": "working",
            "label": "Working",
            "tone": "info",
            "detail": f"{_plural(working, 'change')} in progress",
            "next_step": "Follow progress on the change card",
        }
    unfinished = sum(
        run.get("status") in {"failed", "interrupted"} or bool(run.get("can_retry"))
        for run in runs
    )
    if unfinished:
        return {
            "id": "attention",
            "label": "Needs attention",
            "tone": "danger",
            "detail": f"{_plural(unfinished, 'change')} did not finish",
            "next_step": "Open the change: it says what happened and offers Retry",
        }
    awaiting = sum(
        run.get("status") == "succeeded" and not run.get("reviewer_note")
        for run in runs
    )
    if awaiting:
        return {
            "id": "review",
            "label": "Ready for review",
            "tone": "warning",
            "detail": f"{_plural(awaiting, 'result')} awaiting your note",
            "next_step": "Open the result and record the review",
        }
    return {
        "id": "ready",
        "label": "Ready for a new change",
        "tone": "success",
        "detail": "Nothing is waiting on you",
        "next_step": "Describe the next change below",
    }


def build_project_home_summary(
    workspace: Mapping[str, Any],
    items: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build the bounded Home briefing from the same canonical feed."""

    project = workspace.get("workspace") or {}
    summary = workspace.get("summary") or {}
    total = max(0, int(summary.get("total_requirements") or 0))
    proven = max(0, min(total, int(summary.get("attested") or 0)))
    recent_ids, recent_group_sizes = _recent_result_projection(items)
    return {
        "schema": "apatch.studio.project-home.v1",
        "project": {
            "name": str(project.get("name") or "Local project"),
            "branch": str(project.get("branch") or ""),
        },
        "state": _current_state(items),
        "summary": {
            "proven": proven,
            "total": total,
            "remaining": max(0, total - proven),
            "uncommitted_files": max(0, int(project.get("dirty_files") or 0)),
        },
        "history_count": len(items),
        "recent_ids": recent_ids,
        "recent_group_sizes": recent_group_sizes,
    }


def build_unified_change_feed(
    studio_runs: Iterable[Mapping[str, Any]],
    imported_changes: Iterable[Mapping[str, Any]],
    *,
    workspace: Mapping[str, Any] | None = None,
    limit: int = 100,
) -> dict[str, Any]:
    """Merge by exact governed session id without copying either source."""

    runs = [dict(run) for run in studio_runs]
    managed_sessions = {
        str((run.get("work_ref") or {}).get("governed_session_id"))
        for run in runs
        if (run.get("work_ref") or {}).get("governed_session_id")
    }
    items: list[dict[str, Any]] = [
        {
            "kind": "studio_run",
            "id": str(run.get("run_id") or ""),
            "occurred_at": _run_time(run),
            "run": run,
        }
        for run in runs
        if run.get("run_id")
    ]
    for change in imported_changes:
        session_id = str(change.get("governed_session_id") or "")
        if not change.get("change_id") or session_id in managed_sessions:
            continue
        items.append(
            {
                "kind": "imported_change",
                "id": str(change["change_id"]),
                "occurred_at": str(change.get("updated_at") or change.get("created_at") or ""),
                "change": dict(change),
            }
        )

    items.sort(key=lambda item: (item["occurred_at"], item["id"]), reverse=True)
    bounded_items = items[: max(1, min(int(limit), 200))]
    page: dict[str, Any] = {
        "schema": "apatch.studio.change-feed.v1",
        "count": len(items),
        "items": bounded_items,
    }
    if workspace is not None:
        page["home"] = build_project_home_summary(workspace, bounded_items)
    assert_projection_safe(page)
    return page
