from __future__ import annotations

import json

from fastapi.testclient import TestClient

from apatch_studio.app import create_app
from apatch_studio.edition import StudioEdition


class JourneyAdapter:
    def overview(self, *, force=False):
        return {
            "schema": "apatch.studio.workspace-overview.v1",
            "generated_at": "2026-09-01T00:00:00Z",
            "workspace": {"name": "Journey", "clean": False, "dirty_files": 2},
            "runtime": {"hygiene": "degraded", "apatch_version": "0.8.36", "tool_count": 122},
        }


class JourneyRuns:
    def __init__(self):
        self.note = None

    def runners(self):
        return [{"id": "codex", "label": "Codex", "available": True}]

    def journal(self):
        return {
            "schema": "apatch.studio.run-journal-status.v1",
            "persistent": True,
            "status": "ready",
            "warning": None,
            "record_count": 1,
            "retention": 200,
            "interrupted_on_start": 0,
        }

    def list(self):
        return [self.get("apr_" + "1" * 32)]

    def get(self, run_id):
        return {
            "run_id": run_id,
            "status": "succeeded",
            "reviewer_note": self.note,
            "contribution": {
                "contribution_receipt": {"status": "recorded", "event_id": "ace_123"},
                "avatar_sync": {"status": "acknowledged", "pending_outbox_items": 0},
            },
        }

    def save_reviewer_note(self, run_id, text):
        self.note = {
            "schema": "apatch.studio.reviewer-note.v1",
            "text": text,
            "updated_at": "2026-09-01T00:00:00Z",
        }
        return self.get(run_id)

    def close(self):
        return None


class JourneyActions:
    def system_action(self, request):
        return {
            "schema": "apatch.studio.action-receipt.v1",
            "request_id": request.request_id,
            "command": request.action,
            "status": "complete",
            "result": {"action": request.action, "counts": {"orphan_ephemeral": 2}},
        }


class JourneyReview:
    def open(self, run_id, request):
        return {
            "schema": "apatch.studio.local-review-handoff.v1",
            "request_id": request.request_id,
            "run_id": run_id,
            "status": "opened",
            "artifact_id": "apsreview_" + "2" * 32,
            "file_count": 2,
            "byte_count": 120,
            "launcher": "local_viewer",
            "expires_in_sec": 900,
        }


class JourneyDelivery:
    def status(self):
        return {
            "schema": "apatch.studio.delivery-status.v1",
            "branch": "feature",
            "detached": False,
            "staged_count": 2,
            "unstaged_count": 0,
            "untracked_count": 0,
            "upstream_configured": True,
            "ahead": 1,
            "behind": 0,
            "can_commit": True,
            "can_push": True,
            "can_open_pr": True,
            "pr_provider": "github",
        }

    def act(self, request):
        return {
            "schema": "apatch.studio.delivery-receipt.v1",
            "request_id": request.request_id,
            "request_hash": "sha256:" + "3" * 64,
            "action": request.action,
            "status": "complete",
            "completed_at": "2026-09-01T00:00:00Z",
            "result": {"commit_created": True},
        }


class JourneyContribution:
    def timesheet(self, request):
        return {
            "schema": "apatch.studio.timesheet-draft.v1",
            "request_id": request.request_id,
            "source": "apatch.run_timesheet",
            "basis": "operation_spacing_estimate",
            "accepted_time": False,
            "group_by": request.group_by,
            "groups": [],
            "warnings": [],
            "disclaimer": "Operation-spacing estimate, not accepted time.",
        }

    def health(self):
        return {
            "schema": "apatch.studio.contribution-health.v1",
            "timesheet_available": True,
            "tracker_state": "acknowledged",
            "tracker_configured": True,
            "tracker_auth_configured": True,
            "contract_status": "compatible",
            "evidence_pending": 0,
            "contribution_pending": 0,
            "pending_total": 0,
            "last_acknowledgement": "2026-09-01T00:00:00Z",
        }


def test_closed_local_loop_exposes_actions_without_content_leak(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    runs = JourneyRuns()
    app = create_app(
        str(workspace),
        adapter=JourneyAdapter(),
        run_manager=runs,
        workflow_facade=JourneyActions(),
        review_handoff=JourneyReview(),
        delivery_workflow=JourneyDelivery(),
        contribution_workflow=JourneyContribution(),
        frontend_root=tmp_path,
        edition=StudioEdition.OSS,
    )
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    headers = {
        "x-apatch-studio-session": app.state.studio_guard.token,
        "origin": "http://127.0.0.1:8765",
    }
    run_id = "apr_" + "1" * 32

    cleanup = client.post(
        "/api/v1/system/actions",
        headers=headers,
        json={"request_id": "apsreq_journey_cleanup_001", "action": "gc_preview"},
    )
    note = client.post(
        f"/api/v1/runs/{run_id}/review-note",
        headers=headers,
        json={"text": "Ready after the exact governed verification."},
    )
    local_review = client.post(
        f"/api/v1/runs/{run_id}/local-review",
        headers=headers,
        json={"request_id": "apsreq_journey_review_001"},
    )
    delivery = client.post(
        "/api/v1/delivery/actions",
        headers=headers,
        json={
            "request_id": "apsreq_journey_delivery_001",
            "action": "commit",
            "confirmed": True,
            "message": "Record governed result",
        },
    )
    timesheet = client.post(
        "/api/v1/timesheet/actions",
        headers=headers,
        json={
            "request_id": "apsreq_journey_timesheet_001",
            "action": "draft",
            "group_by": ["project", "spec", "day"],
        },
    )
    health = client.get("/api/v1/contributions/health", headers=headers)

    assert [response.status_code for response in (
        cleanup, note, local_review, delivery, timesheet, health
    )] == [200, 200, 200, 200, 200, 200]
    assert cleanup.json()["result"]["counts"]["orphan_ephemeral"] == 2
    assert note.json()["reviewer_note"]["text"].startswith("Ready after")
    assert local_review.json()["status"] == "opened"
    assert delivery.json()["action"] == "commit"
    assert timesheet.json()["source"] == "apatch.run_timesheet"
    assert timesheet.json()["accepted_time"] is False
    assert health.json()["pending_total"] == 0

    projection = json.dumps({
        "cleanup": cleanup.json(),
        "note": note.json(),
        "review": local_review.json(),
        "delivery": delivery.json(),
        "timesheet": timesheet.json(),
        "health": health.json(),
    })
    assert str(workspace) not in projection
    for forbidden in ("source_code", "full_diff", "session_token", "private_key"):
        assert forbidden not in projection


def test_frontend_closes_the_visible_work_review_delivery_contribution_loop():
    root = __import__("pathlib").Path(__file__).resolve().parents[2]
    app = "\n".join((root / "frontend" / "src" / name).read_text(encoding="utf-8") for name in (
        "OutsideInViews.tsx", "OutsideInAdmin.tsx", "TimeLibrary.tsx", "ProofDetails.tsx",
    ))
    shell = (root / "frontend" / "src" / "OutsideInApp.tsx").read_text(encoding="utf-8")

    for label in (
        "Run safe cleanup",
        "Open local diff",
        "Commit",
        "Push",
        "Open PR",
        "Verify records",
        "Delivery",
    ):
        assert label in app
    assert 'role="alertdialog"' in shell
