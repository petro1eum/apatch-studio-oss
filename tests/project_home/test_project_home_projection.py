from apatch_studio.change_feed import build_unified_change_feed


def workspace(*, proven: int = 7, total: int = 9, dirty: int = 2) -> dict:
    return {
        "workspace": {"name": "Sample", "branch": "main", "dirty_files": dirty},
        "summary": {"attested": proven, "total_requirements": total},
    }


def imported(
    change_id: str,
    *,
    at: str,
    spec_id: str = "SPEC-X",
    requirement_id: str = "R1",
    files: int = 1,
    mutations: int = 1,
    status: str = "proven",
) -> dict:
    return {
        "change_id": change_id,
        "governed_session_id": f"session-{change_id}",
        "objective": f"{spec_id}#{requirement_id}: Human result {change_id}",
        "status": status,
        "created_at": at,
        "updated_at": at,
        "spec_id": spec_id,
        "requirement_id": requirement_id,
        "file_count": files,
        "mutation_count": mutations,
    }


def run(run_id: str, status: str, *, reviewer_note: dict | None = None) -> dict:
    return {
        "run_id": run_id,
        "status": status,
        "created_at": "2026-09-01T00:00:00Z",
        "reviewer_note": reviewer_note,
        "can_retry": status in {"failed", "interrupted"},
        "work_ref": {"governed_session_id": None},
    }


def test_project_briefing_precedes_history() -> None:
    page = build_unified_change_feed([], [], workspace=workspace())

    assert page["home"]["project"] == {"name": "Sample", "branch": "main"}
    assert page["home"]["state"]["label"] == "Ready for a new change"
    assert page["home"]["summary"] == {
        "proven": 7,
        "total": 9,
        "remaining": 2,
        "uncommitted_files": 2,
    }
    assert page["home"]["history_count"] == 0


def test_recent_outcomes_exclude_attest_only_records_and_are_bounded() -> None:
    changes = [
        imported(
            "attest-only",
            at="2026-09-01T00:10:00Z",
            files=0,
            mutations=0,
            requirement_id="R0",
        ),
        *[
            imported(
                f"meaningful-{index}",
                at=f"2026-09-01T00:0{index}:00Z",
                spec_id=f"SPEC-{index}",
                requirement_id=f"R{index}",
            )
            for index in range(1, 8)
        ],
    ]

    home = build_unified_change_feed([], changes, workspace=workspace())["home"]

    assert len(home["recent_ids"]) == 6
    assert "attest-only" not in home["recent_ids"]
    assert home["recent_ids"][0] == "meaningful-7"


def test_one_spec_collapses_to_one_newest_project_result() -> None:
    changes = [
        imported("spec-x-r1", at="2026-09-01T00:01:00Z"),
        imported("spec-y-r1", at="2026-09-01T00:02:00Z", spec_id="SPEC-Y"),
        imported("spec-x-r2", at="2026-09-01T00:03:00Z", requirement_id="R2"),
    ]

    home = build_unified_change_feed([], changes, workspace=workspace())["home"]

    assert home["recent_ids"] == ["spec-x-r2", "spec-y-r1"]
    assert home["recent_group_sizes"] == {"spec-x-r2": 2, "spec-y-r1": 1}


def test_current_state_priority_is_deterministic() -> None:
    assert build_unified_change_feed(
        [run("review", "succeeded"), run("active", "running")],
        [],
        workspace=workspace(),
    )["home"]["state"]["id"] == "working"
    assert build_unified_change_feed(
        [run("review", "succeeded"), run("failed", "failed")],
        [],
        workspace=workspace(),
    )["home"]["state"]["id"] == "attention"
    assert build_unified_change_feed(
        [run("review", "succeeded")],
        [],
        workspace=workspace(),
    )["home"]["state"]["id"] == "review"
    assert build_unified_change_feed(
        [run("reviewed", "succeeded", reviewer_note={"text": "Accepted"})],
        [],
        workspace=workspace(),
    )["home"]["state"]["id"] == "ready"
