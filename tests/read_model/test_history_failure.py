"""Supplemental history-failure regressions; frozen READ-INDEX tests are untouched."""
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from apatch_studio.adapter import APatchStudioAdapter
from apatch_studio.read_index import WorkspaceReadIndex
from apatch_studio.projection import assert_projection_safe

ROOT = Path(__file__).resolve().parents[2]


def workspace(tmp_path):
    (tmp_path / ".git").mkdir()
    (tmp_path / ".trustchain" / "objects").mkdir(parents=True)
    return tmp_path


def record(root, number):
    path = root / ".trustchain" / "objects" / f"op_{number}.json"
    value = {"id": f"op_{number}", "signature": "signed-fixture-123456789",
             "timestamp": number,
             "value": {"tool_id": "apatch", "data": {"action": "apply", "intent": "fixture"}}}
    path.write_text(json.dumps(value))
    return path


def watch_reads(monkeypatch):
    reads = []
    original = Path.read_bytes
    def watched(path):
        if path.parent.name == "objects":
            reads.append(path.name)
        return original(path)
    monkeypatch.setattr(Path, "read_bytes", watched)
    return reads


def test_retry_reuses_valid_and_invalid_bytes_without_publishing_partial_generation(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    record(root, 1)
    record(root, 2).write_text("{broken")
    record(root, 3)
    index = WorkspaceReadIndex(root)
    reads = watch_reads(monkeypatch)
    with pytest.raises(ValueError):
        index.read()
    assert sorted(reads) == ["op_1.json", "op_2.json", "op_3.json"]
    assert index.generation == 0
    before = list(reads)
    with pytest.raises(ValueError):
        index.read()
    assert reads == before
    assert index.generation == 0


def test_retry_repair_reads_only_changed_object_and_publishes_one_complete_generation(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    record(root, 1)
    record(root, 2).write_text("{broken")
    record(root, 3)
    index = WorkspaceReadIndex(root)
    reads = watch_reads(monkeypatch)
    with pytest.raises(ValueError):
        index.read()
    reads.clear()
    record(root, 2)
    rows, active = index.read()
    assert active and {row["id"] for row in rows} == {"op_1", "op_2", "op_3"}
    assert reads == ["op_2.json"]
    assert index.generation == 1
    assert index.failure_summary() is None


def test_diagnostics_are_complete_bounded_and_never_include_raw_data_or_paths(tmp_path):
    root = workspace(tmp_path)
    bad = b"{broken:canary-private-value"
    for number in range(40):
        record(root, number).write_bytes(bad)
    index = WorkspaceReadIndex(root)
    with pytest.raises(ValueError):
        index.read()
    summary = index.failure_summary()
    assert summary["code"] == "invalid_ledger_objects"
    assert summary["affected_count"] == 40
    assert summary["truncated"] is True
    assert len(summary["items"]) == 16
    assert {item["object_id"] for item in summary["items"]} <= {f"op_{i}" for i in range(40)}
    for item in summary["items"]:
        assert item["digest"] == "sha256:" + hashlib.sha256(bad).hexdigest()
        assert item["reason"] == "invalid_json"
    assert "canary" not in repr(summary)
    assert str(root) not in repr(summary)
    assert_projection_safe(summary)
    summary["items"].clear()
    assert len(index.failure_summary()["items"]) == 16


def test_diagnostics_disappear_after_removal_without_rewriting_original_bytes(tmp_path):
    root = workspace(tmp_path)
    good = record(root, 1)
    bad = record(root, 2)
    bad.write_text("{broken")
    before = good.read_bytes()
    index = WorkspaceReadIndex(root)
    with pytest.raises(ValueError):
        index.read()
    bad.unlink()
    assert [r["id"] for r in index.read()[0]] == ["op_1"]
    assert good.read_bytes() == before
    assert index.failure_summary() is None


def test_runtime_survives_history_failure_without_full_doctor(tmp_path, monkeypatch):
    import apatch_studio.adapter as module
    root = workspace(tmp_path)
    record(root, 1).write_text("{broken")
    calls = []
    def posture(_root):
        calls.append("configuration")
        return {"version": "0.8.47", "trustchain": {"mode": "enforce"},
                "enforcement": {"active": True},
                "hygiene": {"status": "clean", "issues": []},
                "mcp_health": {"mcp_tool_catalog": {"count": 123}},
                "writer_protocol": {"protocol": "v1", "disjoint_concurrency": True},
                "trust_anchor": {"level": "enrolled"}}
    def forbidden(*args, **kwargs):
        raise AssertionError("full archive doctor must not run")
    monkeypatch.setattr(module, "runtime_posture", posture)
    monkeypatch.setattr(module, "run_doctor", forbidden)
    adapter = APatchStudioAdapter(root, nonblocking=True)
    adapter.overview()
    adapter.wait_for_read_model(timeout=3)
    result = adapter.overview()
    assert result["read_model"]["status"] == "unavailable"
    assert result["runtime"]["enforcement"] is True
    assert result["runtime"]["trust_mode"] == "enforce"
    assert result["runtime"]["tool_count"] == 123
    assert result["runtime"]["hygiene"] == "clean"
    assert result["summary"]["coverage_status"] == "unavailable"
    assert calls == ["configuration"]


def test_failed_refresh_never_returns_old_evidence_as_current(tmp_path, monkeypatch):
    root = workspace(tmp_path)
    adapter = APatchStudioAdapter(root, nonblocking=True)
    monkeypatch.setattr(adapter, "_build", lambda: {
        "schema": "ready", "degraded": [], "summary": {"attested": 900},
        "evidence": [{"id": "old-attestation"}]})
    adapter.overview()
    adapter.wait_for_read_model(timeout=2)
    assert adapter.overview()["read_model"]["status"] == "ready"
    def fail():
        raise ValueError("canary-private-payload")
    monkeypatch.setattr(adapter, "_build", fail)
    adapter.overview(force=True)
    adapter.wait_for_read_model(timeout=2)
    failed = adapter.overview()
    assert failed["read_model"]["status"] == "unavailable"
    assert "attested" not in failed["summary"]
    assert failed["evidence"] == []
    assert "old-attestation" not in repr(failed)
    assert "canary" not in repr(failed)


def test_diagnostic_is_projected_without_claiming_a_ready_history(tmp_path):
    root = workspace(tmp_path)
    record(root, 7).write_text("{broken")
    adapter = APatchStudioAdapter(root, nonblocking=True)
    adapter.overview()
    adapter.wait_for_read_model(timeout=3)
    result = adapter.overview()
    assert result["read_model"]["status"] == "unavailable"
    summary = result["read_model"]["diagnostic"]
    assert summary["affected_count"] == 1
    assert summary["items"][0]["object_id"] == "op_7"
    assert str(root) not in repr(summary)
    assert_projection_safe(result)


def test_navigation_allows_documents_and_admin_but_not_evidence_views_during_failure():
    code = """
import assert from 'node:assert/strict';
import { canRenderWorkspaceView } from './frontend/src/readModelVisibility.ts';
for (const status of ['building', 'unavailable']) {
  assert.equal(canRenderWorkspaceView('backlog', status), true);
  assert.equal(canRenderWorkspaceView('admin', status), true);
  for (const view of ['home', 'library', 'inbox'])
    assert.equal(canRenderWorkspaceView(view, status), false);
}
for (const status of ['ready', 'refreshing', undefined])
  for (const view of ['home', 'library', 'inbox', 'admin', 'backlog'])
    assert.equal(canRenderWorkspaceView(view, status), true);
"""
    subprocess.run(["node", "--experimental-strip-types", "--input-type=module", "-e", code],
                   cwd=ROOT, check=True, capture_output=True, text=True)
