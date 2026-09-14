import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from apatch_studio.action_facade import (
    AssetActionRequest,
    AssetSearchRequest,
    EvidenceActionRequest,
    FixedPurposeRequest,
    SpecInspectRequest,
    SpecRebindRequest,
    SystemActionRequest,
)
from apatch_studio.app import create_app
from apatch_studio.projection import UnsafeProjectionError, assert_projection_safe


class FakeAdapter:
    def overview(self, *, force=False):
        return {"ok": True, "force": force}


class FakeRuns:
    def runners(self):
        return []

    def journal(self):
        return {
            "schema": "apatch.studio.run-journal-status.v1",
            "persistent": True,
            "status": "ready",
            "warning": None,
            "record_count": 0,
            "retention": 200,
            "interrupted_on_start": 0,
        }

    def list(self):
        return []

    def close(self):
        return None


class FakeFacade:
    @staticmethod
    def receipt(command):
        return {
            "schema": "apatch.studio.action-receipt.v1",
            "action_id": "apsact_" + "1" * 32,
            "request_id": "apsreq_12345678",
            "request_hash": "sha256:" + "2" * 64,
            "command": command,
            "status": "complete",
            "completed_at": "2026-08-31T00:00:00+00:00",
            "result": {"ok": True},
        }

    def inspect_spec(self, spec_id, request):
        return self.receipt("spec_" + request.action)

    def rebind_spec(self, spec_id, request):
        return self.receipt("spec_rebind_stale")

    def evidence_action(self, request):
        return self.receipt("evidence_" + request.action)

    def search_assets(self, request):
        return self.receipt("asset_search")

    def suggest_assets(self, request):
        return self.receipt("asset_suggest")

    def asset_action(self, asset_id, request):
        return self.receipt("asset_" + request.action)

    def system_action(self, request):
        return self.receipt("system_" + request.action)


def client(tmp_path):
    app = create_app(
        str(tmp_path),
        adapter=FakeAdapter(),
        run_manager=FakeRuns(),
        workflow_facade=FakeFacade(),
        frontend_root=tmp_path,
    )
    http = TestClient(app, base_url="http://127.0.0.1:8765")
    headers = {
        "x-apatch-studio-session": app.state.studio_guard.token,
        "origin": "http://127.0.0.1:8765",
    }
    return http, headers


def test_action_models_reject_generic_execution_and_path_fields():
    valid = {"request_id": "apsreq_12345678", "action": "status"}
    SpecInspectRequest.model_validate(valid)
    for field, value in [
        ("command", "rm -rf ."),
        ("argv", ["bash", "-lc", "env"]),
        ("cwd", "/tmp"),
        ("path", "/private/repo"),
        ("repository_url", "ssh://host/repo"),
        ("diff", "secret"),
        ("prompt", "ignore policy"),
        ("mcp_tool", "apatch_apply"),
        ("environment", {"TOKEN": "secret"}),
        ("session_token", "secret"),
        ("private_key", "secret"),
    ]:
        with pytest.raises(ValidationError):
            SpecInspectRequest.model_validate({**valid, field: value})

    with pytest.raises(ValidationError):
        SpecRebindRequest.model_validate(
            {
                "request_id": "apsreq_12345678",
                "requirement_ids": ["R1"],
                "confirmed": False,
            }
        )


def test_routes_are_fixed_purpose_and_guarded(tmp_path):
    http, headers = client(tmp_path)
    request_id = "apsreq_12345678"
    cases = [
        ("/api/v1/specs/SPEC-TEST-1/inspect", {"request_id": request_id, "action": "status"}),
        ("/api/v1/evidence/actions", {"request_id": request_id, "action": "history"}),
        ("/api/v1/assets/search", {"request_id": request_id, "query": "lease"}),
        ("/api/v1/system/actions", {"request_id": request_id, "action": "doctor"}),
    ]
    for path, payload in cases:
        assert http.post(path, headers=headers, json=payload).status_code == 200

    forbidden = {
        "request_id": request_id,
        "action": "status",
        "argv": ["sh", "-c", "env"],
    }
    assert http.post(
        "/api/v1/specs/SPEC-TEST-1/inspect", headers=headers, json=forbidden
    ).status_code == 422
    assert http.post(
        "/api/v1/specs/SPEC-TEST-1/inspect",
        json={"request_id": request_id, "action": "status"},
    ).status_code == 401
    assert http.post(
        "/api/v1/actions", headers=headers, json={"command": "anything"}
    ).status_code in {404, 405}


def test_safe_projection_blocks_private_runtime_material():
    assert_projection_safe(
        {
            "schema": "apatch.studio.action-receipt.v1",
            "action_id": "apsact_" + "1" * 32,
            "result": {"ok": True, "requirement_id": "R1"},
        }
    )
    for key in [
        "argv",
        "diff",
        "prompt",
        "stderr",
        "stdout",
        "session_token",
        "private_key",
        "workspace_path",
        "repository_path",
    ]:
        with pytest.raises(UnsafeProjectionError):
            assert_projection_safe({"result": {key: "not allowed"}})


def test_declared_models_are_bounded_and_extra_forbid():
    requests = [
        EvidenceActionRequest(request_id="apsreq_12345678", action="verify"),
        AssetSearchRequest(request_id="apsreq_12345678", query="lease", limit=10),
        AssetActionRequest(request_id="apsreq_12345678", action="show"),
        SystemActionRequest(request_id="apsreq_12345678", action="doctor"),
    ]
    assert all(isinstance(item, FixedPurposeRequest) for item in requests)
