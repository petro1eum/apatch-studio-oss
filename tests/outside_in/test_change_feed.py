from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_home_is_a_durable_change_feed_not_a_protocol_dashboard() -> None:
    main = (ROOT / "frontend/src/main.tsx").read_text(encoding="utf-8")
    shell = (ROOT / "frontend/src/OutsideInApp.tsx").read_text(encoding="utf-8")
    views = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
    proof = (ROOT / "frontend/src/ProofDetails.tsx").read_text(encoding="utf-8")

    assert 'import { OutsideInApp } from "./OutsideInApp"' in main
    assert "<OutsideInApp />" in main
    assert "outsideInNavigationTargets" in shell
    assert "<HomeView" in shell
    assert "visibleChanges.map((item)" in views
    assert "<ImportedChangeCard" in views
    assert "<ChangeCard" in views
    assert "What do you want to change?" in views
    assert "deltaLabel(run)" in views
    assert "scopeState(run.scope)" in views
    assert "proofState(run)" in views
    assert "oi-next-action" in views
    assert "<ProofDetails" in views
    assert "<details" in proof


def test_change_drill_in_keeps_review_delivery_and_recovery_actionable() -> None:
    source = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")

    for capability in [
        "openRunLocalReview",
        "saveRunReviewNote",
        "runDeliveryAction",
        "retryRun",
        '"recovery"',
        '"rollback_preview"',
        "cancelRun",
    ]:
        assert capability in source
    assert "window.confirm" not in source
    assert "requestConfirm" in source


def test_home_uses_safe_run_projection_without_raw_source_surfaces() -> None:
    source = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
    forbidden = ["full_diff", "source_code", "repository_path", "workspace_path", "prompt"]
    assert not any(term in source for term in forbidden)
