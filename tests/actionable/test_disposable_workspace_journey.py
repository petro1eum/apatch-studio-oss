import json
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from apatch.trustchain_helper import TrustChainHelper
from apatch_studio.agent_runs import AgentRunManager
from apatch_studio.app import create_app


_RUNNER = r'''
import json
import sys
from pathlib import Path

from apatch.ingestor import PatchCandidate
from apatch.trustchain_helper import TrustChainHelper
from apatch.tui import InteractiveTUI

sys.stdin.read()
root = Path.cwd()
print(json.dumps({"type": "thread.started", "thread_id": "disposable-journey"}), flush=True)
TrustChainHelper(str(root), auto_init=True)
print(json.dumps({"type": "tool", "tool_name": "apatch_apply"}), flush=True)
InteractiveTUI(
    [PatchCandidate(
        step_index=1,
        tool_name="replace_file_content",
        target_file="app.py",
        old_content="value = 1",
        new_content="value = 2",
    )],
    str(root),
    non_interactive=True,
    quiet=True,
).run_apply_loop()
print(json.dumps({"type": "tool", "tool_name": "apatch_verify"}), flush=True)
print(json.dumps({"type": "turn.completed"}), flush=True)
'''


class JourneyCatalog:
    def projection(self):
        return [
            {"id": "codex", "label": "Disposable governed runner", "available": True},
            {"id": "claude", "label": "Claude Code", "available": False},
        ]

    def command(self, runner, _workspace):
        assert runner == "codex"
        return [sys.executable, "-c", _RUNNER]


def _git(root: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _ready_workspace(root: Path) -> None:
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    _git(root, "config", "user.name", "APatch Studio test")
    _git(root, "config", "user.email", "studio-test@example.invalid")
    (root / ".apatch").mkdir()
    (root / ".apatch/mcp.json").write_text(
        json.dumps({"mcpServers": {}}) + "\n", encoding="utf-8"
    )
    (root / "AGENTS.md").write_text("# Disposable governed workspace\n", encoding="utf-8")
    (root / "app.py").write_text("value = 1\n", encoding="utf-8")
    _git(root, "add", ".apatch/mcp.json", "AGENTS.md", "app.py")
    _git(root, "commit", "-q", "-m", "baseline")
    TrustChainHelper(str(root), auto_init=True)


def test_disposable_oss_onboarding_run_review_and_verified_evidence(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _ready_workspace(workspace)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))

    manager = AgentRunManager(
        workspace,
        catalog=JourneyCatalog(),
        max_concurrent=1,
        state_root=tmp_path / "run-state",
    )
    app = create_app(
        str(workspace),
        run_manager=manager,
        frontend_root=tmp_path / "missing-frontend",
        edition="oss",
    )
    headers = {
        "x-apatch-studio-session": app.state.studio_guard.token,
        "origin": "http://127.0.0.1:8765",
    }

    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        onboarding = client.post(
            "/api/v1/workspaces/actions",
            headers=headers,
            json={
                "request_id": "apsreq_journey_register_0001",
                "action": "register",
                "alias": "journey",
                "confirmed": True,
            },
        )
        assert onboarding.status_code == 200
        assert onboarding.json()["result"]["ready"] is True

        started = client.post(
            "/api/v1/runs",
            headers=headers,
            json={
                "mode": "specification",
                "runner": "codex",
                "objective": "Change the disposable application value",
                "spec_id": "SPEC-JOURNEY-1",
            },
        )
        assert started.status_code == 202
        completed = manager.wait(started.json()["run_id"], timeout=20)
        assert completed["status"] == "succeeded"
        assert completed["event_count"] >= 3
        assert completed["review"]["delta"]["dirty_files"] >= 1
        assert completed["review"]["attribution"] == "workspace_observation_only"
        assert (workspace / "app.py").read_text(encoding="utf-8") == "value = 2\n"

        verified = client.post(
            "/api/v1/evidence/actions",
            headers=headers,
            json={
                "request_id": "apsreq_journey_verify_000001",
                "action": "verify",
                "scope": "working_tree",
            },
        )
        assert verified.status_code == 200
        result = verified.json()["result"]
        assert result["ok"] is True
        assert result["checked"] == 1
        assert result["notarized_file_count"] == 1
        assert result["ledger_entries"] >= 2
        assert result["trustchain_active"] is True

        replay = client.post(
            "/api/v1/evidence/actions",
            headers=headers,
            json={
                "request_id": "apsreq_journey_verify_000001",
                "action": "verify",
                "scope": "working_tree",
            },
        )
        assert replay.json() == verified.json()
