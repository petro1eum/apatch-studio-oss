from __future__ import annotations

import json
from pathlib import Path

import pytest

from apatch_studio.agent_runs import AgentRunManager
from apatch_studio.run_store import RECORD_SCHEMA, RunJournalError, RunStore


class _Catalog:
    def projection(self) -> list[dict[str, object]]:
        return [{"id": "codex", "label": "Test runner", "available": True}]

    def command(self, runner: str, workspace: Path) -> list[str]:
        raise AssertionError("restoring a terminal journal must not start a runner")


def _handoff() -> dict:
    return {
        "schema": "apatch.studio.plan-handoff.v1",
        "status": "review_ready",
        "spec_id": "SPEC-PLAN-1",
        "requirement_ids": ["R1", "R2"],
        "objective": "Prepare an exact implementation plan",
        "prepared_at": "2026-09-02T10:00:00+00:00",
        "package_hash": "sha256:" + "a" * 64,
    }


def _record(*, include_handoff: bool = True) -> dict:
    value = {
        "schema": RECORD_SCHEMA,
        "run_id": "apr_" + "1" * 32,
        "request": {
            "mode": "new_change",
            "runner": "codex",
            "objective": "Prepare an exact implementation plan",
            "acceptance_criteria": ["The owner can review exact scope and checks"],
            "spec_id": None,
            "requirement_id": None,
            "governed_session_id": None,
        },
        "retry_of": None,
        "status": "succeeded",
        "phase": "complete",
        "created_at": "2026-09-02T10:00:00+00:00",
        "started_at": "2026-09-02T10:00:01+00:00",
        "ended_at": "2026-09-02T10:00:02+00:00",
        "outcome": "plan_ready",
        "message": "Plan is ready for owner review",
        "thread_id": None,
        "event_count": 0,
        "review": None,
        "updated_at": "2026-09-02T10:00:02+00:00",
    }
    if include_handoff:
        value["plan_handoff"] = _handoff()
    return value


def test_plan_handoff_round_trips_and_survives_manager_restart(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    store = RunStore(workspace, state_root=state_root)
    store.save([_record()])

    manager = AgentRunManager(
        workspace,
        catalog=_Catalog(),
        review_collector=lambda: None,
        state_root=state_root,
    )
    restored = manager.get(_record()["run_id"])

    assert restored["plan_handoff"] == _handoff()
    assert restored["work_ref"] == {
        "spec_id": "SPEC-PLAN-1",
        "requirement_id": "R1",
        "governed_session_id": None,
    }
    assert restored["available_actions"] == ["review_plan"]
    manager.close()

    journal = next(state_root.glob("workspaces/*/runs.json")).read_text(encoding="utf-8")
    assert "repository_path" not in journal
    assert "prompt" not in journal
    assert "source_code" not in journal


def test_legacy_journal_without_plan_handoff_remains_readable(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    RunStore(workspace, state_root=state_root).save([_record(include_handoff=False)])

    manager = AgentRunManager(
        workspace,
        catalog=_Catalog(),
        review_collector=lambda: None,
        state_root=state_root,
    )
    restored = manager.get(_record()["run_id"])

    assert restored["status"] == "succeeded"
    assert restored["plan_handoff"] is None
    manager.close()


def test_plan_handoff_rejects_unbounded_or_unsafe_projection(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    store = RunStore(workspace, state_root=tmp_path / "state")
    unsafe = _record()
    unsafe["plan_handoff"] = {**_handoff(), "repository_path": "/Users/private/repo"}

    with pytest.raises(RunJournalError, match="forbidden fields"):
        store.save([unsafe])

    invalid = _record()
    invalid["plan_handoff"] = {**_handoff(), "requirement_ids": []}
    with pytest.raises(RunJournalError, match="requirements"):
        store.save([invalid])
