"""A granted release invalidates the judges that moved, and nothing else."""

from datetime import datetime, timezone

import pytest

from apatch_studio.lock_authority import LockAuthority, LockAuthorityError

SPEC = "SPEC-DEMO-1"
TENANT = "11111111-1111-4111-8111-111111111111"
ALL = ["R1", "R2", "R3"]


class _Principal:
    def __init__(self, subject, membership):
        self.subject = subject
        self.membership_id = "apsmem_" + membership * 32
        self.tenant_id = TENANT


MANAGER = _Principal("rita@example.test", "a")
TAKER = _Principal("dana@example.test", "b")


def _contract():
    from apatch.sdd_integrity import freeze_contract

    command = ["python3", "-m", "pytest", "tests/demo.py", "-q"]
    from apatch.sdd_integrity import canonical_hash

    obligation = {
        "acceptance_id": "AC-2",
        "test_id": "tests/demo.py",
        "oracle": "the reviewed behaviour holds",
        "perspectives": ["positive", "negative", "boundary", "regression"],
        "asset_hashes": ["sha256:" + "a" * 64],
        "judge_assets": [{"path": "tests/demo.py", "sha256": "sha256:" + "a" * 64}],
        "command": command,
        "command_hash": canonical_hash(command),
        "baseline": {"kind": "observed_red", "result_hash": "sha256:" + "b" * 64},
        "falsification": {
            "kind": "reversible_seed",
            "expected": "red",
            "target_hash": "sha256:" + "c" * 64,
            "target_path": "src/demo.py",
        },
        "approver": "owner:pending",
        "material": True,
    }
    return freeze_contract(
        {
            "brief_hash": "sha256:" + "1" * 64,
            "rfp_hash": "sha256:" + "2" * 64,
            "spec_hash": "sha256:" + "3" * 64,
            "plan_hash": "sha256:" + "4" * 64,
            "baseline_hash": "sha256:" + "5" * 64,
            "coverage": {"complete": True, "missing": [], "ambiguous": [], "waivers": []},
            "obligations": [obligation],
            "authority": {"actor_id": "owner:local", "role": "authority"},
            "source_mutation_count": 0,
        }
    )


def _granted(root):
    authority = LockAuthority(
        root, clock=lambda: datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
    )
    authority.lock_team(SPEC, "R2", set_by=MANAGER, taken_by=TAKER)
    authority.request_release(
        SPEC, "R2", asked_by=TAKER, reason="the frozen test contradicts the agreed scope"
    )
    authority.answer_release(
        SPEC, "R2", answered_by=MANAGER, decision="grant", reason="agreed, the scope moved"
    )
    return authority


def test_only_the_requirement_that_moved_is_invalidated(tmp_path):
    authority = _granted(tmp_path)

    amendment = authority.amendment_for_release(
        SPEC,
        "R2",
        contract=_contract(),
        changed_acceptance_ids=["AC-2"],
        affected_requirements=["R2"],
        all_requirements=ALL,
    )

    assert amendment["invalidated_requirement_ids"] == ["R2"]
    assert amendment["preserved_requirement_ids"] == ["R1", "R3"]
    assert amendment["implementation_actor_may_approve"] is False


def test_the_amendment_carries_the_consent_that_allowed_it(tmp_path):
    authority = _granted(tmp_path)

    amendment = authority.amendment_for_release(
        SPEC,
        "R2",
        contract=_contract(),
        changed_acceptance_ids=["AC-2"],
        affected_requirements=["R2"],
        all_requirements=ALL,
    )

    assert amendment["authority"]["actor_id"] == "rita@example.test"
    assert amendment["reason"] == "agreed, the scope moved"


def test_a_release_nobody_granted_amends_nothing(tmp_path):
    authority = LockAuthority(tmp_path)
    authority.lock_team(SPEC, "R2", set_by=MANAGER, taken_by=TAKER)
    authority.request_release(
        SPEC, "R2", asked_by=TAKER, reason="asking whether this can be lifted"
    )

    with pytest.raises(LockAuthorityError):
        authority.amendment_for_release(
            SPEC,
            "R2",
            contract=_contract(),
            changed_acceptance_ids=["AC-2"],
            affected_requirements=["R2"],
            all_requirements=ALL,
        )


def test_an_amendment_that_invalidates_nothing_is_refused(tmp_path):
    authority = _granted(tmp_path)

    with pytest.raises(LockAuthorityError):
        authority.amendment_for_release(
            SPEC,
            "R2",
            contract=_contract(),
            changed_acceptance_ids=["AC-2"],
            affected_requirements=[],
            all_requirements=ALL,
        )
