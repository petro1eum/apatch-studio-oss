import json
import stat

import pytest

from apatch_studio.run_store import (
    RECORD_SCHEMA,
    RunJournalError,
    RunJournalInUseError,
    RunStore,
)


def record(index=1, status="succeeded"):
    return {
        "schema": RECORD_SCHEMA,
        "run_id": f"apr_{index:032x}",
        "request": {
            "mode": "new_change",
            "runner": "codex",
            "objective": f"Deliver bounded change {index}",
            "acceptance_criteria": ["The focused verification passes"],
            "spec_id": None,
            "requirement_id": None,
            "governed_session_id": None,
        },
        "retry_of": None,
        "status": status,
        "phase": "complete" if status != "running" else "working",
        "created_at": f"2026-08-31T00:00:{index:02d}+00:00",
        "started_at": None,
        "ended_at": None,
        "outcome": "complete" if status == "succeeded" else None,
        "message": "Safe local status",
        "thread_id": None,
        "event_count": 0,
        "review": None,
        "updated_at": f"2026-08-31T00:00:{index:02d}+00:00",
    }


def make_store(tmp_path, *, retention=200):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    return workspace, RunStore(workspace, state_root=state_root, retention=retention)


def test_run_store_uses_private_workspace_scoped_state(tmp_path):
    workspace, store = make_store(tmp_path)
    assert store.workspace_identity not in str(workspace)
    assert store.journal_path.is_relative_to(tmp_path / "state")
    assert not store.journal_path.is_relative_to(workspace)
    assert store.journal_path.name == "runs.json"


def test_atomic_private_write_and_round_trip(tmp_path):
    _workspace, store = make_store(tmp_path)
    store.acquire_instance()
    second = RunStore(store.workspace, state_root=tmp_path / "state")
    with pytest.raises(RunJournalInUseError):
        second.acquire_instance()

    accepted = store.save([record()])
    loaded = store.load()
    assert loaded.records == accepted
    assert stat.S_IMODE(store.state_root.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.workspaces_directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(store.journal_path.stat().st_mode) == 0o600
    assert not list(store.directory.glob("*.tmp"))

    store.close()
    second.acquire_instance()
    second.close()


def test_store_rejects_forbidden_fields(tmp_path):
    _workspace, store = make_store(tmp_path)
    unsafe = record()
    unsafe["raw"] = "PRIVATE_KEY=/secret source=/Users/person/repo"
    with pytest.raises(RunJournalError, match="forbidden fields"):
        store.save([unsafe])

    nested = record()
    nested["request"]["session_token"] = "secret"
    with pytest.raises(RunJournalError, match="forbidden fields"):
        store.save([nested])
    assert not store.journal_path.exists()


def test_run_store_retains_bounded_terminal_history(tmp_path):
    _workspace, store = make_store(tmp_path, retention=2)
    kept = store.save([record(1), record(2), record(3), record(4, status="running")])
    assert [item["run_id"] for item in kept] == [record(2)["run_id"], record(3)["run_id"], record(4)["run_id"]]
    assert [item["run_id"] for item in store.load().records] == [item["run_id"] for item in kept]


def test_corrupt_journal_is_quarantined_not_executed(tmp_path):
    _workspace, store = make_store(tmp_path)
    store.directory.mkdir(parents=True)
    store.journal_path.write_text('{"schema":"wrong","records":[{"raw":"execute me"}]}', encoding="utf-8")
    loaded = store.load()
    assert loaded.records == []
    assert loaded.status == "recovered"
    assert loaded.warning == "invalid_journal_quarantined"
    assert not store.journal_path.exists()
    quarantined = list(store.directory.glob("runs.corrupt.*.json"))
    assert len(quarantined) == 1
    assert json.loads(quarantined[0].read_text())["schema"] == "wrong"
    assert stat.S_IMODE(quarantined[0].stat().st_mode) == 0o600
