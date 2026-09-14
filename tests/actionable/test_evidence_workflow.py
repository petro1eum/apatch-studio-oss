from pathlib import Path

import pytest
from pydantic import ValidationError

from apatch_studio.action_facade import EvidenceActionRequest, StudioWorkflowFacade


def test_evidence_requests_are_bounded_and_ratify_requires_exact_requirement():
    with pytest.raises(ValidationError):
        EvidenceActionRequest(
            request_id="apsreq_evidence_bad_001",
            action="ratify",
            artifact="spec:SPEC-DEMO-1",
        )
    with pytest.raises(ValidationError):
        EvidenceActionRequest.model_validate(
            {
                "request_id": "apsreq_evidence_bad_002",
                "action": "verify",
                "verify": "rm -rf .",
            }
        )
    request = EvidenceActionRequest(
        request_id="apsreq_evidence_ratify_001",
        action="ratify",
        artifact="spec:SPEC-DEMO-1#R2",
    )
    assert request.artifact == "spec:SPEC-DEMO-1#R2"


def test_ratify_derives_the_gate_from_apatch_spec(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr(
        "apatch_studio.action_facade.spec_status_workspace",
        lambda root, spec: {
            "requirements": [{"id": "R2", "verify": "python3 -m pytest tests/test_demo.py -q"}]
        },
    )

    def fake_ratify(root, verify):
        captured["verify"] = verify
        return {"verdict": "ratified", "current_rc": 0, "new_failures": []}

    monkeypatch.setattr("apatch_studio.action_facade.ratify", fake_ratify)
    receipt = StudioWorkflowFacade(tmp_path).evidence_action(
        EvidenceActionRequest(
            request_id="apsreq_evidence_ratify_002",
            action="ratify",
            artifact="spec:SPEC-DEMO-1#R2",
        )
    )
    assert receipt["result"]["ok"] is True
    assert captured["verify"] == "python3 -m pytest tests/test_demo.py -q"


def test_inclusion_failure_is_projected_without_proof_payload(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "apatch_studio.action_facade.verify_inclusion",
        lambda root: {
            "ok": False,
            "checked": 3,
            "verified": 2,
            "missing": ["op_secret"],
            "inconsistent": [],
            "errors": [],
        },
    )
    receipt = StudioWorkflowFacade(tmp_path).evidence_action(
        EvidenceActionRequest(request_id="apsreq_evidence_include_001", action="inclusion")
    )
    assert receipt["status"] == "attention"
    assert receipt["result"]["missing_count"] == 1
    assert "op_secret" not in str(receipt)


def test_evidence_ui_exposes_verification_and_recovery_actions():
    root = Path(__file__).resolve().parents[2]
    app = (root / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
    api = (root / "frontend/src/api.ts").read_text(encoding="utf-8")
    for label in [
        "View history", "Verify proof", "Check coverage",
        "Independent log check", "Check source state", "Re-check policy gate", "Export",
    ]:
        assert label in app
    assert "runEvidenceAction" in api
    assert "runEvidenceAction(action, artifact || null)" in app
