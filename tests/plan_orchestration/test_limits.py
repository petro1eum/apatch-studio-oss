from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

from apatch_studio.agent_runs import AgentRunManager
from apatch_studio.operations import AgentRunRequest


class _CodeCatalog:
    def __init__(self, code: str):
        self.code = code

    def projection(self):
        return [{"id": "codex", "label": "Test", "available": True}]

    def command(self, runner, workspace):
        return [sys.executable, "-u", "-c", self.code]


class _NeverCollector:
    def capture(self):
        return object()

    def resolve(self, before):
        raise AssertionError("partial planning output must never resolve")


def _request() -> AgentRunRequest:
    return AgentRunRequest.model_validate({
        "mode": "new_change",
        "runner": "codex",
        "objective": "Prepare one bounded contract",
        "acceptance_criteria": ["The owner can review exact checks"],
    })


def _manager(tmp_path: Path, code: str, **limits) -> AgentRunManager:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "application.py").write_text("sentinel = True\n", encoding="utf-8")
    return AgentRunManager(
        workspace,
        catalog=_CodeCatalog(code),
        plan_handoff_collector=_NeverCollector(),
        review_collector=lambda: None,
        state_root=tmp_path / "state",
        **limits,
    )


def test_discovery_budget_stops_first_over_budget_pre_contract_inspection_and_preserves_source(tmp_path: Path) -> None:
    event = json.dumps({"type": "item.started", "item": {"type": "command_execution"}})
    code = "import sys,time; sys.stdin.read();\nfor _ in range(4): print(" + repr(event) + ", flush=True)\ntime.sleep(20)"
    manager = _manager(
        tmp_path,
        code,
        planning_inspection_limit=3,
        planning_stall_seconds=1,
        planning_timeout_seconds=5,
    )
    result = manager.wait(manager.start(_request())["run_id"], timeout=3)
    assert result["status"] == "failed"
    assert result["outcome"] == "plan_discovery_budget_exceeded"
    assert result["can_retry"] is True
    assert result["plan_handoff"] is None
    assert (tmp_path / "workspace" / "application.py").read_text(encoding="utf-8") == "sentinel = True\n"
    manager.close()


def test_soft_stall_then_hard_timeout_is_visible_retryable_and_source_safe(tmp_path: Path) -> None:
    code = "import json,sys,time; sys.stdin.read(); print(json.dumps({'type':'thread.started','thread_id':'opaque'}), flush=True); time.sleep(20)"
    manager = _manager(
        tmp_path,
        code,
        planning_stall_seconds=0.05,
        planning_timeout_seconds=0.15,
    )
    result = manager.wait(manager.start(_request())["run_id"], timeout=3)
    assert result["status"] == "failed"
    assert result["outcome"] == "plan_timeout"
    assert result["failure"]["headline"] == "Planning ran out of time"
    assert result["failure"]["retryable"] is True
    assert result["can_retry"] is True
    assert any(item["phase"] == "waiting" for item in result["timeline"])
    assert result["timeline"][-1]["phase"] == "complete"
    assert (tmp_path / "workspace" / "application.py").read_text(encoding="utf-8") == "sentinel = True\n"
    manager.close()


def test_planning_limit_boundaries_are_rejected(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises(ValueError):
        AgentRunManager(workspace, planning_inspection_limit=0, state_root=tmp_path / "s1")
    with pytest.raises(ValueError):
        AgentRunManager(workspace, planning_stall_seconds=5, planning_timeout_seconds=5, state_root=tmp_path / "s2")
