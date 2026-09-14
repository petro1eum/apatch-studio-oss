from pathlib import Path

import pytest
from pydantic import ValidationError

from apatch_studio.action_facade import StudioWorkflowFacade, SystemActionRequest


ROOT = Path(__file__).resolve().parents[2]


def test_safe_cleanup_preview_and_execution_keep_backend_confirmation(monkeypatch, tmp_path):
    calls = []

    def fake_gc(_root, *, mode, dry_run):
        calls.append((mode, dry_run))
        if dry_run:
            return {
                "ok": True,
                "report": {
                    "status": "degraded",
                    "artifact_count": 18,
                    "orphan_count": 2,
                    "unclassified_count": 1,
                    "inferred_count": 4,
                },
            }
        return {
            "ok": True,
            "deleted_count": 5,
            "reclaimed_bytes": 2048,
            "skipped": [],
        }

    monkeypatch.setattr("apatch_studio.action_facade.run_gc", fake_gc)
    facade = StudioWorkflowFacade(tmp_path)
    preview = facade.system_action(SystemActionRequest(
        request_id="apsreq_loop_gc_preview_001",
        action="gc_preview",
    ))
    assert preview["result"]["counts"]["artifact_count"] == 18
    assert preview["result"]["action_required"] is True

    with pytest.raises(ValidationError):
        SystemActionRequest(
            request_id="apsreq_loop_gc_execute_bad",
            action="gc_execute",
        )

    executed = facade.system_action(SystemActionRequest(
        request_id="apsreq_loop_gc_execute_001",
        action="gc_execute",
        confirmed=True,
    ))
    assert executed["result"]["deleted_count"] == 5
    assert executed["result"]["reclaimed_bytes"] == 2048
    assert calls == [("report", True), ("safe", False)]


def test_work_hygiene_is_actionable_with_studio_confirmation() -> None:
    overview = (ROOT / "frontend/src/OutsideInAdmin.tsx").read_text(encoding="utf-8")
    shell = (ROOT / "frontend/src/OutsideInApp.tsx").read_text(encoding="utf-8")
    styles = (ROOT / "frontend/src/outside-in.css").read_text(encoding="utf-8")

    assert 'act("gc_preview")' in overview
    assert 'act("gc_execute", true)' in overview
    assert 'title: "Run safe cleanup"' in overview
    assert "await onChanged()" in overview
    assert "window.confirm" not in overview
    assert 'role="alertdialog"' in shell
    assert ".oi-dialog-backdrop" in styles
