from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_primary_action_is_plain_and_advanced_controls_are_collapsed() -> None:
    source = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")

    assert "What do you want to change?" in source
    assert "Describe the result you want" in source
    assert "Prepare plan" in source
    assert "Run requirement" in source
    assert "Run with agent" not in source
    assert "<summary><ChevronDown size={14} />Options</summary>" in source
    assert "What should become true?" not in source
    assert "Refine verification" not in source


def test_result_cards_hide_protocol_anchors_until_proof() -> None:
    source = (ROOT / "frontend/src/ImportedChangeCard.tsx").read_text(encoding="utf-8")

    assert "humanTitle(change.objective)" in source
    assert "Technical anchor" in source
    assert "humanSpecTitle(resultTitle)" in source
    assert "verified steps · latest" in source
    assert "Existing APatch work" not in source
    assert "View proof" not in source


def test_full_history_and_deep_link_remain_reachable() -> None:
    source = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")

    assert "Show full history" in source
    assert "Show recent results" in source
    assert "selectedRunId && !recentIds.has(selectedRunId)" in source
    assert "visibleChanges.map((item)" in source
