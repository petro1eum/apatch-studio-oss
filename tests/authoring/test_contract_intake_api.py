"""Native HTTP intake behavior; no mocked Core approval or real owner state."""
from __future__ import annotations
import importlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

_path = Path(__file__).with_name("contract_intake_fixture.py")
_spec = importlib.util.spec_from_file_location("studio_native_contract_intake_fixture", _path)
fixtures = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fixtures)
SPEC, RFP, OWNER = fixtures.SPEC, fixtures.RFP, fixtures.OWNER
BASE = "/api/v1/contract-intake/" + SPEC


@pytest.fixture
def consumer(tmp_path, monkeypatch):
    f = fixtures.make_workspace(tmp_path, monkeypatch)
    client, headers, runs = fixtures.studio_client(f)
    with client:
        yield SimpleNamespace(f=f, client=client, headers=headers, runs=runs)


def proposal(c, *, request_id="apsreq_intake_proposal", files=None, **extra):
    return c.client.post(BASE, headers=c.headers, json={
        "request_id": request_id, "rfp_id": RFP, "actor_id": fixtures.ACTOR,
        "reason": "Review exactly this fixed-ID independent contract package",
        "files": files if files is not None else c.f.files, **extra,
    })


def review(c):
    response = proposal(c)
    assert response.status_code == 200, "Native intake route is missing or refused a valid proposal: " + response.text
    return response.json()


def approve(c, snapshot, *, request_id="apsreq_intake_approval", **extra):
    return c.client.post(BASE + "/approve", headers=c.headers, json={
        "request_id": request_id, "confirmed": True, "snapshot": snapshot, **extra,
    })


def no_execution(c):
    fixtures.preserved(c.f)
    assert c.runs.bindings == []
    assert not (c.f.root / ".apatch/sdd/prepared" / (SPEC + ".json")).exists()


def test_http_review_is_available_without_run_or_borrowed_release(consumer):
    c = consumer
    empty = c.client.get(BASE, headers=c.headers)
    assert empty.status_code == 200, empty.text
    assert empty.json()["status"] == "not_prepared"
    before = len(fixtures.native_records(c.f))
    proposed = review(c)
    assert proposed["status"] == "awaiting_approval"
    assert proposed["snapshot"] == proposed["review"]["document_hash"]
    assert proposed["review"]["spec_id"] == SPEC and proposed["review"]["rfp_id"] == RFP
    assert proposed["functional_acceptance"] is False
    assert c.client.get(BASE, headers=c.headers).json() == proposed
    assert len(fixtures.native_records(c.f)) == before
    assert not any((c.f.root / x["path"]).exists() for x in c.f.files)
    no_execution(c)


def test_http_owner_approval_uses_actual_core_signatures_and_preserves_active_profile(consumer):
    c = consumer
    proposed = review(c)
    result = approve(c, proposed["snapshot"])
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["status"] == "prepared" and data["functional_acceptance"] is False
    assert data["result"]["implementation_allowed"] is False
    assert data["result"]["owner_freeze_required"] is True
    assert c.client.get(BASE, headers=c.headers).json() == data
    for item in c.f.files:
        assert (c.f.root / item["path"]).read_bytes() == item["content"].encode()
    rows = [r for r in fixtures.native_records(c.f) if r["tool"] == fixtures.TOOL]
    assert len(rows) == 2 and {r["data"]["stage"] for r in rows} == {"approved", "completed"}
    assert all(r["data"]["authority_id"] == OWNER["id"] for r in rows)
    no_execution(c)


def test_replay_same_request_and_approval_survive_adapter_recreation(consumer):
    c = consumer
    original = review(c)
    assert proposal(c).json() == original
    accepted = approve(c, original["snapshot"])
    assert accepted.status_code == 200, accepted.text
    before = fixtures.snapshot(c.f.root)
    client, headers, runs = fixtures.studio_client(c.f)
    with client:
        copy = SimpleNamespace(f=c.f, client=client, headers=headers, runs=runs)
        again = approve(copy, original["snapshot"])
        assert again.status_code == 200, again.text
        assert again.json() == accepted.json()
        assert proposal(copy).json() == accepted.json()
    assert fixtures.snapshot(c.f.root) == before
    assert len([r for r in fixtures.native_records(c.f) if r["tool"] == fixtures.TOOL]) == 2
    no_execution(c)


