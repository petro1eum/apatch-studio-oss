from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RFP = (ROOT / "docs" / "RFP-007-studio-outside-in-experience.md").read_text(encoding="utf-8")
SPEC = (ROOT / "docs" / "specs" / "SPEC-STUDIO-OUTSIDE-IN-1.md").read_text(encoding="utf-8")
ACCEPTANCE_IDS = [f"OUT-{index}" for index in range(1, 10)]


def _section(document: str, heading: str) -> str:
    marker = f"## {heading}"
    start = document.index(marker)
    tail = document[start + len(marker) :]
    match = re.search(r"^## ", tail, flags=re.MULTILINE)
    return tail[: match.start()] if match else tail


def _flat(value: str) -> str:
    return " ".join(value.split())


def test_rfp_and_spec_traceability_are_exact() -> None:
    assert re.findall(r"^\| (OUT-\d+) \|", RFP, flags=re.MULTILINE) == ACCEPTANCE_IDS
    assert re.findall(
        r"^\| (OUT-\d+) \| R(\d+) \| covered \|$", SPEC, flags=re.MULTILINE
    ) == [(value, str(index)) for index, value in enumerate(ACCEPTANCE_IDS, 1)]
    assert re.findall(r"^## R(\d+) ", SPEC, flags=re.MULTILINE) == [
        str(index) for index in range(10)
    ]


def test_every_requirement_has_one_specific_gate() -> None:
    gates = re.findall(r"^\(verify: (.+)\)$", SPEC, flags=re.MULTILINE)
    assert len(gates) == 10
    assert len(set(gates)) == 10
    assert all("TODO" not in gate for gate in gates)
    assert "R1-R9 become attested only" in SPEC


def test_outside_in_contract_preserves_authority_and_privacy() -> None:
    decision = _flat(_section(RFP, "1. Decision"))
    non_goals = _flat(_section(RFP, "Non-goals"))
    scope = _flat(_section(SPEC, "R4 Scope honesty"))
    proof = _flat(_section(SPEC, "R6 Progressive proof disclosure"))
    assert "APatch remains the engine and the sole truth" in decision
    assert "does not weaken sandbox, governance or evidence semantics" in non_goals
    assert "never source or raw repository paths" in scope
    assert "Full local diff remains an explicit local-only action" in proof


def test_release_gate_requires_real_journeys() -> None:
    release = _flat(_section(SPEC, "R9 Outside-in release proof"))
    assert "disposable first-run journey" in release
    assert "complete Python suite" in release
    assert "production frontend build" in release
    assert "desktop/mobile browser QA" in release
    assert "without weakening RFP-006 functionality" in release
