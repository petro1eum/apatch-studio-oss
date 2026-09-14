from pathlib import Path
import subprocess
import sys

from apatch_studio.agent_runs import AgentRunManager
from apatch_studio.operations import AgentRunRequest


class DisposableProcessCatalog:
    def projection(self):
        return [{"id": "codex", "label": "Disposable process", "available": True}]

    def command(self, runner, workspace):
        assert runner == "codex"
        script = (
            "import json,sys; prompt=sys.stdin.read(); "
            "assert 'APatch doctor' in prompt; "
            "print(json.dumps({'type':'thread.started','thread_id':'smoke-thread'})); "
            "print(json.dumps({'type':'turn.completed'}))"
        )
        return [sys.executable, "-u", "-c", script]


def git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def test_disposable_managed_process_does_not_mutate_source(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    git(workspace, "init", "-q")
    source = workspace / "module.py"
    source.write_text("VALUE = 1\\n", encoding="utf-8")
    git(workspace, "add", "module.py")
    git(
        workspace,
        "-c",
        "user.name=APatch Studio Test",
        "-c",
        "user.email=studio@example.invalid",
        "commit",
        "-q",
        "-m",
        "fixture",
    )
    before_bytes = source.read_bytes()
    before_head = git(workspace, "rev-parse", "HEAD")
    assert git(workspace, "status", "--porcelain") == ""

    manager = AgentRunManager(
        workspace,
        state_root=tmp_path / "state",
        catalog=DisposableProcessCatalog(),
        max_concurrent=1,
    )
    request = AgentRunRequest.model_validate(
        {
            "mode": "specification",
            "runner": "codex",
            "objective": "Inspect the disposable workspace without changing source",
            "spec_id": "SPEC-SMOKE-1",
        }
    )
    completed = manager.wait(manager.start(request)["run_id"], timeout=5)
    manager.close()

    assert completed["status"] == "succeeded"
    assert completed["thread_id"] == "smoke-thread"
    assert source.read_bytes() == before_bytes
    assert git(workspace, "rev-parse", "HEAD") == before_head
    assert git(workspace, "status", "--porcelain") == ""
