from __future__ import annotations

import inspect
import json
from pathlib import Path

from apatch_studio import contribution_workflow as contribution_module
from apatch_studio.contribution_workflow import (
    ContributionWorkflow,
    TimesheetRequest,
    extract_attestation_delivery,
)


def test_timesheet_uses_canonical_runner_without_second_aggregation(tmp_path):
    calls = []

    def canonical_runner(**kwargs):
        calls.append(kwargs)
        if kwargs["do_verify"]:
            return {"verify": {"ok": True, "checked": 8, "drift": [], "unsigned": []}}
        return {
            "groups": [
                {
                    "key": ["demo", "SPEC-1", "2026-08-31"],
                    "sessions": 2,
                    "hours": 1.25,
                    "active_sec": 4500,
                    "ops": 7,
                    "files_touched": 3,
                    "insertions": 0,
                    "deletions": 0,
                }
            ]
        }

    workflow = ContributionWorkflow(tmp_path, timesheet_runner=canonical_runner)
    draft = workflow.timesheet(
        TimesheetRequest(
            request_id="apsreq_timesheet_draft_001",
            action="draft",
            group_by=["project", "spec", "day"],
        )
    )
    verified = workflow.timesheet(
        TimesheetRequest(
            request_id="apsreq_timesheet_verify_001",
            action="verify",
            group_by=["project"],
        )
    )

    assert draft["source"] == "apatch.run_timesheet"
    assert draft["accepted_time"] is False
    assert draft["warnings"] == ["line_volume_unavailable"]
    assert verified["ok"] is True
    assert [call["do_verify"] for call in calls] == [False, True]
    source = inspect.getsource(contribution_module.ContributionWorkflow)
    assert "load_events" not in source
    assert "aggregate(" not in source


def test_attestation_delivery_projection_is_allowlisted():
    projected = extract_attestation_delivery(
        {
            "result": {
                "contribution_receipt": {
                    "status": "recorded",
                    "code": "accepted",
                    "event_id": "ace_123",
                    "secret": "never-return",
                },
                "avatar_sync": {
                    "ok": False,
                    "status": "AVATAR_CONTRACT_UNAVAILABLE",
                    "retryable": True,
                    "outbox_preserved": True,
                    "pending_outbox_items": 2,
                    "action_required": ["AVATAR_CONTRACT_UNAVAILABLE"],
                    "error": "/private/workspace",
                },
            }
        }
    )

    assert projected == {
        "contribution_receipt": {
            "status": "recorded",
            "code": "accepted",
            "event_id": "ace_123",
        },
        "avatar_sync": {
            "ok": False,
            "status": "AVATAR_CONTRACT_UNAVAILABLE",
            "retryable": True,
            "outbox_preserved": True,
            "pending_outbox_items": 2,
            "action_required": ["AVATAR_CONTRACT_UNAVAILABLE"],
        },
    }
    encoded = json.dumps(projected)
    assert "never-return" not in encoded
    assert "/private/workspace" not in encoded


def test_sync_health_is_safe_and_keeps_local_timesheet_available(tmp_path):
    workflow = ContributionWorkflow(
        tmp_path,
        compatibility_supplier=lambda: {
            "ok": False,
            "status": "dependency_incompatible",
            "module_path": "/private",
        },
        tracker_supplier=lambda: {"base_url": "", "service_token": "secret"},
        evidence_pending_supplier=lambda: 2,
        contribution_preview_supplier=lambda: {"pending": 5},
        last_ack_supplier=lambda: "2026-08-31T12:00:00+00:00",
    )
    health = workflow.health()

    assert health["timesheet_available"] is True
    assert health["tracker_state"] == "dependency_unavailable"
    assert health["tracker_auth_configured"] is True
    assert health["pending_total"] == 7
    encoded = json.dumps(health)
    assert "secret" not in encoded
    assert "/private" not in encoded
    assert "credential" not in encoded


def test_studio_surfaces_timesheet_receipt_and_sync_health():
    root = Path(__file__).resolve().parents[2]
    app_source = (root / "frontend" / "src" / "TimeLibrary.tsx").read_text(encoding="utf-8")
    proof_source = (root / "frontend" / "src" / "ProofDetails.tsx").read_text(encoding="utf-8")
    api_source = (root / "apatch_studio" / "app.py").read_text(encoding="utf-8")

    assert "Calculate" in app_source
    assert "Verify records" in app_source
    assert "Export CSV" in app_source
    assert "Account delivery" in app_source
    assert "avatar_sync" in proof_source
    assert "/api/v1/timesheet/actions" in api_source
    assert "/api/v1/contributions/health" in api_source
