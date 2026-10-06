"""R1: a coarse filesystem clock cannot turn changed bytes into fresh evidence."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from apatch_studio.read_index import WorkspaceReadIndex


def workspace(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".trustchain" / "objects").mkdir(parents=True)
    return tmp_path


def record(root, name, *, artifacts=None, tool="apatch", timestamp=1, files=None):
    path = root / ".trustchain" / "objects" / (name + ".json")
    payload = {"action": "apply", "governed_session_id": "apatch_sess_test123456",
               "intent": "test"}
    if artifacts is not None:
        payload["artifacts"] = artifacts
    if files is not None:
        payload["files"] = files
    value = {"id": name, "signature": "signed-test-value-123456789",
             "timestamp": timestamp, "value": {"tool_id": tool, "data": payload}}
    path.write_text(json.dumps(value))
    return path


def art(spec):
    return [{"kind": "spec", "id": spec + "#R1", "content_hash": "sha256:fixture"}]


def pin_coarse_metadata(monkeypatch, path):
    """Preserve real write events while modeling equal size/inode/time metadata."""
    original = Path.stat
    observed = original(path)
    pinned = SimpleNamespace(**{
        name: getattr(observed, name) for name in dir(observed)
        if name.startswith("st_")
    })

    def stat(chosen, *args, **kwargs):
        actual = original(chosen, *args, **kwargs)
        return pinned if chosen == path else actual

    monkeypatch.setattr(Path, "stat", stat)
    return WorkspaceReadIndex._stamp(path)


def reads_of_objects(monkeypatch):
    reads = []
    original = Path.read_bytes

    def tracked(path):
        if path.parent.name == "objects":
            reads.append(path.name)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", tracked)
    return reads


def test_incremental_equal_metadata_replacement_updates_only_changed_object(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    one = record(root, "one", artifacts=art("SPEC-A"))
    for number in range(8):
        record(root, "stable" + str(number), artifacts=art("SPEC-S"))
    index = WorkspaceReadIndex(root)
    reads = reads_of_objects(monkeypatch)
    original_rows, _, _, original_groups, _ = index.snapshot()
    before = index.generation
    first_reads = len(reads)
    stamp = pin_coarse_metadata(monkeypatch, one)
    record(root, "one", artifacts=art("SPEC-B"), timestamp=9)
    assert WorkspaceReadIndex._stamp(one) == stamp

    rows, _, _, groups, _ = index.snapshot()
    assert next(row for row in rows if row["id"] == "one")["timestamp"] == 9
    assert "SPEC-B" in groups and "SPEC-A" not in groups
    assert "SPEC-A" in original_groups
    assert next(row for row in original_rows if row["id"] == "one")["timestamp"] == 1
    assert index.generation == before + 1
    assert reads[first_reads:] == ["one.json"]
    index.snapshot()
    assert reads[first_reads:] == ["one.json"]


def test_incremental_equal_metadata_corruption_is_not_cached_as_ready(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    one = record(root, "one", artifacts=art("SPEC-A"))
    index = WorkspaceReadIndex(root)
    index.read()
    size = one.stat().st_size
    stamp = pin_coarse_metadata(monkeypatch, one)
    one.write_bytes(b"{" + b" " * (size - 1))
    assert WorkspaceReadIndex._stamp(one) == stamp
    with pytest.raises(ValueError, match="ledger_objects_unavailable"):
        index.read()
    assert index.failure_summary()["code"] == "invalid_ledger_objects"
    assert index.failure_summary()["affected_count"] == 1


def test_incremental_equal_metadata_repair_clears_failed_parse_without_full_scan(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    one = record(root, "one", artifacts=art("SPEC-A"))
    size = one.stat().st_size
    one.write_bytes(b"{" + b" " * (size - 1))
    index = WorkspaceReadIndex(root)
    stamp = pin_coarse_metadata(monkeypatch, one)
    with pytest.raises(ValueError, match="ledger_objects_unavailable"):
        index.read()
    record(root, "one", artifacts=art("SPEC-B"), timestamp=7)
    assert WorkspaceReadIndex._stamp(one) == stamp

    reads = reads_of_objects(monkeypatch)
    rows, active = index.read()
    assert active and rows[0]["timestamp"] == 7
    assert index.failure_summary() is None
    assert index.generation == 1
    index.read()
    assert reads == ["one.json"]
