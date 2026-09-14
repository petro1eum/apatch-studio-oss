from pathlib import Path

from apatch_studio.project_documents import ProjectKnowledgeWorkspace


RFP = """# RFP-103 -- Explain proof\n\n## 1. Decision\n\nExplain why a result is proven.\n\n## Acceptance\n\n| Id | Requirement | Level |\n|---|---|---|\n| PROOF-1 | Show the configured basis | MUST |\n"""
SPEC = """# SPEC-PROOF-1 -- Explain proof\n\n> **apatch artifact:** `spec:SPEC-PROOF-1`  \n> **Anchors:** RFP-103  \n\n## R0 RFP traceability gate (meta)\n\n| RFP id | SPEC Rk | Disposition |\n|---|---|---|\n| PROOF-1 | R1 | covered |\n\n(verify: true)\n\n## R1 Visible basis\n\nThe result states exactly why the configured check supports it.\n\n(verify: python3 -m pytest tests/test_visible.py -q)\n"""


def test_spec_reader_contains_statements_state_and_progressive_verification(tmp_path: Path) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/RFP-103-proof.md").write_text(RFP, encoding="utf-8")
    (tmp_path / "docs/specs/SPEC-PROOF-1.md").write_text(SPEC, encoding="utf-8")
    status = {"specs": [{"id": "SPEC-PROOF-1", "done": True, "summary": {"total": 2, "attested": 2, "stale": 0, "blocked": 0}, "requirements": [{"id": "R0", "state": "attested"}, {"id": "R1", "state": "attested"}]}]}

    document = ProjectKnowledgeWorkspace(tmp_path).document("SPEC-PROOF-1", status)
    requirement = next(row for row in document["requirements"] if row["id"] == "R1")

    assert document["kind"] == "specification"
    assert document["summary"] == "Explain why a result is proven."
    assert document["status"] == "Complete"
    assert document["requirements"][0]["statement"] == "This plan is explicitly linked to its proposal and acceptance criteria."
    assert requirement["statement"] == "The result states exactly why the configured check supports it."
    assert requirement["state"] == "attested"
    assert requirement["verification"]["label"] == "Passed and recorded"
    assert requirement["acceptance"]["id"] == "PROOF-1"
    assert "pytest" not in requirement["verification"]["explanation"]
    assert "pytest" in requirement["technical"]["verification_command"]


def test_spec_reader_repairs_escaped_markdown_table_breaks_for_display(tmp_path: Path) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/RFP-103-proof.md").write_text(RFP, encoding="utf-8")
    escaped_spec = SPEC.replace(
        "| RFP id | SPEC Rk | Disposition |\n|---|---|---|\n",
        "| RFP id | SPEC Rk | Disposition |\\n|---|---|---|\\n\n",
    )
    (tmp_path / "docs/specs/SPEC-PROOF-1.md").write_text(escaped_spec, encoding="utf-8")

    document = ProjectKnowledgeWorkspace(tmp_path).document("SPEC-PROOF-1")

    assert document["traceability"]["status"] == "complete"
    assert document["traceability"]["mappings"] == [
        {"acceptance_id": "PROOF-1", "requirement_id": "R1"}
    ]
    assert document["requirements"][0]["statement"] == (
        "This plan is explicitly linked to its proposal and acceptance criteria."
    )
    assert "\\n" not in document["requirements"][0]["statement"]
