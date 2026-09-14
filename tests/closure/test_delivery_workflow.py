import json
from pathlib import Path
import subprocess

import pytest
from pydantic import ValidationError

from apatch_studio.action_facade import StudioWorkflowError
from apatch_studio.delivery_workflow import DeliveryActionRequest, GitDeliveryWorkflow


def _git(workspace: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=workspace,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _request(action: str, suffix: str, **fields):
    return DeliveryActionRequest.model_validate(
        {
            "request_id": "apsreq_delivery_" + suffix,
            "action": action,
            "confirmed": True,
            **fields,
        }
    )


def _repository(tmp_path):
    workspace = tmp_path / "workspace"
    remote = tmp_path / "remote.git"
    workspace.mkdir()
    _git(tmp_path, "init", "--bare", str(remote))
    _git(workspace, "init")
    _git(workspace, "config", "user.email", "test@example.com")
    _git(workspace, "config", "user.name", "APatch Test")
    source = workspace / "tracked.txt"
    source.write_text("base\n", encoding="utf-8")
    _git(workspace, "add", "tracked.txt")
    _git(workspace, "commit", "-m", "base")
    _git(workspace, "branch", "-M", "main")
    _git(workspace, "remote", "add", "origin", str(remote))
    _git(workspace, "push", "-u", "origin", "main")
    return workspace, remote


def test_delivery_commits_only_staged_notarized_set_and_pushes_current_branch(tmp_path):
    workspace, remote = _repository(tmp_path)
    tracked = workspace / "tracked.txt"
    tracked.write_text("staged\n", encoding="utf-8")
    _git(workspace, "add", "tracked.txt")
    tracked.write_text("staged\nuncommitted\n", encoding="utf-8")

    workflow = GitDeliveryWorkflow(
        workspace,
        state_root=tmp_path / "state",
        notarization=lambda _root, staged: {
            "ok": staged,
            "checked": 1,
            "violations": [],
        },
    )
    before = workflow.status()
    assert before["staged_count"] == 1
    assert before["unstaged_count"] == 1
    assert before["can_commit"] is True

    commit = workflow.act(
        _request("commit", "commit_001", message="Record governed staged change")
    )
    assert commit["result"]["committed_file_count"] == 1
    assert commit["result"]["notarization_checked"] == 1
    assert commit["result"]["remaining"]["unstaged_count"] == 1
    assert workflow.act(
        _request("commit", "commit_001", message="Record governed staged change")
    ) == commit
    assert workflow.status()["ahead"] == 1

    pushed = workflow.act(_request("push", "push_001"))
    assert pushed["result"]["pushed"] is True
    assert pushed["result"]["after"]["ahead"] == 0
    remote_head = subprocess.run(
        ["git", "rev-parse", "refs/heads/main"],
        cwd=remote,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert remote_head == commit["result"]["commit_id"]

    serialized = json.dumps([before, commit, pushed])
    assert str(workspace) not in serialized
    assert str(remote) not in serialized
    assert "tracked.txt" not in serialized


def test_delivery_fails_closed_without_exact_staged_notarization(tmp_path):
    workspace, _remote = _repository(tmp_path)
    (workspace / "tracked.txt").write_text("changed\n", encoding="utf-8")
    _git(workspace, "add", "tracked.txt")
    workflow = GitDeliveryWorkflow(
        workspace,
        state_root=tmp_path / "state",
        notarization=lambda _root, staged: {
            "ok": False,
            "checked": 0,
            "violations": [{"reason": "missing"}],
        },
    )
    with pytest.raises(StudioWorkflowError, match="notarization"):
        workflow.act(_request("commit", "denied_001", message="Should not commit"))
    assert workflow.status()["staged_count"] == 1


@pytest.mark.parametrize("field,value", [
    ("remote", "attacker"),
    ("ref", "refs/heads/other"),
    ("force", True),
    ("argv", ["git", "push", "--force"]),
    ("path", "/private/repo"),
])
def test_delivery_request_rejects_arbitrary_git_surface(field, value):
    with pytest.raises(ValidationError):
        DeliveryActionRequest.model_validate(
            {
                "request_id": "apsreq_delivery_invalid_001",
                "action": "push",
                "confirmed": True,
                field: value,
            }
        )


def test_review_ui_exposes_confirmed_delivery_without_generic_git():
    root = Path(__file__).resolve().parents[2]
    app = (root / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
    shell = (root / "frontend/src/OutsideInApp.tsx").read_text(encoding="utf-8")
    api = (root / "frontend/src/api.ts").read_text(encoding="utf-8")
    backend = (root / "apatch_studio/delivery_workflow.py").read_text(encoding="utf-8")

    for label in [">Commit<", ">Push<", ">Open PR<"]:
        assert label in app
    assert 'role="alertdialog"' in shell
    assert '["push", "--porcelain"]' in backend
    assert '"--force"' not in backend
    assert "/api/v1/delivery/actions" in api
