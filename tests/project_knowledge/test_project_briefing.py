from pathlib import Path

from apatch_studio.project_documents import ProjectKnowledgeWorkspace


def test_project_brief_uses_bounded_repository_owned_content(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text(
        "# Human Project\n\nBuilds understandable governed changes for developers.\n\n"
        "- Read the plan\n- Run the next item\n"
        "![remote](https://example.test/image.png)\n<script>bad()</script>\n",
        encoding="utf-8",
    )

    brief = ProjectKnowledgeWorkspace(tmp_path).project_brief()

    assert brief == {
        "schema": "apatch.studio.project-brief.v1",
        "title": "Human Project",
        "purpose": "Builds understandable governed changes for developers.",
        "highlights": ["Read the plan", "Run the next item"],
        "description_missing": False,
        "document_id": "PROJECT-README",
    }
    assert "https://" not in repr(brief)
    assert "<script" not in repr(brief).casefold()
    assert "bad()" not in repr(brief)


def test_missing_readme_is_reported_honestly(tmp_path: Path) -> None:
    brief = ProjectKnowledgeWorkspace(tmp_path).project_brief()

    assert brief["description_missing"] is True
    assert brief["document_id"] is None
