from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RFP = (ROOT / "docs" / "RFP-006-studio-loop-closure.md").read_text(encoding="utf-8")
SPEC = (ROOT / "docs" / "specs" / "SPEC-STUDIO-LOOP-CLOSURE-1.md").read_text(encoding="utf-8")
ACCEPTANCE_IDS = [f"LOOP-{index}" for index in range(1, 8)]


def _section(document: str, heading: str) -> str:
    marker = f"## {heading}"
    start = document.index(marker)
    tail = document[start + len(marker) :]
    match = re.search(r"^## ", tail, flags=re.MULTILINE)
    return tail[: match.start()] if match else tail


def _flat(value: str) -> str:
    return " ".join(value.split())


def test_rfp_and_spec_traceability_are_exact() -> None:
    assert re.findall(r"^\| (LOOP-\d+) \|", RFP, flags=re.MULTILINE) == ACCEPTANCE_IDS
    assert re.findall(
        r"^\| (LOOP-\d+) \| R(\d+) \| covered \|$", SPEC, flags=re.MULTILINE
    ) == [(value, str(index)) for index, value in enumerate(ACCEPTANCE_IDS, 1)]
    assert re.findall(r"^## R(\d+) ", SPEC, flags=re.MULTILINE) == [
        str(index) for index in range(8)
    ]


def test_every_requirement_has_one_specific_gate() -> None:
    gates = re.findall(r"^\(verify: (.+)\)$", SPEC, flags=re.MULTILINE)
    assert len(gates) == 8
    assert len(set(gates)) == 8
    assert all("TODO" not in gate for gate in gates)
    assert "R1-R7 remain pending" in SPEC


def test_status_review_delivery_and_cowork_boundaries_are_explicit() -> None:
    r1 = _flat(_section(SPEC, "R1 Canonical file-drift status"))
    r3 = _flat(_section(SPEC, "R3 Private local review handoff"))
    r4 = _flat(_section(SPEC, "R4 Governed Git delivery"))
    r5 = _flat(_section(SPEC, "R5 Optional signed Cowork Inbox"))
    assert "one ledger read per refresh" in r1
    assert "unavailable state instead of" in r1
    assert "owner-only temporary artifact" in r3
    assert "neither source, paths, raw diff nor runner transcript" in r3
    assert "already staged set" in r4
    assert "Never auto-stage, force-push" in r4
    assert "keep import inert" in r5
    assert "Local workflows remain usable" in r5


def test_contribution_contract_uses_apatch_truth_and_separate_acceptance() -> None:
    r6 = _flat(_section(SPEC, "R6 Canonical contribution and timesheet workflow"))
    rfp8 = _flat(_section(RFP, "8. Contribution and timesheet contract"))
    for phrase in (
        "run_timesheet",
        "must not aggregate ContributionEvent",
        "operation-spacing estimates",
        "contribution_receipt",
        "avatar_sync",
        "AVATAR_CONTRACT_UNAVAILABLE",
        "pending outbox",
        "Missing providers never disable the local draft",
    ):
        assert phrase in r6
    assert "A separate authority decision remains required for accepted time" in rfp8
    assert "local execution and timesheet verification remain usable" in rfp8


def test_release_gate_requires_interaction_and_browser_proof() -> None:
    r7 = _flat(_section(SPEC, "R7 Closed-loop release proof"))
    assert "full Python suite" in r7
    assert "production frontend build" in r7
    assert "desktop and mobile browser QA" in r7
    assert "Compilation or label presence alone is insufficient" in r7
