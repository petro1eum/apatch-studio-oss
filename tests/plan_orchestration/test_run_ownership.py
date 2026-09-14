from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from apatch_studio.agent_runs import (
    AgentRunManager,
    build_governed_prompt,
    cleanup_planning_session,
    planning_contract_ids,
    planning_lane_for_run,
)
from apatch_studio.operations import AgentRunRequest
from apatch_studio.scope_projection import (
    empty_scope_outcome,
    scope_violation_fingerprints,
    update_scope_outcome,
)


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


def _tool_event(name: str, result: dict[str, object]) -> dict[str, object]:
    return {
        "type": "item.completed",
        "item": {
            "type": "mcp_tool_call",
            "server": "apatch",
            "tool": name,
            "result": result,
        },
    }


def _request() -> AgentRunRequest:
    return AgentRunRequest.model_validate({
        "mode": "new_change",
        "runner": "codex",
        "objective": "Prepare one bounded contract",
        "acceptance_criteria": ["The owner can review exact checks"],
    })


def test_prompt_binds_exact_owned_lane_and_forbids_sibling_recovery() -> None:
    run_id = "apr_11111111111111111111111111111111"
    lane = planning_lane_for_run(run_id)
    rfp_id, spec_id = planning_contract_ids(run_id)
    prompt = build_governed_prompt(_request(), studio_run_id=run_id)

    assert lane in prompt
    assert rfp_id == "RFP-STUDIO-111111111111"
    assert spec_id == "SPEC-STUDIO-CHANGE-111111111111"
    assert rfp_id in prompt and spec_id in prompt
    assert "Never recover, resume, attest, roll back or close a pre-existing or sibling session" in prompt
    assert run_id in prompt



