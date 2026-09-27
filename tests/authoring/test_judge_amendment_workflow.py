"""Studio request and identity boundaries; Core behaviours need a real-Core roundtrip."""
from pathlib import Path
from types import SimpleNamespace
import pytest
from apatch_studio import judge_amendment_workflow as workflow
from apatch_studio.authoring_workflow import AuthoringApprovalRequest

HASH = "sha256:" + "a" * 64
SPEC, RK = "SPEC-DEMO-1", "R4"

def request(**extra):
    return workflow.JudgeAmendmentRequest(request_id="apsreq_correction_draft",
        acceptance_id="A04", judge_path="tests/test_r04.py", replacement_text="assert True\n",
        reason="Correct the retry policy", **extra)

def approval(snapshot=HASH, **extra):
    return AuthoringApprovalRequest(request_id="apsreq_correction_approve",
        confirmed=True, snapshot=snapshot, **extra)

@pytest.fixture
def core(monkeypatch):
    calls = []
    def prepare(root, **kwargs):
        calls.append(("prepare", kwargs))
        return {"schema": "apatch.sdd.judge-amendment-review.v1", "spec_id": SPEC,
                "requirement_id": RK, "document_hash": HASH, "functional_acceptance": False,
                "contract_hash": "sha256:" + "b" * 64, "judge_path": kwargs["judge_path"],
                "old_judge_hash": "sha256:" + "c" * 64, "new_judge_hash": "sha256:" + "d" * 64,
                "invalidated_acceptance_ids": ["A04"], "affected_requirements": ["R4"],
                "preserved_acceptance_ids": ["A01", "A03", "A05"], "replacement_text": kwargs["replacement_text"]}
    def activate(root, review, *, authority_id, expected_snapshot):
        calls.append(("activate", authority_id, expected_snapshot))
        return {"contract_hash": "sha256:" + "e" * 64, "functional_acceptance": False}
    api = SimpleNamespace(prepare_judge_amendment=prepare, activate_judge_amendment=activate)
    monkeypatch.setattr(workflow, "amendment_core", lambda: api)
    return api, calls

def test_review_is_separate_and_exact_approval_replay_is_idempotent(tmp_path, core):
    flow = workflow.JudgeAmendmentWorkflow(tmp_path)
    reviewed = flow.propose(SPEC, RK, request())
    assert reviewed["status"] == "awaiting_approval"
    assert not any(c[0] == "activate" for c in core[1])
    accepted = flow.approve(SPEC, RK, approval(), authority_id="owner")
    assert core[1][-1] == ("activate", "owner", HASH)
    assert accepted["functional_acceptance"] is False
    assert flow.approve(SPEC, RK, approval(), authority_id="owner") == accepted
    assert len(list(tmp_path.glob(".apatch/sdd/judge-amendment-reviews/*/*/history/*.json"))) == 2

def test_stale_snapshot_never_calls_core_activation(tmp_path, core):
    flow = workflow.JudgeAmendmentWorkflow(tmp_path)
    flow.propose(SPEC, RK, request())
    with pytest.raises(workflow.SddWorkflowError):
        flow.approve(SPEC, RK, approval("sha256:" + "f" * 64), authority_id="owner")
    assert not any(c[0] == "activate" for c in core[1])

@pytest.mark.parametrize("extra", [{"authority_id": "owner"}, {"role": "authority"}, {"review": {}}])
def test_request_cannot_inject_authority(extra):
    with pytest.raises(ValueError):
        request(**extra)
    with pytest.raises(ValueError):
        approval(**extra)

def test_wrong_requirement_cannot_be_persisted(tmp_path, core):
    flow = workflow.JudgeAmendmentWorkflow(tmp_path)
    with pytest.raises(workflow.SddWorkflowError):
        flow.propose(SPEC, "R5", request())
    assert not list(tmp_path.rglob("*.json"))

