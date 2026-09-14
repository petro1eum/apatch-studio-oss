from pathlib import Path


def test_review_exposes_real_technical_actions_and_exact_recovery():
    root = Path(__file__).resolve().parents[2]
    app = (root / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
    proof = (root / "frontend/src/ProofDetails.tsx").read_text(encoding="utf-8")
    for label in [
        "Review result",
        "Save note",
        "Retry",
        "Recover",
        "Preview rollback",
    ]:
        assert label in app
    assert "Open local diff" in proof


def test_review_keeps_technical_and_business_decisions_separate():
    root = Path(__file__).resolve().parents[2]
    app = (root / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
    detail = (root / "frontend/src/ChangeDetailView.tsx").read_text(encoding="utf-8")
    assert "Technical proof, human acceptance and reviewed time remain separate" in detail
    assert "runDeliveryAction" in app


def test_review_notes_are_bounded_and_local_only():
    root = Path(__file__).resolve().parents[2]
    app = (root / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
    api = (root / "frontend/src/api.ts").read_text(encoding="utf-8")
    assert "saveRunReviewNote(run.run_id, note)" in app
    assert "/review-note" in api
    assert "window.localStorage" not in app
    assert "Reviewer note" in app
