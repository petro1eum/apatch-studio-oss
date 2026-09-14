from __future__ import annotations

import json

from apatch_studio.change_history import project_signed_changes


def _entry(op_id, tool, timestamp, session, *, intent, files=None, artifacts=None):
    payload = {
        "governed_session_id": session,
        "session_id": session,
        "intent": intent,
        "artifacts": artifacts or [],
    }
    if files is not None:
        payload.update({"action": "chunk", "applied_patches": 1, "files": files})
    return {
        "id": op_id,
        "tool_id": tool,
        "timestamp": timestamp,
        "key_id": "key_" + op_id,
        "payload": payload,
    }


def test_signed_ledger_sessions_become_safe_ordered_changes() -> None:
    first = "apatch_sess_1000000000000000_first"
    second = "apatch_sess_2000000000000000_second"
    entries = [
        _entry(
            "op_1",
            "apatch",
            10,
            first,
            intent="Implement /Users/private/source.py safely",
            artifacts=[{"kind": "spec", "id": "SPEC-DEMO-1#R2"}],
            files={
                "frontend/src/App.tsx": {
                    "diff": "--- a/x\n+++ b/x\n-old\n+new\n+more\n"
                },
                "tests/test_app.py": {"diff": "--- a/y\n+++ b/y\n+assert ok\n"},
            },
        ),
        _entry(
            "op_2",
            "apatch_attest",
            20,
            first,
            intent="Implement /Users/private/source.py safely",
            artifacts=[{"kind": "spec", "id": "SPEC-DEMO-1#R2"}],
        ),
        _entry("op_3", "apatch", 30, second, intent="Record another change", files={}),
    ]

    changes = project_signed_changes(entries)

    assert [item["governed_session_id"] for item in changes] == [second, first]
    proven = changes[1]
    assert proven["status"] == "proven"
    assert proven["spec_id"] == "SPEC-DEMO-1"
    assert proven["requirement_id"] == "R2"
    assert proven["file_count"] == 2
    assert proven["logical_areas"] == ["frontend", "tests"]
    assert (proven["insertions"], proven["deletions"]) == (3, 1)
    assert proven["mutation_count"] == 1
    assert proven["attestation_count"] == 1
    assert "[local path]" in proven["objective"]

    encoded = json.dumps(changes)
    assert "/Users/private" not in encoded
    assert "frontend/src/App.tsx" not in encoded
    assert "--- a/x" not in encoded
    for forbidden in ("source_code", "full_diff", "session_token", "private_key"):
        assert forbidden not in encoded


def test_projection_drops_unbound_records_and_bounds_results() -> None:
    entries = [
        {"id": "noise", "tool_id": "apatch", "timestamp": 1, "payload": {"intent": "none"}},
        _entry("op_1", "apatch", 2, "apatch_sess_1000000000000000_bound", intent="Bound", files={}),
    ]
    assert len(project_signed_changes(entries, limit=1)) == 1
    assert project_signed_changes(entries, limit=1)[0]["objective"] == "Bound"
