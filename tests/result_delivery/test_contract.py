from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RFP = ROOT / "docs/RFP-024-studio-cowork-result-delivery.md"
SPEC = ROOT / "docs/specs/SPEC-STUDIO-COWORK-RESULT-DELIVERY-1.md"


def _acceptance_ids(text: str) -> set[str]:
    return {
        match.group(1)
        for match in re.finditer(r"^\| (SDR-[1-9][0-9]*) \| .+ \| MUST \|$", text, re.M)
    }


def _traceability(text: str) -> dict[str, str]:
    return {
        match.group(1): match.group(2)
        for match in re.finditer(
            r"^\| (SDR-[1-9][0-9]*) \| (R[1-9][0-9]*) \| covered \|$",
            text,
            re.M,
        )
    }


def test_rfp_acceptance_is_fully_mapped() -> None:
    rfp_text = RFP.read_text(encoding="utf-8")
    spec_text = SPEC.read_text(encoding="utf-8")
    acceptance = _acceptance_ids(rfp_text)
    mapping = _traceability(spec_text)
    assert acceptance == {"SDR-1", "SDR-2", "SDR-3", "SDR-4", "SDR-5"}
    assert set(mapping) == acceptance
    assert set(mapping.values()) == {"R1", "R2", "R3", "R4", "R5"}
    for requirement in mapping.values():
        section = re.search(
            rf"^## {requirement} .+?\n(.*?)(?=^## |\Z)",
            spec_text,
            re.M | re.S,
        )
        assert section is not None
        verify = re.findall(r"^\(verify: (.+)\)$", section.group(1), re.M)
        assert len(verify) == 1
        assert "pytest" in verify[0]
