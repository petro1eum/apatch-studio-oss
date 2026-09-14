from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_primary_states_use_human_product_language() -> None:
    language = (ROOT / "frontend/src/productLanguage.ts").read_text(encoding="utf-8")
    assert 'label: "Verified"' in language
    assert 'label: "Needs re-check"' in language
    assert 'label: "Recorded"' in language
    assert 'label: "Requested scope only"' in language


def test_exact_proof_is_hidden_by_default_and_keeps_full_fidelity() -> None:
    proof = (ROOT / "frontend/src/ProofDetails.tsx").read_text(encoding="utf-8")
    assert "<details" in proof
    assert "<details open" not in proof
    assert ">Proof</summary>" in proof
    for exact_ref in [
        "run.work_ref.spec_id",
        "run.work_ref.requirement_id",
        "run.work_ref.governed_session_id",
        "receipt?.event_id",
        "run.run_id",
    ]:
        assert exact_ref in proof


def test_full_diff_is_an_explicit_local_only_action() -> None:
    proof = (ROOT / "frontend/src/ProofDetails.tsx").read_text(encoding="utf-8")
    views = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
    assert "Open local diff" in proof
    assert "onOpenLocalReview" in proof
    assert "openRunLocalReview(run.run_id)" in views
    assert "full_diff" not in proof
    assert "source_code" not in proof
