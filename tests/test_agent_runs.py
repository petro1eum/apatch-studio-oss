import json
from pathlib import Path
import sys
import time

from apatch_studio.agent_runs import AgentRunManager, RunnerCatalog, build_governed_prompt
from apatch_studio.operations import AgentRunRequest
from apatch_studio.run_store import RECORD_SCHEMA, RunStore


class PythonCatalog:
    def __init__(self, code: str):
        self.code = code

    def projection(self):
        return [{"id": "codex", "label": "Test runner", "available": True}]

    def command(self, runner, workspace):
        assert runner == "codex"
        return [sys.executable, "-u", "-c", self.code]


def request(mode="new_change"):
    payload = {
        "mode": mode,
        "runner": "codex",
        "objective": "Deliver a bounded deterministic change",
    }
    if mode == "new_change":
        payload["acceptance_criteria"] = ["The focused verification passes"]
    elif mode == "requirement":
        payload.update(spec_id="SPEC-DEMO-1", requirement_id="R2")
    else:
        payload["governed_session_id"] = "apatch_sess_1234_a1b2c3"
    return AgentRunRequest.model_validate(payload)


def make_manager(tmp_path, *, catalog, **kwargs):
    workspace = tmp_path / "workspace"
    workspace.mkdir(exist_ok=True)
    return AgentRunManager(
        workspace,
        catalog=catalog,
        state_root=tmp_path / "state",
        **kwargs,
    )


