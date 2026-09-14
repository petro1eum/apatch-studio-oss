from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RFP = ROOT / "docs/RFP-011-studio-project-knowledge-decisions.md"
SPEC = ROOT / "docs/specs/SPEC-STUDIO-PROJECT-KNOWLEDGE-1.md"


def test_rfp_011_is_completely_mapped_to_executable_requirements() -> None:
    rfp = RFP.read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")
    acceptance_ids = re.findall(r"\| (KNOW-\d+) \|", rfp)
    mappings = dict(re.findall(r"\| (KNOW-\d+) \| (R\d+) \| covered \|", spec))

    assert acceptance_ids == [f"KNOW-{index}" for index in range(1, 11)]
    assert mappings == {f"KNOW-{index}": f"R{index}" for index in range(1, 11)}
    assert "TODO" not in spec
    assert spec.count("(verify: python3 -m pytest tests/project_knowledge/") == 11


def test_requirements_are_human_readable_before_their_verify_commands() -> None:
    spec = SPEC.read_text(encoding="utf-8")
    titles = [
        "Project briefing",
        "Plans catalog",
        "Proposal reader",
        "Executable plan reader",
        "Exact decision lineage",
        "Result decision basis",
        "Contextual actions",
        "Human-first language",
        "Bounded document API",
        "Release journey",
    ]
    for index, title in enumerate(titles, start=1):
        section = spec.split(f"## R{index} {title}\n\n", 1)[1]
        statement, verify = section.split("\n\n(verify:", 1)
        assert len(statement.strip()) >= 80
        assert "python3 -m pytest" in verify
