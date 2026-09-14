from __future__ import annotations

from datetime import date

from apatch_studio.contribution_workflow import ContributionWorkflow, TimesheetRequest


def test_timesheet_is_scoped_to_selected_workspace_project(tmp_path) -> None:
    calls = []

    def runner(**kwargs):
        calls.append(kwargs)
        if kwargs["do_verify"]:
            return {"verify": {"ok": True, "checked": 2, "drift": [], "unsigned": []}}
        return {"groups": []}

    workflow = ContributionWorkflow(
        tmp_path,
        timesheet_runner=runner,
        project_supplier=lambda _root: {"id": "project_123", "name": "Current workspace"},
    )
    draft = workflow.timesheet(
        TimesheetRequest(
            request_id="apsreq_scope_draft_001",
            action="draft",
            since=date(2026, 8, 25),
            until=date(2026, 8, 31),
            group_by=["day"],
        )
    )
    verified = workflow.timesheet(
        TimesheetRequest(
            request_id="apsreq_scope_verify_001",
            action="verify",
            since=date(2026, 8, 25),
            until=date(2026, 8, 31),
            group_by=["spec"],
        )
    )

    assert [call["project"] for call in calls] == ["project_123", "project_123"]
    assert [call["since"] for call in calls] == ["2026-08-25", "2026-08-25"]
    assert [call["until"] for call in calls] == ["2026-08-31", "2026-08-31"]
    assert all(call["include_audit"] is True for call in calls)
    assert draft["project"] == {"id": "project_123", "name": "Current workspace"}
    assert draft["period"] == {"since": "2026-08-25", "until": "2026-08-31"}
    assert verified["project"]["id"] == "project_123"


def test_default_period_is_seven_calendar_days_inclusive() -> None:
    request = TimesheetRequest(request_id="apsreq_scope_default_001", action="draft")
    assert request.since is not None
    assert request.until is not None
    assert (request.until - request.since).days == 6
