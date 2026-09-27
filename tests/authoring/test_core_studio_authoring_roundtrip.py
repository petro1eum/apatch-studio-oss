"""Cross-layer authoring checks use real Core and disposable consumer state.

Run with the candidate Core checkout on PYTHONPATH. These tests do not grant
permissions in the user's workspace or accept any consumer business feature.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest


def _fixture_module():
    path = Path(__file__).parents[1] / "sdd/test_sdd_owner_execution_flow.py"
    spec = importlib.util.spec_from_file_location("owner_execution_fixture", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def consumer(tmp_path):
    fixture = _fixture_module()
    fixture._write_prepared(tmp_path)
    client, headers, _ = fixture._client(tmp_path)
    base = f"/api/v1/specs/{fixture.SPEC_ID}/requirements/{fixture.REQUIREMENT_ID}"
    with client:
        review = client.get(base + "/execution-contract", headers=headers)
        assert review.status_code == 200, review.text
        frozen = client.post(base + "/execution-contract/freeze", headers=headers, json={
            "request_id": "apsreq_roundtrip_freeze", "confirmed": True,
            "snapshot": review.json()["approval_snapshot"],
        })
        assert frozen.status_code == 200, frozen.text
        original = (tmp_path / ".apatch/sdd_verification_contract.json").read_bytes()
        yield client, headers, base, tmp_path, original


def _release(client, headers, base):
    requested = client.post(base + "/lock/release-request", headers=headers, json={
        "request_id": "apsreq_roundtrip_release",
        "reason": "Prepare additional acceptance tests while preserving all existing judges",
    })
    assert requested.status_code == 200, requested.text
    answer = client.post(base + "/lock/release-answer", headers=headers, json={
        "request_id": "apsreq_roundtrip_consent", "decision": "grant",
    })
    assert answer.status_code == 200, answer.text
    assert answer.json()["state"] == "released"


def _propose(client, headers, base, files=None):
    return client.post(base + "/authoring", headers=headers, json={
        "request_id": "apsreq_roundtrip_scope",
        "actor_id": "agent:authoring-test",
        "files": files or ["tests/test_new_acceptance.py"],
    })


def test_release_is_not_itself_a_scope_approval(consumer):
    client, headers, base, root, original = consumer
    before = _propose(client, headers, base)
    assert before.status_code == 409, before.text
    _release(client, headers, base)
    proposed = _propose(client, headers, base)
    assert proposed.status_code == 200, proposed.text
    assert not list((root / ".apatch/sdd/authoring").glob("*.json"))
    assert (root / ".apatch/sdd_verification_contract.json").read_bytes() == original


def test_exact_scope_approval_produces_a_real_core_binding(consumer):
    client, headers, base, root, original = consumer
    _release(client, headers, base)
    proposed = _propose(client, headers, base)
    assert proposed.status_code == 200, proposed.text
    approved = client.post(base + "/authoring/approve", headers=headers, json={
        "request_id": "apsreq_roundtrip_approval", "confirmed": True,
        "snapshot": proposed.json()["snapshot"],
    })
    assert approved.status_code == 200, approved.text
    data = approved.json()
    grant = json.loads((root / ".apatch/sdd/authoring" / (data["grant_hash"].split(":", 1)[1] + ".json")).read_text())
    assert grant["functional_acceptance"] is False
    binding = {
        "actor_id": "agent:authoring-test",
        "sdd_contract": json.loads(original),
        "task_envelope": {"schema": "apatch.sdd.authoring-reference.v1", "grant_hash": data["grant_hash"]},
    }
    from apatch.runtime.session import start_session, end_session
    started = start_session(
        str(root), "Prepare only the approved new acceptance file",
        sdd_contract=binding["sdd_contract"], task_envelope=binding["task_envelope"],
        actor={"actor_id": binding["actor_id"], "role": "implementation"},
    )
    assert started["ok"] is True, started
    end_session(str(root))
    assert (root / ".apatch/sdd_verification_contract.json").read_bytes() == original


def test_scope_snapshot_cannot_be_reused_after_target_appears(consumer):
    client, headers, base, root, original = consumer
    _release(client, headers, base)
    proposed = _propose(client, headers, base)
    assert proposed.status_code == 200, proposed.text
    target = root / "tests/test_new_acceptance.py"
    target.write_text("# another writer's file\n")
    response = client.post(base + "/authoring/approve", headers=headers, json={
        "request_id": "apsreq_roundtrip_stale", "confirmed": True,
        "snapshot": proposed.json()["snapshot"],
    })
    assert response.status_code == 409, response.text
    assert target.read_text() == "# another writer's file\n"
    assert (root / ".apatch/sdd_verification_contract.json").read_bytes() == original


@pytest.mark.parametrize("target", [
    "tests/test_feature.py", "src/runtime.py", "../tests/escape.py",
    ".apatch/sdd_verification_contract.json",
])
def test_authoring_does_not_authorize_old_judges_or_runtime(consumer, target):
    client, headers, base, root, original = consumer
    _release(client, headers, base)
    response = _propose(client, headers, base, [target])
    assert response.status_code in (409, 422), response.text
    assert (root / ".apatch/sdd_verification_contract.json").read_bytes() == original


def test_judge_drift_after_review_prevents_approval(consumer):
    client, headers, base, root, original = consumer
    _release(client, headers, base)
    proposed = _propose(client, headers, base)
    assert proposed.status_code == 200, proposed.text
    (root / "tests/test_feature.py").write_text("raise RuntimeError('unreviewed drift')\n")
    response = client.post(base + "/authoring/approve", headers=headers, json={
        "request_id": "apsreq_roundtrip_judge_drift", "confirmed": True,
        "snapshot": proposed.json()["snapshot"],
    })
    assert response.status_code == 409, response.text
    assert not list((root / ".apatch/sdd/authoring").glob("*.json"))
    assert (root / ".apatch/sdd_verification_contract.json").read_bytes() == original


def test_symlink_parent_cannot_escape_authoring_scope(consumer, tmp_path):
    client, headers, base, root, original = consumer
    _release(client, headers, base)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "tests/redirect").symlink_to(outside, target_is_directory=True)
    response = _propose(client, headers, base, ["tests/redirect/test_escape.py"])
    assert response.status_code in (409, 422), response.text
    assert list(outside.iterdir()) == []


def test_caller_cannot_select_approval_authority(consumer):
    client, headers, base, root, original = consumer
    _release(client, headers, base)
    proposed = _propose(client, headers, base)
    assert proposed.status_code == 200, proposed.text
    response = client.post(base + "/authoring/approve", headers=headers, json={
        "request_id": "apsreq_roundtrip_impostor", "confirmed": True,
        "snapshot": proposed.json()["snapshot"], "authority_id": "agent:authoring-test",
    })
    assert response.status_code == 422, response.text
    assert not list((root / ".apatch/sdd/authoring").glob("*.json"))


def test_superseded_proposal_cannot_be_approved_with_old_snapshot(consumer):
    client, headers, base, root, original = consumer
    _release(client, headers, base)
    first = _propose(client, headers, base)
    second = _propose(client, headers, base, ["tests/test_different_acceptance.py"])
    assert first.status_code == second.status_code == 200
    response = client.post(base + "/authoring/approve", headers=headers, json={
        "request_id": "apsreq_roundtrip_superseded", "confirmed": True,
        "snapshot": first.json()["snapshot"],
    })
    assert response.status_code == 409, response.text
    assert not list((root / ".apatch/sdd/authoring").glob("*.json"))


def test_new_release_request_invalidates_previously_reviewed_scope(consumer):
    client, headers, base, root, original = consumer
    _release(client, headers, base)
    first = _propose(client, headers, base)
    assert first.status_code == 200, first.text
    response = client.post(base + "/lock/release-request", headers=headers, json={
        "request_id": "apsreq_roundtrip_new_release",
        "reason": "A different change now needs a separate owner decision",
    })
    assert response.status_code == 200, response.text
    response = client.post(base + "/authoring/approve", headers=headers, json={
        "request_id": "apsreq_roundtrip_old_release", "confirmed": True,
        "snapshot": first.json()["snapshot"],
    })
    assert response.status_code == 409, response.text
    assert not list((root / ".apatch/sdd/authoring").glob("*.json"))


@pytest.mark.parametrize("enforced", [False, True])
def test_full_governed_creation_verification_and_preparation_attestation(consumer, monkeypatch, enforced):
    client, headers, base, root, original = consumer
    _release(client, headers, base)
    target = "bot_v1/tests/test_new_acceptance.py"
    proposed = _propose(client, headers, base, [target])
    assert proposed.status_code == 200, proposed.text
    approved = client.post(base + "/authoring/approve", headers=headers, json={
        "request_id": "apsreq_roundtrip_full_cycle", "confirmed": True,
        "snapshot": proposed.json()["snapshot"],
    })
    assert approved.status_code == 200, approved.text
    if enforced:
        (root / ".apatch/sandbox.json").write_text(json.dumps({
            "version": 1, "mode": "enforce", "protected_globs": ["bot_v1/**"],
            "allow_globs": [".apatch/**", ".trustchain/**", ".git/**"],
            "lease_max_seconds": 300,
        }))
        (root / ".apatch/enforcement.json").write_text(json.dumps({
            "mode": "strict", "governed_mode": "strict", "require_trustchain_on_apply": True,
            "fail_apply_if_notarization_fails": True, "incremental_notarization": True,
            "require_ed25519_block_on_disk": True,
        }))
    from apatch.runtime.session import start_session
    from apatch.runtime.runtime import MutationRuntime
    from apatch.workflows import generate_patch_jsonl_batch
    from apatch.sdd_authoring import VERIFY_COMMAND
    from apatch.session_state import load_session_state
    started = start_session(str(root), "Author a future behavioural test", sdd_contract=json.loads(original),
        task_envelope={"schema": "apatch.sdd.authoring-reference.v1", "grant_hash": approved.json()["grant_hash"]},
        actor={"actor_id": "agent:authoring-test", "role": "implementation"})
    assert started["ok"], started
    session_id = started["session"]["session_id"]
    generated = generate_patch_jsonl_batch(
        needles=[{"action": "create", "target_file": target,
                  "content": "def test_future_feature():\n    assert False, 'not implemented yet'\n"}],
        target_dir=str(root), out_path=str(root / "patches.jsonl"), governed_session_id=session_id)
    assert generated["ok"], generated
    runtime = MutationRuntime(str(root), session_id=session_id, session_token=started["session_token"])
    applied = runtime.apply_session(generated["out_path"], verify_deferred=True)
    assert applied["ok"], applied
    assert not applied.get("continue"), applied
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"])
    verified = runtime.verify_run(verify=VERIFY_COMMAND)
    assert verified["ok"], verified
    attested = runtime.attest(message="Preparation only; feature intentionally still fails")
    assert attested["ok"], attested
    state = load_session_state(str(root))
    assert state["sdd"]["functional_acceptance"] is False
    assert state.get("requirement") is None
    assert (root / ".apatch/sdd_verification_contract.json").read_bytes() == original
