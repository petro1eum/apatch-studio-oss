from __future__ import annotations

import json
from pathlib import Path
import sys

from apatch_studio.agent_runs import AgentRunManager, runner_phase_from_event
from apatch_studio.operations import AgentRunRequest


class _Catalog:
    def projection(self):
        return [{"id": "codex", "label": "Test", "available": True}]

    def command(self, runner, workspace):
        event = json.dumps({"type": "item.started", "item": {"type": "command_execution", "command": "cat /Users/private/secret"}})
        code = "import json,sys; sys.stdin.read(); print(" + repr(event) + "); print(" + repr(event) + "); print(json.dumps({'type':'turn.completed'}))"
        return [sys.executable, "-u", "-c", code]


class _Collector:
    def capture(self):
        return object()

    def resolve(self, before):
        return {
            "schema": "apatch.studio.plan-handoff.v1",
            "status": "review_ready",
            "spec_id": "SPEC-PLAN-1",
            "requirement_ids": ["R1"],
            "objective": "Prepare one bounded contract",
            "prepared_at": "2026-09-02T10:00:00+00:00",
            "package_hash": "sha256:" + "a" * 64,
        }


def _request() -> AgentRunRequest:
    return AgentRunRequest.model_validate({
        "mode": "new_change",
        "runner": "codex",
        "objective": "Prepare one bounded contract",
        "acceptance_criteria": ["The owner can review exact checks"],
    })


def test_structured_runner_events_map_to_human_planning_stages() -> None:
    samples = [
        ({"type": "item.started", "item": {"type": "command_execution", "command": "private"}}, "inspecting"),
        ({"type": "item.started", "item": {"type": "file_change", "path": "/private"}}, "preparing_contract"),
        ({"type": "item.started", "item": {"type": "mcp_tool_call", "tool": "apatch_rfp_lint"}}, "preparing_contract"),
        ({"type": "item.started", "item": {"type": "mcp_tool_call", "tool": "apatch_verify_run"}}, "verifying"),
    ]
    for event, expected in samples:
        phase = runner_phase_from_event(event, mode="new_change")
        assert phase is not None
        assert phase[0] == expected


def test_private_runner_content_never_enters_progress_projection() -> None:
    event = {"type": "item.started", "item": {"type": "command_execution", "command": "TOKEN=secret /Users/private/repo"}}
    projected = runner_phase_from_event(event, mode="new_change")
    assert projected is not None
    assert "secret" not in json.dumps(projected)
    assert "/Users/private" not in json.dumps(projected)


def test_repeated_events_refresh_activity_but_keep_timeline_deduplicated(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = AgentRunManager(
        workspace,
        catalog=_Catalog(),
        plan_handoff_collector=_Collector(),
        review_collector=lambda: None,
        state_root=tmp_path / "state",
    )
    result = manager.wait(manager.start(_request())["run_id"], timeout=3)
    inspecting = [item for item in result["timeline"] if item["phase"] == "inspecting"]
    assert result["status"] == "succeeded"
    assert len(inspecting) == 1
    assert result["planning"]["inspection_events"] == 2
    assert result["planning"]["last_activity_at"]
    serialized = json.dumps(result)
    assert "/Users/private" not in serialized
    assert "TOKEN=secret" not in serialized
    manager.close()