def test_reused_request_id_cannot_change_content_even_after_later_request(consumer):
    c = consumer
    first = review(c)
    second_files = fixtures.package()
    second_files[2]["content"] += "# Explicitly revised preparation\n"
    second = proposal(c, request_id="apsreq_intake_second", files=second_files)
    assert second.status_code == 200, second.text
    assert second.json()["snapshot"] != first["snapshot"]
    before = fixtures.snapshot(c.f.root)
    assert proposal(c, files=second_files).status_code == 409
    assert fixtures.snapshot(c.f.root) == before
    assert approve(c, first["snapshot"]).status_code == 409
    assert not any((c.f.root / x["path"]).exists() for x in c.f.files)


def test_revised_proposal_preserves_immutable_prior_history(consumer):
    c = consumer
    first = review(c)
    files = fixtures.package()
    files[2]["content"] += "# Owner must review this new version\n"
    response = proposal(c, request_id="apsreq_intake_revision", files=files)
    assert response.status_code == 200, response.text
    history = c.f.root / ".apatch/sdd/contract-intake-reviews" / SPEC
    records = [json.loads(path.read_bytes()) for path in history.glob("*.json")]
    assert any(value["review"] == first["review"] for value in records)
    assert any(value["review"] == response.json()["review"] for value in records)
    assert approve(c, first["snapshot"]).status_code == 409


@pytest.mark.parametrize("extra", [
    {"owner": OWNER}, {"authority_id": OWNER["id"]}, {"certified": True},
    {"role": "authority"}, {"review": {}},
])
def test_request_cannot_choose_owner_or_review(consumer, extra):
    c = consumer
    proposed = review(c)
    before = fixtures.snapshot(c.f.root)
    assert approve(c, proposed["snapshot"], **extra).status_code == 422
    assert fixtures.snapshot(c.f.root) == before
    assert not [r for r in fixtures.native_records(c.f) if r["tool"] == fixtures.TOOL]


@pytest.mark.parametrize("confirmed,snapshot", [
    (False, None), (True, "not-a-snapshot"), (True, "sha256:" + "0" * 64),
])
def test_request_explicit_confirmation_and_exact_snapshot_required(consumer, confirmed, snapshot):
    c = consumer
    proposed = review(c)
    before = fixtures.snapshot(c.f.root)
    response = approve(c, snapshot or proposed["snapshot"], confirmed=confirmed)
    assert response.status_code in (409, 422), response.text
    assert fixtures.snapshot(c.f.root) == before


@pytest.mark.parametrize("identity", [
    {"machine_name": OWNER["id"], "certified": False},
    {"machine_name": "foreign-owner-fixture", "certified": True},
])
def test_owner_enrollment_not_caller_claim_controls_approval(consumer, identity):
    c = consumer
    proposed = review(c)
    path = c.f.root / ".apatch/machine-identity.json"
    record = json.loads(path.read_bytes())
    record.update(identity)
    path.write_text(json.dumps(record))
    before = fixtures.snapshot(c.f.root)
    response = approve(c, proposed["snapshot"])
    assert response.status_code in (403, 409), response.text
    assert fixtures.snapshot(c.f.root) == before
    assert not [r for r in fixtures.native_records(c.f) if r["tool"] == fixtures.TOOL]