@pytest.mark.parametrize("reason", ["judge drift", "contract drift", "owner mismatch", "shared judge affects preserved acceptance"])
def test_core_denial_keeps_review_pending(tmp_path, core, reason):
    flow = workflow.JudgeAmendmentWorkflow(tmp_path)
    flow.propose(SPEC, RK, request())
    def reject(*args, **kwargs): raise ValueError(reason)
    core[0].activate_judge_amendment = reject
    with pytest.raises(workflow.SddWorkflowError, match=reason):
        flow.approve(SPEC, RK, approval(), authority_id="owner")
    assert flow.review(SPEC, RK)["status"] == "awaiting_approval"

def test_other_actor_cannot_replay_completed_approval(tmp_path, core):
    flow = workflow.JudgeAmendmentWorkflow(tmp_path)
    flow.propose(SPEC, RK, request())
    flow.approve(SPEC, RK, approval(), authority_id="owner")
    before = len(core[1])
    with pytest.raises(workflow.SddWorkflowError):
        flow.approve(SPEC, RK, approval(), authority_id="implementation")
    assert len(core[1]) == before

def test_core_unavailable_is_explicit(monkeypatch):
    import sys
    monkeypatch.setitem(sys.modules, "apatch.sdd_judge_amendment", None)
    with pytest.raises(workflow.SddWorkflowError) as error:
        workflow.amendment_core()
    assert error.value.status_code == 503


def test_http_routes_resolve_owner_and_reject_injected_authority(tmp_path, core):
    import importlib.util
    fixture_path = Path(__file__).resolve().parents[1] / "sdd/test_sdd_owner_execution_flow.py"
    spec = importlib.util.spec_from_file_location("amendment_owner_fixtures", fixture_path)
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    client, headers, _ = fixtures._client(tmp_path)
    url = f"/api/v1/specs/{SPEC}/requirements/{RK}/judge-amendment"
    with client:
        assert client.post(url, json=request().model_dump()).status_code in {401, 403}
        assert client.post(url, headers=headers, json=request().model_dump()).status_code == 200
        forged = {**approval().model_dump(), "authority_id": "implementation"}
        assert client.post(url + "/approve", headers=headers, json=forged).status_code == 422
        accepted = client.post(url + "/approve", headers=headers, json=approval().model_dump())
        assert accepted.status_code == 200
        assert core[1][-1] == ("activate", "studio-laptop", HASH)

def test_browser_renders_exact_diff_before_explicit_confirmation():
    source = (Path(__file__).resolve().parents[2] / "frontend/src/JudgeAmendmentReview.tsx").read_text()
    for field in ("correction.diff", "correction.old_judge_hash", "correction.new_judge_hash",
                  "correction.contract_hash", "correction.invalidated_acceptance_ids",
                  "correction.preserved_acceptance_ids"):
        assert field in source
    assert 'state?.status === "awaiting_approval"' in source
    assert "does not mark the feature as verified" in source


def test_proposal_retry_returns_exact_snapshot_and_conflicting_payload_is_denied(tmp_path, core):
    flow = workflow.JudgeAmendmentWorkflow(tmp_path)
    first = flow.propose(SPEC, RK, request())
    other = workflow.JudgeAmendmentWorkflow(tmp_path)
    assert other.propose(SPEC, RK, request()) == first
    assert len(core[1]) == 1
    changed = request().model_copy(update={"replacement_text": "assert False\n"})
    with pytest.raises(workflow.SddWorkflowError, match="different amendment inputs"):
        other.propose(SPEC, RK, changed)
    assert flow.review(SPEC, RK) == first

def test_proposal_retry_recovers_receipt_gap(tmp_path, core, monkeypatch):
    flow = workflow.JudgeAmendmentWorkflow(tmp_path)
    persist = flow._persist_request
    def fail(*args): raise OSError("lost response")
    monkeypatch.setattr(flow, "_persist_request", fail)
    with pytest.raises(workflow.SddWorkflowError):
        flow.propose(SPEC, RK, request())
    first = flow.review(SPEC, RK)
    monkeypatch.setattr(flow, "_persist_request", persist)
    assert flow.propose(SPEC, RK, request()) == first
    assert len(core[1]) == 1

