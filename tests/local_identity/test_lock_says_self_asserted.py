"""A lock says whose word the approver's name is on."""

import json
from datetime import datetime, timezone
from pathlib import Path

from apatch_studio.endpoint_enrollment import name_this_machine
from apatch_studio.lock_authority import LockAuthority
from apatch_studio.projection import assert_projection_safe

SPEC = "SPEC-DEMO-1"


def _authority(root):
    return LockAuthority(
        root, clock=lambda: datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
    )


def _enrolled(root, name="issued-laptop"):
    (root / "machine-identity.json").write_text(
        json.dumps(
            {
                "schema": "apatch.studio.machine-identity.v1",
                "machine_name": name,
                "certified": True,
                "key_path": str(root / "agent.key"),
                "certificate_path": str(root / "agent.crt"),
            }
        ),
        encoding="utf-8",
    )


def test_a_self_named_machine_marks_its_lock_as_its_own_word(tmp_path):
    name_this_machine(state_root=tmp_path, hostname="studio-box")
    _authority(tmp_path).lock_solo(SPEC, "R1")

    view = _authority(tmp_path).view(SPEC, "R1")
    assert view["agreed_by"][0]["name"] == "studio-box"
    assert view["agreed_by"][0]["self_asserted"] is True


def test_a_certified_machine_is_not_marked_self_asserted(tmp_path):
    """Otherwise the mark says nothing, because it would be on everything."""

    _enrolled(tmp_path)
    _authority(tmp_path).lock_solo(SPEC, "R1")

    view = _authority(tmp_path).view(SPEC, "R1")
    assert view["agreed_by"][0]["name"] == "issued-laptop"
    assert view["agreed_by"][0]["self_asserted"] is False


def test_the_mark_survives_a_release_exchange(tmp_path):
    name_this_machine(state_root=tmp_path, hostname="studio-box")
    authority = _authority(tmp_path)
    authority.lock_solo(SPEC, "R1")
    authority.request_release(SPEC, "R1", reason="the scope moved under this test")
    authority.answer_release(
        SPEC, "R1", decision="refuse", reason="not until the note is written"
    )

    view = authority.view(SPEC, "R1")
    assert view["agreed_by"][0]["self_asserted"] is True
    assert view["exchanges"][-1]["answer"] == "refuse"


def test_the_view_still_carries_nothing_that_should_not_leave_the_machine(tmp_path):
    name_this_machine(state_root=tmp_path, hostname="studio-box")
    _authority(tmp_path).lock_solo(SPEC, "R1")
    assert_projection_safe(_authority(tmp_path).view(SPEC, "R1"))


def test_the_screen_shows_the_mark_beside_the_approver():
    """A record nobody reads is not a disclosure."""

    view = Path("frontend/src/ProjectPlanView.tsx").read_text(encoding="utf-8")
    types = Path("frontend/src/types.ts").read_text(encoding="utf-8")
    assert "self_asserted" in types, "the screen cannot see the mark"
    parties = view.split("oi-lock-parties", 1)[1].split("</dl>", 1)[0]
    assert "self_asserted" in parties, "the mark is not shown beside the approver"
    assert "Nobody outside it vouched" in parties