@pytest.mark.parametrize("path", ["tests/frozen/test_existing.py", fixtures.PROFILE, "docs/" + RFP + ".md"])
def test_http_drift_between_review_and_owner_decision_is_denied(consumer, path):
    c = consumer
    proposed = review(c)
    original = c.f.root / path
    fixtures.write(c.f.root, path, original.read_bytes() + b"\n" if original.exists() else b"# Another writer\n")
    before = fixtures.snapshot(c.f.root)
    assert approve(c, proposed["snapshot"]).status_code == 409
    assert fixtures.snapshot(c.f.root) == before
    assert not [r for r in fixtures.native_records(c.f) if r["tool"] == fixtures.TOOL]


def test_security_missing_session_and_cross_origin_never_propose_or_approve(consumer):
    c = consumer
    body = {"request_id": "apsreq_guarded_intake", "rfp_id": RFP,
            "actor_id": fixtures.ACTOR, "reason": "A guarded exact package", "files": c.f.files}
    before = fixtures.snapshot(c.f.root)
    for path in (BASE, BASE + "/approve"):
        assert c.client.post(path, json=body).status_code == 401
        headers = {**c.headers, "origin": "https://unrelated.example"}
        assert c.client.post(path, headers=headers, json=body).status_code == 403
    assert c.client.get(BASE).status_code == 401
    assert fixtures.snapshot(c.f.root) == before


def test_security_unknown_proposal_field_does_not_allocate_a_run(consumer):
    c = consumer
    # First demand a real route so an unrelated 404 cannot satisfy this rejection.
    reviewed = review(c)
    before = fixtures.snapshot(c.f.root)
    assert proposal(c, spec_id="SPEC-CALLER-ALLOCATED").status_code == 422
    assert fixtures.snapshot(c.f.root) == before
    assert c.client.get(BASE, headers=c.headers).json() == reviewed
    no_execution(c)


def test_security_symlink_review_store_is_refused(consumer, tmp_path):
    c = consumer
    # Creating the symlink belongs only to disposable test state.
    outside = tmp_path / "unrelated-review-store"
    outside.mkdir()
    path = c.f.root / ".apatch/sdd/contract-intake-reviews"
    path.symlink_to(outside, target_is_directory=True)
    response = proposal(c)
    assert response.status_code in (409, 422), response.text
    assert not list(outside.iterdir())
    assert not any((c.f.root / x["path"]).exists() for x in c.f.files)
    assert not [r for r in fixtures.native_records(c.f) if r["tool"] == fixtures.TOOL]


def test_security_review_cannot_be_copied_to_another_spec(consumer):
    c = consumer
    proposed = review(c)
    original = c.f.root / ".apatch/sdd/contract-intake-reviews" / (SPEC + ".json")
    assert original.is_file()
    copied = original.with_name("SPEC-OTHER-1.json")
    copied.write_bytes(original.read_bytes())
    before = fixtures.snapshot(c.f.root)
    response = c.client.post(BASE.replace(SPEC, "SPEC-OTHER-1") + "/approve",
        headers=c.headers, json={"request_id": "apsreq_intake_foreign", "confirmed": True,
                                 "snapshot": proposed["snapshot"]})
    assert response.status_code == 409, response.text
    assert fixtures.snapshot(c.f.root) == before


def test_old_core_missing_intake_is_explicitly_unavailable_not_a_runner_fallback(consumer, monkeypatch):
    c = consumer
    # Simulates version skew only; no fake Core approve or fake signed receipt.
    name = "apatch_studio.contract_intake_workflow"
    assert importlib.util.find_spec(name) is not None, "Studio has no native intake adapter"
    module = importlib.import_module(name)
    assert callable(getattr(module, "intake_core", None))
    from apatch_studio.sdd_workflow import SddWorkflowError
    def unavailable():
        raise SddWorkflowError("Installed Core has no owner intake", code="sdd_contract_intake_unavailable", status_code=503)
    monkeypatch.setattr(module, "intake_core", unavailable)
    before = fixtures.snapshot(c.f.root)
    response = proposal(c)
    assert response.status_code == 503, response.text
    assert response.json()["error_code"] == "sdd_contract_intake_unavailable"
    assert fixtures.snapshot(c.f.root) == before
    no_execution(c)