def test_two_processes_serialize_proposals_and_approvals(tmp_path, core, monkeypatch):
    import multiprocessing
    import os
    import time
    if "fork" not in multiprocessing.get_all_start_methods():
        pytest.skip("fork unavailable on this platform")
    original_prepare = core[0].prepare_judge_amendment
    count = tmp_path / "prepare-calls"
    def prepare(root, **kwargs):
        with count.open("a") as output: output.write("prepare\n")
        time.sleep(0.08)
        return original_prepare(root, **kwargs)
    core[0].prepare_judge_amendment = prepare
    original_activate = core[0].activate_judge_amendment
    sentinel = tmp_path / "activation-active"
    def activate(*args, **kwargs):
        fd = os.open(sentinel, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        try:
            time.sleep(0.08)
            return original_activate(*args, **kwargs)
        finally:
            os.close(fd)
            sentinel.unlink()
    core[0].activate_judge_amendment = activate
    ctx = multiprocessing.get_context("fork")
    queue = ctx.Queue()
    def worker(action):
        try:
            flow = workflow.JudgeAmendmentWorkflow(tmp_path)
            result = flow.propose(SPEC, RK, request()) if action == "propose" else flow.approve(SPEC, RK, approval(), authority_id="owner")
            queue.put(("ok", result))
        except Exception as exc:
            queue.put(("error", repr(exc)))
    for action in ("propose", "approve"):
        processes = [ctx.Process(target=worker, args=(action,)) for _ in range(2)]
        for process in processes: process.start()
        results = [queue.get(timeout=10) for _ in processes]
        for process in processes:
            process.join(10)
            assert process.exitcode == 0
        assert all(result[0] == "ok" for result in results), results
        assert results[0][1] == results[1][1]
    assert count.read_text() == "prepare\n"
    assert len(list(tmp_path.glob(".apatch/sdd/judge-amendment-reviews/*/*/history/*.json"))) == 2

def test_requirement_navigation_remounts_review_state():
    source = (Path(__file__).resolve().parents[2] / "frontend/src/ProjectPlanView.tsx").read_text()
    assert '<JudgeAmendmentReview key={specificationId + "#" + requirement.id}' in source

def test_new_request_id_recovers_activated_history_before_latest_write(tmp_path, core, monkeypatch):
    flow = workflow.JudgeAmendmentWorkflow(tmp_path)
    flow.propose(SPEC, RK, request())
    original_write = workflow.write_json
    failures = [True]
    def write(path, result):
        if path == flow._path(SPEC, RK) and result.get("status") == "activated" and failures[0]:
            failures[0] = False
            raise OSError("latest pointer write failed")
        return original_write(path, result)
    monkeypatch.setattr(workflow, "write_json", write)
    # This fake boundary models Core's durable, idempotent activation receipt.
    effect_count = []
    receipt = None
    original_activate = core[0].activate_judge_amendment
    def activate(*args, **kwargs):
        nonlocal receipt
        if receipt is None:
            receipt = original_activate(*args, **kwargs)
            effect_count.append("effect")
        return receipt
    core[0].activate_judge_amendment = activate
    with pytest.raises(workflow.SddWorkflowError, match="latest pointer write failed"):
        flow.approve(SPEC, RK, approval(), authority_id="owner")
    assert flow.review(SPEC, RK)["status"] == "awaiting_approval"
    history = next(tmp_path.glob(".apatch/sdd/judge-amendment-reviews/*/*/history/*-activated.json"))
    historical_bytes = history.read_bytes()
    new_http_request = approval().model_copy(update={"request_id": "apsreq_retry_new_browser_id"})
    recovered = workflow.JudgeAmendmentWorkflow(tmp_path).approve(SPEC, RK, new_http_request, authority_id="owner")
    import json
    assert recovered == json.loads(historical_bytes)
    assert recovered["approval_request_id"] == approval().request_id
    assert history.read_bytes() == historical_bytes
    assert flow.review(SPEC, RK) == recovered
    assert effect_count == ["effect"]
