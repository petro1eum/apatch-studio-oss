from __future__ import annotations

from apatch_studio.delivery_pack import (
    AcceptanceActRequest,
    AcceptedTimeDecisionRequest,
    DeliveryPackWorkflow,
    verify_delivery_signature,
)


def test_complete_delivery_pack_journey(tmp_path, signer, change_detail) -> None:
    workflow = DeliveryPackWorkflow(tmp_path, signer=signer)
    initial = workflow.project(change_detail)
    act_request = AcceptanceActRequest(
        request_id="apsreq_journey_acceptance",
        expected_basis_hash=initial["basis_hash"],
        decision="accepted",
        note="Tests and recorded result reviewed.",
        confirmed=True,
    )
    act = workflow.record_acceptance(change_detail, act_request)
    assert workflow.record_acceptance(change_detail, act_request) == act

    time = workflow.record_time_decision(
        change_detail,
        AcceptedTimeDecisionRequest(
            request_id="apsreq_journey_time",
            expected_basis_hash=initial["basis_hash"],
            expected_effort_hash=initial["effort"]["effort_hash"],
            decision="accepted",
            accepted_hours=2.25,
            note="Accepted independently from result acceptance.",
            confirmed=True,
        ),
    )
    final = workflow.project(change_detail)

    assert verify_delivery_signature(
        final["acceptance"]["latest"], purpose="delivery.acceptance.record"
    )["act_id"] == act["act_id"]
    assert verify_delivery_signature(
        final["time_decision"]["latest"], purpose="delivery.time.record"
    )["decision_id"] == time["decision_id"]
    assert final["acceptance"]["latest"]["decision"] == "accepted"
    assert final["time_decision"]["latest"]["accepted_hours"] == 2.25
    assert final["document_hash"].startswith("sha256:")
