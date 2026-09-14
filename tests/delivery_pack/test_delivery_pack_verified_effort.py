from __future__ import annotations

import base64
import hashlib
import json
from copy import deepcopy

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from apatch_studio.delivery_pack import (
    AcceptedTimeDecisionRequest,
    DeliveryPackError,
    DeliveryPackWorkflow,
)
from apatch_studio.sdd_workflow import APatchSddFacts


def _rows(session_id: str, *, insertions: int = 5) -> list[dict]:
    return [
        {
            "id": "op_exact",
            "timestamp": 1788280000.0,
            "payload": {
                "governed_session_id": session_id,
                "files": {"src/exact.py": "sha256:" + "1" * 64},
                "insertions": insertions,
                "deletions": 1,
            },
        }
    ]


def _signed_event(
    session_id: str,
    *,
    duration_sec: float = 900.0,
    insertions: int = 5,
) -> dict:
    private_key = Ed25519PrivateKey.from_private_bytes(bytes([0x19]) * 32)
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    event = {
        "schema_version": 3,
        "kind": "fact",
        "event_id": hashlib.sha256(session_id.encode("utf-8")).hexdigest()[:32],
        "trust_level": "attested",
        "identity": {
            "key_id": hashlib.sha256(public_key).hexdigest()[:32],
            "public_key": base64.b64encode(public_key).decode("ascii"),
        },
        "project": {"id": "project-exact-session"},
        "session": {
            "session_id": session_id,
            "artifacts": ["spec:SPEC-EXACT#R5"],
            "started_at": "2026-09-01T10:00:00+00:00",
            "ended_at": "2026-09-01T10:15:00+00:00",
            "duration_sec": duration_sec,
        },
        "volume": {
            "ops": 1,
            "files_touched": 1,
            "insertions": insertions,
            "deletions": 1,
        },
        "proof_ref": {"op_ids": ["op_exact"], "head": "op_exact"},
    }
    canonical = json.dumps(
        event,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    event["signature"] = base64.b64encode(private_key.sign(canonical)).decode("ascii")
    return event


def _install_events(monkeypatch, events: list[dict], *, ledger_insertions: int = 5) -> None:
    import apatch.timesheet as timesheet

    monkeypatch.setattr(timesheet, "load_events", lambda _store=None: events)
    monkeypatch.setattr(
        timesheet,
        "_ledger_rows_for_session",
        lambda _root, session_id: _rows(
            session_id,
            insertions=ledger_insertions,
        ),
    )


def test_effort_is_bound_to_one_exact_governed_session(tmp_path, monkeypatch) -> None:
    exact = _signed_event("apatch_sess_exact", duration_sec=900.0)
    foreign = _signed_event("apatch_sess_foreign", duration_sec=7200.0)
    _install_events(monkeypatch, [foreign, exact])

    effort = APatchSddFacts(tmp_path)._effort("apatch_sess_exact")

    assert effort["derivation"] == "signed_event_op_spacing"
    assert effort["draft_hours"] == 0.25
    assert effort["quality"] == "verified_estimate"
    assert effort["reason"] is None
    assert effort["signed_event_count"] == 1
    assert effort["verification"] == {
        "ok": True,
        "status": "verified",
        "checked": 1,
        "signed_event_count": 1,
        "event_ids": [exact["event_id"]],
        "key_ids": [exact["identity"]["key_id"]],
        "ledger_drift_count": 0,
        "unsigned_count": 0,
    }


@pytest.mark.parametrize(
    ("events", "reason", "status"),
    [
        ([], "signed_event_missing", "missing"),
        (
            [{**_signed_event("apatch_sess_exact"), "signature": None}],
            "signed_event_unsigned",
            "unsigned",
        ),
    ],
)
def test_missing_or_unsigned_event_is_not_a_time_draft(
    tmp_path,
    monkeypatch,
    events,
    reason,
    status,
) -> None:
    _install_events(monkeypatch, events)

    effort = APatchSddFacts(tmp_path)._effort("apatch_sess_exact")

    assert effort["derivation"] == "unavailable"
    assert effort["draft_hours"] is None
    assert effort["reason"] == reason
    assert effort["signed_event_count"] == 0
    assert effort["verification"]["ok"] is False
    assert effort["verification"]["status"] == status


def test_invalid_signature_is_not_a_time_draft(tmp_path, monkeypatch) -> None:
    event = _signed_event("apatch_sess_exact")
    event["volume"]["insertions"] = 6
    _install_events(monkeypatch, [event], ledger_insertions=6)

    effort = APatchSddFacts(tmp_path)._effort("apatch_sess_exact")

    assert effort["reason"] == "signed_event_signature_invalid"
    assert effort["verification"]["status"] == "signature_invalid"


def test_ledger_drift_is_not_a_time_draft(tmp_path, monkeypatch) -> None:
    event = _signed_event("apatch_sess_exact")
    _install_events(monkeypatch, [event], ledger_insertions=0)

    effort = APatchSddFacts(tmp_path)._effort("apatch_sess_exact")

    assert effort["reason"] == "signed_event_ledger_drift"
    assert effort["verification"]["status"] == "ledger_drift"
    assert effort["verification"]["ledger_drift_count"] == 1


def test_delivery_pack_and_time_decision_fail_closed_on_unverified_effort(
    tmp_path,
    signer,
    change_detail,
) -> None:
    detail = deepcopy(change_detail)
    detail["sdd"]["effort"]["verification"] = {
        "ok": False,
        "status": "ledger_drift",
        "checked": 1,
        "signed_event_count": 1,
        "event_ids": ["event-drifted"],
        "key_ids": ["key-drifted"],
        "ledger_drift_count": 1,
        "unsigned_count": 0,
    }
    detail["sdd"]["effort"]["reason"] = "signed_event_ledger_drift"
    workflow = DeliveryPackWorkflow(tmp_path, signer=signer)
    pack = workflow.project(detail)

    assert pack["effort"]["available"] is False
    assert pack["effort"]["draft_hours"] is None
    assert pack["effort"]["reason"] == "signed_event_ledger_drift"
    assert pack["effort"]["verification"]["status"] == "ledger_drift"

    with pytest.raises(DeliveryPackError) as captured:
        workflow.record_time_decision(
            detail,
            AcceptedTimeDecisionRequest(
                request_id="apsreq_unverified_effort",
                decision="accepted",
                expected_basis_hash=pack["basis_hash"],
                expected_effort_hash=pack["effort"]["effort_hash"],
                accepted_hours=0.25,
                confirmed=True,
            ),
        )

    assert captured.value.code == "delivery_effort_unavailable"
