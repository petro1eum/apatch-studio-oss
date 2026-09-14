from pathlib import Path

from apatch_studio.project_documents import ProjectKnowledgeWorkspace


RFP = """# RFP-101 -- Human plan\n\n## 1. Decision\n\nMake the project understandable before showing protocol records.\n\n## Acceptance\n\n| Id | Requirement | Level |\n|---|---|---|\n| H-1 | A person can open the plan | MUST |\n"""
SPEC = """# SPEC-HUMAN-1 -- Executable human plan\n\n> **apatch artifact:** `spec:SPEC-HUMAN-1`  \n> **Anchors:** RFP-101  \n\n## R0 RFP traceability gate (meta)\n\n| RFP id | SPEC Rk | Disposition |\n|---|---|---|\n| H-1 | R1 | covered |\n\n(verify: true)\n\n## R1 Open the plan\n\nThe developer can read the exact plan.\n\n(verify: true)\n"""


def test_catalog_pairs_proposals_and_specs_with_human_context(tmp_path: Path) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/RFP-101-human-plan.md").write_text(RFP, encoding="utf-8")
    (tmp_path / "docs/specs/SPEC-HUMAN-1.md").write_text(SPEC, encoding="utf-8")
    status = {"specs": [{"id": "SPEC-HUMAN-1", "done": False, "coverage_status": "available", "summary": {"total": 2, "attested": 1, "stale": 1, "blocked": 0}, "requirements": [{"id": "R1", "state": "stale"}]}]}

    page = ProjectKnowledgeWorkspace(tmp_path).catalog(status)
    plan = page["items"][0]

    assert page["count"] == 1
    assert plan["title"] == "Human plan"
    assert plan["purpose"] == "Make the project understandable before showing protocol records."
    assert plan["state_label"] == "Needs re-check"
    assert plan["progress"] == {"complete": 1, "total": 2, "percent": 50.0}
    assert plan["open_document_id"] == "SPEC-HUMAN-1"
    assert "docs/" not in repr(page)
    assert str(tmp_path) not in repr(page)



def test_studio_generated_rfp_is_paired_with_its_spec_and_decision_links(tmp_path: Path) -> None:
    rfp_id = "RFP-STUDIO-0D8C58AD09D5"
    spec_id = "SPEC-STUDIO-CHANGE-0D8C58AD09D5"
    rfp = RFP.replace("RFP-101", rfp_id).replace("H-1", "WORK-1")
    spec = (
        SPEC.replace("SPEC-HUMAN-1", spec_id)
        .replace("RFP-101", rfp_id)
        .replace("H-1", "WORK-1")
    )
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / f"docs/{rfp_id}-governed-work.md").write_text(rfp, encoding="utf-8")
    (tmp_path / f"docs/specs/{spec_id}.md").write_text(spec, encoding="utf-8")

    workspace = ProjectKnowledgeWorkspace(tmp_path)
    catalog = workspace.catalog()
    document = workspace.document(spec_id)

    assert catalog["count"] == 1
    assert catalog["items"][0]["proposal_id"] == rfp_id
    assert document["proposal_id"] == rfp_id
    assert document["traceability"]["status"] == "complete"
    assert document["requirements"][1]["acceptance"] == {
        "id": "WORK-1",
        "requirement": "A person can open the plan",
        "level": "MUST",
    }

def test_catalog_omits_repository_spec_templates(tmp_path: Path) -> None:
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/specs/SPEC-HUMAN-1.md").write_text(SPEC, encoding="utf-8")
    (tmp_path / "docs/specs/SPEC-TEMPLATE.md").write_text(
        "# SPEC-<ID> -- <Human title>\n\n## R0 Template\n\n(verify: true)\n",
        encoding="utf-8",
    )

    page = ProjectKnowledgeWorkspace(tmp_path).catalog()

    assert [item["id"] for item in page["items"]] == ["SPEC-HUMAN-1"]
