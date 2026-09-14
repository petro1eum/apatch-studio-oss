"""A machine can say which machine it is without anyone else being involved."""

import json

import pytest

from apatch_studio.endpoint_enrollment import (
    default_machine_name,
    name_this_machine,
    stored_identity,
)


def test_naming_needs_no_organization_invitation_or_network(tmp_path, monkeypatch):
    """The platform is not running; the product must still be usable."""

    def _no_network(*_args, **_kwargs):
        raise AssertionError("naming this machine must not reach the network")

    monkeypatch.setattr("socket.socket", _no_network)

    record = name_this_machine(state_root=tmp_path, hostname="Eds-MacBook.local")
    assert record["machine_name"] == "eds-macbook-local"
    assert record["certified"] is False
    assert record["key_path"] is None


def test_the_name_is_read_off_the_machine_not_taken_from_the_caller(tmp_path):
    """A caller who can choose the name can choose to be another machine."""

    with pytest.raises(TypeError):
        name_this_machine(state_root=tmp_path, machine_name="someone-elses-laptop")


def test_a_named_machine_is_readable_afterwards(tmp_path):
    name_this_machine(state_root=tmp_path, hostname="studio-box")

    record = stored_identity(tmp_path)
    assert record is not None
    assert record["machine_name"] == "studio-box"
    assert record["certified"] is False


def test_naming_is_stable_across_calls(tmp_path):
    """One machine keeps one name, or a lock means nothing across a restart."""

    first = name_this_machine(state_root=tmp_path, hostname="studio-box")
    second = name_this_machine(state_root=tmp_path, hostname="studio-box")
    assert first["machine_name"] == second["machine_name"]


def test_an_unusable_hostname_falls_back_rather_than_naming_nothing(tmp_path):
    record = name_this_machine(state_root=tmp_path, hostname="...")
    assert record["machine_name"] == default_machine_name("...")
    assert json.loads((tmp_path / "machine-identity.json").read_text())[
        "machine_name"
    ] == record["machine_name"]
