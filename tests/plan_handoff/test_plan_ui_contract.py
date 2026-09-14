from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VIEWS = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
TYPES = (ROOT / "frontend/src/types.ts").read_text(encoding="utf-8")
LANGUAGE = (ROOT / "frontend/src/productLanguage.ts").read_text(encoding="utf-8")
SHELL = (ROOT / "frontend/src/OutsideInApp.tsx").read_text(encoding="utf-8")
PLAN = (ROOT / "frontend/src/ProjectPlanView.tsx").read_text(encoding="utf-8")


def test_plan_ready_card_uses_human_status_and_source_honesty() -> None:
    assert "plan_handoff:" in TYPES
    assert 'label: "Plan ready"' in LANGUAGE
    assert '"0 source files changed"' in VIEWS
    assert 'label: "Source unchanged"' in VIEWS
    assert ">Review plan<" in VIEWS
    assert "Prepared plan" in VIEWS


def test_exact_route_opens_first_prepared_requirement() -> None:
    assert "onOpenPlan: (documentId: string) => void" in VIEWS
    assert 'run.plan_handoff.spec_id + "#" + run.plan_handoff.requirement_ids[0]' in VIEWS
    assert 'onOpenPlan={(documentId) => navigate("backlog", "requirements", documentId)}' in SHELL
    assert 'const [documentId, selectedRequirementId] = resourceId.split("#", 2)' in PLAN


def test_plan_only_run_hides_implementation_actions() -> None:
    assert 'run.status !== "succeeded" || planOnly' in VIEWS
    assert '!planOnly && run.status === "succeeded" && delivery' in VIEWS
    assert '!planOnly ? <ProofDetails' in VIEWS


def test_implementation_actions_remain_available_for_real_source_runs() -> None:
    for label in ("Commit", "Push", "Open PR"):
        assert f">{label}<" in VIEWS
    assert "openRunLocalReview" in VIEWS


def test_owner_continuation_reuses_existing_freeze_and_requirement_flow() -> None:
    assert "freezeExecutionContract" in PLAN
    assert "Approve scope & tests" in PLAN
    assert 'mode: "requirement"' in PLAN
    assert "ready_for_owner" in PLAN
    assert "Source work is blocked until you approve" in PLAN
