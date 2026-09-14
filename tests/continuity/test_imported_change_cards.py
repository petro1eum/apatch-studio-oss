from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_imported_card_is_truthful_and_has_no_reconstructed_mutation_actions() -> None:
    source = (ROOT / "frontend/src/ImportedChangeCard.tsx").read_text(encoding="utf-8")

    for visible in (
        "humanTitle(change.objective)",
        "Open result",
        "Signed proof available",
        "This result comes from signed project history",
        "Actions from the original run are no longer available",
        "Technical anchor",
        "Signed records",
    ):
        assert visible in source
    for unavailable in (
        "retryRun",
        "cancelRun",
        "runDeliveryAction",
        "rollback_preview",
        "openRunLocalReview",
        "saveRunReviewNote",
    ):
        assert unavailable not in source


def test_imported_card_uses_only_content_safe_aggregate_fields() -> None:
    source = (ROOT / "frontend/src/ImportedChangeCard.tsx").read_text(encoding="utf-8")
    for field in (
        "file_count",
        "insertions",
        "deletions",
        "logical_areas",
        "mutation_count",
        "attestation_count",
        "signed_event_count",
    ):
        assert "change." + field in source
    for forbidden in ("full_diff", "source_code", "repository_path", "workspace_path", "prompt"):
        assert forbidden not in source
