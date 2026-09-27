"""Real signed preparation → revision → owner successor activation in a temp workspace.

Use the candidate Core on PYTHONPATH. No real consumer authority is exercised.
The deliberately failing fixture check is never accepted as a business feature.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

from apatch_studio import candidate_workflow

ROOT = Path(__file__).resolve().parents[2]
fixture_spec = importlib.util.spec_from_file_location("successor_real_fixture", ROOT / "tests/sdd/test_sdd_owner_execution_flow.py")
fixtures = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(fixtures)


def post(client, headers, url, **values):
    return client.post(url, headers=headers, json={"request_id": "apsreq_successor_roundtrip", **values})


def author(root, old, grant_hash, files, monkeypatch, *, replace=False):
    from apatch.runtime.session import start_session
    from apatch.runtime.runtime import MutationRuntime
    from apatch.workflows import generate_patch_jsonl_batch
    from apatch.sdd_authoring import VERIFY_COMMAND
    started = start_session(str(root), "Prepare independent candidate fixtures", sdd_contract=old,
        task_envelope={"schema": "apatch.sdd.authoring-reference.v1", "grant_hash": grant_hash},
        actor={"actor_id": "agent:preparation", "role": "implementation"})
    assert started["ok"], started
    sid = started["session"]["session_id"]
    needles = [{"action": "replace", "target_file": path, "find_text": (root / path).read_text(), "replace_text": content}
               if replace else {"action": "create", "target_file": path, "content": content} for path, content in files.items()]
    patch = generate_patch_jsonl_batch(needles=needles, target_dir=str(root), out_path=str(root / "patches.jsonl"), governed_session_id=sid)
    assert patch["ok"], patch
    runtime = MutationRuntime(str(root), session_id=sid, session_token=started["session_token"])
    applied = runtime.apply_session(patch["out_path"], verify_deferred=True)
    assert applied["ok"], applied
    assert not applied.get("continue"), applied
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"])
    verified = runtime.verify_run(verify=VERIFY_COMMAND)
    assert verified["ok"], verified
    attested = runtime.attest(message="Preparation only; fixture behaviour remains intentionally red")
    assert attested["ok"], attested
    closed = runtime.close_session()
    assert closed["ok"], closed


def test_real_signed_revision_owner_activation_and_receipt_gap(tmp_path, monkeypatch):
    from apatch.sdd_integrity import canonical_hash
    canonical = fixtures._write_prepared(tmp_path)
    canonical_bytes = canonical.read_bytes()
    judge_bytes = (tmp_path / "tests/test_feature.py").read_bytes()
    client, headers, _ = fixtures._client(tmp_path)
    base = "/api/v1/specs/SPEC-DEMO-1/requirements/R1"
    test_path = "tests/test_additional.py"
    candidate_path = ".apatch/sdd/prepared/SPEC-DEMO-1-FOUNDATION.json"
    initial_test = "import unittest\nclass Additional(unittest.TestCase):\n    def test_pending(self):\n        self.fail('Pending behaviour')\n"
    with client:
        reviewed = client.get(base + "/execution-contract", headers=headers).json()
        frozen = post(client, headers, base + "/execution-contract/freeze", confirmed=True, snapshot=reviewed["approval_snapshot"])
        assert frozen.status_code == 200, frozen.text
        old_bytes = (tmp_path / ".apatch/sdd_verification_contract.json").read_bytes()
        old = json.loads(old_bytes)
        assert post(client, headers, base + "/lock/release-request", reason="Prepare additional acceptance requirements with original checks retained").status_code == 200
        assert post(client, headers, base + "/lock/release-answer", decision="grant").status_code == 200
        proposal = post(client, headers, base + "/authoring", actor_id="agent:preparation", files=[test_path, candidate_path])
        assert proposal.status_code == 200, proposal.text
        granted = post(client, headers, base + "/authoring/approve", confirmed=True, snapshot=proposal.json()["snapshot"])
        assert granted.status_code == 200, granted.text
        first_hash = granted.json()["grant_hash"]
        author(tmp_path, old, first_hash, {test_path: initial_test, candidate_path: json.dumps({"source_mutation_count": 0, "status": "draft_only"})}, monkeypatch)
        invalid = post(client, headers, base + "/implementation-candidate", candidate_path=candidate_path, authoring_grant_hash=first_hash)
        assert invalid.status_code == 422, invalid.text
        assert (tmp_path / ".apatch/sdd_verification_contract.json").read_bytes() == old_bytes

        revision = post(client, headers, base + "/authoring", actor_id="agent:preparation", files=[test_path, candidate_path], previous_grant_hash=first_hash)
        assert revision.status_code == 200, revision.text
        assert revision.json()["scope"]["before_hashes"][test_path] == "sha256:" + hashlib.sha256(initial_test.encode()).hexdigest()
        second_granted = post(client, headers, base + "/authoring/approve", confirmed=True, snapshot=revision.json()["snapshot"])
        assert second_granted.status_code == 200, second_granted.text
        second_hash = second_granted.json()["grant_hash"]
        revised_test = initial_test.replace("Pending behaviour", "Revised pending behaviour")
        command = ["python3", "-m", "unittest", "discover", "-s", "tests", "-p", "test_additional.py", "-q"]
        # Execute the exact revised test payload before its governed write.
        # This fixture red is never a passing implementation or falsification.
        red = subprocess.run(["python3", "-"], input=(revised_test + "\nunittest.main()\n").encode(), cwd=tmp_path, capture_output=True)
        assert red.returncode != 0
        judge_hash = "sha256:" + hashlib.sha256(revised_test.encode()).hexdigest()
        obligation = {**old["obligations"][0], "acceptance_id": "AC-2", "test_id": test_path,
                      "oracle": "Additional fixture behaviour must eventually pass", "approver": "pending-owner",
                      "asset_hashes": [judge_hash], "judge_assets": [{"path": test_path, "sha256": judge_hash}],
                      "command": command, "command_hash": canonical_hash(command),
                      "baseline": {"kind": "observed_red", "result_hash": canonical_hash({"returncode": red.returncode, "stderr": red.stderr.decode()})}}
        package = fixtures._prepared_package()
        package["objective"] = "Reviewed successor with preserved baseline and additional check"
        package["contract_request"]["obligations"] = [*old["obligations"], obligation]
        envelope = package["task_envelopes"]["R2"]
        envelope["commands"] = [entry["command"] for entry in package["contract_request"]["obligations"]]
        envelope["checks"] = ["AC-1", "AC-2"]
        package["task_envelopes"] = {"R2": envelope}
        author(tmp_path, old, second_hash, {test_path: revised_test, candidate_path: json.dumps(package)}, monkeypatch, replace=True)
        selected = post(client, headers, base + "/implementation-candidate", candidate_path=candidate_path, authoring_grant_hash=second_hash)
        assert selected.status_code == 200, selected.text
        snapshot = selected.json()["snapshot"]
        assert (tmp_path / ".apatch/sdd_verification_contract.json").read_bytes() == old_bytes
        assert post(client, headers, base + "/implementation-candidate/approve", confirmed=True, snapshot="sha256:" + "0" * 64).status_code == 409
        original_write = candidate_workflow.write_json
        def lose_receipt(path, value):
            if value.get("status") == "activated":
                raise OSError("Simulated Studio receipt failure after Core activation")
            return original_write(path, value)
        monkeypatch.setattr(candidate_workflow, "write_json", lose_receipt)
        lost = post(client, headers, base + "/implementation-candidate/approve", confirmed=True, snapshot=snapshot)
        assert lost.status_code == 409, lost.text
        active = json.loads((tmp_path / ".apatch/sdd_verification_contract.json").read_text())
        assert active["document_hash"] != old["document_hash"]
        monkeypatch.setattr(candidate_workflow, "write_json", original_write)
        recovered = post(client, headers, base + "/implementation-candidate/approve", confirmed=True, snapshot=snapshot)
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["activation"]["contract_hash"] == active["document_hash"]
        assert recovered.json()["functional_acceptance"] is False
        assert active["obligations"][0] == old["obligations"][0]
        assert active["supersedes_hash"] == old["document_hash"]
        assert canonical.read_bytes() == canonical_bytes
        assert (tmp_path / "tests/test_feature.py").read_bytes() == judge_bytes
        archived = tmp_path / ".apatch/sdd/frozen" / (old["document_hash"][7:] + ".json")
        assert json.loads(archived.read_text()) == old
        state = client.get(base.replace("/R1", "/R2") + "/execution-contract", headers=headers)
        assert state.status_code == 200, state.text
        assert state.json()["status"] == "frozen"
        repeated = post(client, headers, base + "/implementation-candidate/approve", confirmed=True, snapshot=snapshot)
        assert repeated.status_code == 200, repeated.text
        assert repeated.json() == recovered.json()
        # A new CREATE-only wave is legitimate only after that exact approved
        # preparation became the active successor. Old judges stay frozen.
        successor_bytes = (tmp_path / ".apatch/sdd_verification_contract.json").read_bytes()
        next_file = "tests/test_next_wave.py"
        next_proposal = post(client, headers, base + "/authoring", actor_id="agent:preparation", files=[next_file])
        assert next_proposal.status_code == 200, next_proposal.text
        next_scope = next_proposal.json()["scope"]
        assert next_scope["effects"] == ["create"]
        assert next_scope["contract_hash"] == active["document_hash"]
        assert test_path in next_scope["judge_assets"]
        assert "tests/test_feature.py" in next_scope["judge_assets"]
        assert post(client, headers, base + "/authoring", actor_id="agent:preparation", files=[test_path]).status_code == 409
        next_approval = post(client, headers, base + "/authoring/approve", confirmed=True, snapshot=next_proposal.json()["snapshot"])
        assert next_approval.status_code == 200, next_approval.text
        author(tmp_path, active, next_approval.json()["grant_hash"], {next_file: "# Next independent preparation; not functional acceptance\n"}, monkeypatch)
        assert (tmp_path / ".apatch/sdd_verification_contract.json").read_bytes() == successor_bytes
        previous_receipts = list(tmp_path.glob(".apatch/sdd/authoring-proposals/SPEC-DEMO-1/R1/history/*-approved.json"))
        assert any(json.loads(path.read_text())["grant_hash"] == second_hash for path in previous_receipts)
