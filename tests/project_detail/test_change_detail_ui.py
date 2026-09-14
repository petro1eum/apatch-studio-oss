from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_deep_link_renders_dedicated_change_workspace() -> None:
    shell = (ROOT / "frontend/src/OutsideInApp.tsx").read_text(encoding="utf-8")
    detail = (ROOT / "frontend/src/ChangeDetailView.tsx").read_text(encoding="utf-8")

    assert 'import { ChangeDetailView } from "./ChangeDetailView"' in shell
    assert "route.resourceId ? (" in shell
    assert "<ChangeDetailView" in shell
    assert "All changes" in detail
    assert "Changed files" in detail
    assert "Open patch locally" in detail
    assert "Why this result is proven" in detail
    assert "View specification" in detail
    assert "View proposal" in detail


def test_actor_roles_are_distinct_and_human_readable() -> None:
    source = (ROOT / "frontend/src/ChangeDetailView.tsx").read_text(encoding="utf-8")

    assert "Studio runner" in source
    assert "Local operator" in source
    assert "Recorded by" in source
    assert "No files were changed" in source
    assert "It is proof, not a code change." in source


def test_studio_run_detail_retains_contextual_actions() -> None:
    detail = (ROOT / "frontend/src/ChangeDetailView.tsx").read_text(encoding="utf-8")
    views = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")

    assert "<ChangeCard" in detail
    assert "standalone" in detail
    assert "requestConfirm={requestConfirm}" in detail
    for capability in [
        "openRunLocalReview",
        "saveRunReviewNote",
        "runDeliveryAction",
        "retryRun",
        '"recovery"',
        '"rollback_preview"',
        "cancelRun",
    ]:
        assert capability in views
