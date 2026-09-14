import json
import subprocess
import sys

from apatch_studio.agent_runs import AgentRunManager
from apatch_studio.operations import AgentRunRequest
from apatch_studio.run_review import WorkspaceReviewCollector, build_review
from apatch_studio.run_store import RunStore


class PythonCatalog:
    def projection(self):
        return [{"id": "codex", "label": "Test runner", "available": True}]

    def command(self, runner, workspace):
        assert runner == "codex"
        return [
            sys.executable,
            "-u",
            "-c",
            "import json,sys; sys.stdin.read(); print(json.dumps({'type':'result','raw':'never persist'}))",
        ]


def git(root, *args):
    return subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def init_repo(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    git(workspace, "init")
    git(workspace, "config", "user.email", "studio@example.invalid")
    git(workspace, "config", "user.name", "Studio Test")
    (workspace / "README.md").write_text("one\n", encoding="utf-8")
    git(workspace, "add", "README.md")
    git(workspace, "commit", "-m", "baseline")
    return workspace


def test_workspace_review_contains_only_aggregate_observations(tmp_path):
    workspace = init_repo(tmp_path)
    overview = {
        "summary": {"attested": 3, "stale_count": 1},
        "evidence": [{"id": "one"}, {"id": "two"}],
        "work_assets": {"count": 5},
    }
    collector = WorkspaceReviewCollector(workspace, overview_supplier=lambda: overview)
    baseline = collector.capture()
    (workspace / "README.md").write_text("one\ntwo\nthree\n", encoding="utf-8")
    result = collector.capture()
    review = build_review(baseline, result)

    assert review["attribution"] == "workspace_observation_only"
    assert review["delta"]["dirty_files"] == 1
    assert review["result"]["insertions"] == 2
    assert review["result"]["attested_requirements"] == 3
    assert review["result"]["evidence_events"] == 2
    serialized = json.dumps(review)
    assert "README.md" not in serialized
    assert str(workspace) not in serialized
    assert "one\\ntwo" not in serialized


def test_run_manager_persists_before_after_review(tmp_path):
    workspace = init_repo(tmp_path)
    observations = iter([
        {
            "schema": "apatch.studio.workspace-observation.v1",
            "captured_at": "2026-08-31T00:00:00+00:00",
            "branch": "main",
            "head": "111111111111",
            "dirty_files": 0,
            "insertions": 0,
            "deletions": 0,
            "attested_requirements": 1,
            "stale_requirements": 0,
            "evidence_events": 1,
            "work_assets": 0,
        },
        {
            "schema": "apatch.studio.workspace-observation.v1",
            "captured_at": "2026-08-31T00:00:02+00:00",
            "branch": "main",
            "head": "111111111111",
            "dirty_files": 2,
            "insertions": 7,
            "deletions": 1,
            "attested_requirements": 2,
            "stale_requirements": 0,
            "evidence_events": 3,
            "work_assets": 1,
        },
    ])
    request = AgentRunRequest.model_validate({
        "mode": "new_change",
        "runner": "codex",
        "objective": "Deliver a reviewed local change",
        "acceptance_criteria": ["The review delta is durable"],
    })
    manager = AgentRunManager(
        workspace,
        state_root=tmp_path / "state",
        catalog=PythonCatalog(),
        review_collector=lambda: next(observations),
    )
    completed = manager.wait(manager.start(request)["run_id"], timeout=3)
    assert completed["review"]["delta"]["insertions"] == 7
    assert completed["review"]["delta"]["attested_requirements"] == 1
    manager.close()

    stored = RunStore(workspace, state_root=tmp_path / "state").load().records
    assert stored[0]["review"] == completed["review"]
    assert "never persist" not in json.dumps(stored)
