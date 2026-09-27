"""HTTP tests use real Core signatures and mutation lifecycle, not a green stub."""
import json
from pathlib import Path

import pytest

import importlib.util

_fixture_spec = importlib.util.spec_from_file_location(
    "draft_owner_fixture", Path(__file__).resolve().parents[1] / "sdd/test_sdd_owner_execution_flow.py")
_fixture_module = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_module)
_client = _fixture_module._client

RUN = "apr_abcdef1234567890abcdef1234567890"
RETRY = "apr_123456abcdef7890123456abcdef7890"
SPEC = "SPEC-STUDIO-CHANGE-ABCDEF123456"
REL = f"docs/specs/{SPEC}.md"
URL = f"/api/v1/runs/{RUN}/draft-amendment"


@pytest.fixture
def setup(tmp_path, monkeypatch):
    from apatch import sdd_draft_amendment as core
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
    key = tmp_path / "identity.pem"
    key.write_bytes(Ed25519PrivateKey.generate().private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    monkeypatch.setenv("APATCH_AGENT_ID", "studio-draft-test")
    monkeypatch.setenv("APATCH_AGENT_KEY", str(key))
    monkeypatch.delenv("APATCH_AGENT_CERT", raising=False)
    # This disposable consumer tests the checkout, not the parent MCP process.
    monkeypatch.delenv("APATCH_CANONICAL_RUNTIME", raising=False)
    monkeypatch.setenv("PYTHONPATH", str(Path(core.__file__).resolve().parent.parent))
    original = f'# {SPEC}\n> **apatch artifact:** `spec:{SPEC}`\n> **ownership mode:** strict\n\n## R1 Future behaviour\n(verify: python3 -m pytest tests/test_future.py -q)\n'
    (tmp_path / REL).parent.mkdir(parents=True)
    (tmp_path / REL).write_text(original)
    client, headers, runs = _client(tmp_path)
    records = {RUN: {"run_id": RUN, "mode": "new_change", "status": "failed", "retry_of": None},
               RETRY: {"run_id": RETRY, "mode": "new_change", "status": "failed", "retry_of": RUN}}
    runs.get = lambda run_id: records[run_id]
    package = {"request_id": "apsreq_draft_prepare_1", "reason": "Repair the original planning contract", "files": [
        {"path": REL, "content": original.replace("## R1 Future behaviour\n", f"## R1 Future behaviour\nowns: {REL}, tests/test_future.py\n")},
        {"path": "tests/test_future.py", "content": "def test_future():\n    assert False, 'implementation remains pending'\n"},
    ]}
    return client, headers, records, package, original


def proposal(client, headers, package, url=URL):
    response = client.post(url, headers=headers, json=package)
    assert response.status_code == 200, response.text
    return response.json()


def approval(snapshot):
    return {"request_id": "apsreq_draft_approve_1", "confirmed": True, "snapshot": snapshot}


def test_existing_failed_plan_is_repaired_in_place_without_accepting_implementation(setup, tmp_path):
    from apatch.external_dependency import _signed_rows
    client, headers, records, package, original = setup
    assert client.get(URL, headers=headers).json()["status"] == "not_prepared"
    retry_url = f"/api/v1/runs/{RETRY}/draft-amendment"
    review = proposal(client, headers, package, retry_url)
    assert (tmp_path / REL).read_text() == original  # preview has no governed mutation
    assert review["review"]["run_id"] == RUN
    result = client.post(retry_url + "/approve", headers=headers, json=approval(review["snapshot"]))
    assert result.status_code == 200, result.text
    assert result.json()["ok"] and result.json()["functional_acceptance"] is False
    assert (tmp_path / REL).read_text() == package["files"][0]["content"]
    assert not (tmp_path / ".apatch/sdd_verification_contract.json").exists()
    rows = _signed_rows(tmp_path)
    approved = [r["payload"] for r in rows if r["tool_id"] == "apatch_draft_amendment" and r["payload"]["stage"] == "approved"]
    assert len(approved) == 1 and approved[0]["owner"]["id"] == "studio-laptop"
    assert approved[0]["owner"]["is_person"] is False
    assert client.post(URL + "/approve", headers=headers, json=approval(review["snapshot"])).json() == result.json()
    assert len(_signed_rows(tmp_path)) == len(rows)
    # A second server reads the signed completion; no in-memory success flag.
    restarted, new_headers, runs = _client(tmp_path)
    runs.get = lambda run_id: records[run_id]
    completed = restarted.get(URL, headers=new_headers).json()
    assert completed["status"] == "completed" and completed["functional_acceptance"] is False
    assert completed["result"] == result.json()


@pytest.mark.parametrize("fault", ["token", "origin", "owner", "confirmation", "snapshot", "drift", "active", "cycle", "source"])
def test_rejected_approval_never_mutates_the_draft(setup, tmp_path, fault):
    client, headers, records, package, original = setup
    review = proposal(client, headers, package)
    payload = approval(review["snapshot"])
    headers = dict(headers)
    if fault == "token":
        headers.pop("x-apatch-studio-session")
    elif fault == "origin":
        headers["origin"] = "https://untrusted.example"
    elif fault == "owner":
        payload["owner"] = {"kind": "machine", "id": "forged-owner"}
    elif fault == "confirmation":
        payload["confirmed"] = False
    elif fault == "snapshot":
        payload["snapshot"] = "sha256:" + "0" * 64
    elif fault == "drift":
        (tmp_path / REL).write_text(original + "changed after review\n")
    elif fault == "active":
        records[RUN]["status"] = "running"
    elif fault == "cycle":
        records[RUN]["retry_of"] = RUN
    else:
        package["files"].append({"path": "src/app.py", "content": "escaped = True\n"})
        denied = client.post(URL, headers=headers, json=package)
        assert denied.status_code == 409, denied.text
        assert not (tmp_path / "src/app.py").exists()
        return
    before = (tmp_path / REL).read_bytes()
    denied = client.post(URL + "/approve", headers=headers, json=payload)
    assert denied.status_code in {401, 403, 409, 422}, denied.text
    assert (tmp_path / REL).read_bytes() == before
    assert not (tmp_path / "tests/test_future.py").exists()
    assert not (tmp_path / ".apatch/sdd_verification_contract.json").exists()


def test_pending_repair_blocks_owner_freeze_and_recovers_same_snapshot(setup, tmp_path, monkeypatch):
    from apatch import sdd_draft_amendment as core
    from apatch_studio.sdd_workflow import SddWorkflowFacade, SddWorkflowError
    client, headers, _records, package, _original = setup
    review = proposal(client, headers, package)
    actual_record = core._record
    def interrupt(*args, **kwargs):
        value = actual_record(*args, **kwargs)
        if args[2] == "approved":
            raise OSError("process stopped after durable approval")
        return value
    with monkeypatch.context() as scope:
        scope.setattr(core, "_record", interrupt)
        pending = client.post(URL + "/approve", headers=headers, json=approval(review["snapshot"]))
        assert pending.status_code == 409, pending.text
    with pytest.raises(SddWorkflowError) as error:
        SddWorkflowFacade(tmp_path).freeze_requirement(SPEC, "R1", owner_actor_id="studio-laptop", confirmed=True)
    assert error.value.code == "sdd_draft_pending"
    assert not (tmp_path / ".apatch/sdd/frozen").exists()
    recovered = client.post(URL + "/approve", headers=headers, json=approval(review["snapshot"]))
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["functional_acceptance"] is False
