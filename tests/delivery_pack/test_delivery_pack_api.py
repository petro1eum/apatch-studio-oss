from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from apatch_studio.app import create_app
from apatch_studio.delivery_pack import DeliveryPackWorkflow

from .conftest import CHANGE_ID


class _Adapter:
    def __init__(self, detail):
        self.detail = detail

    def overview(self, *, force=False):
        return {"schema": "test.overview.v1", "changes": []}

    def change_detail(self, change_id):
        assert change_id == CHANGE_ID
        return deepcopy(self.detail)


class _Sdd:
    def __init__(self, detail):
        self.detail = detail

    def change(self, change_id):
        assert change_id == CHANGE_ID
        return deepcopy(self.detail["sdd"])


class _Runs:
    def runners(self):
        return []

    def list(self):
        return []

    def journal(self):
        return {"schema": "test.journal.v1"}

    def close(self):
        pass


def _client(tmp_path, signer, change_detail):
    workflow = DeliveryPackWorkflow(tmp_path, signer=signer)
    app = create_app(
        str(tmp_path),
        adapter=_Adapter(change_detail),
        run_manager=_Runs(),
        sdd_facade=_Sdd(change_detail),
        delivery_pack_workflow=workflow,
        frontend_root=tmp_path,
    )
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    headers = {"x-apatch-studio-session": app.state.studio_guard.token}
    writes = {**headers, "origin": "http://127.0.0.1:8765"}
    return client, headers, writes


def test_delivery_pack_api_is_guarded_and_fail_closed(
    tmp_path, signer, change_detail
) -> None:
    client, headers, writes = _client(tmp_path, signer, change_detail)
    endpoint = f"/api/v1/changes/{CHANGE_ID}/delivery-pack"

    assert client.get(endpoint).status_code == 401
    pack = client.get(endpoint, headers=headers).json()
    assert pack["test_protocol"]["meaningful"] is True

    accepted = client.post(
        f"/api/v1/changes/{CHANGE_ID}/acceptance",
        headers=writes,
        json={
            "request_id": "apsreq_api_acceptance",
            "expected_basis_hash": pack["basis_hash"],
            "decision": "accepted",
            "note": "",
            "confirmed": True,
        },
    )
    assert accepted.status_code == 200
    assert accepted.json()["decision"] == "accepted"

    stale = client.post(
        f"/api/v1/changes/{CHANGE_ID}/acceptance",
        headers=writes,
        json={
            "request_id": "apsreq_api_stale",
            "expected_basis_hash": "sha256:" + "9" * 64,
            "decision": "accepted",
            "note": "",
            "confirmed": True,
        },
    )
    assert stale.status_code == 409
    assert stale.json()["error_code"] == "delivery_basis_stale"


def test_api_records_time_separately_and_exports_current_pack(
    tmp_path, signer, change_detail
) -> None:
    client, headers, writes = _client(tmp_path, signer, change_detail)
    endpoint = f"/api/v1/changes/{CHANGE_ID}/delivery-pack"
    pack = client.get(endpoint, headers=headers).json()
    response = client.post(
        f"/api/v1/changes/{CHANGE_ID}/time-decision",
        headers=writes,
        json={
            "request_id": "apsreq_api_time",
            "expected_basis_hash": pack["basis_hash"],
            "expected_effort_hash": pack["effort"]["effort_hash"],
            "decision": "accepted",
            "accepted_hours": 2.0,
            "note": "Reviewed",
            "confirmed": True,
        },
    )

    assert response.status_code == 200
    current = client.get(endpoint, headers=headers).json()
    assert current["acceptance"]["latest"] is None
    assert current["time_decision"]["latest"]["accepted_hours"] == 2.0
