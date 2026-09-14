from pathlib import Path
import sys

import pytest

from apatch_studio.agent_runs import AgentRunManager, apatch_phase_from_event, build_governed_prompt
from apatch_studio.operations import AgentRunRequest


ROOT = Path(__file__).resolve().parents[2]
SESSION_ID = "apatch_sess_1788195936380116000_7901e1e0cac2"


class FailingCatalog:
    def projection(self):
        return [{"id": "codex", "label": "Codex", "available": True}]

    def command(self, runner, workspace):
        assert runner == "codex"
        return [sys.executable, "-c", "import sys; sys.stdin.read(); raise SystemExit(2)"]


def test_work_accepts_exact_governed_modes_and_rejects_ambiguous_shape() -> None:
    payloads = [
        {
            "mode": "new_change",
            "runner": "codex",
            "objective": "Deliver the bounded outcome",
            "acceptance_criteria": ["The focused verification passes"],
        },
        {
            "mode": "requirement",
            "runner": "codex",
            "objective": "Execute the selected requirement",
            "spec_id": "SPEC-DEMO-1",
            "requirement_id": "R2",
        },
        {
            "mode": "recovery",
            "runner": "codex",
            "objective": "Recover exact governed work",
            "governed_session_id": SESSION_ID,
        },
        {
            "mode": "rollback_preview",
            "runner": "codex",
            "objective": "Preview exact checkpoint rollback",
            "governed_session_id": SESSION_ID,
        },
    ]
    assert [AgentRunRequest.model_validate(item).mode for item in payloads] == [
        "new_change",
        "requirement",
        "recovery",
        "rollback_preview",
    ]

    with pytest.raises(ValueError):
        AgentRunRequest.model_validate(
            {
                **payloads[-1],
                "spec_id": "SPEC-DEMO-1",
            }
        )


def test_rollback_preview_prompt_cannot_authorize_mutation() -> None:
    request = AgentRunRequest.model_validate(
        {
            "mode": "rollback_preview",
            "runner": "codex",
            "objective": "Inspect rollback impact",
            "governed_session_id": SESSION_ID,
        }
    )
    prompt = build_governed_prompt(request)

    assert "apatch_rollback with preview=true" in prompt
    assert "Do not execute rollback, mutate files, attest new work" in prompt
    assert SESSION_ID in prompt


def test_structured_apatch_events_project_real_lifecycle_phases() -> None:
    samples = {
        "apatch_execute_next": "planning",
        "apatch_apply_session": "applying",
        "apatch_verify_run": "verifying",
        "apatch_attest": "attesting",
        "apatch_recover": "recovering",
        "apatch_rollback": "rolling_back",
    }
    for tool, expected in samples.items():
        phase = apatch_phase_from_event(
            {"type": "item.started", "item": {"type": "mcp_tool_call", "tool": tool}}
        )
        assert phase is not None
        assert phase[0] == expected

    assert apatch_phase_from_event(
        {"type": "item.started", "item": {"tool": "read_file"}}
    ) is None


def test_failed_exact_session_run_exposes_safe_recovery_choices(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = AgentRunManager(
        workspace,
        catalog=FailingCatalog(),
        state_root=tmp_path / "state",
    )
    request = AgentRunRequest.model_validate(
        {
            "mode": "recovery",
            "runner": "codex",
            "objective": "Recover exact governed work",
            "governed_session_id": SESSION_ID,
        }
    )
    completed = manager.wait(manager.start(request)["run_id"], timeout=3)

    assert completed["status"] == "failed"
    assert completed["work_ref"] == {
        "spec_id": None,
        "requirement_id": None,
        "governed_session_id": SESSION_ID,
    }
    assert set(completed["available_actions"]) == {
        "open_review",
        "fix_forward",
        "recover",
        "rollback_preview",
    }
    assert "session_token" not in str(completed)
    manager.close()


def test_work_ui_unifies_start_progress_and_exact_recovery_actions() -> None:
    app = (ROOT / "frontend" / "src" / "OutsideInViews.tsx").read_text(encoding="utf-8")
    types = (ROOT / "frontend" / "src" / "types.ts").read_text(encoding="utf-8")

    for label in [
        '"new_change"',
        '"requirement"',
        '"recovery"',
        '"rollback_preview"',
        "Review result",
        "Recover",
        "Preview rollback",
    ]:
        assert label in app

    assert "apatch_phase_from_event" in (
        ROOT / "apatch_studio" / "agent_runs.py"
    ).read_text(encoding="utf-8")
    assert '"rollback_preview"' in types
    assert 'launchMode("recovery")' in app
