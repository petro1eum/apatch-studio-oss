from __future__ import annotations

from datetime import datetime, timezone

import pytest


CHANGE_ID = "apchg_" + "1" * 32
CONTRACT_HASH = "sha256:" + "2" * 64
ENVELOPE_HASH = "sha256:" + "3" * 64
EVIDENCE_HASH = "sha256:" + "4" * 64


@pytest.fixture()
def signer():
    from apatch_studio.delivery_pack import DeliverySigner

    return DeliverySigner.from_seed(
        b"delivery-pack-test-seed-32-byte!"[:32],
        actor_id="owner:test",
        label="Test project owner",
        trust="local-self-signed",
        clock=lambda: datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc),
    )


@pytest.fixture()
def change_detail() -> dict:
    return {
        "schema": "apatch.studio.imported-change-detail.v1",
        "privacy_band": "local_source",
        "change_id": CHANGE_ID,
        "governed_session_id": "apatch_sess_delivery_test",
        "result_kind": "code_change",
        "result_message": "Two files changed and recorded.",
        "objective": "Prevent unauthorized project mutations",
        "status": "proven",
        "created_at": "2026-09-01T10:00:00Z",
        "updated_at": "2026-09-01T11:00:00Z",
        "spec_id": "SPEC-DELIVERY-DEMO",
        "requirement_id": "R4",
        "project": {
            "name": "Delivery demo",
            "repository": "owner/delivery-demo",
            "branch": "main",
            "head": "abc123",
            "operator": "Local Developer",
        },
        "summary": {
            "file_count": 2,
            "insertions": 18,
            "deletions": 4,
            "mutation_count": 3,
            "attestation_count": 1,
            "signed_event_count": 6,
        },
        "files": [{
            "path": "/Users/private/project/secret.py",
            "patch": "--- old secret\n+++ new secret",
        }],
        "events": [{"stdout": "secret command output"}],
        "sdd": {
            "schema": "apatch.studio.sdd-change.v1",
            "available": True,
            "scope": {
                "containment": "mediated_only",
                "allowed": ["Change approved application source"],
                "forbidden": ["Approved tests and frozen contract"],
                "budgets": {"files": 4},
                "violations": [],
                "amendment": {"status": "not_requested"},
            },
            "verification": {
                "capability": "non_mutating",
                "collected": 8,
                "executed": 8,
                "passed": 8,
                "failed": 0,
                "skipped": 0,
                "perspectives": ["positive", "negative", "boundary", "regression"],
                "falsification": {"observed_red": True, "restored_green": True},
                "gate_quality": "meaningful",
                "accepted": True,
                "reasons": [],
                "checks": [{
                    "acceptance_id": "DEL-4",
                    "test_id": "tests/delivery/test_acceptance.py::test_exact_basis",
                    "oracle": "A stale basis cannot be accepted",
                    "perspectives": ["positive", "negative", "boundary", "regression"],
                }],
            },
            "proof": {
                "status": "proven",
                "contract_hash": CONTRACT_HASH,
                "envelope_hash": ENVELOPE_HASH,
                "evidence_hash": EVIDENCE_HASH,
                "adherence": "compliant",
                "actor": "agent:codex",
                "mutation_count": 3,
                "checkpoint_refs": ["checkpoint:1"],
                "ledger_refs": ["op:1"],
            },
            "effort": {
                "derivation": "signed_event_op_spacing",
                "draft_hours": 2.5,
                "quality": "verified_estimate",
                "accepted_time": False,
                "reason": None,
                "signed_event_count": 1,
                "verification": {
                    "ok": True,
                    "status": "verified",
                    "checked": 1,
                    "signed_event_count": 1,
                    "event_ids": ["event-delivery-test"],
                    "key_ids": ["key-delivery-test"],
                    "ledger_drift_count": 0,
                    "unsigned_count": 0,
                },
                "method_note": "Estimate from signed APatch event spacing, not a stopwatch",
            },
        },
    }
