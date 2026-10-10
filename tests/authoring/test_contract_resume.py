"""Real signed contract recovery across native Studio specification switches."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex

import pytest

ROOT = Path(__file__).resolve().parents[2]
fixture_spec = importlib.util.spec_from_file_location(
    "contract_resume_fixtures", ROOT / "tests/authoring/test_shared_authoring_roundtrip.py"
)
fixtures = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(fixtures)
SPEC = "SPEC-DEMO-1"
BASE = "/api/v1/specs/" + SPEC + "/requirements/R1"
OTHER = "/api/v1/specs/SPEC-OTHER-1/requirements/R1"


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def post(client, headers, url, **values):
    from uuid import uuid4
    values.setdefault("request_id", "apsreq_resume_" + uuid4().hex)
    return client.post(url, headers=headers, json=values)


@pytest.fixture
def switched(tmp_path, monkeypatch):
    from apatch.sdd_integrity import canonical_hash
    from apatch import sdd_judge_amendment
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption

    assert sdd_judge_amendment.PYTEST_BOOTSTRAP_AMENDMENT is True
    key = tmp_path / "fixture-key.pem"
    key.write_bytes(Ed25519PrivateKey.generate().private_bytes(
        Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    monkeypatch.setenv("APATCH_AGENT_ID", "contract-resume-fixture")
    monkeypatch.setenv("APATCH_AGENT_KEY", str(key))
    monkeypatch.setenv("APATCH_KEY_BACKEND", "pem")
    for name in ("APATCH_CANONICAL_RUNTIME", "APATCH_AGENT_SIGN_CMD",
                 "APATCH_AGENT_PUBKEY", "APATCH_AGENT_CERT"):
        monkeypatch.delenv(name, raising=False)

    canonical = fixtures.fixtures._write_prepared(tmp_path)
    package = json.loads(canonical.read_text())
    (tmp_path / "tests/__init__.py").write_text("")
    (tmp_path / "tests/conftest.py").write_text("# Explicit fixture plugin\n")
    command = [*package["contract_request"]["obligations"][0]["command"], "-p", "tests.conftest"]
    package["contract_request"]["obligations"][0].update(
        command=command, command_hash=canonical_hash(command))
    for envelope in package["task_envelopes"].values():
        envelope["commands"] = [command]
    spec = tmp_path / "docs/specs" / (SPEC + ".md")
    spec.parent.mkdir(parents=True)
    spec.write_text("# " + SPEC + "\n## R1 Reviewed check\n(verify: " +
                    shlex.join(command) + ")\n## R2 Additional check\n")
    package["contract_request"]["spec_hash"] = digest(spec.read_bytes())
    canonical.write_text(json.dumps(package))
    canonical_bytes = canonical.read_bytes()
    client, headers, runs = fixtures.fixtures._client(tmp_path)

    with client:
        review = client.get(BASE + "/execution-contract", headers=headers).json()
        frozen = post(client, headers, BASE + "/execution-contract/freeze",
                      confirmed=True, snapshot=review["approval_snapshot"])
        assert frozen.status_code == 200, frozen.text
        old = json.loads((tmp_path / ".apatch/sdd_verification_contract.json").read_text())
        base_envelope = json.loads((tmp_path / ".apatch/sdd/envelopes" / SPEC / "R1.json").read_text())
        assert post(client, headers, BASE + "/lock/release-request",
                    reason="Prepare additional independent acceptance checks").status_code == 200
        assert post(client, headers, BASE + "/lock/release-answer", decision="grant").status_code == 200
        candidate_path = ".apatch/sdd/prepared/" + SPEC + "-successor.json"
        test_path = "tests/test_additional.py"
        proposal = post(client, headers, BASE + "/authoring", actor_id="agent:preparation",
                        files=[test_path, candidate_path])
        assert proposal.status_code == 200, proposal.text
        approval = post(client, headers, BASE + "/authoring/approve", confirmed=True,
                        snapshot=proposal.json()["snapshot"])
        assert approval.status_code == 200, approval.text
        pending = ("import unittest\nclass Pending(unittest.TestCase):\n"
                   "    def test_pending(self):\n        self.fail('Pending fixture behavior')\n")
        additional_command = ["python3", "-m", "unittest", "discover", "-s", "tests",
                              "-p", "test_additional.py", "-q"]
        additional = {**old["obligations"][0], "acceptance_id": "AC-2",
                      "test_id": test_path, "command": additional_command,
                      "command_hash": canonical_hash(additional_command),
                      "asset_hashes": [digest(pending.encode()), *old["obligations"][0]["asset_hashes"]],
                      "judge_assets": [{"path": test_path, "sha256": digest(pending.encode())},
                                       *old["obligations"][0]["judge_assets"]]}
        candidate = copy.deepcopy(package)
        candidate["objective"] = "Owner-approved successor preserving all original obligations"
        candidate["contract_request"]["obligations"] = [*old["obligations"], additional]
        candidate["task_envelopes"]["R2"].update(checks=["AC-2"], commands=[additional_command])
        fixtures.author(tmp_path, old, approval.json()["grant_hash"],
                        {test_path: pending, candidate_path: json.dumps(candidate)}, monkeypatch)
        selected = post(client, headers, BASE + "/implementation-candidate",
                        candidate_path=candidate_path, authoring_grant_hash=approval.json()["grant_hash"])
        assert selected.status_code == 200, selected.text
        activated = post(client, headers, BASE + "/implementation-candidate/approve",
                         confirmed=True, snapshot=selected.json()["snapshot"])
        assert activated.status_code == 200, activated.text

        judge = tmp_path / "tests/test_feature.py"
        corrected = judge.read_text() + "# Exact owner-approved shared judge correction\n"
        amendment = post(client, headers, BASE + "/judge-amendment", acceptance_id="AC-1",
                         judge_path="tests/test_feature.py", replacement_text=corrected,
                         reason="Preserve shared checks while correcting fixture determinism")
        assert amendment.status_code == 200, amendment.text
        assert amendment.json()["review"]["affected_requirement_refs"] == [SPEC + "#R1", SPEC + "#R2"]
        amended = post(client, headers, BASE + "/judge-amendment/approve", confirmed=True,
                       snapshot=amendment.json()["snapshot"])
        assert amended.status_code == 200, amended.text
        bootstrap = post(client, headers, BASE + "/judge-amendment", acceptance_id="AC-1",
                         judge_path="tests/test_feature.py", replacement_text=corrected,
                         reason="Avoid duplicate loading of the explicit conftest plugin",
                         disable_pytest_conftest_autoload=True)
        assert bootstrap.status_code == 200, bootstrap.text
        bootstrapped = post(client, headers, BASE + "/judge-amendment/approve", confirmed=True,
                            snapshot=bootstrap.json()["snapshot"])
        assert bootstrapped.status_code == 200, bootstrapped.text
        effective = json.loads((tmp_path / ".apatch/sdd_verification_contract.json").read_text())
        envelopes = {rid: json.loads((tmp_path / ".apatch/sdd/envelopes" / SPEC /
                                    (rid + ".json")).read_text()) for rid in ("R1", "R2")}
        assert effective["obligations"][0]["command"] == [*command, "--noconftest"]
        assert judge.read_text() == corrected

        other = copy.deepcopy(package)
        other["spec_id"] = "SPEC-OTHER-1"
        other["objective"] = "Independent second specification"
        other_command = ["python3", "-m", "pytest", "tests/test_other.py", "-q"]
        other_judge = tmp_path / "tests/test_other.py"
        other_judge.write_text("def test_other():\n    assert True\n")
        other["contract_request"]["spec_hash"] = "sha256:" + "c" * 64
        other["contract_request"]["obligations"] = [{
            **package["contract_request"]["obligations"][0], "test_id": "tests/test_other.py",
            "command": other_command, "command_hash": canonical_hash(other_command),
            "asset_hashes": [digest(other_judge.read_bytes())],
            "judge_assets": [{"path": "tests/test_other.py", "sha256": digest(other_judge.read_bytes())}],
        }]
        other["task_envelopes"] = {"R1": {
            **package["task_envelopes"]["R1"], "requirement": "SPEC-OTHER-1#R1",
            "commands": [other_command],
        }}
        canonical.with_name("SPEC-OTHER-1.json").write_text(json.dumps(other))
        other_review = client.get(OTHER + "/execution-contract", headers=headers)
        assert other_review.status_code == 200, other_review.text
        other_frozen = post(client, headers, OTHER + "/execution-contract/freeze", confirmed=True,
                            snapshot=other_review.json()["approval_snapshot"])
        assert other_frozen.status_code == 200, other_frozen.text
        current_bytes = (tmp_path / ".apatch/sdd_verification_contract.json").read_bytes()
        yield {"root": tmp_path, "client": client, "headers": headers, "runs": runs,
               "effective": effective, "envelopes": envelopes, "current_bytes": current_bytes,
               "canonical_bytes": canonical_bytes, "candidate_path": candidate_path,
               "bootstrap_review": bootstrap.json()["review"], "base_envelope": base_envelope}


def test_switch_and_return_preserves_signed_successor_shared_amendment_and_bootstrap(switched):
    root, client, headers = switched["root"], switched["client"], switched["headers"]
    other_envelope = root / ".apatch/sdd/envelopes/SPEC-OTHER-1/R1.json"
    other_bytes = other_envelope.read_bytes()
    lock_path = root / ".apatch/locks" / SPEC / "R1.json"
    journal_path = root / ".apatch/locks/journal.jsonl"
    boundary_bytes, journal_bytes = lock_path.read_bytes(), journal_path.read_bytes()
    assert json.loads(boundary_bytes)["release"]["state"] == "granted"
    reviewed = client.get(BASE + "/execution-contract", headers=headers)
    assert reviewed.status_code == 200, reviewed.text
    review = reviewed.json()
    assert review["status"] == "ready_for_owner"
    assert review["contract_hash"] == switched["effective"]["document_hash"]
    assert review["checks"][0]["test_id"] == switched["effective"]["obligations"][0]["test_id"]
    assert review["scope"]["commands"] == switched["envelopes"]["R1"]["commands"]
    assert (root / ".apatch/sdd_verification_contract.json").read_bytes() == switched["current_bytes"]
    frozen = post(client, headers, BASE + "/execution-contract/freeze",
                  confirmed=True, snapshot=review["approval_snapshot"])
    assert frozen.status_code == 200, frozen.text
    assert lock_path.read_bytes() == boundary_bytes
    assert journal_path.read_bytes() == journal_bytes
    from apatch.external_dependency import _signed_rows
    proofs = _signed_rows(root, tool_ids={"apatch_sdd_contract_resume"})
    assert len(proofs) == 1
    assert proofs[0]["payload"]["functional_acceptance"] is False
    assert proofs[0]["payload"]["contract_hash"] == switched["effective"]["document_hash"]
    assert proofs[0]["payload"]["envelope_hashes"] == {
        rid: value["document_hash"] for rid, value in switched["envelopes"].items()}
    assert json.loads((root / ".apatch/sdd_verification_contract.json").read_text()) == switched["effective"]
    for rid, expected in switched["envelopes"].items():
        assert json.loads((root / ".apatch/sdd/envelopes" / SPEC / (rid + ".json")).read_text()) == expected
    assert other_envelope.read_bytes() == other_bytes
    assert (root / ".apatch/sdd/prepared" / (SPEC + ".json")).read_bytes() == switched["canonical_bytes"]
    rerun = client.get(BASE + "/execution-contract", headers=headers)
    assert rerun.status_code == 200, rerun.text
    assert rerun.json()["status"] == "frozen"
    repeated = post(client, headers, BASE + "/execution-contract/freeze", confirmed=True,
                    snapshot=rerun.json()["approval_snapshot"])
    assert repeated.status_code == 200, repeated.text
    assert lock_path.read_bytes() == boundary_bytes
    assert journal_path.read_bytes() == journal_bytes
    started = client.post("/api/v1/runs", headers=headers, json=fixtures.fixtures._run_payload())
    assert started.status_code == 202, started.text
    assert switched["runs"].bindings[-1]["contract"] == switched["effective"]


@pytest.mark.parametrize("corruption", ["judge", "candidate", "archive", "receipt", "approval", "spec", "envelope", "signature", "history"])
def test_inactive_successor_drift_or_tampering_never_falls_back_to_original(switched, corruption):
    from apatch.sdd_integrity import canonical_hash, validate_task_envelope
    root, client, headers = switched["root"], switched["client"], switched["headers"]
    if corruption in {"judge", "candidate", "spec"}:
        relative = {"judge": "tests/test_feature.py", "candidate": switched["candidate_path"],
                    "spec": "docs/specs/" + SPEC + ".md"}[corruption]
        path = root / relative
        path.write_bytes(path.read_bytes() + b"\n")
    elif corruption == "archive":
        path = root / ".apatch/sdd/frozen" / (switched["effective"]["document_hash"][7:] + ".json")
        value = json.loads(path.read_text())
        value["plan_hash"] = "sha256:" + "f" * 64
        value.pop("document_hash")
        value["document_hash"] = canonical_hash(value)
        path.write_text(json.dumps(value))
    elif corruption == "receipt":
        path = root / ".apatch/sdd/judge-amendments" / (
            switched["bootstrap_review"]["document_hash"][7:]) / "receipt.json"
        value = json.loads(path.read_text())
        value["result"]["envelopes"][str(Path(".apatch/sdd/envelopes") / SPEC / "R1.json")]["budgets"]["files"] += 1
        value.pop("document_hash")
        value["document_hash"] = canonical_hash(value)
        path.write_text(json.dumps(value))
    elif corruption == "approval":
        path = next(root.glob(".apatch/sdd/candidate-reviews/" + SPEC + "/*/history/*-activated.json"))
        value = json.loads(path.read_text())
        value["approved_by"] = "agent:implementation"
        path.write_text(json.dumps(value))
    elif corruption == "history":
        for path in root.glob(".apatch/sdd/candidate-reviews/" + SPEC + "/*/history/*-activated.json"):
            path.unlink()
        (root / ".apatch/sdd/candidate-reviews" / SPEC / "R1.json").unlink()
    elif corruption == "signature":
        from apatch.external_dependency import _signed_rows
        import base64
        rows = _signed_rows(root, tool_ids={"apatch_sdd_judge_amendment"})
        rows = [item for item in rows if item["payload"]["stage"] == "activated"
                and item["payload"]["amendment_id"] == switched["bootstrap_review"]["document_hash"]]
        assert rows
        for row in rows:
            path = root / ".trustchain" / row["object_path"]
            value = json.loads(path.read_text())
            value.get("value", value)["signature"] = base64.b64encode(bytes(64)).decode()
            path.write_text(json.dumps(value))
    else:
        path = root / ".apatch/sdd/envelopes" / SPEC / "R1.json"
        value = json.loads(path.read_text())
        value["budgets"]["files"] += 1
        value.pop("document_hash")
        path.write_text(json.dumps(validate_task_envelope(value)))
    rejected = client.get(BASE + "/execution-contract", headers=headers)
    assert rejected.status_code == 409, rejected.text
    assert (root / ".apatch/sdd_verification_contract.json").read_bytes() == switched["current_bytes"]


def test_old_or_missing_envelopes_are_recovered_only_from_exact_approved_history(switched):
    root, client, headers = switched["root"], switched["client"], switched["headers"]
    envelope_dir = root / ".apatch/sdd/envelopes" / SPEC
    (envelope_dir / "R1.json").write_text(json.dumps(switched["base_envelope"]))
    (envelope_dir / "R2.json").unlink()
    reviewed = client.get(BASE + "/execution-contract", headers=headers)
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["contract_hash"] == switched["effective"]["document_hash"]
    frozen = post(client, headers, BASE + "/execution-contract/freeze", confirmed=True,
                  snapshot=reviewed.json()["approval_snapshot"])
    assert frozen.status_code == 200, frozen.text
    for rid, expected in switched["envelopes"].items():
        assert json.loads((envelope_dir / (rid + ".json")).read_text()) == expected


def test_coordinated_resealed_root_history_cannot_replace_signed_candidate_effects(switched):
    from apatch.sdd_integrity import _seal, validate_task_envelope
    root, client, headers = switched["root"], switched["client"], switched["headers"]
    path = next(root.glob(".apatch/sdd/candidate-reviews/" + SPEC + "/*/history/*-activated.json"))
    record = json.loads(path.read_text())
    old_snapshot = record["snapshot"]
    contract = record["review"]["successor_contract"]
    contract.pop("document_hash")
    contract["plan_hash"] = "sha256:" + "f" * 64
    contract = _seal(contract)
    envelopes = {}
    for rid, value in record["review"]["task_envelopes"].items():
        value.pop("document_hash")
        value["contract_hash"] = contract["document_hash"]
        envelopes[rid] = validate_task_envelope(value)
    review = record["review"]
    review.pop("document_hash")
    review.update(successor_contract=contract, task_envelopes=envelopes)
    record["review"] = _seal(review)
    record["snapshot"] = record["review"]["document_hash"]
    result = record["activation"]
    result.update(contract=contract, contract_hash=contract["document_hash"], envelopes=envelopes)
    new_path = path.with_name(record["snapshot"][7:] + "-activated.json")
    new_path.write_text(json.dumps(record))
    path.unlink()
    (root / ".apatch/sdd/frozen" / (contract["document_hash"][7:] + ".json")).write_text(json.dumps(contract))
    receipt = _seal({"scope_snapshot": record["snapshot"], "contract_hash": contract["document_hash"],
                     "result": result})
    (root / ".apatch/sdd/successor-receipts" / (record["snapshot"][7:] + ".json")).write_text(json.dumps(receipt))
    assert record["snapshot"] != old_snapshot
    rejected = client.get(BASE + "/execution-contract", headers=headers)
    assert rejected.status_code == 409, rejected.text
    assert (root / ".apatch/sdd_verification_contract.json").read_bytes() == switched["current_bytes"]


def test_resume_requires_same_owner_and_rejects_changes_since_review(switched):
    root, client, headers = switched["root"], switched["client"], switched["headers"]
    reviewed = client.get(BASE + "/execution-contract", headers=headers)
    assert reviewed.status_code == 200, reviewed.text
    snapshot = reviewed.json()["approval_snapshot"]
    fixtures.fixtures._enrol(root, name="different-owner")
    denied = post(client, headers, BASE + "/execution-contract/freeze", confirmed=True, snapshot=snapshot)
    assert denied.status_code == 409, denied.text
    fixtures.fixtures._enrol(root)
    (root / "tests/test_feature.py").write_text("def test_feature():\n    assert False\n")
    denied = post(client, headers, BASE + "/execution-contract/freeze", confirmed=True, snapshot=snapshot)
    assert denied.status_code == 409, denied.text
    assert (root / ".apatch/sdd_verification_contract.json").read_bytes() == switched["current_bytes"]


def test_resume_refuses_an_active_governed_session(switched):
    root, client, headers = switched["root"], switched["client"], switched["headers"]
    reviewed = client.get(BASE + "/execution-contract", headers=headers).json()
    state = root / ".apatch/lanes/other-work/session_state.json"
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({"session_id": "apatch_sess_foreign_active"}))
    denied = post(client, headers, BASE + "/execution-contract/freeze",
                  confirmed=True, snapshot=reviewed["approval_snapshot"])
    assert denied.status_code == 409, denied.text
    assert (root / ".apatch/sdd_verification_contract.json").read_bytes() == switched["current_bytes"]
