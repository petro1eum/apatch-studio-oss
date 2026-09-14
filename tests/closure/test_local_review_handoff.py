import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from pydantic import ValidationError

from apatch_studio.agent_runs import AgentRunManager, RunStateError
from apatch_studio.local_review import (
    LocalReviewHandoff,
    LocalReviewRequest,
    ReviewerNoteRequest,
)


class PythonCatalog:
    def projection(self):
        return [{"id": "codex", "label": "Test runner", "available": True}]

    def command(self, runner, workspace):
        assert runner == "codex"
        event = json.dumps(
            {
                "type": "item.completed",
                "item": {"tool_name": "mcp__apatch__apatch_verify"},
            }
        )
        return [
            sys.executable,
            "-u",
            "-c",
            "import sys; sys.stdin.read(); print(" + repr(event) + ")",
        ]


def _request():
    from apatch_studio.operations import AgentRunRequest

    return AgentRunRequest.model_validate(
        {
            "mode": "new_change",
            "runner": "codex",
            "objective": "Create a durable local review",
            "acceptance_criteria": ["The review remains private and actionable"],
        }
    )


def _git(workspace: Path, *args: str) -> None:
    subprocess.run(
        ["git", *args],
        cwd=workspace,
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def test_reviewer_note_and_phase_timeline_are_bounded_and_durable(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    manager = AgentRunManager(
        workspace,
        catalog=PythonCatalog(),
        state_root=state_root,
    )
    completed = manager.wait(manager.start(_request())["run_id"], timeout=3)
    updated = manager.save_reviewer_note(
        completed["run_id"],
        "  Verification passed; keep the exact requirement boundary.  ",
    )

    assert updated["reviewer_note"]["text"] == (
        "Verification passed; keep the exact requirement boundary."
    )
    assert any(event["phase"] == "verifying" for event in updated["timeline"])
    assert updated["timeline"][-1]["phase"] == "complete"
    assert len(updated["timeline"]) <= 64
    manager.close()

    restored = AgentRunManager(
        workspace,
        catalog=PythonCatalog(),
        state_root=state_root,
    ).get(completed["run_id"])
    assert restored["reviewer_note"] == updated["reviewer_note"]
    assert restored["timeline"] == updated["timeline"]

    with pytest.raises(RunStateError):
        manager.save_reviewer_note(completed["run_id"], "  ")
    with pytest.raises(ValidationError):
        ReviewerNoteRequest.model_validate({"text": "ok", "path": "/private/repo"})


def test_local_review_opens_owner_only_artifact_without_http_content(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    _git(workspace, "init")
    _git(workspace, "config", "user.email", "test@example.com")
    _git(workspace, "config", "user.name", "APatch Test")
    source = workspace / "example.txt"
    source.write_text("before\n", encoding="utf-8")
    _git(workspace, "add", "example.txt")
    _git(workspace, "commit", "-m", "base")
    source.write_text("after\n", encoding="utf-8")

    opened: list[Path] = []
    handoff = LocalReviewHandoff(
        workspace,
        state_root=tmp_path / "state",
        launcher=lambda artifact: opened.append(artifact) or "test_viewer",
    )
    receipt = handoff.open(
        "apr_" + "1" * 32,
        LocalReviewRequest(request_id="apsreq_local_review_001"),
    )

    assert receipt["status"] == "opened"
    assert receipt["file_count"] == 1
    assert receipt["launcher"] == "test_viewer"
    assert len(opened) == 1
    assert os.stat(opened[0]).st_mode & 0o777 == 0o600
    assert b"-before" in opened[0].read_bytes()
    serialized = json.dumps(receipt)
    assert "example.txt" not in serialized
    assert str(workspace) not in serialized
    assert "before" not in serialized
    assert set(receipt) == {
        "schema",
        "request_id",
        "run_id",
        "status",
        "artifact_id",
        "file_count",
        "byte_count",
        "launcher",
        "expires_in_sec",
    }


def test_review_routes_and_frontend_use_fixed_purpose_backend(tmp_path):
    root = Path(__file__).resolve().parents[2]
    app = (root / "apatch_studio/app.py").read_text(encoding="utf-8")
    frontend = (root / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
    api = (root / "frontend/src/api.ts").read_text(encoding="utf-8")

    assert '"/api/v1/runs/{run_id}/review-note"' in app
    assert '"/api/v1/runs/{run_id}/local-review"' in app
    assert "saveRunReviewNote(run.run_id, note)" in frontend
    assert "openRunLocalReview(run.run_id)" in frontend
    assert "window.localStorage" not in frontend
    assert "<ProofDetails" in frontend
    assert "/local-review" in api
