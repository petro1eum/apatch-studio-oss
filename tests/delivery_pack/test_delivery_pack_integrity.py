"""SEC-8: workspace bytes never become trusted human decisions."""
from copy import deepcopy
import inspect
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import apatch_studio.delivery_pack as delivery
from apatch_studio.app import create_app
from apatch_studio.delivery_pack import (
    AcceptanceActRequest, AcceptedTimeDecisionRequest, DeliveryPackError,
    DeliveryPackWorkflow, DeliverySigner, verify_delivery_signature,
)

from .conftest import CHANGE_ID


def _workflow(tmp_path, signer=None, *, name="workspace", state="private"):
    workspace = tmp_path / name
    workspace.mkdir(exist_ok=True)
    kwargs = {"signer": signer} if signer else {}
    # Run the same behavioural attacks on the pre-fix API, which has no override.
    if "state_root" in inspect.signature(DeliveryPackWorkflow).parameters:
        kwargs["state_root"] = tmp_path / state
    return DeliveryPackWorkflow(workspace, **kwargs)


def _accept(workflow, detail, request_id="apsreq_sec8_accept", decision="accepted"):
    request = AcceptanceActRequest(
        request_id=request_id, expected_basis_hash=workflow.project(detail)["basis_hash"],
        decision=decision, confirmed=True,
    )
    return request, workflow.record_acceptance(detail, request)


