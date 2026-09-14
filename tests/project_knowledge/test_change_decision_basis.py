from pathlib import Path

import apatch_studio.adapter as adapter_module
from apatch_studio.adapter import APatchStudioAdapter


RFP = """# RFP-105 -- Explain a result

## 1. Decision

Every result explains its decision basis.

## Acceptance

| Id | Requirement | Level |
|---|---|---|
| BASIS-1 | Explain the exact result | MUST |
"""
SPEC = """# SPEC-BASIS-1 -- Explain a result

> **apatch artifact:** `spec:SPEC-BASIS-1`
> **Anchors:** RFP-105

## R0 RFP traceability gate (meta)

| RFP id | SPEC Rk | Disposition |
|---|---|---|
| BASIS-1 | R1 | covered |

(verify: true)

## R1 Explain the result

Show the exact requirement and why its configured check passed.

(verify: true)
"""


def test_spec_linked_change_includes_human_decision_basis(
    tmp_path: Path,
    monkeypatch,
) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "docs/specs").mkdir(parents=True)
    (tmp_path / "docs/RFP-105-result-basis.md").write_text(RFP, encoding="utf-8")
    (tmp_path / "docs/specs/SPEC-BASIS-1.md").write_text(SPEC, encoding="utf-8")
    adapter = APatchStudioAdapter(tmp_path)
    status = {
        "specs": [
            {
                "id": "SPEC-BASIS-1",
                "done": True,
                "coverage_status": "available",
                "summary": {"total": 2, "attested": 2},
                "requirements": [{"id": "R1", "state": "attested"}],
            }
        ]
    }
    monkeypatch.setattr(adapter, "_canonical_status_snapshot", lambda: status)
    monkeypatch.setattr(adapter_module, "_ledger_entries", lambda _root: ([], True))
    monkeypatch.setattr(
        adapter_module,
        "project_signed_change_detail",
        lambda *_args, **_kwargs: {
            "spec_id": "SPEC-BASIS-1",
            "requirement_id": "R1",
        },
    )

    detail = adapter.change_detail("apchg_11111111111111111111111111111111")
    basis = detail["decision_basis"]

    assert basis["requirement"] == {
        "id": "R1",
        "title": "Explain the result",
        "statement": "Show the exact requirement and why its configured check passed.",
        "state": "attested",
        "state_label": "Passed and recorded",
    }
    assert basis["proposal"]["id"] == "RFP-105"
    assert basis["proposal"]["criterion"]["id"] == "BASIS-1"
    assert basis["verification"]["outcome"] == "passed_and_recorded"
    assert "configured check passed" in basis["verification"]["explanation"]
