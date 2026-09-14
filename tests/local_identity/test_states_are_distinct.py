"""Certified, self-named and nothing at all are three answers, never two."""

import inspect
import json

from apatch_studio.endpoint_enrollment import name_this_machine
from apatch_studio.endpoint_identity import endpoint_identity_status
from apatch_studio.projection import assert_projection_safe

EPHEMERAL = {"level": "ephemeral", "secure": False, "agent_id": None, "has_cert": False}
CERTIFIED = {
    "level": "ca-issued",
    "secure": True,
    "agent_id": "issued-laptop",
    "has_cert": True,
}


def _status(tmp_path, anchor):
    return endpoint_identity_status(
        str(tmp_path), status_provider=lambda _w: anchor, state_root=str(tmp_path)
    )


def test_a_machine_that_named_itself_is_reported_as_exactly_that(tmp_path):
    name_this_machine(state_root=tmp_path, hostname="studio-box")

    status = _status(tmp_path, EPHEMERAL)
    assert status["self_named"] is True
    assert status["certified"] is False
    assert status["enrolled"] is False
    assert status["machine_name"] == "studio-box"


def test_a_self_named_machine_never_wears_the_words_of_a_certified_one(tmp_path):
    """The weaker answer must not be readable as the stronger one."""

    name_this_machine(state_root=tmp_path, hostname="studio-box")
    self_named = _status(tmp_path, EPHEMERAL)
    certified = endpoint_identity_status(
        str(tmp_path), status_provider=lambda _w: CERTIFIED, state_root=str(tmp_path)
    )

    assert self_named["headline"] != certified["headline"]
    assert self_named["explanation"] != certified["explanation"]
    words = self_named["headline"] + " " + self_named["explanation"]
    for claim in ("certified", "verifiable", "your organization issued"):
        assert claim not in words.lower(), f"a self-named machine claims to be {claim}"
    assert "nobody outside it vouched" in self_named["explanation"]


def test_nothing_at_all_stays_distinct_from_a_name(tmp_path):
    status = _status(tmp_path, EPHEMERAL)
    assert status["self_named"] is False
    assert status["machine_name"] is None
    assert "temporary key" in status["headline"].lower()


def test_the_report_carries_nothing_that_should_not_leave_the_machine(tmp_path):
    name_this_machine(state_root=tmp_path, hostname="studio-box")
    assert_projection_safe(_status(tmp_path, EPHEMERAL))


def test_the_workspace_overview_carries_the_three_states(tmp_path):
    """The place people actually read this must not flatten it back to two."""

    from apatch_studio.adapter import APatchStudioAdapter

    projected = inspect.getsource(APatchStudioAdapter)
    assert "endpoint_identity_status" in projected
    status = _status(tmp_path, EPHEMERAL)
    assert set(("enrolled", "self_named", "certified")) <= set(status)


def test_the_startup_banner_says_which_of_the_three_it_is(tmp_path):
    """An operator reads this line before anything else about the machine."""

    from apatch_studio import cli

    banner = inspect.getsource(cli.serve)
    assert "identity['headline']" in banner or 'identity["headline"]' in banner
    name_this_machine(state_root=tmp_path, hostname="studio-box")
    assert _status(tmp_path, EPHEMERAL)["headline"] == "This machine named itself"


def test_the_report_never_reads_this_machine_when_a_state_root_is_given(tmp_path):
    """A judge that describes a machine must not consult a different one.

    Reading the real machine by default made an existing test describe whatever
    name this laptop happened to hold, which is how the regression surfaced.
    """

    name_this_machine(state_root=tmp_path, hostname="studio-box")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    assert _status(elsewhere, EPHEMERAL)["self_named"] is False
    assert _status(elsewhere, EPHEMERAL)["machine_name"] is None
    assert _status(tmp_path, EPHEMERAL)["machine_name"] == "studio-box"


def test_a_damaged_record_reads_as_no_name_rather_than_a_name(tmp_path):
    """Failing closed here means claiming less, never more."""

    (tmp_path / "machine-identity.json").write_text("{not json", encoding="utf-8")
    assert _status(tmp_path, EPHEMERAL)["self_named"] is False

    (tmp_path / "machine-identity.json").write_text(
        json.dumps({"schema": "apatch.studio.machine-identity.v1", "certified": False}),
        encoding="utf-8",
    )
    assert _status(tmp_path, EPHEMERAL)["self_named"] is False
