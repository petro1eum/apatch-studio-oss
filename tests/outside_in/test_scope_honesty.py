from __future__ import annotations

import json
from pathlib import Path

from apatch_studio.agent_runs import AgentRunManager
from apatch_studio.operations import AgentRunRequest
from apatch_studio.scope_projection import empty_scope_outcome, update_scope_outcome


def _tool_event(name: str, result: dict) -> dict:
    return {
        "type": "item.completed",
        "item": {
            "type": "mcp_tool_call",
            "name": name,
            "result": result,
        },
    }


def test_scope_stays_pending_until_an_explicit_clean_audit() -> None:
    planned = update_scope_outcome(
        empty_scope_outcome(),
        _tool_event(
            "mcp__apatch__apatch_execute_next",
            {
                "planned_paths": [
                    "frontend/src/Home.tsx",
                    "tests/outside_in/test_home.py",
                ]
            },
        ),
    )
    assert planned == {
        "schema": "apatch.studio.scope-outcome.v1",
        "status": "pending",
        "audit_observed": False,
        "planned_file_count": 2,
        "logical_areas": ["frontend", "tests"],
        "blocked_out_of_scope": 0,
        "reverted_out_of_scope": 0,
        "unresolved_out_of_scope": 0,
    }

    clean = update_scope_outcome(
        planned,
        _tool_event(
            "mcp__apatch__apatch_sandbox_audit",
            {
                "ok": True,
                "scanned_violations": 0,
                "violations": [],
                "reverted_tracked": [],
                "removed_untracked": [],
                "revert_failed": [],
            },
        ),
    )
    assert clean["status"] == "clean"
    assert clean["audit_observed"] is True


def test_scope_counts_protection_without_leaking_repository_paths() -> None:
    protected = update_scope_outcome(
        empty_scope_outcome(),
        _tool_event(
            "mcp__apatch__apatch_sandbox_audit",
            {
                "ok": True,
                "scanned_violations": 2,
                "violations": [
                    {"file": "/Users/person/private/client.py"},
                    {"file": "/Users/person/private/secret.env"},
                ],
                "reverted_tracked": ["/Users/person/private/client.py"],
                "removed_untracked": ["/Users/person/private/secret.env"],
                "revert_failed": [],
            },
        ),
    )
    assert protected["status"] == "protected"
    assert protected["blocked_out_of_scope"] == 2
    assert protected["reverted_out_of_scope"] == 2
    assert protected["unresolved_out_of_scope"] == 0
    serialized = json.dumps(protected)
    assert "/Users/" not in serialized
    assert "client.py" not in serialized
    assert "secret.env" not in serialized


def test_unresolved_scope_violation_never_claims_clean() -> None:
    result = update_scope_outcome(
        empty_scope_outcome(),
        _tool_event(
            "mcp__apatch__apatch_sandbox_audit",
            {
                "ok": False,
                "scanned_violations": 3,
                "reverted_count": 1,
                "revert_failed": ["sensitive/location"],
            },
        ),
    )
    assert result["status"] == "attention"
    assert result["unresolved_out_of_scope"] == 2


def test_run_projection_persists_only_bounded_scope_truth(tmp_path: Path) -> None:
    workspace = tmp_path / "repo"
    workspace.mkdir()
    manager = AgentRunManager(
        workspace,
        state_root=tmp_path / "state",
        catalog=_UnavailableCatalog(),
    )
    record = manager._restore_record(
        {
            "run_id": "apr_" + "1" * 32,
            "request": AgentRunRequest(
                mode="new_change",
                runner="codex",
                objective="Make the requested behavior true",
                acceptance_criteria=["The behavior is verified"],
            ).model_dump(),
            "execution_context": None,
            "retry_of": None,
            "status": "succeeded",
            "phase": "complete",
            "created_at": "2026-09-01T00:00:00+00:00",
            "started_at": None,
            "ended_at": "2026-09-01T00:01:00+00:00",
            "outcome": "complete",
            "message": "complete",
            "thread_id": None,
            "event_count": 1,
            "review": None,
            "timeline": [],
            "reviewer_note": None,
            "contribution": None,
            "scope": update_scope_outcome(
                empty_scope_outcome(),
                _tool_event(
                    "mcp__apatch__apatch_sandbox_audit",
                    {"ok": True, "scanned_violations": 0},
                ),
            ),
            "updated_at": "2026-09-01T00:01:00+00:00",
        }
    )
    projection = manager._project(record)
    assert projection["scope"]["status"] == "clean"
    assert set(projection["scope"]) == {
        "schema",
        "status",
        "audit_observed",
        "planned_file_count",
        "logical_areas",
        "blocked_out_of_scope",
        "reverted_out_of_scope",
        "unresolved_out_of_scope",
    }
    manager.close()


class _UnavailableCatalog:
    def projection(self) -> list[dict]:
        return []

    def command(self, runner: str, workspace: Path) -> list[str]:
        raise AssertionError("runner is not used")
