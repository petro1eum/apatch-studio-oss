from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VIEWS = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
TYPES = (ROOT / "frontend/src/types.ts").read_text(encoding="utf-8")
CSS = (ROOT / "frontend/src/outside-in.css").read_text(encoding="utf-8")


def test_running_plan_card_shows_human_budget_and_stop() -> None:
    assert "planning:" in TYPES
    for label in ("Elapsed", "Last activity", "Time remaining", "Stop"):
        assert label in VIEWS
    assert "oi-planning-budget" in VIEWS
    assert ".oi-planning-budget" in CSS


def test_planning_ui_does_not_render_runner_commands_or_protocol_ids() -> None:
    planning_block = VIEWS[VIEWS.index('className="oi-planning-budget"'):]
    for forbidden in ("command", "argv", "cwd", "session_token", "governed_session_id"):
        assert "{" + "run.planning." + forbidden + "}" not in planning_block


def test_retry_opens_the_new_run_instead_of_leaving_the_failed_run_selected() -> None:
    detail = (ROOT / "frontend/src/ChangeDetailView.tsx").read_text(encoding="utf-8")
    shell = (ROOT / "frontend/src/OutsideInApp.tsx").read_text(encoding="utf-8")

    assert 'const created = await perform("retry", () => retryRun(run.run_id));' in VIEWS
    assert "if (created) onOpenRun(created.run_id);" in VIEWS
    assert "onOpenRun={onOpenRun}" in detail
    assert 'onOpenRun={(runId) => navigate("home", "feed", runId)}' in shell