def _legacy(workflow, value):
    path = workflow.root / ".apatch/studio/delivery-pack/decisions.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _store(workflow):
    return json.loads(workflow.state_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("attack", ["history", "cache", "foreign_key", "rollback"])
def test_workspace_cannot_rewrite_current_decision_or_retry(tmp_path, signer, change_detail, attack):
    workflow = _workflow(tmp_path, signer)
    request, accepted = _accept(workflow, change_detail)
    snapshot = _store(workflow)
    reject_request, rejected = _accept(workflow, change_detail, "apsreq_sec8_rejected", "rejected")
    forged = _store(workflow)
    record = forged["changes"][CHANGE_ID]
    if attack == "history":
        record["acceptance"][-1]["decision"] = "accepted"
    elif attack == "cache":
        record["requests"][reject_request.request_id]["result"] = accepted
    elif attack == "foreign_key":
        foreign = DeliverySigner.from_seed(b"x" * 32, actor_id="foreign:board", label="Foreign board", trust="organization-authority")
        unsigned = deepcopy(rejected)
        unsigned.pop("signature")
        unsigned.update(decision="accepted", authority=foreign.authority())
        record["acceptance"][-1] = foreign.sign(unsigned, purpose="delivery.acceptance.record")
    else:
        forged = snapshot
    _legacy(workflow, forged)
    assert workflow.project(change_detail)["acceptance"]["latest"] == rejected
    assert workflow.record_acceptance(change_detail, reject_request) == rejected
    assert workflow.record_acceptance(change_detail, request) == accepted


def test_default_key_and_journal_are_private_and_survive_restart(tmp_path, monkeypatch, change_detail):
    monkeypatch.setattr(delivery, "default_state_root", lambda: tmp_path / "os-state", raising=False)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    workflow = DeliveryPackWorkflow(workspace)
    request, act = _accept(workflow, change_detail)
    assert not workflow.state_path.is_relative_to(workspace)
    assert not (workspace / ".apatch/studio/delivery-pack/owner-key.json").exists()
    assert not (workspace / ".apatch/studio/delivery-pack/decisions.json").exists()
    restarted = DeliveryPackWorkflow(workspace)
    assert restarted.signer.key_id == workflow.signer.key_id
    assert restarted.record_acceptance(change_detail, request) == act
    if os.name != "nt":
        for path in (workflow.state_path, workflow.state_root / "owner-key.json"):
            assert path.stat().st_mode & 0o077 == 0
        assert workflow.state_root.stat().st_mode & 0o077 == 0


def test_old_workspace_key_and_history_are_not_silently_adopted(tmp_path, change_detail):
    original = _workflow(tmp_path, state="old-private")
    _request, act = _accept(original, change_detail)
    legacy = _store(original)
    legacy["schema"] = "apatch.studio.delivery-decisions.v1"
    path = _legacy(original, legacy)
    old_bytes = path.read_bytes()
    # A copied legacy seed is a disclosed workspace credential, not a trust root.
    key = path.parent / "owner-key.json"
    if not key.exists():
        key.write_bytes((original.state_root / "owner-key.json").read_bytes())
    old_key = key.read_bytes()
    migrated = _workflow(tmp_path, state="fresh-private")
    pack = migrated.project(change_detail)
    assert migrated.signer.key_id != act["authority"]["key_id"]
    assert pack["acceptance"]["latest"] is None
    assert pack["legacy_history"]["status"] == "unverified"
    assert pack["legacy_history"]["acceptance_count"] == 1
    assert path.read_bytes() == old_bytes and key.read_bytes() == old_key
    _request, new_act = _accept(migrated, change_detail, "apsreq_sec8_fresh_review")
    assert new_act["revision"] == 1
    assert migrated.project(change_detail)["acceptance"]["latest"] == new_act
    assert path.read_bytes() == old_bytes


def test_stale_basis_keeps_history_but_not_current_acceptance_or_hours(tmp_path, signer, change_detail):
    workflow = _workflow(tmp_path, signer)
    _request, act = _accept(workflow, change_detail)
    pack = workflow.project(change_detail)
    time_request = AcceptedTimeDecisionRequest(
        request_id="apsreq_sec8_precise_hours", expected_basis_hash=pack["basis_hash"],
        expected_effort_hash=pack["effort"]["effort_hash"], decision="accepted",
        accepted_hours=1.123456789, confirmed=True,
    )
    time = workflow.record_time_decision(change_detail, time_request)
    assert workflow.record_time_decision(change_detail, time_request) == time
    changed = deepcopy(change_detail)
    changed["updated_at"] = "2026-09-02T12:00:00Z"
    current = workflow.project(changed)
    assert current["acceptance"]["latest"] is None
    assert current["time_decision"]["latest"] is None
    assert current["acceptance"]["status"] == "stale"
    assert current["time_decision"]["status"] == "stale"
    assert current["acceptance"]["history"] == [act]
    assert current["time_decision"]["history"] == [time]
    _request, fresh = _accept(workflow, changed, "apsreq_sec8_new_basis")
    assert fresh["revision"] == 2
    current = workflow.project(changed)
    assert current["acceptance"]["latest"] == fresh
    assert current["time_decision"]["latest"] is None
    # Do not search backwards and resurrect an older matching-basis act.
    assert workflow.project(change_detail)["acceptance"]["latest"] is None


@pytest.mark.parametrize("attack", ["history", "cache", "foreign_key", "version", "workspace", "reorder", "cache_swap"])
def test_private_journal_corruption_is_rejected_on_read_and_retry(tmp_path, signer, change_detail, attack):
    workflow = _workflow(tmp_path, signer)
    request, accepted = _accept(workflow, change_detail)
    reject_request, rejected = _accept(workflow, change_detail, "apsreq_sec8_reject_corrupt", "rejected")
    state = _store(workflow)
    record = state["changes"][CHANGE_ID]
    if attack == "history":
        record["acceptance"][-1]["decision"] = "accepted"
    elif attack == "cache":
        record["requests"][reject_request.request_id]["result"] = accepted
    elif attack == "foreign_key":
        foreign = DeliverySigner.from_seed(b"f" * 32, actor_id="foreign:owner", label="Other", trust="organization-authority")
        state.pop("signature", None)
        state["authority"] = foreign.authority()
        state = foreign.sign(state, purpose="delivery.decisions.store")
    elif attack == "version":
        state["schema"] = "apatch.studio.delivery-decisions.v99"
    elif attack == "workspace":
        state["workspace_id"] = "0" * 32
    elif attack == "reorder":
        record["acceptance"].reverse()
    else:
        record["requests"][reject_request.request_id]["result"] = accepted
    if attack in {"reorder", "cache_swap", "version", "workspace"}:
        state.pop("signature", None)
        state = signer.sign(state, purpose="delivery.decisions.store")
    workflow.state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(DeliveryPackError):
        workflow.project(change_detail)
    with pytest.raises(DeliveryPackError):
        workflow.record_acceptance(change_detail, reject_request)


def test_journal_cannot_be_reused_by_another_workspace_or_authority(tmp_path, signer, change_detail):
    first = _workflow(tmp_path, signer)
    _accept(first, change_detail)
    other = _workflow(tmp_path, signer, name="other-workspace")
    other.state_path.parent.mkdir(parents=True, exist_ok=True)
    other.state_path.write_bytes(first.state_path.read_bytes())
    other.state_path.chmod(0o600)
    with pytest.raises(DeliveryPackError):
        other.project(change_detail)
    foreign = DeliverySigner.from_seed(b"q" * 32, actor_id="foreign:owner", label="Other", trust="local-self-signed")
    with pytest.raises(DeliveryPackError):
        _workflow(tmp_path, foreign).project(change_detail)


def test_missing_key_never_resets_an_existing_journal(tmp_path, change_detail):
    workflow = _workflow(tmp_path)
    _accept(workflow, change_detail)
    before = workflow.state_path.read_bytes()
    (workflow.state_root / "owner-key.json").unlink()
    with pytest.raises(DeliveryPackError):
        _workflow(tmp_path)
    assert workflow.state_path.read_bytes() == before


def test_state_root_inside_workspace_is_rejected(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    with pytest.raises((ValueError, DeliveryPackError)):
        DeliveryPackWorkflow(workspace, state_root=workspace / "private")


@pytest.mark.skipif(os.name == "nt", reason="POSIX private-file mode contract")
@pytest.mark.parametrize("target", ["owner-key.json", "decisions.json", "decisions.lock"])
def test_private_symlink_or_shared_file_is_not_followed(tmp_path, change_detail, target):
    workflow = _workflow(tmp_path)
    _accept(workflow, change_detail)
    path = workflow.state_root / target
    external = tmp_path / "external.json"
    original = path.read_bytes()
    external.write_bytes(original)
    external.chmod(0o600)
    path.unlink()
    path.symlink_to(external)
    with pytest.raises(DeliveryPackError):
        _workflow(tmp_path).project(change_detail)
    assert external.read_bytes() == original
    path.unlink()
    path.write_bytes(original)
    path.chmod(0o644)
    with pytest.raises(DeliveryPackError):
        _workflow(tmp_path).project(change_detail)


def test_integrity_warning_and_stale_states_are_visible_in_ui():
    source = (Path(delivery.__file__).parents[1] / "frontend/src/ChangeDetailView.tsx").read_text()
    assert "Legacy delivery records are unverified" in source
    assert 'pack.acceptance.status === "stale"' in source
    assert 'pack.time_decision.status === "stale"' in source


def test_guarded_http_does_not_display_forged_workspace_consent(tmp_path, signer, change_detail):
    class Adapter:
        def overview(self, *, force=False): return {"schema": "test.overview.v1", "changes": []}
        def change_detail(self, change_id): return deepcopy(change_detail)

    class Sdd:
        def change(self, change_id): return deepcopy(change_detail["sdd"])

    class Runs:
        def runners(self): return []
        def list(self): return []
        def journal(self): return {"schema": "test.journal.v1"}
        def close(self): pass

    workflow = _workflow(tmp_path, signer)
    app = create_app(str(workflow.root), adapter=Adapter(), sdd_facade=Sdd(), run_manager=Runs(),
                     delivery_pack_workflow=workflow, frontend_root=workflow.root,
                     identity_root=tmp_path / "identity", intent_state_root=tmp_path / "intents")
    headers = {"x-apatch-studio-session": app.state.studio_guard.token, "origin": "http://127.0.0.1:8765"}
    endpoint = f"/api/v1/changes/{CHANGE_ID}"
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        assert client.get(endpoint + "/delivery-pack").status_code == 401
        pack = client.get(endpoint + "/delivery-pack", headers=headers).json()
        request = {"request_id": "apsreq_sec8_http_reject", "expected_basis_hash": pack["basis_hash"],
                   "decision": "rejected", "note": "Reviewed", "confirmed": True}
        response = client.post(endpoint + "/acceptance", headers=headers, json=request)
        assert response.status_code == 200
        real = response.json()
        assert verify_delivery_signature(real, purpose="delivery.acceptance.record")["decision"] == "rejected"
        forged = _store(workflow)
        forged["changes"][CHANGE_ID]["acceptance"][-1]["decision"] = "accepted"
        forged["changes"][CHANGE_ID]["requests"][request["request_id"]]["result"]["decision"] = "accepted"
        _legacy(workflow, forged)
        assert client.get(endpoint + "/delivery-pack", headers=headers).json()["acceptance"]["latest"] == real
        assert client.post(endpoint + "/acceptance", headers=headers, json=request).json() == real
