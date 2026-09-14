from __future__ import annotations

import json

from apatch_studio.delivery_pack import (
    AcceptanceActRequest,
    DeliveryPackWorkflow,
)
from apatch_studio.projection import assert_projection_safe


def test_delivery_export_is_content_safe(tmp_path, signer, change_detail) -> None:
    workflow = DeliveryPackWorkflow(tmp_path, signer=signer)
    pack = workflow.project(change_detail)
    workflow.record_acceptance(
        change_detail,
        AcceptanceActRequest(
            request_id="apsreq_privacy_acceptance",
            expected_basis_hash=pack["basis_hash"],
            decision="accepted",
            confirmed=True,
        ),
    )
    exported = workflow.project(change_detail)
    serialized = json.dumps(exported, ensure_ascii=False)

    assert_projection_safe(exported)
    for forbidden in (
        "/Users/private",
        "--- old secret",
        "secret command output",
        '"files"',
        '"patch"',
        '"stdout"',
        '"prompt"',
        '"environment"',
    ):
        assert forbidden not in serialized
    assert exported["change"]["summary"]["file_count"] == 2
    assert exported["change"]["summary"]["insertions"] == 18
