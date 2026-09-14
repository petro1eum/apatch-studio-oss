from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_time_surface_is_a_bounded_workflow_not_a_raw_dump() -> None:
    source = (ROOT / "frontend/src/TimeLibrary.tsx").read_text(encoding="utf-8")

    for capability in (
        "lastDays(7)",
        "choosePreset(30)",
        'type="date"',
        "By day",
        "By requirement",
        "Estimated hours",
        "Governed changes",
        "Governed operations",
        "File touches",
        "Verify records",
        "Export CSV",
        ".slice(0, 80)",
    ):
        assert capability in source
    assert "pending across all workspaces" in source
    assert "verification.signature_status" in source
    assert "verification.integrity_status" in source
    assert "Recorded volumes match" in source
    assert "Verify record integrity before relying on this draft" in source
    assert "Draft time is never accepted automatically" in source


def test_time_surface_uses_canonical_api_and_no_event_aggregation() -> None:
    source = (ROOT / "frontend/src/TimeLibrary.tsx").read_text(encoding="utf-8")
    backend = (ROOT / "apatch_studio/contribution_workflow.py").read_text(encoding="utf-8")

    assert "runTimesheet(action, [grouping], since, until)" in source
    assert '"project": self.project_id' in backend
    assert "self._timesheet(**common" in backend
    assert "load_events" not in backend
    assert "aggregate(" not in backend
