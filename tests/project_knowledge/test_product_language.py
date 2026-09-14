from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_primary_project_surfaces_use_goals_and_decisions_before_protocol() -> None:
    shell = _read("frontend/src/OutsideInApp.tsx")
    views = _read("frontend/src/OutsideInViews.tsx")
    plan = _read("frontend/src/ProjectPlanView.tsx")
    detail = _read("frontend/src/ChangeDetailView.tsx")
    navigation = _read("frontend/src/navigation.contract.json")

    assert "project_brief.purpose" in views
    assert "What this project does" in views
    assert "View project plans" in views
    assert "data.plans.items.map" in views
    assert "Open plan" in views
    assert '"label": "Plans"' in navigation
    assert "<ProjectPlanView" in shell
    assert "What must become true" in plan
    assert "Work to be done" in plan
    assert "Expected outcome" in plan
    assert "Why this status" in plan
    assert "Why this result is proven" in detail
    assert "basis.requirement.statement" in detail
    assert "basis.proposal?.criterion?.requirement" in detail
    assert "View specification" in detail
    assert "View proposal" in detail
    assert "Technical audit" in plan
    assert "Technical audit" in detail
    assert "JSON.stringify" not in plan
    assert "next: " not in views
