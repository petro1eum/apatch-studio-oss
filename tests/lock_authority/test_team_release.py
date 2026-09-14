"""In connected work the answer comes from the side that did not ask."""

from datetime import datetime, timezone

import pytest

from apatch_studio.lock_authority import LockAuthority, LockAuthorityError

SPEC = "SPEC-DEMO-1"
TENANT = "11111111-1111-4111-8111-111111111111"


class _Principal:
    def __init__(self, subject, membership, tenant=TENANT):
        self.subject = subject
        self.membership_id = "apsmem_" + membership * 32
        self.tenant_id = tenant


MANAGER = _Principal("rita@example.test", "a")
TAKER = _Principal("dana@example.test", "b")
OUTSIDER = _Principal("sam@example.test", "c")


def _authority(root):
    return LockAuthority(
        root, clock=lambda: datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
    )


def _asked(root, asker):
    authority = _authority(root)
    authority.lock_team(SPEC, "R1", set_by=MANAGER, taken_by=TAKER)
    authority.request_release(
        SPEC, "R1", asked_by=asker, reason="the frozen test contradicts the agreed scope"
    )
    return authority


def test_the_side_that_asked_cannot_also_answer(tmp_path):
    authority = _asked(tmp_path, TAKER)

    with pytest.raises(LockAuthorityError):
        authority.answer_release(
            SPEC, "R1", answered_by=TAKER, decision="grant", reason="I agree with myself"
        )
    assert authority.is_locked(SPEC, "R1") is True


def test_the_side_that_set_the_task_cannot_release_its_own_lock(tmp_path):
    """Seniority is not consent. The manager asks like anybody else."""

    authority = _asked(tmp_path, MANAGER)

    with pytest.raises(LockAuthorityError):
        authority.answer_release(
            SPEC,
            "R1",
            answered_by=MANAGER,
            decision="grant",
            reason="I set this task so I am lifting it",
        )
    assert authority.is_locked(SPEC, "R1") is True


def test_the_other_side_can_answer(tmp_path):
    authority = _asked(tmp_path, TAKER)

    record = authority.answer_release(
        SPEC, "R1", answered_by=MANAGER, decision="grant", reason="agreed, the scope moved"
    )

    assert record["release"]["state"] == "granted"
    assert record["release"]["answer"]["by"]["id"] == "rita@example.test"
    assert authority.is_locked(SPEC, "R1") is False


def test_a_third_person_cannot_answer_for_either_side(tmp_path):
    authority = _asked(tmp_path, TAKER)

    with pytest.raises(LockAuthorityError):
        authority.answer_release(
            SPEC,
            "R1",
            answered_by=OUTSIDER,
            decision="grant",
            reason="I am happy to approve this for them",
        )
    assert authority.is_locked(SPEC, "R1") is True