def test_retry_uses_fresh_lane_and_root_contract_identity(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    code = (
        "import os,pathlib,sys; "
        "pathlib.Path(os.environ['APATCH_LANE'] + '.txt').write_text(sys.stdin.read()); "
        "raise SystemExit(1)"
    )
    manager = AgentRunManager(
        workspace,
        catalog=_CodeCatalog(code),
        plan_handoff_collector=_NeverCollector(),
        review_collector=lambda: None,
        state_root=tmp_path / "state",
    )
    first = manager.start(_request())
    manager.wait(first["run_id"], timeout=3)
    retried = manager.retry(first["run_id"])
    manager.wait(retried["run_id"], timeout=3)

    retry_prompt = (workspace / f"{planning_lane_for_run(retried['run_id'])}.txt").read_text()
    root_rfp, root_spec = planning_contract_ids(first["run_id"])
    retry_rfp, retry_spec = planning_contract_ids(retried["run_id"])
    assert planning_lane_for_run(retried["run_id"]) in retry_prompt
    assert root_rfp in retry_prompt and root_spec in retry_prompt
    assert retry_rfp not in retry_prompt and retry_spec not in retry_prompt
    assert "prior exact contract lineage" in retry_prompt
    assert "must write exactly one new review-package revision" in retry_prompt
    assert "mutate only the preparation-package JSON" in retry_prompt
    assert "do not rewrite RFP or SPEC planning labels" in retry_prompt
    assert "never guess a Markdown anchor" in retry_prompt
    assert "Never call apatch_execute_next with an empty needles list" in retry_prompt
    assert "an unchanged preparation package is a failed retry" in retry_prompt
    manager.close()


def test_retry_scope_does_not_blame_preexisting_sandbox_violations() -> None:
    existing = [
        {"path": "AGENTS.md", "sha256": "a" * 64, "reason": "direct_write_blocked"},
        {
            "path": "docs/specs/SPEC-TEMPLATE.md",
            "sha256": "b" * 64,
            "reason": "direct_write_blocked",
        },
    ]
    baseline = scope_violation_fingerprints(existing)
    unchanged = update_scope_outcome(
        empty_scope_outcome(),
        _tool_event(
            "mcp__apatch__apatch_sandbox_audit",
            {
                "ok": False,
                "scanned_violations": 2,
                "violations": existing,
                "reverted_tracked": [],
                "removed_untracked": [],
                "revert_failed": [],
            },
        ),
        baseline_violations=baseline,
    )
    assert unchanged["status"] == "clean"
    assert unchanged["blocked_out_of_scope"] == 0
    assert unchanged["unresolved_out_of_scope"] == 0

    current = [
        *existing,
        {"path": "src/new.py", "sha256": "c" * 64, "reason": "direct_write_blocked"},
    ]
    changed = update_scope_outcome(
        empty_scope_outcome(),
        _tool_event(
            "mcp__apatch__apatch_sandbox_audit",
            {
                "ok": False,
                "scanned_violations": 3,
                "violations": current,
                "reverted_tracked": [],
                "removed_untracked": [],
                "revert_failed": [],
            },
        ),
        baseline_violations=baseline,
    )
    assert changed["status"] == "attention"
    assert changed["blocked_out_of_scope"] == 1
    assert changed["unresolved_out_of_scope"] == 1
    serialized = json.dumps(changed)
    assert "AGENTS.md" not in serialized
    assert "src/new.py" not in serialized

def test_timeout_injects_owned_lane_and_calls_exact_cleanup(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    seen: dict[str, str] = {}
    cleanup_calls: list[str] = []
    code = "import sys,time; sys.stdin.read(); time.sleep(20)"

    def popen(argv, **kwargs):
        seen["lane"] = kwargs["env"]["APATCH_LANE"]
        return subprocess.Popen(argv, **kwargs)

    manager = AgentRunManager(
        workspace,
        catalog=_CodeCatalog(code),
        plan_handoff_collector=_NeverCollector(),
        review_collector=lambda: None,
        state_root=tmp_path / "state",
        popen=popen,
        planning_session_cleanup=lambda run_id: cleanup_calls.append(run_id) or "closed",
        planning_stall_seconds=0.05,
        planning_timeout_seconds=0.15,
    )
    started = manager.start(_request())
    result = manager.wait(started["run_id"], timeout=3)

    assert seen["lane"] == planning_lane_for_run(started["run_id"])
    assert cleanup_calls == [started["run_id"]]
    assert result["planning"]["cleanup"] == "closed"
    manager.close()


def test_cleanup_recovers_only_exact_owned_lane(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    run_id = "apr_22222222222222222222222222222222"
    own_session = "apatch_sess_1000_aaaaaaaaaaaa"
    sibling_session = "apatch_sess_2000_bbbbbbbbbbbb"
    own_path = workspace / ".apatch" / "lanes" / planning_lane_for_run(run_id) / "session_state.json"
    sibling_path = workspace / ".apatch" / "lanes" / "sibling" / "session_state.json"
    own_path.parent.mkdir(parents=True)
    sibling_path.parent.mkdir(parents=True)
    own_path.write_text(json.dumps({"session_id": own_session, "checkpoint": "checkpoint-own", "ended_at": None}), encoding="utf-8")
    sibling_path.write_text(json.dumps({"session_id": sibling_session, "checkpoint": "checkpoint-sibling", "ended_at": None}), encoding="utf-8")
    calls: list[tuple[str, str]] = []

    class _Runtime:
        def __init__(self, target_dir, *, session_id=None, session_token=None, enforce_binding=False):
            assert Path(target_dir) == workspace
            assert session_id == own_session
            self.session_id = session_id

        def recover_session(self):
            calls.append(("recover", self.session_id))
            return {"ok": True, "recovery": "resumed", "session_token": "rotated-token"}

        def rollback(self, session_id=None, *, preview=False):
            assert session_id is None
            calls.append(("rollback", self.session_id))
            return {"ok": True}

        def close_session(self):
            calls.append(("close", self.session_id))
            return {"ok": True}

    monkeypatch.setattr("apatch.runtime.runtime.MutationRuntime", _Runtime)

    assert cleanup_planning_session(workspace, run_id) == "rolled_back"
    assert calls == [("recover", own_session), ("rollback", own_session), ("close", own_session)]
    assert json.loads(sibling_path.read_text(encoding="utf-8"))["session_id"] == sibling_session
