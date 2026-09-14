"""A connected lock is made when the task is taken, and names both sides."""

from datetime import datetime, timezone

import pytest

from apatch_studio.lock_authority import LockAuthority, LockAuthorityError

SPEC = "SPEC-DEMO-1"
TENANT = "11111111-1111-4111-8111-111111111111"
OTHER_TENANT = "22222222-2222-4222-8222-222222222222"


class _Principal:
    """The minimal shape of a verified connected person."""

    def __init__(self, subject, membership, tenant=TENANT):
        self.subject = subject
        self.membership_id = "apsmem_" + membership * 32
        self.tenant_id = tenant


MANAGER = _Principal("rita@example.test", "a")
TAKER = _Principal("dana@example.test", "b")


def _authority(root):
    return LockAuthority(
        root, clock=lambda: datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
    )


def test_both_sides_are_on_the_record(tmp_path):
    record = _authority(tmp_path).lock_team(
        SPEC, "R1", set_by=MANAGER, taken_by=TAKER
    )

    assert record["edition"] == "cowork"
    assert record["approved_by_a_person"] is True
    roles = {party["role"]: party for party in record["parties"]}
    assert set(roles) == {"set_by", "taken_by"}
    assert roles["set_by"]["id"] == "rita@example.test"
    assert roles["taken_by"]["id"] == "dana@example.test"
    assert all(party["is_person"] for party in record["parties"])


def test_a_name_is_not_a_side(tmp_path):
    with pytest.raises(LockAuthorityError):
        _authority(tmp_path).lock_team(
            SPEC, "R1", set_by="rita", taken_by=TAKER
        )


def test_one_person_cannot_be_both_sides(tmp_path):
    with pytest.raises(LockAuthorityError):
        _authority(tmp_path).lock_team(
            SPEC, "R1", set_by=MANAGER, taken_by=MANAGER
        )


def test_sides_from_different_organizations_are_refused(tmp_path):
    outsider = _Principal("sam@example.test", "c", tenant=OTHER_TENANT)
    with pytest.raises(LockAuthorityError):
        _authority(tmp_path).lock_team(
            SPEC, "R1", set_by=MANAGER, taken_by=outsider
        )


def test_taking_a_task_after_the_code_exists_is_refused(tmp_path):
    with pytest.raises(LockAuthorityError):
        _authority(tmp_path).lock_team(
            SPEC,
            "R1",
            set_by=MANAGER,
            taken_by=TAKER,
            source_changed_at="2026-09-04T11:00:00+00:00",
        )
    assert LockAuthority(tmp_path).read(SPEC, "R1") is None
