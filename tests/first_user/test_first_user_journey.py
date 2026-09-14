import json
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from apatch_studio.agent_runs import AgentRunManager
from apatch_studio.app import create_app


ROOT = Path(__file__).resolve().parents[2]
_RUNNER = r'''
import json
import sys
from pathlib import Path

sys.stdin.read()
root = Path.cwd()
spec_id = "SPEC-FIRST-USER-1"
spec = root / "docs" / "specs" / f"{spec_id}.md"
spec.parent.mkdir(parents=True, exist_ok=True)
spec.write_text(
    "# SPEC-FIRST-USER-1 - First user plan\n\n"
    "> **apatch artifact:** `spec:SPEC-FIRST-USER-1`\n\n"
    "## R1 Reviewable plan\n\n"
    "(verify: python3 -m pytest -q)\n",
    encoding="utf-8",
)
prepared = root / ".apatch" / "sdd" / "prepared" / f"{spec_id}.json"
prepared.parent.mkdir(parents=True, exist_ok=True)
prepared.write_text(
    json.dumps(
        {
            "schema": "apatch.studio.sdd-preparation.v1",
            "spec_id": spec_id,
            "objective": "Prepare a verified delivery pack",
            "prepared_at": "2026-09-02T10:00:00+00:00",
            "source_mutation_count": 0,
            "contract_request": {"obligations": []},
            "task_envelopes": {"R1": {"requirement": f"{spec_id}#R1"}},
        },
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
print(json.dumps({"type": "thread.started", "thread_id": "first-user-journey"}))
print(json.dumps({"type": "turn.completed"}))
'''


class _JourneyCatalog:
    def projection(self):
        return [
            {"id": "codex", "label": "Codex", "available": True},
            {"id": "claude", "label": "Claude Code", "available": False},
        ]

    def command(self, runner, _workspace):
        assert runner == "codex"
        return [sys.executable, "-u", "-c", _RUNNER]


def test_home_explains_plan_preparation_and_exact_requirement_execution() -> None:
    source = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")

    assert "Prepare plan" in source
    assert "Run requirement" in source
    assert "Studio first prepares a reviewable plan and verification contract." in source
    assert "Run only the selected planned item through its frozen checks." in source
    assert "Run with agent" not in source


def test_first_user_can_start_plan_preparation_through_the_real_api(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    (workspace / ".apatch").mkdir()
    manager = AgentRunManager(
        workspace,
        catalog=_JourneyCatalog(),
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
        response = client.post(
            "/api/v1/runs",
            headers=headers,
            json={
                "mode": "new_change",
                "runner": "codex",
                "objective": "Prepare a verified delivery pack",
                "acceptance_criteria": ["The plan is ready for owner review"],
            },
        )
        assert response.status_code == 202
        completed = manager.wait(response.json()["run_id"], timeout=3)

    assert completed["status"] == "succeeded"
    assert completed["mode"] == "new_change"
    assert completed["thread_id"] == "first-user-journey"
    assert completed["outcome"] == "plan_ready"
    assert completed["message"] == (
        "Plan is ready for owner review; nothing in the project was changed"
    )
    assert completed["plan_handoff"]["spec_id"] == "SPEC-FIRST-USER-1"
    assert completed["plan_handoff"]["requirement_ids"] == ["R1"]
    assert completed["available_actions"] == ["review_plan"]


def test_readme_describes_the_public_oss_product_without_claiming_pro_code() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "APatch Studio OSS is the local workspace" in readme
    assert "useful without an account, subscription or network connection" in readme
    assert "contains no organization control plane" in readme
