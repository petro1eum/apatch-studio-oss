from pathlib import Path
import re

import pytest

from apatch_studio.operations import AgentRunRequest

ROOT = Path(__file__).resolve().parents[1]


def test_rfp_traceability():
    rfp = (ROOT / "docs/RFP-002-studio-operational-workspace.md").read_text(
        encoding="utf-8"
    )
    spec = (ROOT / "docs/specs/SPEC-STUDIO-OPERATIONS-1.md").read_text(
        encoding="utf-8"
    )
    acceptance = re.findall(r"\| (OP-\d+) \|", rfp)
    traced = re.findall(r"\| (OP-\d+) \| R\d+ \| covered \|", spec)

    assert len(acceptance) == len(set(acceptance)) == 9
    assert len(traced) == len(set(traced)) == 9
    assert set(acceptance) == set(traced) == {f"OP-{index}" for index in range(1, 10)}


def test_typed_requests_reject_ambiguous_work():
    new_change = AgentRunRequest.model_validate(
        {
            "mode": "new_change",
            "runner": "codex",
            "objective": "Add a bounded export workflow",
            "acceptance_criteria": ["The export is deterministic"],
        }
    )
    requirement = AgentRunRequest.model_validate(
        {
            "mode": "requirement",
            "runner": "claude",
            "objective": "Implement the selected requirement",
            "spec_id": "SPEC-EXPORT-1",
            "requirement_id": "R3",
        }
    )
    recovery = AgentRunRequest.model_validate(
        {
            "mode": "recovery",
            "runner": "codex",
            "objective": "Recover the interrupted governed work",
            "governed_session_id": "apatch_sess_1234_a1b2c3",
        }
    )

    assert new_change.acceptance_criteria == ["The export is deterministic"]
    assert requirement.spec_id == "SPEC-EXPORT-1"
    assert recovery.governed_session_id == "apatch_sess_1234_a1b2c3"

    invalid = [
        {
            "mode": "new_change",
            "runner": "codex",
            "objective": "Run a shell command",
            "acceptance_criteria": ["The command returns zero"],
            "command": "rm -rf .",
        },
        {
            "mode": "new_change",
            "runner": "codex",
            "objective": "Missing criteria",
        },
        {
            "mode": "requirement",
            "runner": "claude",
            "objective": "Missing requirement",
            "spec_id": "SPEC-EXPORT-1",
        },
        {
            "mode": "requirement",
            "runner": "codex",
            "objective": "Invalid identifier",
            "spec_id": "../../etc/passwd",
            "requirement_id": "R1",
        },
        {
            "mode": "recovery",
            "runner": "codex",
            "objective": "Ambiguous recovery",
            "governed_session_id": "apatch_sess_1234_a1b2c3",
            "spec_id": "SPEC-EXPORT-1",
        },
    ]
    for payload in invalid:
        with pytest.raises(ValueError):
            AgentRunRequest.model_validate(payload)
