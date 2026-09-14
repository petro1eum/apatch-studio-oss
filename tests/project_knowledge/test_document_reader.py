from pathlib import Path

from apatch_studio.project_documents import ProjectKnowledgeWorkspace


def test_rfp_reader_returns_structured_safe_decision_content(tmp_path: Path) -> None:
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/RFP-102-reader.md").write_text(
        "# RFP-102 -- Readable decisions\n\n> **Status:** Approved\n\n"
        "## 1. Decision\n\nRender repository decisions as product content.\n\n"
        "## 2. Problem\n\nMachine codes do not explain the work.\n\n"
        "## Acceptance\n\n| Id | Requirement | Level |\n|---|---|---|\n| READ-1 | Read the decision | MUST |\n\n"
        "## Non-goals\n\n- Do not create a second database.\n\n"
        "[external](https://example.test) <script>bad()</script>\n",
        encoding="utf-8",
    )

    document = ProjectKnowledgeWorkspace(tmp_path).document("RFP-102")

    assert document["kind"] == "proposal"
    assert document["title"] == "Readable decisions"
    assert document["status"] == "Approved"
    assert document["acceptance"][0]["requirement"] == "Read the decision"
    section_titles = [section["title"] for section in document["sections"]]
    assert "1. Decision" in section_titles
    assert "Non-goals" in section_titles
    rendered = repr(document)
    assert "https://example.test" not in rendered
    assert "<script>" not in rendered
    assert str(tmp_path) not in rendered
