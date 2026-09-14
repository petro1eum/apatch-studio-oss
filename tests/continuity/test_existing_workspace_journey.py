from pathlib import Path

from apatch_studio.change_feed import build_unified_change_feed


ROOT = Path(__file__).resolve().parents[2]


def test_existing_signed_work_prevents_false_first_run() -> None:
    page = build_unified_change_feed(
        [],
        [
            {
                "schema": "apatch.studio.imported-change.v1",
                "change_id": "apchg_existing",
                "governed_session_id": "apatch_sess_1000000000000000_existing",
                "objective": "Existing governed result",
                "created_at": "2026-09-01T10:00:00Z",
                "updated_at": "2026-09-01T10:05:00Z",
                "status": "proven",
            }
        ],
    )
    assert page["count"] == 1
    assert page["items"][0]["kind"] == "imported_change"

    views = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
    shell = (ROOT / "frontend/src/OutsideInApp.tsx").read_text(encoding="utf-8")
    assert "changes.length === 0" in views
    assert "visibleChanges.map((item)" in views
    assert "<ImportedChangeCard" in views
    assert "loadChangeFeed()" in shell


def test_true_empty_workspace_still_has_one_clear_start() -> None:
    assert build_unified_change_feed([], [])["items"] == []
    views = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
    home = views.split("export function HomeView", 1)[1].split("function ChangeCard", 1)[0]
    assert home.count("oi-start-button") == 1
    assert "Start your first change" in home
    assert "What do you want to change?" in home
