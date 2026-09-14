from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import apatch_studio.adapter as adapter_module
from apatch_studio.adapter import APatchStudioAdapter


def _adapter(tmp_path):
    (tmp_path / ".git").mkdir()
    return APatchStudioAdapter(tmp_path, cache_ttl=0)


def _patch_snapshot_dependencies(monkeypatch, *, coverage):
    calls = {"ledger": 0}

    def ledger(_root):
        calls["ledger"] += 1
        return ([{"id": "op-1", "payload": {}}], True)

    monkeypatch.setattr(adapter_module, "_ledger_entries", ledger)
    monkeypatch.setattr(adapter_module, "_discover_spec_ids", lambda _root: ["SPEC-A", "SPEC-B"])
    monkeypatch.setattr(
        adapter_module,
        "_load_spec",
        lambda _root, *, spec: SimpleNamespace(
            id=spec,
            title=spec + " title",
            source_path="/private/source/must-not-project",
        ),
    )
    monkeypatch.setattr(adapter_module, "spec_coverage_from_entries", coverage)
    monkeypatch.setattr(adapter_module, "build_traceability_index", lambda _rows: {})
    monkeypatch.setattr(adapter_module, "_activity_from_index", lambda _index: [])
    monkeypatch.setattr(
        adapter_module,
        "build_doctor_hygiene",
        lambda _root: {"status": "clean", "issues": []},
    )
    return calls


def test_one_ledger_read_drives_rows_totals_and_exact_stale_ids(monkeypatch, tmp_path) -> None:
    def coverage(spec, entries, root):
        assert entries == [{"id": "op-1", "payload": {}}]
        assert root == str(tmp_path)
        requirements = (
            [
                {"id": "R1", "state": "stale", "stale": True},
                {"id": "R2", "state": "pending", "stale": False},
            ]
            if spec.id == "SPEC-A"
            else [{"id": "R1", "state": "attested", "stale": False}]
        )
        return {
            "ok": True,
            "requirements": requirements,
            "summary": {
                "total": len(requirements),
                "attested": sum(row["state"] == "attested" for row in requirements),
                "stale": sum(row["state"] == "stale" for row in requirements),
                "pending": sum(row["state"] == "pending" for row in requirements),
                "in_progress": 0,
            },
        }

    calls = _patch_snapshot_dependencies(monkeypatch, coverage=coverage)
    status = _adapter(tmp_path)._canonical_status_snapshot()
    rows = APatchStudioAdapter._specifications(status)

    assert calls["ledger"] == 1
    assert status["summary"] == {
        "spec_count": 2,
        "coverage_status": "available",
        "coverage_error": None,
        "total_requirements": 3,
        "attested": 1,
        "stale_count": 1,
        "percent_complete": 33.3,
    }
    spec_a = next(row for row in rows if row["id"] == "SPEC-A")
    assert spec_a["stale"] == 1
    assert spec_a["stale_ids"] == ["R1"]
    assert spec_a["pending_ids"] == ["R2"]
    assert "/private/source" not in repr(status)


def test_coverage_failure_is_visible_and_never_becomes_false_zero(monkeypatch, tmp_path) -> None:
    def coverage(spec, _entries, _root):
        if spec.id == "SPEC-B":
            raise RuntimeError("private path and ledger internals")
        return {
            "ok": True,
            "requirements": [{"id": "R1", "state": "attested"}],
            "summary": {
                "total": 1,
                "attested": 1,
                "stale": 0,
                "pending": 0,
                "in_progress": 0,
            },
        }

    calls = _patch_snapshot_dependencies(monkeypatch, coverage=coverage)
    status = _adapter(tmp_path)._canonical_status_snapshot()
    rows = APatchStudioAdapter._specifications(status)

    assert calls["ledger"] == 1
    assert status["summary"]["coverage_status"] == "unavailable"
    assert "total_requirements" not in status["summary"]
    failed = next(row for row in rows if row["id"] == "SPEC-B")
    assert failed["coverage_status"] == "unavailable"
    assert failed["coverage_error"] == "RuntimeError"
    assert "private path" not in repr(status)


def test_frontend_renders_unavailable_instead_of_zero() -> None:
    source = (Path(__file__).resolve().parents[2] / "frontend" / "src" / "OutsideInViews.tsx").read_text()
    assert "Live requirement coverage is unavailable" in source
    assert "coverage_status" in source
