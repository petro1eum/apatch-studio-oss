from pathlib import Path

from apatch_studio.project_documents import ProjectKnowledgeWorkspace


RFP = """# RFP-104 -- Trace decisions\n\n## 1. Decision\n\nKeep exact lineage.\n\n## Acceptance\n\n| Id | Requirement | Level |\n|---|---|---|\n| TRACE-1 | First outcome | MUST |\n| TRACE-2 | Second outcome | MUST |\n"""


def _spec(rows: str) -> str:
    return f"""# SPEC-TRACE-1 -- Trace decisions\n\n> **apatch artifact:** `spec:SPEC-TRACE-1`  \n> **Anchors:** RFP-104  \n\n## R0 RFP traceability gate (meta)\n\n| RFP id | SPEC Rk | Disposition |\n|---|---|---|\n{rows}\n\n(verify: true)\n\n## R1 First\n\nFirst statement.\n\n(verify: true)\n\n## R2 Second\n\nSecond statement.\n\n(verify: true)\n"""


def _workspace(tmp_path: Path, rows: str) -> ProjectKnowledgeWorkspace:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/RFP-104-trace.md").write_text(RFP, encoding="utf-8")
    (tmp_path / "docs/specs/SPEC-TRACE-1.md").write_text(_spec(rows), encoding="utf-8")
    return ProjectKnowledgeWorkspace(tmp_path)


def test_traceability_is_exact_and_bidirectional(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, "| TRACE-1 | R1 | covered |\n| TRACE-2 | R2 | covered |")
    document = workspace.document("SPEC-TRACE-1")

    assert document["traceability"]["status"] == "complete"
    assert document["traceability"]["mappings"] == [
        {"acceptance_id": "TRACE-1", "requirement_id": "R1"},
        {"acceptance_id": "TRACE-2", "requirement_id": "R2"},
    ]


def test_named_traceability_table_outside_r0_remains_linked(tmp_path: Path) -> None:
    rows = "| TRACE-1 | R1 | covered |\n| TRACE-2 | R2 | covered |"
    workspace = _workspace(tmp_path, rows)
    spec_path = tmp_path / "docs/specs/SPEC-TRACE-1.md"
    source = spec_path.read_text(encoding="utf-8")
    source = source.replace(
        "## R0 RFP traceability gate (meta)\n\n",
        "## RFP traceability table\n\n",
        1,
    )
    source = source.replace(
        "(verify: true)\n\n## R1 First",
        "(verify: true)\n\n## R0 Contract coverage gate (meta)\n\n"
        "The mappings above are exact.\n\n(verify: true)\n\n## R1 First",
        1,
    )
    spec_path.write_text(source, encoding="utf-8")

    document = workspace.document("SPEC-TRACE-1")

    assert document["traceability"]["status"] == "complete"
    requirement = next(row for row in document["requirements"] if row["id"] == "R1")
    assert requirement["acceptance"]["id"] == "TRACE-1"


def test_missing_and_ambiguous_links_are_not_guessed(tmp_path: Path) -> None:
    missing = _workspace(tmp_path / "missing", "| TRACE-1 | R1 | covered |")
    assert missing.document("SPEC-TRACE-1")["traceability"]["status"] == "missing"

    ambiguous = _workspace(tmp_path / "ambiguous", "| TRACE-1 | R1 | covered |\n| TRACE-1 | R2 | covered |\n| TRACE-2 | R2 | covered |")
    trace = ambiguous.document("SPEC-TRACE-1")["traceability"]
    assert trace["status"] == "ambiguous"
    assert trace["ambiguous_acceptance_ids"] == ["TRACE-1"]
    assert trace["ambiguous_requirement_ids"] == ["R2"]
