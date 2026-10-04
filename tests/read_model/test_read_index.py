from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import threading
import time

import pytest

from apatch_studio.adapter import APatchStudioAdapter
from apatch_studio.read_index import WorkspaceReadIndex, entries_for_spec, runtime_posture


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


def test_incremental_unchanged_and_append_only_read_new_object(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    record(root, "one", artifacts=art("SPEC-A"))
    index = WorkspaceReadIndex(root)
    reads = []
    original = Path.read_bytes
    def tracked(path):
        if path.parent.name == "objects":
            reads.append(path.name)
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", tracked)
    rows, active = index.read()
    assert active and [r["id"] for r in rows] == ["one"]
    first = len(reads)
    assert first == 1
    index.read()
    assert len(reads) == first
    record(root, "two", timestamp=2, artifacts=art("SPEC-A"))
    rows, active = index.read()
    assert {r["id"] for r in rows} == {"one", "two"}
    assert reads[first:] == ["two.json"]


def test_incremental_replacement_and_deletion_are_observed(tmp_path):
    root = workspace(tmp_path)
    old = record(root, "one", artifacts=art("SPEC-A"))
    index = WorkspaceReadIndex(root)
    index.read()
    record(root, "one", artifacts=art("SPEC-B"), timestamp=9)
    rows, _ = index.read()
    assert rows[0]["timestamp"] == 9
    old.unlink()
    assert index.read()[0] == []


def test_membership_keeps_implicit_predecessor_and_excludes_other_specs(tmp_path):
    root = workspace(tmp_path)
    record(root, "context", artifacts=art("SPEC-A"), timestamp=1)
    record(root, "implicit", timestamp=2, files={"app.py": {"sha256": "abc"}})
    record(root, "other", artifacts=art("SPEC-B"), timestamp=3)
    rows, _ = WorkspaceReadIndex(root).read()
    chosen = entries_for_spec(rows, "SPEC-A")
    assert {r["id"] for r in chosen} == {"context", "implicit"}
    from apatch.traceability import build_traceability_index
    canonical = build_traceability_index(rows)["by_artifact"]["spec:SPEC-A#R1"]
    scoped = build_traceability_index(chosen)["by_artifact"]["spec:SPEC-A#R1"]
    assert scoped == canonical


def test_membership_keeps_global_amendment_and_sdd_acceptance():
    rows = [
        {"id": "normal", "tool_id": "apatch", "timestamp": 1,
         "payload": {"artifacts": art("SPEC-A"), "intent": "begin"}},
        {"id": "amend", "tool_id": "apatch_sdd_judge_amendment", "timestamp": 2,
         "payload": {"schema": "apatch.sdd.judge-amendment.v1"}},
        {"id": "proof", "tool_id": "apatch_attest", "timestamp": 3,
         "payload": {"artifacts": art("SPEC-B"), "sdd_evidence": {"schema": "proof"}}},
    ]
    assert {r["id"] for r in entries_for_spec(rows, "SPEC-A")} == {"normal", "amend", "proof"}


def test_corrupt_object_does_not_masquerade_as_ready(tmp_path):
    root = workspace(tmp_path)
    path = record(root, "one", artifacts=art("SPEC-A"))
    index = WorkspaceReadIndex(root)
    index.read()
    path.write_text("{invalid")
    with pytest.raises((ValueError, RuntimeError)):
        index.read()
    record(root, "one", artifacts=art("SPEC-A"), timestamp=7)
    assert index.read()[0][0]["timestamp"] == 7


def test_concurrent_incremental_read_is_one_generation(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    record(root, "one", artifacts=art("SPEC-A"))
    index = WorkspaceReadIndex(root)
    count = []
    original = Path.read_bytes
    def tracked(path):
        if path.parent.name == "objects":
            count.append(path)
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", tracked)
    with ThreadPoolExecutor(max_workers=6) as pool:
        answers = list(pool.map(lambda _: index.read(), range(6)))
    assert all(answer == answers[0] for answer in answers)
    assert len(count) == 1


def test_posture_never_runs_archive_audit(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    from apatch.trustchain_helper import TrustChainHelper
    def forbidden(*args, **kwargs):
        raise AssertionError("full archive audit in UI read")
    monkeypatch.setattr(TrustChainHelper, "count_signed_blocks", forbidden)
    monkeypatch.setattr(TrustChainHelper, "iter_ledger_entries", forbidden)
    posture = runtime_posture(root)
    assert posture["version"]
    assert "trustchain" in posture and "enforcement" in posture


def test_drift_is_still_checked_against_live_source(tmp_path):
    import hashlib
    from apatch.spec import parse_spec_file
    from apatch.spec_coverage import spec_coverage_from_entries
    root = workspace(tmp_path)
    source = root / "app.py"
    source.write_text("original")
    spec_path = root / "SPEC-A.md"
    spec_path.write_text("# SPEC-A\n\n> **apatch artifact:** `spec:SPEC-A`\n\n## R1 Work\n\n(verify: pytest)\n")
    spec = parse_spec_file(str(spec_path))
    artifacts = [{"kind": "spec", "id": "SPEC-A#R1",
                  "content_hash": spec.requirements[0].content_hash}]
    record(root, "mutation", artifacts=artifacts,
           files={"app.py": {"sha256": hashlib.sha256(b"original").hexdigest()}})
    record(root, "attestation", artifacts=artifacts, tool="apatch_attest", timestamp=2)
    index = WorkspaceReadIndex(root)
    entries, _ = index.read()
    assert spec_coverage_from_entries(spec, entries_for_spec(entries, "SPEC-A"), str(root))["requirements"][0]["state"] == "attested"
    source.write_text("changed")
    entries, _ = index.read()
    row = spec_coverage_from_entries(spec, entries_for_spec(entries, "SPEC-A"), str(root))["requirements"][0]
    assert row["state"] == "stale" and row["stale_reason"] == "file_drift"


def test_opening_returns_before_blocked_builder_and_coalesces(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    adapter = APatchStudioAdapter(root, nonblocking=True, cache_ttl=0)
    started, release = threading.Event(), threading.Event()
    builds = []
    def blocked():
        builds.append(True)
        started.set()
        assert release.wait(5)
        return {"schema": "ready", "degraded": []}
    monkeypatch.setattr(adapter, "_build", blocked)
    begin = time.monotonic()
    first = adapter.overview()
    assert time.monotonic() - begin < 1
    assert first["read_model"]["status"] == "building"
    assert started.wait(1)
    for _ in range(4):
        assert adapter.overview()["read_model"]["status"] == "building"
    assert builds == [True]
    release.set()
    adapter.wait_for_read_model(timeout=2)
    # Do not force another build just to obtain the completed snapshot.
    adapter.cache_ttl = 60
    assert adapter.overview()["read_model"]["status"] == "ready"


def test_opening_failure_is_visible_and_retryable(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    adapter = APatchStudioAdapter(root, nonblocking=True)
    def fail():
        raise ValueError("secret-token-must-not-leak")
    monkeypatch.setattr(adapter, "_build", fail)
    adapter.overview()
    adapter.wait_for_read_model(timeout=2)
    failed = adapter.overview()
    assert failed["read_model"]["status"] == "unavailable"
    assert "secret-token" not in repr(failed)
    monkeypatch.setattr(adapter, "_build", lambda: {"schema": "ready", "degraded": []})
    adapter.overview(force=True)
    adapter.wait_for_read_model(timeout=2)
    assert adapter.overview()["read_model"]["status"] == "ready"


def test_incremental_index_writes_no_ledger_database(tmp_path):
    root = workspace(tmp_path)
    record(root, "one", artifacts=art("SPEC-A"))
    before = {p.relative_to(root) for p in root.rglob("*")}
    WorkspaceReadIndex(root).read()
    assert {p.relative_to(root) for p in root.rglob("*")} == before
