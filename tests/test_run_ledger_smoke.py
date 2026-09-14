import json
import stat
import subprocess
import sys
from pathlib import Path

from apatch_studio.agent_runs import AgentRunManager
from apatch_studio.operations import AgentRunRequest
from apatch_studio.run_store import RunStore


class DisposableCatalog:
    def projection(self):
        return [{"id": "codex", "label": "Disposable process", "available": True}]

    def command(self, runner, workspace):
        assert runner == "codex"
        leaked_event = json.dumps(
            {
                "type": "thread.started",
                "thread_id": "opaque-smoke-thread",
                "raw": (
                    "PRIVATE_KEY=top-secret "
                    f"path={workspace / 'module.py'} "
                    "prompt=raw transcript must never persist"
                ),
            }
        )
        completed_event = json.dumps({"type": "turn.completed"})
        script = (
            "import sys; sys.stdin.read(); "
            f"print({leaked_event!r}); "
            f"print({completed_event!r})"
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


def test_completed_run_survives_manager_recreation_without_source_or_transcript(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    git(workspace, "init", "-q")
    git(workspace, "config", "user.name", "APatch Studio Test")
    git(workspace, "config", "user.email", "studio@example.invalid")
    source = workspace / "module.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    git(workspace, "add", "module.py")
    git(workspace, "commit", "-q", "-m", "fixture")

    before_bytes = source.read_bytes()
    before_head = git(workspace, "rev-parse", "HEAD")
    assert git(workspace, "status", "--porcelain") == ""

    request = AgentRunRequest.model_validate(
        {
            "mode": "specification",
            "runner": "codex",
            "objective": "Prove durable local run review",
            "spec_id": "SPEC-LEDGER-SMOKE-1",
        }
    )
    manager = AgentRunManager(
        workspace,
        state_root=state_root,
        catalog=DisposableCatalog(),
        max_concurrent=1,
    )
    try:
        completed = manager.wait(manager.start(request)["run_id"], timeout=5)
    finally:
        manager.close()

    assert completed["status"] == "succeeded"
    assert completed["thread_id"] == "opaque-smoke-thread"
    assert completed["persisted"] is True
    assert completed["review"]["baseline"] is not None
    assert completed["review"]["result"] is not None
    assert completed["review"]["attribution"] == "workspace_observation_only"

    store = RunStore(workspace, state_root=state_root)
    payload = store.journal_path.read_text(encoding="utf-8")
    document = json.loads(payload)
    assert document["records"][0]["run_id"] == completed["run_id"]
    assert stat.S_IMODE(store.directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.journal_path.stat().st_mode) == 0o600
    assert not store.journal_path.is_relative_to(workspace)
    for forbidden in (
        "PRIVATE_KEY",
        "top-secret",
        str(workspace),
        "module.py",
        "raw transcript",
        "prompt=",
    ):
        assert forbidden not in payload

    restored_manager = AgentRunManager(
        workspace,
        state_root=state_root,
        catalog=DisposableCatalog(),
    )
    try:
        restored = restored_manager.get(completed["run_id"])
        journal = restored_manager.journal()
    finally:
        restored_manager.close()

    assert restored["status"] == "succeeded"
    assert restored["thread_id"] == completed["thread_id"]
    assert restored["review"] == completed["review"]
    assert journal["status"] == "ready"
    assert journal["record_count"] == 1
    assert source.read_bytes() == before_bytes
    assert git(workspace, "rev-parse", "HEAD") == before_head
    assert git(workspace, "status", "--porcelain") == ""
