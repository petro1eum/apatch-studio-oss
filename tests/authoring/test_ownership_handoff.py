"""Real native owner/executor separation for ownership-only corrections."""
import copy
import json
import pytest
from fastapi.testclient import TestClient
from test_document_publication import api, workspace, write, byte_hash, preserved, OWNER, SPEC, native_app, separate_owner_executor

OLD = "SPEC-PREDECESSOR-1"
OLD_TEXT = f"# {OLD}\n> **ownership mode:** strict\n## R1 Memory\nowns: backend/a.py\nKeep memory isolated.\n(verify: pytest tests/frozen/test_feature.py)\n"
NEW_TEXT = f"# {SPEC}\n> **ownership mode:** strict\n## R0 Signed memory\nowns: backend/a.py\n(verify: pytest tests/frozen/test_feature.py)\n"


@pytest.fixture
def ownership_workspace(workspace):
    from apatch.sdd_integrity import _seal
    root = workspace
    active = json.loads((root / ".apatch/sdd_verification_contract.json").read_text())
    active = _seal({**{key: value for key, value in active.items() if key != "document_hash"},
                    "spec_hash": byte_hash(NEW_TEXT.encode())})
    write(root, ".apatch/sdd_verification_contract.json", active)
    write(root, ".apatch/sdd/frozen/" + active["document_hash"][7:] + ".json", active)
    package_path = ".apatch/sdd/prepared/" + SPEC + ".json"
    package = json.loads((root / package_path).read_text())
    package["contract_request"]["spec_hash"] = active["spec_hash"]
    write(root, package_path, package)
    envelope_path = ".apatch/sdd/envelopes/" + SPEC + "/R0.json"
    envelope = json.loads((root / envelope_path).read_text())
    envelope = _seal({**{key: value for key, value in envelope.items() if key != "document_hash"}, "contract_hash": active["document_hash"]})
    write(root, envelope_path, envelope)
    old = copy.deepcopy(active)
    old["spec_hash"] = byte_hash(OLD_TEXT.encode())
    old["obligations"][0]["test_id"] = OLD + "#R1"
    old = _seal({key: value for key, value in old.items() if key != "document_hash"})
    write(root, ".apatch/sdd/frozen/" + old["document_hash"][7:] + ".json", old)
    write(root, "docs/specs/" + OLD + ".md", OLD_TEXT.encode())
    write(root, "docs/specs/" + SPEC + ".md", NEW_TEXT.encode())
    write(root, "backend/a.py", b"# preserve source\n")
    body = dict(request_id="apsreq_native_ownership_handoff", source_spec=OLD,
        source_contract_hash=old["document_hash"], paths=["backend/a.py"], reason="Owner approved ownership-only correction")
    return root, body


def test_owner_approves_exact_handoff_over_native_route(ownership_workspace, tmp_path, monkeypatch):
    root, body = ownership_workspace
    state = tmp_path / "native-owner"
    separate_owner_executor(root, state, monkeypatch)
    before = preserved(root)
    app, headers = native_app(root, state)
    base = "/api/v1/specs/" + SPEC + "/ownership-handoff"
    routes = [getattr(r, "path", "") for r in app.routes]
    assert routes.index("/api/v1/specs/{spec_id}/ownership-handoff") < routes.index("/{route:path}")
    with TestClient(app, base_url="http://localhost") as client:
        assert client.get(base, headers=headers).json()["status"] == "not_prepared"
        assert client.post(base, json=body).status_code == 401
        assert client.post(base, headers={**headers, "Origin": "http://evil.example"}, json=body).status_code == 403
        assert client.post(base, headers=headers, json={**body, "actor_id": OWNER}).status_code == 422
        proposed = client.post(base, headers=headers, json=body)
        assert proposed.status_code == 200, proposed.text
        assert (root / "docs/specs" / (OLD + ".md")).read_text() == OLD_TEXT
        assert client.post(base, headers=headers, json=body).json() == proposed.json()
        assert client.post(base, headers=headers, json={**body, "reason": "Changed request under same id"}).status_code == 422
        approval = dict(request_id="apsreq_native_ownership_approval", confirmed=True, snapshot=proposed.json()["snapshot"])
        for extra in ({"owner": OWNER}, {"confirmed": False}, {"confirmed": 1}):
            assert client.post(base + "/approve", headers=headers, json={**approval, **extra}).status_code == 422
        result = client.post(base + "/approve", headers=headers, json=approval)
        assert result.status_code == 200, result.text
        assert result.json()["status"] == "completed" and result.json()["functional_acceptance"] is False
        assert client.get(base, headers=headers).json() == result.json()
        assert client.post(base + "/approve", headers=headers, json=approval).json() == result.json()
    assert before == preserved(root)
    assert (root / "backend/a.py").read_bytes() == b"# preserve source\n"
    assert (root / "docs/specs" / (SPEC + ".md")).read_text() == NEW_TEXT


def test_executor_cannot_claim_owner_authority(ownership_workspace, tmp_path, monkeypatch):
    root, body = ownership_workspace
    state = tmp_path / "native-owner"
    _, executor = separate_owner_executor(root, state, monkeypatch)
    monkeypatch.setenv("APATCH_AGENT_ID", "separate-publication-executor")
    monkeypatch.setenv("APATCH_AGENT_KEY", str(executor))
    app, headers = native_app(root, state)
    with TestClient(app, base_url="http://localhost") as client:
        result = client.post("/api/v1/specs/" + SPEC + "/ownership-handoff", headers=headers, json=body)
        assert result.status_code == 422, result.text
    assert (root / "docs/specs" / (OLD + ".md")).read_text() == OLD_TEXT
