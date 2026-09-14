"""A lock whose record vanished is broken, and never merely absent."""

import json
from datetime import datetime, timezone

from apatch_studio.lock_authority import LockAuthority

SPEC = "SPEC-DEMO-1"
TENANT = "11111111-1111-4111-8111-111111111111"


class _Principal:
    def __init__(self, subject, membership):
        self.subject = subject
        self.membership_id = "apsmem_" + membership * 32
        self.tenant_id = TENANT


MANAGER = _Principal("rita@example.test", "a")
TAKER = _Principal("dana@example.test", "b")


def _authority(root):
    return LockAuthority(
        root, clock=lambda: datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
    )


def _delete_the_lock(root, requirement="R1"):
    (root / "locks" / SPEC / f"{requirement}.json").unlink()


def test_a_requirement_nobody_locked_reads_as_unlocked(tmp_path):
    assert _authority(tmp_path).status(SPEC, "R1")["state"] == "unlocked"


def test_a_lock_that_holds_says_so(tmp_path):
    authority = _authority(tmp_path)
    authority.lock_team(SPEC, "R1", set_by=MANAGER, taken_by=TAKER)

    status = authority.status(SPEC, "R1")
    assert status["state"] == "locked"
    assert len(status["parties"]) == 2


def test_a_deleted_lock_is_broken_not_absent(tmp_path):
    authority = _authority(tmp_path)
    authority.lock_team(SPEC, "R1", set_by=MANAGER, taken_by=TAKER)
    _delete_the_lock(tmp_path)

    status = authority.status(SPEC, "R1")
    assert status["state"] == "broken"
    assert status["missing"].endswith("R1.json")
    assert "nothing released it" in status["headline"]


def test_a_granted_release_explains_the_absence(tmp_path):
    authority = _authority(tmp_path)
    authority.lock_team(SPEC, "R1", set_by=MANAGER, taken_by=TAKER)
    authority.request_release(
        SPEC, "R1", asked_by=TAKER, reason="the frozen test contradicts the scope"
    )
    authority.answer_release(
        SPEC, "R1", answered_by=MANAGER, decision="grant", reason="agreed, it moved"
    )
    _delete_the_lock(tmp_path)

    assert authority.status(SPEC, "R1")["state"] == "released"


def test_a_refused_release_does_not_excuse_a_deletion(tmp_path):
    """Being told no is not permission to remove the boundary by hand."""

    authority = _authority(tmp_path)
    authority.lock_team(SPEC, "R1", set_by=MANAGER, taken_by=TAKER)
    authority.request_release(
        SPEC, "R1", asked_by=TAKER, reason="I would like this boundary lifted"
    )
    authority.answer_release(
        SPEC, "R1", answered_by=MANAGER, decision="refuse", reason="no, the scope stands"
    )
    _delete_the_lock(tmp_path)

    assert authority.status(SPEC, "R1")["state"] == "broken"


def test_a_lock_awaiting_an_answer_says_that_instead(tmp_path):
    authority = _authority(tmp_path)
    authority.lock_team(SPEC, "R1", set_by=MANAGER, taken_by=TAKER)
    authority.request_release(
        SPEC, "R1", asked_by=TAKER, reason="the frozen test contradicts the scope"
    )

    assert authority.status(SPEC, "R1")["state"] == "awaiting_answer"
