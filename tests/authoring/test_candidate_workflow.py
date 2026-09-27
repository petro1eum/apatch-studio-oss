"""The Studio boundary never upgrades a release into implementation approval."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from apatch_studio import candidate_workflow as workflow

ROOT = Path(__file__).resolve().parents[2]
fixture_spec = importlib.util.spec_from_file_location("candidate_owner_fixtures", ROOT / "tests/sdd/test_sdd_owner_execution_flow.py")
fixtures = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(fixtures)
URL = "/api/v1/specs/SPEC-DEMO-1/requirements/R1/implementation-candidate"
HASH = "sha256:" + "a" * 64


@pytest.fixture
def core(monkeypatch):
    calls = []
    def prepare(root, *, candidate_path, previous_grant_hash):
        calls.append(("prepare", candidate_path))
        if candidate_path == "draft.json":
            raise ValueError("contract_request and task_envelopes are required")
        return {"spec_id": "SPEC-DEMO-1", "requirement_id": "R1", "candidate_path": candidate_path,
                "previous_grant_hash": previous_grant_hash, "document_hash": HASH,
                "contract_hash": "sha256:" + "b" * 64}
    def activate(root, review, *, authority_id, expected_snapshot):
        calls.append(("activate", authority_id, expected_snapshot))
        return {"contract_hash": "sha256:" + "c" * 64, "functional_acceptance": False}
    backend = SimpleNamespace(prepare_successor=prepare, activate_successor=activate)
    monkeypatch.setattr(workflow, "successor_core", lambda: backend)
    return backend, calls


def select(client, headers, path=".apatch/sdd/prepared/valid.json"):
    return client.post(URL, headers=headers, json={"request_id": "apsreq_select_candidate", "candidate_path": path, "authoring_grant_hash": HASH})


def approve(client, headers, snapshot=HASH, **extra):
    return client.post(URL + "/approve", headers=headers, json={"request_id": "apsreq_approve_candidate", "confirmed": True, "snapshot": snapshot, **extra})


def test_owner_activation_is_separate_and_history_preserved(tmp_path, core):
    backend, calls = core
    old = tmp_path / ".apatch/sdd_verification_contract.json"
    old.parent.mkdir()
    old.write_text('{"existing":"immutable"}')
    before = old.read_bytes()
    client, headers, _ = fixtures._client(tmp_path)
    with client:
        selected = select(client, headers)
        assert selected.status_code == 200
        assert old.read_bytes() == before
        assert not any(row[0] == "activate" for row in calls)
        activated = approve(client, headers)
        assert activated.status_code == 200
        assert activated.json()["status"] == "activated"
        assert calls[-1] == ("activate", "studio-laptop", HASH)
        assert old.read_bytes() == before, "Studio cannot write an active Core profile itself"
        repeated = approve(client, headers)
        assert repeated.status_code == 200
        assert repeated.json() == activated.json()
        records = list(tmp_path.glob(".apatch/sdd/candidate-reviews/SPEC-DEMO-1/R1/history/*.json"))
        assert {json.loads(path.read_text())["status"] for path in records} == {"awaiting_approval", "activated"}


def test_draft_candidate_is_actionable_error_not_review_ready(tmp_path, core):
    client, headers, _ = fixtures._client(tmp_path)
    with client:
        result = select(client, headers, "draft.json")
        assert result.status_code == 422
        assert "contract_request and task_envelopes" in result.json()["error"]
        assert client.get(URL, headers=headers).json()["status"] == "not_selected"


def test_stale_snapshot_never_calls_activation(tmp_path, core):
    client, headers, _ = fixtures._client(tmp_path)
    with client:
        select(client, headers)
        assert approve(client, headers, "sha256:" + "d" * 64).status_code == 409
        assert not any(row[0] == "activate" for row in core[1])


@pytest.mark.parametrize("extra", [{"authority_id": "fake-owner"}, {"review": {}}, {"role": "authority"}])
def test_caller_cannot_select_activation_authority(tmp_path, core, extra):
    client, headers, _ = fixtures._client(tmp_path)
    with client:
        select(client, headers)
        assert approve(client, headers, **extra).status_code == 422
        assert not any(row[0] == "activate" for row in core[1])


@pytest.mark.parametrize("reason", ["Candidate hash changed", "Old judge weakened", "Source changed before approval"])
def test_core_rejection_keeps_review_pending_without_fake_success(tmp_path, core, reason):
    def reject(*args, **kwargs):
        raise ValueError(reason)
    core[0].activate_successor = reject
    client, headers, _ = fixtures._client(tmp_path)
    with client:
        select(client, headers)
        result = approve(client, headers)
        assert result.status_code == 409
        assert reason in result.json()["error"]
        assert client.get(URL, headers=headers).json()["status"] == "awaiting_approval"


def test_browser_displays_exact_implementation_authority():
    source = (ROOT / "frontend/src/ImplementationCandidateReview.tsx").read_text()
    for field in ("candidate.candidate_hash", "candidate.contract_hash", "candidate.release_hash", "candidate.judge_assets", "candidate.task_envelopes", "candidate.obligations", "envelope.budgets", "envelope.network"):
        assert field in source
    assert 'state?.status === "awaiting_approval"' in source
    assert "it does not mean the feature passed its tests" in source
