import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from apatch_studio.action_facade import StudioWorkflowFacade, SystemActionRequest
from apatch_studio.settings_workflow import WorkspaceActionRequest


def ready_workspace(root: Path) -> None:
    (root / ".git").mkdir()
    (root / ".apatch").mkdir()
    (root / ".apatch/mcp.json").write_text("{}\n", encoding="utf-8")
    (root / "AGENTS.md").write_text("# Local contract\n", encoding="utf-8")


def test_system_cleanup_requires_confirmation_and_projects_counts(tmp_path, monkeypatch):
    facade = StudioWorkflowFacade(tmp_path)

    def fake_gc(_root, *, mode, dry_run):
        if mode == "report":
            return {
                "ok": True,
                "report": {
                    "status": "degraded",
                    "artifact_count": 12,
                    "orphan_count": 0,
                    "unclassified_count": 1,
                    "inferred_count": 3,
                },
            }
        return {
            "ok": True,
            "deleted_count": 4,
            "reclaimed_bytes": 512,
            "skipped": ["protected"],
        }

    monkeypatch.setattr("apatch_studio.action_facade.run_gc", fake_gc)
    preview = facade.system_action(SystemActionRequest(
        request_id="apsreq_gc_preview_001", action="gc_preview",
    ))
    assert preview["result"]["counts"]["artifact_count"] == 12
    assert preview["result"]["counts"]["orphan_count"] == 0
    assert {"label": "Orphan Count", "value": "0"} in preview["presentation"]["facts"]
    assert preview["result"]["action_required"] is True

    with pytest.raises(ValidationError):
        SystemActionRequest(request_id="apsreq_gc_bad_0001", action="gc_execute")

    executed = facade.system_action(SystemActionRequest(
        request_id="apsreq_gc_execute_001", action="gc_execute", confirmed=True,
    ))
    assert executed["result"] == {
        "ok": True,
        "action": "gc_execute",
        "dry_run": False,
        "deleted_count": 4,
        "reclaimed_bytes": 512,
        "skipped_count": 1,
    }


def test_hygiene_attention_is_not_presented_as_healthy(tmp_path, monkeypatch):
    monkeypatch.setattr("apatch_studio.action_facade.run_doctor", lambda _root: {
        "ok": True,
        "hygiene": {"status": "critical", "issues": ["stale artifact"]},
    })
    receipt = StudioWorkflowFacade(tmp_path).system_action(SystemActionRequest(
        request_id="apsreq_hygiene_attention_001", action="hygiene",
    ))
    assert receipt["result"]["ok"] is False
    assert receipt["result"]["hygiene"] == {"status": "critical", "issue_count": 1}
    assert receipt["presentation"]["tone"] == "attention"
    assert receipt["presentation"]["title"] == "Storage needs attention"


def test_current_workspace_alias_lifecycle_is_content_safe(tmp_path, monkeypatch):
    ready_workspace(tmp_path)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    facade = StudioWorkflowFacade(tmp_path)

    registered = facade.workspace_action(WorkspaceActionRequest(
        request_id="apsreq_alias_register_001",
        action="register",
        alias="studio-local",
        confirmed=True,
    ))
    assert registered["result"]["current_workspace"] is True

    listed = facade.workspace_action(WorkspaceActionRequest(
        request_id="apsreq_alias_list_000001",
        action="list",
    ))
    assert listed["result"]["items"][0]["alias"] == "studio-local"
    assert listed["result"]["items"][0]["ready"] is True
    encoded = json.dumps(listed)
    assert str(tmp_path) not in encoded
    assert "canonical_mcp_path" not in encoded
    assert "root_fingerprint" not in encoded

    removed = facade.workspace_action(WorkspaceActionRequest(
        request_id="apsreq_alias_remove_0001",
        action="remove",
        alias="studio-local",
        confirmed=True,
    ))
    assert removed["result"]["removed"] is True


def test_settings_ui_exposes_actions_and_local_boundary():
    root = Path(__file__).resolve().parents[2]
    view = (root / "frontend/src/OutsideInAdmin.tsx").read_text(encoding="utf-8")
    for label in [
        "Check runtime",
        "Check storage",
        "Preview cleanup",
        "Run safe cleanup",
        "Add current workspace",
    ]:
        assert label in view
    assert "Source, prompts, local paths and credentials stay on this computer." in view
