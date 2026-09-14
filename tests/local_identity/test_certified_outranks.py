"""A name an organization issued always beats one this machine gave itself."""

import json

import pytest

from apatch_studio.endpoint_enrollment import name_this_machine, stored_identity
from apatch_studio.endpoint_identity import endpoint_identity_status
from apatch_studio.lock_authority import approver_for

EPHEMERAL = {"level": "ephemeral", "secure": False, "agent_id": None, "has_cert": False}
CERTIFIED = {
    "level": "ca-issued",
    "secure": True,
    "agent_id": "issued-laptop",
    "has_cert": True,
}


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


def test_naming_an_enrolled_machine_is_refused(tmp_path):
    """Silently demoting a checkable name to an unverifiable one is the worst case."""

    _enrolled(tmp_path)
    with pytest.raises(ValueError):
        name_this_machine(state_root=tmp_path)

    assert stored_identity(tmp_path)["machine_name"] == "issued-laptop"
    assert stored_identity(tmp_path)["certified"] is True


def test_the_enrolment_record_survives_the_refusal_untouched(tmp_path):
    _enrolled(tmp_path)
    before = (tmp_path / "machine-identity.json").read_bytes()
    with pytest.raises(ValueError):
        name_this_machine(state_root=tmp_path)
    assert (tmp_path / "machine-identity.json").read_bytes() == before


def test_a_certified_anchor_wins_over_a_self_named_record(tmp_path):
    """Both can exist at once; only one may be reported."""

    name_this_machine(state_root=tmp_path, hostname="studio-box")
    status = endpoint_identity_status(
        str(tmp_path), status_provider=lambda _w: CERTIFIED, state_root=str(tmp_path)
    )
    assert status["certified"] is True
    assert status["self_named"] is False
    assert status["machine_name"] == "issued-laptop"


def test_a_self_named_machine_still_approves(tmp_path):
    """Outranked is not unusable; the product must work with no organization."""

    name_this_machine(state_root=tmp_path, hostname="studio-box")
    party = approver_for(tmp_path)
    assert party["id"] == "studio-box"
    assert party["is_person"] is False


def test_a_new_enrolment_replaces_a_self_asserted_name(tmp_path):
    """Going the other way is an upgrade, and must not be blocked."""

    name_this_machine(state_root=tmp_path, hostname="studio-box")
    _enrolled(tmp_path)
    record = stored_identity(tmp_path)
    assert record["certified"] is True
    assert record["machine_name"] == "issued-laptop"
