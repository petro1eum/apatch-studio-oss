from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RFP = ROOT / "docs/RFP-013-studio-delivery-pack.md"
SPEC = ROOT / "docs/specs/SPEC-STUDIO-DELIVERY-1.md"


def test_rfp_013_has_complete_executable_traceability() -> None:
    rfp = RFP.read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")
    acceptance = set(re.findall(r"^\| (DEL-\d+) \|", rfp, flags=re.MULTILINE))
    mappings = dict(re.findall(r"^\| (DEL-\d+) \| (R\d+) \| covered \|$", spec, flags=re.MULTILINE))

    assert acceptance == {f"DEL-{index}" for index in range(1, 11)}
    assert set(mappings) == acceptance
    assert set(mappings.values()) == {f"R{index}" for index in range(1, 11)}
    assert spec.count("(verify: python3 -m pytest ") == 11


def test_contract_keeps_four_independent_truths() -> None:
    rfp = RFP.read_text(encoding="utf-8")
    for statement in (
        "A green test run is not an acceptance act.",
        "An accepted result does not accept hours.",
        "A timesheet draft is not payroll",
        "Correctness and evidence integrity are not paid features.",
    ):
        assert statement in rfp
