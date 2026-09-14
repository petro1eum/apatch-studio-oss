from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RFP = ROOT / "docs" / "RFP-016-studio-fast-observable-planning.md"
SPEC = ROOT / "docs" / "specs" / "SPEC-STUDIO-PLAN-ORCHESTRATION-1.md"
EXPECTED = {f"FAST-{index}" for index in range(1, 10)}
FROZEN_TESTS = {
    "tests/plan_orchestration/test_plan_contract.py",
    "tests/plan_orchestration/test_prompt_and_runner.py",
    "tests/plan_orchestration/test_progress.py",
    "tests/plan_orchestration/test_limits.py",
    "tests/plan_orchestration/test_run_ownership.py",
    "tests/plan_orchestration/test_ui_contract.py",
}


def test_rfp_016_traceability_and_verification_contract_are_complete() -> None:
    rfp_text = RFP.read_text(encoding="utf-8")
    spec_text = SPEC.read_text(encoding="utf-8")
    acceptance_ids = set(re.findall(r"^\| (FAST-\d+) \|", rfp_text, flags=re.MULTILINE))
    mappings = re.findall(
        r"^\| (FAST-\d+) \| (R\d+) \| covered \|$",
        spec_text,
        flags=re.MULTILINE,
    )

    assert acceptance_ids == EXPECTED
    assert {rfp_id for rfp_id, _ in mappings} == EXPECTED
    assert {rk for _, rk in mappings} == {f"R{index}" for index in range(1, 10)}
    assert spec_text.count("(verify:") == 10
    assert "TODO" not in spec_text
    assert "docs/specs/SPEC-STUDIO-PLAN-ORCHESTRATION-1.md" in rfp_text
    for path in FROZEN_TESTS:
        assert path in spec_text or path == "tests/plan_orchestration/test_plan_contract.py"
        assert (ROOT / path).is_file()
