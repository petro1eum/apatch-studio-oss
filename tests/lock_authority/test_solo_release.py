"""A one-sided release says it is one-sided instead of looking like agreement."""

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


def _enrol(root, name="studio-laptop"):
    (root / "machine-identity.json").write_text(
        json.dumps(
            {
                "schema": "apatch.studio.machine-identity.v1",
                "machine_name": name,
                "key_path": str(root / "agent.key"),
            }
        ),
        encoding="utf-8",
    )


def _authority(root):
    return LockAuthority(
        root, clock=lambda: datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
    )


def test_the_single_user_may_release_and_the_record_says_it_was_one_sided(tmp_path):
    _enrol(tmp_path)
    authority = _authority(tmp_path)
    authority.lock_solo(SPEC, "R1")

    authority.request_release(SPEC, "R1", reason="the scope I agreed no longer fits")
    record = authority.answer_release(
        SPEC, "R1", decision="grant", reason="lifting it, the requirement changed"
    )

    release = record["release"]
    assert release["one_sided"] is True
    assert release["two_sided"] is False
    assert release["state"] == "granted"
    assert release["reason"]
    assert release["answer"]["reason"]
    assert authority.is_locked(SPEC, "R1") is False


def test_a_one_sided_release_is_distinguishable_from_a_two_sided_one(tmp_path):
    """Both are legitimate. Reading one as the other is not."""

    _enrol(tmp_path)
    solo = _authority(tmp_path)
    solo.lock_solo(SPEC, "R1")
    solo.request_release(SPEC, "R1", reason="the scope I agreed no longer fits")
    solo.answer_release(SPEC, "R1", decision="grant", reason="lifting it myself")

    team = _authority(tmp_path)
    team.lock_team(
        SPEC,
        "R2",
        set_by=_Principal("rita@example.test", "a"),
        taken_by=_Principal("dana@example.test", "b"),
    )
    team.request_release(
        SPEC, "R2", asked_by=_Principal("dana@example.test", "b"), reason="the scope moved"
    )
    team.answer_release(
        SPEC,
        "R2",
        answered_by=_Principal("rita@example.test", "a"),
        decision="grant",
        reason="agreed, it did move",
    )

    assert solo.read(SPEC, "R1")["release"]["one_sided"] is True
    assert team.read(SPEC, "R2")["release"]["one_sided"] is False


def test_a_one_sided_refusal_is_recorded_too(tmp_path):
    _enrol(tmp_path)
    authority = _authority(tmp_path)
    authority.lock_solo(SPEC, "R1")
    authority.request_release(SPEC, "R1", reason="wondering whether to lift this")
    record = authority.answer_release(
        SPEC, "R1", decision="refuse", reason="on reflection the boundary was right"
    )

    assert record["release"]["state"] == "refused"
    assert record["release"]["one_sided"] is True
    assert authority.is_locked(SPEC, "R1") is True
