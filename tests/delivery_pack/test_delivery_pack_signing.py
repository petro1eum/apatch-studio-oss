from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest

from apatch_studio.delivery_pack import (
    AcceptanceActRequest,
    DeliveryPackError,
    DeliveryPackWorkflow,
    DeliverySigner,
    verify_delivery_signature,
)


def test_local_owner_signature_verifies(tmp_path, signer, change_detail) -> None:
    workflow = DeliveryPackWorkflow(tmp_path, signer=signer)
    pack = workflow.project(change_detail)
    act = workflow.record_acceptance(
        change_detail,
        AcceptanceActRequest(
            request_id="apsreq_signed_acceptance",
            expected_basis_hash=pack["basis_hash"],
            decision="accepted",
            confirmed=True,
        ),
    )

    unsigned = verify_delivery_signature(act, purpose="delivery.acceptance.record")
    assert unsigned["authority"]["trust"] == "local-self-signed"
    assert unsigned["authority"]["actor_id"] == "owner:test"

    tampered = deepcopy(act)
    tampered["decision"] = "rejected"
    with pytest.raises(DeliveryPackError, match="signature"):
        verify_delivery_signature(tampered, purpose="delivery.acceptance.record")


def test_connected_authority_cannot_weaken_semantics(tmp_path, change_detail) -> None:
    organization_signer = DeliverySigner.from_seed(
        b"organization-authority-seed-0001"[:32],
        actor_id="authority:review-board",
        label="Review board",
        trust="organization-authority",
        clock=lambda: datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
    )
    change_detail["sdd"]["verification"]["executed"] = 0
    workflow = DeliveryPackWorkflow(tmp_path, signer=organization_signer)
    pack = workflow.project(change_detail)

    with pytest.raises(DeliveryPackError, match="meaningful test protocol"):
        workflow.record_acceptance(
            change_detail,
            AcceptanceActRequest(
                request_id="apsreq_pro_cannot_bypass",
                expected_basis_hash=pack["basis_hash"],
                decision="accepted",
                confirmed=True,
            ),
        )
