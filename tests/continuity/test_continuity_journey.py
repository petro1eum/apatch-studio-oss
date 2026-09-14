from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from apatch_studio.app import create_app


ROOT = Path(__file__).resolve().parents[2]
SESSION_ID = "apatch_sess_1788000000000000000_existing"


class _Adapter:
    def overview(self, *, force=False):
        return {
            "schema": "apatch.studio.workspace-overview.v1",
            "workspace": {"name": "Established workspace", "clean": True, "dirty_files": 0},
            "changes": [{
                "schema": "apatch.studio.imported-change.v1",
                "change_id": "apchg_" + "1" * 32,
                "governed_session_id": SESSION_ID,
                "objective": "Keep existing governed work visible",
                "created_at": "2026-08-31T10:00:00Z",
                "updated_at": "2026-08-31T10:05:00Z",
                "status": "proven",
                "spec_id": "SPEC-EXISTING-1",
                "requirement_id": "R2",
                "file_count": 2,
                "logical_areas": ["frontend", "tests"],
                "insertions": 12,
                "deletions": 3,
                "mutation_count": 1,
                "attestation_count": 1,
                "signed_event_count": 4,
            }],
        }


class _Runs:
    def runners(self):
        return []

    def list(self):
        return []

    def journal(self):
        return {"schema": "test.journal.v1", "record_count": 0}

    def close(self):
        return None


class _Contribution:
    def timesheet(self, request):
        return {
            "schema": "apatch.studio.timesheet-draft.v1",
            "request_id": request.request_id,
            "source": "apatch.run_timesheet",
            "project": {"id": "project_established", "name": "Established workspace"},
            "period": {
                "since": request.since.isoformat() if request.since else None,
                "until": request.until.isoformat() if request.until else None,
            },
            "basis": "operation_spacing_estimate",
            "accepted_time": False,
            "group_by": request.group_by,
            "groups": [{
                "key": ["2026-08-31"],
                "sessions": 1,
                "hours": 0.5,
                "active_sec": 1800,
                "ops": 4,
                "files_touched": 2,
                "insertions": 12,
                "deletions": 3,
            }],
            "warnings": [],
            "disclaimer": "Operation-spacing estimate, not accepted time.",
        }

    def health(self):
        return {
            "schema": "apatch.studio.contribution-health.v1",
            "timesheet_available": True,
            "tracker_state": "configured",
            "tracker_configured": True,
            "tracker_auth_configured": True,
            "contract_status": "compatible",
            "evidence_pending": 6000,
            "contribution_pending": 435,
            "pending_total": 6435,
            "last_acknowledgement": None,
        }


def test_established_workspace_continues_into_scoped_verified_time(tmp_path) -> None:
    app = create_app(
        str(tmp_path),
        adapter=_Adapter(),
        run_manager=_Runs(),
        contribution_workflow=_Contribution(),
        frontend_root=tmp_path,
    )
    headers = {
        "x-apatch-studio-session": app.state.studio_guard.token,
        "origin": "http://127.0.0.1:8765",
    }
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        changes = client.get("/api/v1/changes", headers=headers)
        time = client.post(
            "/api/v1/timesheet/actions",
            headers=headers,
            json={
                "request_id": "apsreq_continuity_journey_001",
                "action": "draft",
                "group_by": ["day"],
                "since": "2026-08-25",
                "until": "2026-08-31",
            },
        )
        health = client.get("/api/v1/contributions/health", headers=headers)

    assert changes.status_code == time.status_code == health.status_code == 200
    assert changes.json()["items"][0]["kind"] == "imported_change"
    assert changes.json()["items"][0]["change"]["governed_session_id"] == SESSION_ID
    assert time.json()["project"]["id"] == "project_established"
    assert time.json()["period"] == {"since": "2026-08-25", "until": "2026-08-31"}
    assert time.json()["groups"][0]["hours"] == 0.5
    assert time.json()["accepted_time"] is False
    assert health.json()["pending_total"] == 6435

    safe_projection = json.dumps({"changes": changes.json(), "time": time.json()})
    for forbidden in ("source_code", "full_diff", "workspace_path", "session_token", "private_key"):
        assert forbidden not in safe_projection


def test_frontend_uses_the_unified_feed_and_bounded_time_workflow() -> None:
    app = (ROOT / "frontend/src/OutsideInApp.tsx").read_text(encoding="utf-8")
    views = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
    time = (ROOT / "frontend/src/TimeLibrary.tsx").read_text(encoding="utf-8")

    assert "loadChangeFeed" in app
    assert "changes.length === 0" in views
    assert "<ImportedChangeCard" in views
    assert "<TimeLibrary" in views
    assert "function TimeLibrary" not in views
    assert "lastDays(7)" in time
    assert "pending across all workspaces" in time
    assert "Draft time is never accepted automatically" in time


def test_release_metadata_names_the_continuity_contract() -> None:
    continuity = (ROOT / "docs/specs/SPEC-STUDIO-CONTINUITY-1.md").read_text(encoding="utf-8")
    assert all(f"## R{index}" in continuity for index in range(9))
    publication = (ROOT / "docs/RFP-023-studio-oss-publication.md").read_text(encoding="utf-8")
    assert "recovery" in publication.lower()
