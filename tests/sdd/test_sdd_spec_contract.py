from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RFP_PATH = ROOT / "docs/RFP-012-studio-user-needs-readiness.md"
SPEC_PATH = ROOT / "docs/specs/SPEC-STUDIO-SDD-LIFECYCLE-1.md"
FREEZE_PATH = ROOT / "docs/contracts/RFP-012-owner-freeze.json"
EXPECTED_RFP_HASH = "14568070d1ee44e3f0ef33ae25932e631d8ed76b1ed05463de3c684b874039fa"
EXPECTED_IDS = [f"SDD-{index}" for index in range(1, 21)]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_rfp_012_owner_freeze_and_traceability_are_exact() -> None:
    freeze = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    current = RFP_PATH.read_bytes()
    spec = SPEC_PATH.read_text(encoding="utf-8")

    assert freeze["schema"] == "apatch.studio.owner-rfp-freeze.v1"
    assert freeze["rfp_id"] == "RFP-012"
    assert freeze["source_commit"] is None
    assert freeze["source_hash"] == f"sha256:{EXPECTED_RFP_HASH}"
    assert freeze["acceptance_ids"] == EXPECTED_IDS
    assert freeze["source_implementation_allowed"] is True
    assert _sha256(current) == EXPECTED_RFP_HASH

    mappings = re.findall(r"^\| (SDD-\d+) \| (R\d+) \| covered \|$", spec, re.MULTILINE)
    assert mappings == [(acceptance_id, f"R{index}") for index, acceptance_id in enumerate(EXPECTED_IDS, 1)]
    commands = re.findall(r"^\(verify: ([^)]+)\)$", spec, re.MULTILINE)
    assert len(commands) == 21
    assert all("TODO" not in command and "::test_" in command for command in commands)
