"""Actual Studio HTTP routing and local boundary; publication gateway is a double."""
from types import SimpleNamespace
import subprocess

import pytest
from fastapi.testclient import TestClient

from apatch_studio.app import create_app
from apatch_studio.governed_work_gateway import GovernedWorkGatewayError

PREVIEW = "/api/v1/governed-work/evidence/preview"
PUBLISH = "/api/v1/governed-work/evidence/publish"
BINDING = "tcpsb_" + "a" * 32
PLAN = {"plan_hash": "sha256:" + "b" * 64}


@pytest.fixture(autouse=True)
def git_workspace(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)


@pytest.fixture
def configured(tmp_path):
    calls = []
    gateway = SimpleNamespace()

    def preview(*, binding_id):
        calls.append(("preview", binding_id))
        return {"ok": True, "plan": PLAN}

    def publish(*, plan, confirmation):
        calls.append(("publish", plan, confirmation))
        return {"ok": True, "synchronization": {"status": "acknowledged"}}

    gateway.preview_evidence = preview
    gateway.publish_evidence = publish
    exact = SimpleNamespace(gateway=gateway, trust=SimpleNamespace(trusted_origins=frozenset()))
    app = create_app(str(tmp_path), exact_contract_manager=exact,
                     run_manager=SimpleNamespace(close=lambda: None))
    with TestClient(app, base_url="http://127.0.0.1:8766") as client:
        client.headers.update({"x-apatch-studio-session": app.state.studio_guard.token,
                               "origin": "http://127.0.0.1:8766"})
        yield client, gateway, calls


def test_exact_preview_then_publish_reaches_same_configured_gateway(configured):
    client, gateway, calls = configured
    preview = client.post(PREVIEW, json={"binding_id": BINDING})
    assert preview.status_code == 200
    assert preview.json()["plan"] == PLAN
    confirmation = "publish:" + PLAN["plan_hash"]
    published = client.post(PUBLISH, json={"plan": PLAN, "confirmation": confirmation})
    assert published.status_code == 200
    assert published.json()["synchronization"]["status"] == "acknowledged"
    assert calls == [("preview", BINDING), ("publish", PLAN, confirmation)]


@pytest.mark.parametrize("path,body", [
    (PREVIEW, {"binding_id": "../foreign"}),
    (PREVIEW, {"binding_id": BINDING, "workspace": "/foreign"}),
    (PUBLISH, {"plan": PLAN, "confirmation": ""}),
    (PUBLISH, {"plan": PLAN, "confirmation": "publish", "bypass": True}),
])
def test_malformed_or_extra_fields_never_reach_gateway(configured, path, body):
    client, gateway, calls = configured
    assert client.post(path, json=body).status_code == 422
    assert calls == []


@pytest.mark.parametrize("path,body", [
    (PREVIEW, {"binding_id": BINDING}),
    (PUBLISH, {"plan": PLAN, "confirmation": "publish"}),
])
def test_publication_keeps_local_session_and_same_origin_guards(configured, path, body):
    client, gateway, calls = configured
    assert client.post(path, json=body, headers={"x-apatch-studio-session": ""}).status_code == 401
    response = client.post(path, json=body, headers={"origin": "https://trust-chain.ai"})
    assert response.status_code == 403
    assert "access-control-allow-origin" not in response.headers
    assert calls == []


def test_gateway_refusal_preserves_reason_without_claiming_publication(configured):
    client, gateway, calls = configured
    def refuse(**_):
        raise GovernedWorkGatewayError("Preview the exact evidence first", code="publication_preview_required")
    gateway.publish_evidence = refuse
    response = client.post(PUBLISH, json={"plan": PLAN, "confirmation": "publish"})
    assert response.status_code == 409
    assert response.json() == {"ok": False, "error": "Preview the exact evidence first",
                               "error_code": "publication_preview_required"}
    assert calls == []


def test_unconfigured_publication_is_explicitly_unavailable(tmp_path):
    app = create_app(str(tmp_path), run_manager=SimpleNamespace(close=lambda: None))
    with TestClient(app, base_url="http://127.0.0.1:8766") as client:
        response = client.post(PREVIEW, json={"binding_id": BINDING}, headers={
            "x-apatch-studio-session": app.state.studio_guard.token,
            "origin": "http://127.0.0.1:8766"})
        assert response.status_code == 503
        assert response.json()["error_code"] == "governed_evidence_unconfigured"


def test_exact_hash_is_forwarded_and_invalid_hash_never_reaches_gateway(configured):
    client, gateway, calls = configured
    seen = []
    def exact(**kwargs):
        seen.append(kwargs)
        return {'ok': True, 'plan': PLAN}
    gateway.preview_evidence = exact
    body = {'binding_id': BINDING, 'evidence_bundle_hash': 'sha256:'+'e'*64}
    assert client.post(PREVIEW, json=body).status_code == 200
    assert seen == [body]
    assert client.post(PREVIEW, json={**body, 'evidence_bundle_hash': '../foreign'}).status_code == 422
    assert seen == [body]
