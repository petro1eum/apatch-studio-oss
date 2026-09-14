from __future__ import annotations

import pytest

from apatch_studio.delivery_pack import (
    AcceptanceActRequest,
    AcceptedTimeDecisionRequest,
    DeliveryPackError,
    DeliveryPackWorkflow,
)


def _accept(pack, request_id="apsreq_acceptance_0001", **overrides):
    payload = {
        "request_id": request_id,
        "expected_basis_hash": pack["basis_hash"],
        "decision": "accepted",
        "note": "",
        "confirmed": True,
        **overrides,
    }
    return AcceptanceActRequest(**payload)


def test_unconditional_acceptance_requires_meaningful_protocol(
    tmp_path, signer, change_detail
) -> None:
    change_detail["sdd"]["verification"]["falsification"]["observed_red"] = False
    workflow = DeliveryPackWorkflow(tmp_path, signer=signer)
    pack = workflow.project(change_detail)

    with pytest.raises(DeliveryPackError, match="meaningful test protocol"):
        workflow.record_acceptance(change_detail, _accept(pack))

    reserved = workflow.record_acceptance(
        change_detail,
        _accept(
            pack,
            request_id="apsreq_acceptance_reserved",
            decision="accepted_with_reservations",
            note="Falsification evidence must be completed before release.",
        ),
    )
    assert reserved["decision"] == "accepted_with_reservations"
    assert reserved["technical_gaps"]


def test_acceptance_act_is_signed_and_append_only(
    tmp_path, signer, change_detail
) -> None:
    workflow = DeliveryPackWorkflow(tmp_path, signer=signer)
    pack = workflow.project(change_detail)
    first = workflow.record_acceptance(change_detail, _accept(pack))
    second = workflow.record_acceptance(
        change_detail,
        _accept(
            pack,
            request_id="apsreq_acceptance_0002",
            decision="changes_requested",
            note="Add the missing migration check.",
        ),
    )
    projected = workflow.project(change_detail)

    assert first["schema"] == "apatch.studio.acceptance-act.v1"
    assert first["revision"] == 1
    assert first["basis_hash"] == pack["basis_hash"]
    assert first["signature"]["purpose"] == "delivery.acceptance.record"
    assert second["revision"] == 2
    assert projected["acceptance"]["history_count"] == 2
    assert projected["acceptance"]["latest"] == second


def test_time_decision_is_separate_and_bounded(
    tmp_path, signer, change_detail
) -> None:
    workflow = DeliveryPackWorkflow(tmp_path, signer=signer)
    pack = workflow.project(change_detail)
    act = workflow.record_acceptance(change_detail, _accept(pack))
    request = AcceptedTimeDecisionRequest(
        request_id="apsreq_time_decision_0001",
        expected_basis_hash=pack["basis_hash"],
        expected_effort_hash=pack["effort"]["effort_hash"],
        decision="accepted",
        accepted_hours=2.0,
        note="Reviewed against the signed event draft.",
        confirmed=True,
    )
    time_decision = workflow.record_time_decision(change_detail, request)

    assert "accepted_hours" not in act
    assert time_decision["accepted_hours"] == 2.0
    assert time_decision["effort_hash"] == pack["effort"]["effort_hash"]
    assert time_decision["signature"]["purpose"] == "delivery.time.record"

    with pytest.raises(DeliveryPackError, match="cannot exceed"):
        workflow.record_time_decision(
            change_detail,
            request.model_copy(
                update={
                    "request_id": "apsreq_time_decision_too_high",
                    "accepted_hours": 2.51,
                }
            ),
        )


def test_decisions_are_idempotent_and_stale_safe(
    tmp_path, signer, change_detail
) -> None:
    workflow = DeliveryPackWorkflow(tmp_path, signer=signer)
    pack = workflow.project(change_detail)
    request = _accept(pack)
    first = workflow.record_acceptance(change_detail, request)
    assert workflow.record_acceptance(change_detail, request) == first

    with pytest.raises(DeliveryPackError, match="request id"):
        workflow.record_acceptance(
            change_detail,
            request.model_copy(update={"decision": "rejected", "note": "Changed replay"}),
        )
    with pytest.raises(DeliveryPackError, match="basis"):
        workflow.record_acceptance(
            change_detail,
            _accept(
                pack,
                request_id="apsreq_acceptance_stale",
                expected_basis_hash="sha256:" + "9" * 64,
            ),
        )
    with pytest.raises(DeliveryPackError, match="effort"):
        workflow.record_time_decision(
            change_detail,
            AcceptedTimeDecisionRequest(
                request_id="apsreq_time_stale_0001",
                expected_basis_hash=pack["basis_hash"],
                expected_effort_hash="sha256:" + "8" * 64,
                decision="rejected",
                note="Wrong revision",
                confirmed=True,
            ),
        )
