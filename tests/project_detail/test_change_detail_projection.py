from __future__ import annotations

from typing import Any

import pytest

from apatch_studio.change_details import (
    ChangeDetailNotFound,
    InvalidChangeId,
    _MAX_FILE_PATCH_BYTES,
    change_id_for_session,
    project_signed_change_detail,
    recorded_change_patch,
)


PROJECT = {
    "name": "demo",
    "identity": "workspace-1",
    "repository": "owner/demo",
    "branch": "main",
    "upstream": "origin/main",
    "head": "abc123",
    "operator": "Local Developer",
}


def _entry(
    session_id: str,
    *,
    record_id: str,
    timestamp: float,
    tool_id: str = "apatch",
    files: dict[str, Any] | None = None,
    intent: str = "SPEC-DEMO#R1: Build the result",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "governed_session_id": session_id,
        "intent": intent,
        "artifacts": [{"kind": "spec", "id": "SPEC-DEMO#R1"}],
    }
    if files is not None:
        payload["files"] = files
        payload["applied_patches"] = len(files)
    return {
        "id": record_id,
        "timestamp": timestamp,
        "tool_id": tool_id,
        "key_id": "signer-key-1",
        "payload": payload,
    }


def test_detail_is_derived_from_one_exact_ledger_session() -> None:
    selected = "apatch_sess_selected_12345678"
    foreign = "apatch_sess_foreign_12345678"
    entries = [
        _entry(
            foreign,
            record_id="op_foreign",
            timestamp=1,
            files={"foreign.py": {"diff": "+foreign\n", "mode": "644", "sha256": "a" * 64}},
        ),
        _entry(
            selected,
            record_id="op_mutation",
            timestamp=2,
            files={
                "src/app.py": {
                    "diff": "--- a/src/app.py\n+++ b/src/app.py\n@@ -1 +1 @@\n-old\n+new\n",
                    "mode": "644",
                    "sha256": "b" * 64,
                }
            },
        ),
        _entry(selected, record_id="op_attest", timestamp=3, tool_id="apatch_attest"),
    ]

    detail = project_signed_change_detail(
        entries,
        change_id_for_session(selected),
        project=PROJECT,
    )

    assert detail["governed_session_id"] == selected
    assert detail["result_kind"] == "code_change"
    assert detail["summary"]["file_count"] == 1
    assert detail["summary"]["signed_event_count"] == 2
    assert detail["files"][0]["path"] == "src/app.py"
    assert "foreign" not in repr(detail)
    assert detail["available_actions"] == [
        "back_to_changes",
        "open_recorded_patch",
        "open_backlog",
    ]
    assert recorded_change_patch(detail).startswith(b"--- a/src/app.py")


def test_recorded_patch_is_safe_bounded_and_complete() -> None:
    session = "apatch_sess_safe_paths_12345678"
    oversized = "--- a/src/app.py\n+++ b/src/app.py\n" + ("+value\n" * 50000)
    detail = project_signed_change_detail(
        [
            _entry(
                session,
                record_id="op_paths",
                timestamp=1,
                files={
                    "../secret.env": {"diff": "+secret\n", "mode": "644", "sha256": "c" * 64},
                    "/Users/private/key": {"diff": "+key\n", "mode": "644", "sha256": "d" * 64},
                    "src/app.py": {"diff": oversized, "mode": "755", "sha256": "e" * 64},
                },
            )
        ],
        change_id_for_session(session),
        project=PROJECT,
    )

    assert [row["path"] for row in detail["files"]] == ["src/app.py"]
    file_row = detail["files"][0]
    assert file_row["mode"] == "755"
    assert file_row["sha256"] == "e" * 64
    assert file_row["patch_status"] == "truncated"
    assert file_row["truncated"] is True
    assert file_row["patch_bytes"] <= _MAX_FILE_PATCH_BYTES
    assert detail["summary"]["omitted_file_count"] == 2
    assert detail["summary"]["patch_truncated"] is True
    assert "secret.env" not in repr(detail)
    assert "/Users/" not in repr(detail)


def test_attestation_only_session_is_an_honest_checkpoint() -> None:
    session = "apatch_sess_checkpoint_12345678"
    detail = project_signed_change_detail(
        [_entry(session, record_id="op_attest", timestamp=1, tool_id="apatch_attest")],
        change_id_for_session(session),
        project=PROJECT,
    )

    assert detail["result_kind"] == "verification_checkpoint"
    assert detail["result_message"] == (
        "No files were changed. This record verifies existing project state."
    )
    assert detail["files"] == []
    assert "open_recorded_patch" not in detail["available_actions"]
    assert recorded_change_patch(detail) == b""


def test_invalid_and_unknown_change_ids_fail_closed() -> None:
    with pytest.raises(InvalidChangeId):
        project_signed_change_detail([], "../../secret", project=PROJECT)
    with pytest.raises(ChangeDetailNotFound):
        project_signed_change_detail(
            [],
            "apchg_" + "a" * 32,
            project=PROJECT,
        )