def wait_for_status(manager, run_id, expected, timeout=3.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        current = manager.get(run_id)
        if current["status"] in expected:
            return current
        time.sleep(0.02)
    raise AssertionError(f"run never reached {expected}: {manager.get(run_id)}")


def test_runner_catalog_and_argv_are_allowlisted():
    locations = {
        "codex": "/fixed/bin/codex",
        "claude": "/fixed/bin/claude",
    }
    catalog = RunnerCatalog(which=locations.get)
    workspace = Path("/fixed/workspace")

    assert catalog.projection() == [
        {"id": "codex", "label": "Codex", "available": True},
        {"id": "claude", "label": "Claude Code", "available": True},
    ]
    codex = catalog.command("codex", workspace)
    claude = catalog.command("claude", workspace)

    assert codex == [
        "/fixed/bin/codex",
        "exec",
        "--json",
        "--color",
        "never",
        "--cd",
        "/fixed/workspace",
        "--approve-for-me",
        *RunnerCatalog._codex_mcp_overrides(workspace),
        "-",
    ]
    assert claude == [
        "/fixed/bin/claude",
        "--print",
        "--output-format",
        "stream-json",
        "--verbose",
        "--permission-mode",
        "auto",
        "--mcp-config",
        json.dumps({"mcpServers": {"apatch": RunnerCatalog.apatch_mcp_server(workspace)}}, sort_keys=True),
        "--strict-mcp-config",
    ]
    joined = " ".join(codex + claude)
    assert "dangerously-bypass" not in joined
    assert "bypassPermissions" not in joined


def test_run_lifecycle_and_cancel(tmp_path):
    complete_code = (
        "import json,sys; sys.stdin.read(); "
        "print(json.dumps({'type':'thread.started','thread_id':'opaque-thread'})); "
        "print(json.dumps({'type':'turn.completed'}))"
    )
    manager = make_manager(tmp_path, catalog=PythonCatalog(complete_code), max_concurrent=1)
    started = manager.start(request("requirement"))
    completed = manager.wait(started["run_id"], timeout=3)

    assert started["status"] in {"queued", "running"}
    assert completed["status"] == "succeeded"
    assert completed["outcome"] == "complete"
    assert completed["thread_id"] == "opaque-thread"
    assert completed["started_at"] and completed["ended_at"]
    assert completed["persisted"] is True
    manager.close()

    slow_code = "import sys,time; sys.stdin.read(); print('{}', flush=True); time.sleep(30)"
    manager = make_manager(tmp_path, catalog=PythonCatalog(slow_code), max_concurrent=1)
    active = manager.start(request())
    wait_for_status(manager, active["run_id"], {"running"})
    manager.cancel(active["run_id"])
    cancelled = manager.wait(active["run_id"], timeout=3)

    assert cancelled["status"] == "cancelled"
    assert cancelled["can_retry"] is True
    retried = manager.retry(active["run_id"])
    assert retried["retry_of"] == active["run_id"]
    manager.cancel(retried["run_id"])
    manager.wait(retried["run_id"], timeout=3)
    manager.close()


def test_restart_marks_inflight_interrupted_and_allows_retry(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    run_id = "apr_00000000000000000000000000000001"
    stored = {
        "schema": RECORD_SCHEMA,
        "run_id": run_id,
        "request": request("requirement").model_dump(),
        "retry_of": None,
        "status": "running",
        "phase": "working",
        "created_at": "2026-08-31T00:00:00+00:00",
        "started_at": "2026-08-31T00:00:01+00:00",
        "ended_at": None,
        "outcome": None,
        "message": "Agent is working through APatch",
        "thread_id": "opaque-thread",
        "event_count": 3,
        "review": None,
        "updated_at": "2026-08-31T00:00:01+00:00",
    }
    RunStore(workspace, state_root=state_root).save([stored])
    code = "import json,sys; sys.stdin.read(); print(json.dumps({'type':'result'}))"
    manager = AgentRunManager(
        workspace,
        state_root=state_root,
        catalog=PythonCatalog(code),
    )

    interrupted = manager.get(run_id)
    assert interrupted["status"] == "interrupted"
    assert interrupted["outcome"] == "studio_restart"
    assert interrupted["can_retry"] is True
    assert manager.journal()["status"] == "reconciled"
    assert manager.journal()["interrupted_on_start"] == 1

    retried = manager.retry(run_id)
    completed = manager.wait(retried["run_id"], timeout=3)
    assert completed["status"] == "succeeded"
    assert completed["retry_of"] == run_id
    manager.close()


def test_prompts_enforce_apatch_lifecycle():
    prompts = [
        build_governed_prompt(request("new_change")),
        build_governed_prompt(request("requirement")),
        build_governed_prompt(request("recovery")),
    ]
    for prompt in prompts:
        lowered = prompt.lower()
        assert "apatch doctor" in lowered
        assert "governed" in lowered
        assert "verify" in lowered
        assert "attestation" in lowered
        assert "rollback" in lowered
        assert "never push" in lowered
        assert "deploy" in lowered

    assert "SPEC-DEMO-1" in prompts[1] and "R2" in prompts[1]
    assert "apatch_recover" in prompts[2]
    assert "apatch_sess_1234_a1b2c3" in prompts[2]


def test_safe_projection_redacts_raw_runner_output(tmp_path):
    secret_line = {
        "type": "thread.started",
        "thread_id": "opaque-thread",
        "raw": "PRIVATE_KEY=/secret source=/Users/person/repo prompt=do-the-thing",
    }
    code = (
        "import json,sys; sys.stdin.read(); "
        f"print({json.dumps(json.dumps(secret_line))})"
    )
    manager = make_manager(tmp_path, catalog=PythonCatalog(code))
    completed = manager.wait(manager.start(request("requirement"))["run_id"], timeout=3)
    serialized = json.dumps(completed)

    assert completed["status"] == "succeeded"
    assert completed["objective"] == "Deliver a bounded deterministic change"
    assert completed["thread_id"] == "opaque-thread"
    for forbidden in [
        "PRIVATE_KEY",
        "/Users/person/repo",
        "do-the-thing",
        "session_token",
        "argv",
        "cwd",
        "pid",
    ]:
        assert forbidden not in serialized


def test_retry_transports_saved_reviewer_feedback_without_changing_request(tmp_path):
    captured = tmp_path / "runner-prompts.jsonl"
    code = (
        "import json,sys; from pathlib import Path; "
        f"p=Path({str(captured)!r}); "
        "text=sys.stdin.read(); "
        "p.open('a').write(json.dumps(text)+'\\n'); sys.exit(1)"
    )
    manager = make_manager(tmp_path, catalog=PythonCatalog(code))
    original = request("requirement")
    first = manager.wait(manager.start(original)["run_id"], timeout=3)
    assert first["status"] == "failed"
    note = "Owner approved only the isolated Studio product test; preserve the frozen checks and scope."
    manager.save_reviewer_note(first["run_id"], note)
    # Feedback must survive Studio restart and reach the actual retry stdin.
    manager.close()
    manager = make_manager(tmp_path, catalog=PythonCatalog(code))
    retried = manager.retry(first["run_id"])
    completed = manager.wait(retried["run_id"], timeout=3)
    assert completed["status"] == "failed"
    prompts = [json.loads(line) for line in captured.read_text().splitlines()]
    assert len(prompts) == 2
    assert note not in prompts[0]
    assert note in prompts[1]
    assert "does not amend the frozen contract or task authority" in prompts[1]
    assert completed["objective"] == original.objective
    assert completed["retry_of"] == first["run_id"]
    records = RunStore(tmp_path / "workspace", state_root=tmp_path / "state").load()
    assert all(row["request"] == original.model_dump() for row in records.records)
    manager.close()
