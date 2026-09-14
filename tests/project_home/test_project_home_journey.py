from pathlib import Path

from apatch_studio.change_feed import build_unified_change_feed


ROOT = Path(__file__).resolve().parents[2]


def test_home_hierarchy_answers_project_state_action_and_recent_results() -> None:
    source = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")

    project = source.index('className="oi-project-header"')
    state = source.index('className="oi-project-summary"')
    action = source.index('className={"oi-composer "')
    results = source.index('className="oi-home-results"')
    assert project < state < action < results
    for visible in (
        "home.project.name",
        "home.state.label",
        "Verified work",
        "Left to verify",
        "Uncommitted files",
        "What do you want to change?",
        "Recent results",
    ):
        assert visible in source


def test_home_projection_and_full_history_share_one_canonical_response() -> None:
    page = build_unified_change_feed(
        [],
        [
            {
                "change_id": "meaningful",
                "governed_session_id": "session-meaningful",
                "objective": "SPEC-X#R1: Meaningful result",
                "status": "proven",
                "created_at": "2026-09-01T00:00:00Z",
                "updated_at": "2026-09-01T00:00:00Z",
                "spec_id": "SPEC-X",
                "requirement_id": "R1",
                "file_count": 1,
                "mutation_count": 1,
            },
            {
                "change_id": "attest-only",
                "governed_session_id": "session-attest",
                "objective": "SPEC-X#R0: Proof checkpoint",
                "status": "proven",
                "created_at": "2026-08-31T23:00:00Z",
                "updated_at": "2026-08-31T23:00:00Z",
                "spec_id": "SPEC-X",
                "requirement_id": "R0",
                "file_count": 0,
                "mutation_count": 0,
            },
        ],
        workspace={
            "workspace": {"name": "Sample", "branch": "main", "dirty_files": 0},
            "summary": {"attested": 2, "total_requirements": 2},
        },
    )

    assert page["home"]["recent_ids"] == ["meaningful"]
    assert [item["id"] for item in page["items"]] == ["meaningful", "attest-only"]
    assert page["home"]["history_count"] == page["count"] == 2


def test_home_styles_have_stable_desktop_and_mobile_hierarchy() -> None:
    styles = (ROOT / "frontend/src/outside-in.css").read_text(encoding="utf-8")

    for selector in (
        ".oi-project-header",
        ".oi-project-state",
        ".oi-project-summary",
        ".oi-home-results",
        ".oi-section-heading",
    ):
        assert selector in styles
    assert "@media (max-width: 640px)" in styles
    assert ".oi-project-summary { grid-template-columns: 1fr; }" in styles
    assert ".oi-project-header { display: grid; grid-template-columns: minmax(0, 1fr);" in styles
    assert ".oi-project-state { justify-self: start; }" in styles
    assert "overflow-wrap: anywhere" in styles


def test_release_qualification_pins_project_home_spec() -> None:
    specification = (ROOT / "docs/specs/SPEC-STUDIO-PROJECT-HOME-1.md").read_text(encoding="utf-8")
    assert "# SPEC-STUDIO-PROJECT-HOME-1" in specification
    assert "(verify:" in specification
