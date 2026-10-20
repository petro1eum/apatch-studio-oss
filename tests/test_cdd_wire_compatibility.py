"""Existing exact Studio reader; no keys, consent, broker or running service."""
import copy
import hashlib
import json
from pathlib import Path

import pytest

from apatch_studio.exact_contract_handoffs import raw_canonical, validate_native_snapshot
from apatch_studio.execution_intents import ExecutionIntentError

CORPUS = json.loads((Path(__file__).resolve().parents[3] / "apatch/tests/fixtures/sdd_wire_v1.json").read_text())


@pytest.mark.parametrize("case", CORPUS["cases"], ids=lambda c: c["name"])
def test_studio_exact_reads_core_wire_case_without_rewriting(case):
    original = copy.deepcopy(case)
    if case["valid"]:
        validate_native_snapshot(case["contract"], case["envelopes"])
    else:
        with pytest.raises(ExecutionIntentError):
            validate_native_snapshot(case["contract"], case["envelopes"])
    assert case == original


def test_studio_uses_same_golden_unicode_bytes_and_hash():
    raw = CORPUS["golden_canonical"].encode("utf-8")
    assert raw_canonical(json.loads(raw)) == raw
    assert "sha256:" + hashlib.sha256(raw).hexdigest() == CORPUS["golden_hash"]


@pytest.mark.parametrize("case", [c for c in CORPUS["cases"] if c["valid"]], ids=lambda c: c["name"])
def test_studio_accepts_fresh_core_output_without_recompiling(case):
    from apatch.sdd_integrity import freeze_contract, validate_task_envelope
    contract = freeze_contract({**case["contract"], "source_mutation_count": 0})
    envelope = validate_task_envelope({k: v for k, v in case["envelopes"]["R1"].items() if k != "document_hash"})
    validate_native_snapshot(contract, {"R1": envelope})
    assert contract == case["contract"] and envelope == case["envelopes"]["R1"]
