from pathlib import Path

from apatch_studio.contribution_workflow import ContributionWorkflow, TimesheetRequest


ROOT = Path(__file__).resolve().parents[2]


def _workflow(tmp_path: Path, verify: dict) -> ContributionWorkflow:
    return ContributionWorkflow(
        tmp_path,
        timesheet_runner=lambda **_kwargs: {"verify": verify},
        compatibility_supplier=lambda: {"ok": True, "status": "compatible"},
        tracker_supplier=lambda: {},
        evidence_pending_supplier=lambda: 0,
        contribution_preview_supplier=lambda: {"pending": 0},
        last_ack_supplier=lambda: None,
        project_supplier=lambda _root: {"id": "project:demo", "name": "Demo"},
    )


def test_timesheet_separates_signature_coverage_from_integrity(tmp_path: Path) -> None:
    workflow = _workflow(
        tmp_path,
        {
            "ok": False,
            "checked": 30,
            "drift": [],
            "unsigned": ["legacy:1", "legacy:2"],
        },
    )
    result = workflow.timesheet(
        TimesheetRequest(
            request_id="apsreq_time_partial",
            action="verify",
            group_by=["day"],
        )
    )

    assert result["ok"] is False
    assert result["signature_status"] == "partial"
    assert result["integrity_status"] == "matched"
    assert result["accepted_time"] is False
    assert result["summary"] == (
        "2 older audit records are unsigned; signed record volumes still match."
    )
    assert result["next_action"] == "Keep this as a draft or exclude legacy audit history."


def test_timesheet_marks_real_volume_drift_separately(tmp_path: Path) -> None:
    workflow = _workflow(
        tmp_path,
        {
            "ok": False,
            "checked": 12,
            "drift": [{"op_id": "opaque"}],
            "unsigned": [],
        },
    )
    result = workflow.timesheet(
        TimesheetRequest(
            request_id="apsreq_time_drifted",
            action="verify",
            group_by=["spec"],
        )
    )

    assert result["signature_status"] == "complete"
    assert result["integrity_status"] == "drifted"
    assert "1 signed record no longer matches" in result["summary"]
    assert result["next_action"] == "Inspect the changed ledger record before using this draft."


def test_library_has_no_dead_method_action_and_time_uses_honest_labels() -> None:
    methods = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
    time = (ROOT / "frontend/src/TimeLibrary.tsx").read_text(encoding="utf-8")

    assert 'asset.recallable ?' in methods
    assert "Reference only" in methods
    assert "disabled={acting !== null || !asset.recallable" not in methods
    assert "Governed operations" in time
    assert "Signed operations" not in time
    assert "signature_status" in time
    assert "integrity_status" in time
    assert "Draft time is never accepted automatically" in time
