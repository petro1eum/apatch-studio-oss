from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RFP = ROOT / "docs" / "RFP-015-studio-plan-handoff.md"
SPEC = ROOT / "docs" / "specs" / "SPEC-STUDIO-PLAN-HANDOFF-1.md"
EXPECTED = {f"PLAN-{index}" for index in range(1, 9)}


def test_rfp_015_traceability_and_verification_commands_are_complete() -> None:
    rfp_text = RFP.read_text(encoding="utf-8")
    spec_text = SPEC.read_text(encoding="utf-8")

    acceptance_ids = set(re.findall(r"^\| (PLAN-\d+) \|", rfp_text, flags=re.MULTILINE))
    mappings = re.findall(
        r"^\| (PLAN-\d+) \| (R\d+) \| covered \|$",
        spec_text,
        flags=re.MULTILINE,
    )

    assert acceptance_ids == EXPECTED
    assert {rfp_id for rfp_id, _ in mappings} == EXPECTED
    assert {rk for _, rk in mappings} == {f"R{index}" for index in range(1, 9)}
    assert "TODO" not in spec_text
    assert spec_text.count("(verify:") == 9
    assert "docs/specs/SPEC-STUDIO-PLAN-HANDOFF-1.md" in rfp_text
