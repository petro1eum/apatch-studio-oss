from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from apatch_studio.app import create_app
from apatch_studio.change_details import ChangeDetailNotFound, InvalidChangeId


CHANGE_ID = "apchg_" + "1" * 32
PATCH = "--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-old\n+new\n"
DETAIL = {
    "schema": "apatch.studio.imported-change-detail.v1",
    "privacy_band": "local_source",
    "change_id": CHANGE_ID,
    "governed_session_id": "apatch_sess_detail_12345678",
    "result_kind": "code_change",
    "result_message": "1 changed file recorded.",
    "objective": "Build the visible result",
    "status": "proven",
    "created_at": "2026-09-01T00:00:00Z",
    "updated_at": "2026-09-01T00:01:00Z",
    "spec_id": "SPEC-DEMO",
    "requirement_id": "R1",
    "project": {
        "name": "demo",
        "repository": "owner/demo",
        "branch": "main",
        "upstream": "origin/main",
        "head": "abc123",
        "operator": "Local Developer",
    },
    "actor": {
        "type": "apatch_signing_identity",
        "label": "Local APatch signing identity",
        "key_id": "signer-1",
    },
    "summary": {
        "file_count": 1,
        "omitted_file_count": 0,
        "insertions": 1,
        "deletions": 1,
        "mutation_count": 1,
        "attestation_count": 1,
        "signed_event_count": 2,
        "patch_bytes": len(PATCH),
        "patch_truncated": False,
    },
    "files": [
        {
            "path": "src/app.py",
            "mode": "644",
            "sha256": "a" * 64,
            "record_ids": ["op_1"],
            "binary": False,
            "patch": PATCH,
            "patch_status": "available",
            "patch_bytes": len(PATCH),
            "insertions": 1,
            "deletions": 1,
            "truncated": False,
        }
    ],
    "events": [],
    "verification": {
        "status": "proven",
        "attestation_count": 1,
        "latest_record_id": "op_2",
        "latest_signer": "signer-1",
    },
    "available_actions": [
        "back_to_changes",
        "open_recorded_patch",
        "open_backlog",
    ],
}


class _Adapter:
    def overview(self, *, force: bool = False):
        return {"schema": "test.overview.v1", "changes": []}

    def change_detail(self, change_id: str):
        if not change_id.startswith("apchg_"):
            raise InvalidChangeId(change_id)
        if change_id != CHANGE_ID:
            raise ChangeDetailNotFound(change_id)
        return deepcopy(DETAIL)


class _Runs:
    def runners(self):
        return []

    def list(self):
        return []

    def journal(self):
        return {"schema": "test.journal.v1"}

    def close(self):
        pass


class _Review:
    def __init__(self):
        self.opened = None

    def open_payload(self, resource_id, payload, request, *, file_count=None):
        self.opened = (resource_id, payload, request.request_id, file_count)
        return {
            "schema": "apatch.studio.local-review-handoff.v1",
            "request_id": request.request_id,
            "run_id": resource_id,
            "status": "opened",
            "artifact_id": "apsrev_" + "2" * 32,
            "file_count": file_count,
            "byte_count": len(payload),
            "launcher": "test_viewer",
            "expires_in_sec": 86400,
        }


def test_change_detail_api_is_session_guarded_and_exact(tmp_path) -> None:
    review = _Review()
    app = create_app(
        str(tmp_path),
        adapter=_Adapter(),
        run_manager=_Runs(),
        review_handoff=review,
        frontend_root=tmp_path,
    )
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    auth = {"x-apatch-studio-session": app.state.studio_guard.token}

    assert client.get(f"/api/v1/changes/{CHANGE_ID}").status_code == 401
    response = client.get(f"/api/v1/changes/{CHANGE_ID}", headers=auth)
    assert response.status_code == 200
    assert response.json()["files"][0]["patch"] == PATCH

    response = client.post(
        f"/api/v1/changes/{CHANGE_ID}/local-review",
        headers={**auth, "origin": "http://127.0.0.1:8765"},
        json={"request_id": "apsreq_change_review_001"},
    )
    assert response.status_code == 200
    assert review.opened == (
        CHANGE_ID,
        (PATCH + "\n").encode("utf-8"),
        "apsreq_change_review_001",
        1,
    )
    assert "src/app.py" not in repr(response.json())


def test_change_detail_api_fails_closed_for_invalid_and_unknown_ids(tmp_path) -> None:
    app = create_app(
        str(tmp_path),
        adapter=_Adapter(),
        run_manager=_Runs(),
        review_handoff=_Review(),
        frontend_root=tmp_path,
    )
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    auth = {"x-apatch-studio-session": app.state.studio_guard.token}

    assert client.get("/api/v1/changes/not-a-change", headers=auth).status_code == 400
    assert (
        client.get(
            "/api/v1/changes/apchg_" + "9" * 32,
            headers=auth,
        ).status_code
        == 404
    )
