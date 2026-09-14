from __future__ import annotations

from copy import deepcopy

import pytest

from apatch_studio.delivery_pack import DeliveryPackWorkflow


def test_pack_composes_canonical_facts_without_duplicate_truth(
    tmp_path, signer, change_detail
) -> None:
    pack = DeliveryPackWorkflow(tmp_path, signer=signer).project(change_detail)

    assert pack["schema"] == "apatch.studio.delivery-pack.v1"
    assert pack["change"]["change_id"] == change_detail["change_id"]
    assert pack["ownership"] == {
        "execution": "apatch",
        "verification": "apatch",
        "effort": "apatch.run_timesheet",
        "acceptance": "studio_owner_decision",
        "accepted_time": "separate_owner_decision",
    }
    assert pack["acceptance"]["latest"] is None
    assert pack["time_decision"]["latest"] is None
    assert pack["effort"]["accepted_time"] is False


def test_test_protocol_binds_exact_available_evidence(
    tmp_path, signer, change_detail
) -> None:
    protocol = DeliveryPackWorkflow(tmp_path, signer=signer).project(change_detail)[
        "test_protocol"
    ]

    assert protocol["status"] == "passed"
    assert protocol["meaningful"] is True
    assert protocol["contract_hash"] == change_detail["sdd"]["proof"]["contract_hash"]
    assert protocol["envelope_hash"] == change_detail["sdd"]["proof"]["envelope_hash"]
    assert protocol["evidence_hash"] == change_detail["sdd"]["proof"]["evidence_hash"]
    assert protocol["counts"] == {
        "collected": 8,
        "executed": 8,
        "passed": 8,
        "failed": 0,
        "skipped": 0,
    }
    assert protocol["checks"][0]["test_id"].endswith("::test_exact_basis")
    assert protocol["protocol_hash"].startswith("sha256:")


@pytest.mark.parametrize(
    ("overrides", "blocker"),
    [
        ({"collected": 0, "executed": 0, "passed": 0}, "no_tests_collected"),
        ({"executed": 0, "passed": 0}, "no_tests_executed"),
        ({"executed": 4, "passed": 0, "skipped": 4}, "all_tests_skipped"),
        ({"failed": 1, "passed": 7}, "tests_failed"),
        ({"perspectives": ["positive", "boundary", "regression"]}, "missing_perspectives"),
        ({"falsification": {"observed_red": False, "restored_green": True}}, "falsification_incomplete"),
        ({"gate_quality": "incomplete", "accepted": False}, "apatch_gate_incomplete"),
    ],
)
def test_incomplete_gates_fail_closed(
    tmp_path, signer, change_detail, overrides, blocker
) -> None:
    detail = deepcopy(change_detail)
    detail["sdd"]["verification"].update(overrides)
    protocol = DeliveryPackWorkflow(tmp_path, signer=signer).project(detail)["test_protocol"]

    assert protocol["meaningful"] is False
    assert protocol["status"] != "passed"
    assert blocker in protocol["blockers"]
