"""SEC-8 review regression: equal counters do not mean an identical result."""
from copy import deepcopy

import pytest

from apatch_studio.delivery_pack import AcceptedTimeDecisionRequest, DeliveryPackError

from .test_delivery_pack_integrity import _workflow, _accept


@pytest.mark.parametrize("field,value", [
    ("path", "src/replaced.py"),
    ("mode", "755"),
    ("sha256", "9" * 64),
    ("patch", "--- old secret\n+++ substituted code"),
    ("patch_status", "truncated"),
    ("record_ids", ["substituted-record"]),
])
def test_same_count_file_substitution_invalidates_consent(tmp_path, signer, change_detail, field, value):
    workflow = _workflow(tmp_path, signer)
    request, act = _accept(workflow, change_detail)
    before = workflow.project(change_detail)
    time = workflow.record_time_decision(change_detail, AcceptedTimeDecisionRequest(
        request_id="apsreq_sec8_bound_hours", expected_basis_hash=before["basis_hash"],
        expected_effort_hash=before["effort"]["effort_hash"], decision="accepted", accepted_hours=1.0, confirmed=True,
    ))
    changed = deepcopy(change_detail)
    changed["files"][0][field] = value
    assert changed["summary"] == change_detail["summary"]
    after = workflow.project(changed)
    assert after["basis_hash"] != before["basis_hash"]
    assert after["acceptance"]["latest"] is None
    assert after["time_decision"]["latest"] is None
    assert after["acceptance"]["history"] == [act]
    assert after["time_decision"]["history"] == [time]
    with pytest.raises(DeliveryPackError, match="basis changed"):
        workflow.record_acceptance(changed, request)


def test_file_fingerprint_is_content_safe_and_byte_exact(tmp_path, signer, change_detail):
    workflow = _workflow(tmp_path, signer)
    left = deepcopy(change_detail)
    right = deepcopy(change_detail)
    left["files"][0]["patch"] = "+caf\u00e9"
    right["files"][0]["patch"] = "+cafe\u0301"
    first = workflow.project(left)
    second = workflow.project(right)
    assert first["basis_hash"] != second["basis_hash"]
    assert first["recorded_files_hash"] != second["recorded_files_hash"]
    assert first["recorded_files_hash"].startswith("sha256:")
    assert "caf" not in str(first) and "/Users/private/" not in str(first)
