import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_release_uses_the_outside_in_shell_and_contracts() -> None:
    main = (ROOT / "frontend/src/main.tsx").read_text(encoding="utf-8")
    navigation = json.loads(
        (ROOT / "frontend/src/navigation.contract.json").read_text(encoding="utf-8")
    )
    vocabulary = json.loads(
        (ROOT / "frontend/src/vocabulary.contract.json").read_text(encoding="utf-8")
    )
    publication = (ROOT / "docs/specs/SPEC-STUDIO-OSS-PUBLICATION-1.md").read_text(encoding="utf-8")

    assert "<OutsideInApp />" in main
    assert navigation["schema"] == "apatch.studio.navigation.v2"
    assert len(navigation["targets"]) == 5
    assert vocabulary["schema"] == "apatch.studio.product-vocabulary.v1"
    assert "R6 No Pro surface in OSS" in publication


def test_rfp006_actions_remain_reachable_inside_outside_in_destinations() -> None:
    views = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
    admin = (ROOT / "frontend/src/OutsideInAdmin.tsx").read_text(encoding="utf-8")
    time = (ROOT / "frontend/src/TimeLibrary.tsx").read_text(encoding="utf-8")
    source = views + "\n" + admin + "\n" + time

    for capability in [
        "openRunLocalReview",
        "saveRunReviewNote",
        "runDeliveryAction",
        "runTimesheet",
        "runEvidenceAction",
        "runAssetAction",
        "runSystemAction",
        "runWorkspaceAction",
        "runPolicyAction",
        "loadContributionHealth",
    ]:
        assert capability in source
    for action in [
        "Independent log check",
        "Re-check policy gate",
        "Check source state",
        "Sign rules",
        "Restore previous",
    ]:
        assert action in source


def test_all_focused_outside_in_gates_exist_and_are_nonempty() -> None:
    expected = [
        "test_change_feed.py",
        "test_navigation_contract.py",
        "test_vocabulary_contract.py",
        "test_scope_honesty.py",
        "test_start_contract.py",
        "test_proof_disclosure.py",
        "test_first_run_journey.py",
        "test_design_floor.py",
    ]
    directory = ROOT / "tests/outside_in"
    assert all((directory / name).stat().st_size > 200 for name in expected)


def test_active_browser_projection_keeps_local_content_out() -> None:
    source = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in [
            "frontend/src/OutsideInApp.tsx",
            "frontend/src/OutsideInViews.tsx",
            "frontend/src/OutsideInAdmin.tsx",
            "frontend/src/ProofDetails.tsx",
        ]
    )
    for forbidden in ["full_diff", "source_code", "repository_path", "workspace_path"]:
        assert forbidden not in source
