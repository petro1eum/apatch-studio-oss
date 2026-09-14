from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RFP = (ROOT / "docs" / "RFP-008-studio-existing-work-continuity.md").read_text(encoding="utf-8")
SPEC = (ROOT / "docs" / "specs" / "SPEC-STUDIO-CONTINUITY-1.md").read_text(encoding="utf-8")
ACCEPTANCE_IDS = [f"CONT-{index}" for index in range(1, 9)]


def _section(document: str, heading: str) -> str:
    marker = f"## {heading}"
    tail = document[document.index(marker) + len(marker):]
    match = re.search(r"^## ", tail, flags=re.MULTILINE)
    return tail[:match.start()] if match else tail


def _flat(value: str) -> str:
    return " ".join(value.split())


def test_rfp_and_spec_traceability_are_exact() -> None:
    assert re.findall(r"^\| (CONT-\d+) \|", RFP, flags=re.MULTILINE) == ACCEPTANCE_IDS
    assert re.findall(r"^\| (CONT-\d+) \| R(\d+) \| covered \|$", SPEC, flags=re.MULTILINE) == [
        (value, str(index)) for index, value in enumerate(ACCEPTANCE_IDS, 1)
    ]
    assert re.findall(r"^## R(\d+) ", SPEC, flags=re.MULTILINE) == [str(index) for index in range(9)]


def test_every_requirement_has_one_specific_gate() -> None:
    gates = re.findall(r"^\(verify: (.+)\)$", SPEC, flags=re.MULTILINE)
    assert len(gates) == 9
    assert len(set(gates)) == 9
    assert all("TODO" not in gate for gate in gates)


def test_contract_preserves_canonical_truth_and_authority() -> None:
    sources = _flat(_section(RFP, "3. Canonical sources"))
    assert "signed ledger remains the sole source" in _flat(_section(RFP, "1. Decision"))
    assert "run_timesheet" in sources
    assert "does not read or aggregate ContributionEvent files itself" in sources
    assert "Signed proof does not equal business acceptance" in _flat(_section(RFP, "7. Privacy and authority"))
    assert "APatch Studio OSS functionality" in _flat(_section(RFP, "6. Edition boundary"))


def test_release_gate_requires_real_existing_workspace_and_time_qa() -> None:
    release = _flat(_section(SPEC, "R8 Continuity release proof"))
    for phrase in ["complete Python suite", "production frontend build", "desktop/mobile browser QA", "existing-work continuity"]:
        assert phrase in release
