import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VIEWS = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")


def test_start_requires_only_the_intended_outcome() -> None:
    composer = VIEWS.split('<section className={"oi-composer " +', 1)[1].split(
        "</section>",
        1,
    )[0]
    assert 'What do you want to change?' in composer
    assert 'id="change-objective"' in composer
    assert 'className="oi-button oi-button-primary oi-start-button"' in composer
    assert '<details className="oi-refinements">' in composer

    before_refinements = composer.split('<details className="oi-refinements">', 1)[0]
    assert len(re.findall(r"<textarea", before_refinements)) == 1
    assert "<select" not in before_refinements


def test_agent_and_acceptance_defaults_are_selected_without_user_decisions() -> None:
    assert 'availableRunners[0]?.id ?? "codex"' in VIEWS
    assert "criterion.trim() || defaultCriterion(clean)" in VIEWS
    assert 'const exactRequirementSelected = Boolean(specId && requirementId)' in VIEWS
    assert 'mode: exactRequirementSelected ? "requirement" : "new_change"' in VIEWS
    assert "acceptance_criteria:" in VIEWS


def test_recovery_and_rollback_are_contextual_failed_change_actions() -> None:
    start_area = VIEWS.split("export function HomeView", 1)[1].split(
        "function ChangeCard",
        1,
    )[0]
    card_area = VIEWS.split("function ChangeCard", 1)[1].split(
        "export function BacklogView",
        1,
    )[0]

    assert '"recovery"' not in start_area
    assert '"rollback_preview"' not in start_area
    assert 'run.work_ref.governed_session_id && run.can_retry' in card_area
    assert 'launchMode("recovery")' in card_area
    assert 'launchMode("rollback_preview")' in card_area
    assert "run.can_retry" in card_area
