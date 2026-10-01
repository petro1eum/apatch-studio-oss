"""Native Studio document publication; every identity and contract is a fixture."""
import base64
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import subprocess

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
import pytest
from fastapi.testclient import TestClient

SPEC = "SPEC-PUBLICATION-1"
RFP_TEXT = "# RFP-PUBLICATION-1 — Уже утверждено\r\n\r\nExact owner content.\r\n"
SPEC_TEXT = "# SPEC-PUBLICATION-1 — Exact documents\n\n> **RFP:** RFP-PUBLICATION-1\n\n## R0 Publish\n"
OWNER = "publication-owner-fixture"


@pytest.fixture
def api():
    from apatch import sdd_publication
    return sdd_publication


def write(root, path, value):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(value if isinstance(value, bytes) else json.dumps(value).encode("utf-8"))
    return target


def byte_hash(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


@pytest.fixture
def workspace(tmp_path, monkeypatch, api):
    from apatch.sdd_integrity import canonical_hash, freeze_contract, validate_task_envelope
    from apatch.trustchain_helper import TrustChainHelper
    root = tmp_path / "workspace"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
    key = tmp_path / "owner-key.pem"
    key.write_bytes(Ed25519PrivateKey.generate().private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    for name in ("APATCH_AGENT_SIGN_CMD", "APATCH_AGENT_PUBKEY", "APATCH_AGENT_CERT",
                 "APATCH_PLATFORM_URL", "APATCH_CANONICAL_RUNTIME", "APATCH_LANE_ID"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("APATCH_AGENT_ID", OWNER)
    monkeypatch.setenv("APATCH_AGENT_KEY", str(key))
    monkeypatch.setenv("APATCH_KEY_BACKEND", "pem")
    judge = b"def test_already_frozen():\n    assert True\n"
    write(root, "tests/frozen/test_feature.py", judge)
    command = [sys.executable, "-m", "pytest", "tests/frozen/test_feature.py", "-q"]
    request = {"brief_hash": "sha256:" + "1" * 64, "rfp_hash": byte_hash(RFP_TEXT.encode()),
        "spec_hash": byte_hash(SPEC_TEXT.encode()), "plan_hash": "sha256:" + "4" * 64,
        "baseline_hash": "sha256:" + "5" * 64,
        "coverage": {"complete": True, "missing": [], "ambiguous": [], "waivers": []},
        "authority": {"actor_id": OWNER, "role": "authority"}, "source_mutation_count": 0,
        "frozen_at": "2026-10-01T00:00:00Z", "obligations": [{
            "acceptance_id": "AC-0", "test_id": SPEC + "#R0", "oracle": "Exact documents only",
            "perspectives": ["positive", "negative", "boundary", "regression"],
            "asset_hashes": [byte_hash(judge)],
            "judge_assets": [{"path": "tests/frozen/test_feature.py", "sha256": byte_hash(judge)}],
            "command": command, "command_hash": canonical_hash(command),
            "baseline": {"kind": "observed_red", "result_hash": "sha256:" + "6" * 64},
            "falsification": {"kind": "reversible_seed", "expected": "red", "target_hash": "sha256:" + "7" * 64,
                              "target_path": "docs/specs/" + SPEC + ".md"},
            "approver": OWNER, "material": True}]}
    contract = freeze_contract(request)
    envelope = validate_task_envelope({"schema": "apatch.sdd.task-envelope.v1",
        "requirement": SPEC + "#R0", "contract_hash": contract["document_hash"],
        "baseline_hash": request["baseline_hash"], "allowed_reads": ["docs/**", "tests/**"],
        "allowed_writes": ["src/feature.py"], "allowed_symbols": ["feature.apply"],
        "forbidden_paths": ["docs/RFP-*.md", "docs/specs/**", "tests/**"],
        "tools": ["apatch_execute_next"], "commands": [command], "network": [], "remote": [], "services": [],
        "budgets": {"files": 1, "insertions": 1, "deletions": 0, "seconds": 900},
        "checks": ["AC-0"], "rollback_owner": "session:self", "containment": "mediated_only"})
    write(root, ".apatch/sdd_verification_contract.json", contract)
    write(root, ".apatch/sdd/frozen/" + contract["document_hash"][7:] + ".json", contract)
    write(root, ".apatch/sdd/envelopes/" + SPEC + "/R0.json", envelope)
    write(root, ".apatch/sdd/prepared/" + SPEC + ".json", {
        "schema": "apatch.studio.sdd-preparation.v1", "spec_id": SPEC,
        "contract_request": {key: value for key, value in request.items() if key != "authority"},
        "task_envelopes": {"R0": {"requirement": SPEC + "#R0"}}, "source_mutation_count": 0})
    write(root, ".apatch/session_state.json", {"phase": "complete", "session_id": "fixture-ended",
                                               "ended_at": "2026-10-01T00:00:00Z"})
    write(root, ".apatch/studio/locks/old.json", {"locked": True, "release_history": ["must remain exact"]})
    helper = TrustChainHelper(str(root), auto_init=True)
    assert helper.has_trustchain()
    assert helper.commit_action("apatch", {"action": "test_fixture_identity", "functional_acceptance": False})
    return root


def review(api, root):
    return api.prepare_document_publication(root, spec_id=SPEC, spec_markdown=SPEC_TEXT, rfp_markdown=RFP_TEXT)


def publish(api, root, value):
    return api.publish_documents(root, value, authority_id=OWNER,
        expected_snapshot=value["document_hash"], confirmed=True)


def preserved(root):
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*")
            if path.is_file() and (str(path.relative_to(root)).startswith(("tests/", ".apatch/sdd/frozen/",
                  ".apatch/sdd/envelopes/", ".apatch/sdd/prepared/", ".apatch/studio/locks/"))
                or path.name in {"sdd_verification_contract.json", "session_state.json"})}


def native_app(root, identity_root):
    from apatch_studio.app import create_app
    from apatch_studio.security import StudioRequestGuard
    guard = StudioRequestGuard(token="publication-native-app-fixture")
    app = create_app(str(root), guard=guard, identity_root=identity_root)
    return app, {"X-APatch-Studio-Session": guard.token, "Origin": "http://localhost"}


def separate_owner_executor(root, state, monkeypatch):
    from apatch.trust_identity import load_local_identity
    owner_key = os.environ["APATCH_AGENT_KEY"]
    executor_key = state.parent / "separate-executor.pem"
    executor_key.write_bytes(Ed25519PrivateKey.generate().private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    write(root, ".apatch/agent-identity.json", {
        "agent_id": "separate-publication-executor", "key": str(executor_key)})
    write(state, "machine-identity.json", {
        "schema": "apatch.studio.machine-identity.v1", "machine_name": OWNER,
        "key_path": owner_key, "certificate_path": None, "certified": True})
    for name in ("APATCH_AGENT_ID", "APATCH_AGENT_KEY", "APATCH_AGENT_CERT"):
        monkeypatch.delenv(name, raising=False)
    executor = load_local_identity(str(root))
    assert executor.agent_id == "separate-publication-executor"
    from apatch_studio.endpoint_enrollment import apply_stored_identity
    assert apply_stored_identity(state)
    owner = load_local_identity(str(root))
    assert owner.agent_id == OWNER
    assert owner.key_provider.get_public_key() != executor.key_provider.get_public_key()
    return owner_key, executor_key


def test_full_app_exact_publication_distinct_native_owner_and_executor(api, workspace, tmp_path, monkeypatch):
    from apatch.trust_identity import load_local_identity
    from apatch.enforcement import rebuild_notarized_index_from_ledger
    state = tmp_path / "native-studio-owner"
    separate_owner_executor(workspace, state, monkeypatch)
    before = preserved(workspace)
    app, headers = native_app(workspace, state)
    base = "/api/v1/specs/" + SPEC + "/document-publication"
    paths = [getattr(route, "path", "") for route in app.router.routes]
    assert paths.index("/api/v1/specs/{spec_id}/document-publication") < paths.index("/{route:path}")
    body = {"request_id": "apsreq_full_native_publication", "spec_markdown": SPEC_TEXT, "rfp_markdown": RFP_TEXT}
    with TestClient(app, base_url="http://localhost") as client:
        assert client.post(base, json=body).status_code == 401
        assert client.post(base, headers={**headers, "Origin": "http://evil.example"}, json=body).status_code == 403
        assert client.post(base, headers=headers, json={**body, "authority_id": OWNER}).status_code == 422
        proposed = client.post(base, headers=headers, json=body)
        assert proposed.status_code == 200, proposed.text
        assert proposed.json()["functional_acceptance"] is False
        assert not (workspace / "docs").exists()
        approval = {"request_id": "apsreq_full_native_approval", "confirmed": True,
                    "snapshot": proposed.json()["snapshot"]}
        for injection in ({"owner": OWNER}, {"confirmed": 1}, {"confirmed": False}):
            rejected = client.post(base + "/approve", headers=headers, json={**approval, **injection})
            assert rejected.status_code == 422, rejected.text
        result = client.post(base + "/approve", headers=headers, json=approval)
        assert result.status_code == 200, result.text
        value = result.json()
        assert value["status"] == "completed"
        assert value["functional_acceptance"] is False
        assert client.get(base, headers=headers).json() == value
        assert client.post(base + "/approve", headers=headers, json=approval).json() == value
    assert preserved(workspace) == before
    assert (workspace / "docs/RFP-PUBLICATION-1.md").read_bytes() == RFP_TEXT.encode()
    assert (workspace / "docs/specs/SPEC-PUBLICATION-1.md").read_bytes() == SPEC_TEXT.encode()
    identity = load_local_identity(str(workspace))
    assert identity.agent_id == OWNER
    receipt = value["receipt"]
    review = value["review"]
    for stage, field in (("approved", "approval"), ("written", "mutation"), ("completed", "completion")):
        expected = api._payload(review, stage=stage,
            transaction_id="document-publication:" + review["document_hash"][7:],
            created_paths=receipt["created_paths"])
        api._verified_record(workspace, receipt[field], identity, expected)
        raw = json.loads((workspace / ".trustchain" / receipt[field]["object_path"]).read_text())
        assert raw.get("value", raw)["key_id"] == OWNER
    index = rebuild_notarized_index_from_ledger(str(workspace))
    assert set(index["committed_files"]) == {item["path"] for item in review["documents"]}


def test_full_app_executor_cannot_publish_as_stored_owner(api, workspace, tmp_path, monkeypatch):
    state = tmp_path / "native-studio-owner"
    _owner_key, executor_key = separate_owner_executor(workspace, state, monkeypatch)
    monkeypatch.setenv("APATCH_AGENT_ID", "separate-publication-executor")
    monkeypatch.setenv("APATCH_AGENT_KEY", str(executor_key))
    app, headers = native_app(workspace, state)
    body = {"request_id": "apsreq_executor_cannot_publish", "spec_markdown": SPEC_TEXT, "rfp_markdown": RFP_TEXT}
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post("/api/v1/specs/" + SPEC + "/document-publication", headers=headers, json=body)
        assert response.status_code == 422, response.text
        assert "frozen owner" in response.json()["error"]
        assert not (workspace / "docs").exists()


def test_absent_core_publication_capability_is_503_without_writes(api, workspace, tmp_path, monkeypatch):
    import apatch
    monkeypatch.setattr(apatch, "sdd_publication", object())
    app, headers = native_app(workspace, tmp_path / "absent-owner")
    with TestClient(app, base_url="http://localhost") as client:
        response = client.get("/api/v1/specs/" + SPEC + "/document-publication", headers=headers)
        assert response.status_code == 503, response.text
        assert response.json()["error_code"] == "sdd_document_publication_unavailable"
    assert not (workspace / "docs").exists()


def test_publication_review_rejects_request_id_reuse_with_changed_bytes(api, workspace, tmp_path, monkeypatch):
    state = tmp_path / "native-studio-owner"
    separate_owner_executor(workspace, state, monkeypatch)
    app, headers = native_app(workspace, state)
    base = "/api/v1/specs/" + SPEC + "/document-publication"
    body = {"request_id": "apsreq_review_id_fixture", "spec_markdown": SPEC_TEXT, "rfp_markdown": RFP_TEXT}
    with TestClient(app, base_url="http://localhost") as client:
        initial = client.post(base, headers=headers, json=body)
        assert initial.status_code == 200, initial.text
        assert client.post(base, headers=headers, json=body).json() == initial.json()
        changed = client.post(base, headers=headers, json={**body, "rfp_markdown": RFP_TEXT + "\n"})
        assert changed.status_code == 422, changed.text
        assert "reused" in changed.json()["error"]
        assert client.get(base, headers=headers).json() == initial.json()
    assert not (workspace / "docs").exists()


def test_approve_old_snapshot_or_other_stored_owner_never_writes(api, workspace, tmp_path, monkeypatch):
    state = tmp_path / "native-studio-owner"
    owner_key, _executor_key = separate_owner_executor(workspace, state, monkeypatch)
    app, headers = native_app(workspace, state)
    base = "/api/v1/specs/" + SPEC + "/document-publication"
    body = {"request_id": "apsreq_snapshot_fixture", "spec_markdown": SPEC_TEXT, "rfp_markdown": RFP_TEXT}
    with TestClient(app, base_url="http://localhost") as client:
        initial = client.post(base, headers=headers, json=body)
        assert initial.status_code == 200, initial.text
        approval = {"request_id": "apsreq_snapshot_approval", "confirmed": True,
                    "snapshot": initial.json()["snapshot"]}
        stale = client.post(base + "/approve", headers=headers, json={**approval, "snapshot": "sha256:" + "0" * 64})
        assert stale.status_code == 409, stale.text
        write(state, "machine-identity.json", {"schema": "apatch.studio.machine-identity.v1",
            "machine_name": "different-stored-owner", "key_path": owner_key,
            "certificate_path": None, "certified": True})
        wrong_owner = client.post(base + "/approve", headers=headers, json=approval)
        assert wrong_owner.status_code == 409, wrong_owner.text
        assert not (workspace / "docs").exists()

