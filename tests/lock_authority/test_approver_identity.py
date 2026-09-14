"""The name on an approval is resolved by the product, never sent by the caller."""

import json
from pathlib import Path

import pytest

from apatch_studio.lock_authority import LockAuthorityError, approver_for


class _Principal:
    """The minimal shape of a verified connected person."""

    def __init__(self, subject="dana@example.test"):
        self.subject = subject
        self.membership_id = "apsmem_" + "a" * 32
        self.tenant_id = "11111111-1111-4111-8111-111111111111"


def _enrol(root: Path, name: str = "studio-laptop") -> None:
    (root / "machine-identity.json").write_text(
        json.dumps(
            {
                "schema": "apatch.studio.machine-identity.v1",
                "machine_name": name,
                "key_path": str(root / "agent.key"),
                "certificate_path": str(root / "agent.crt"),
            }
        ),
        encoding="utf-8",
    )


def test_a_name_from_the_caller_is_not_an_identity(tmp_path):
    """The old interface sent this literal for every approval anyone ever made."""

    _enrol(tmp_path)
    for supplied in ("owner:local", "owner", "local owner", "anyone at all"):
        with pytest.raises(LockAuthorityError):
            approver_for(tmp_path, principal=supplied)


def test_a_workspace_that_can_name_nobody_cannot_approve(tmp_path):
    with pytest.raises(LockAuthorityError):
        approver_for(tmp_path)


def test_an_enrolled_machine_is_named_and_is_not_claimed_to_be_a_person(tmp_path):
    _enrol(tmp_path)
    party = approver_for(tmp_path)
    assert party["kind"] == "machine"
    assert party["id"] == "studio-laptop"
    assert party["is_person"] is False


def test_a_signed_in_person_is_named_with_their_membership(tmp_path):
    party = approver_for(tmp_path, principal=_Principal())
    assert party["kind"] == "person"
    assert party["id"] == "dana@example.test"
    assert party["is_person"] is True
    assert party["membership_id"].startswith("apsmem_")


def test_a_placeholder_person_is_refused(tmp_path):
    """A principal can exist and still name nobody who could be held to anything."""

    with pytest.raises(LockAuthorityError):
        approver_for(tmp_path, principal=_Principal(subject="owner:local"))


def test_an_enrolment_that_names_nothing_is_refused(tmp_path):
    _enrol(tmp_path, name="unknown")
    with pytest.raises(LockAuthorityError):
        approver_for(tmp_path)


FREEZE = "/api/v1/specs/SPEC-DEMO-1/requirements/R1/execution-contract/freeze"
APPROVAL = {"request_id": "apsreq_freeze_" + "1" * 32, "confirmed": True,
            "snapshot": "sha256:" + "1" * 64}


def _client(workspace: Path):
    """The running product, not the module underneath it."""

    from fastapi.testclient import TestClient

    from apatch_studio.app import create_app

    (workspace / ".git").mkdir()
    (workspace / ".apatch").mkdir(exist_ok=True)
    app = create_app(
        str(workspace), frontend_root=workspace, identity_root=workspace / ".apatch"
    )
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    return client, {
        "x-apatch-studio-session": app.state.studio_guard.token,
        "origin": "http://127.0.0.1:8765",
    }


def test_the_approval_request_has_nowhere_to_put_a_name(tmp_path):
    """A field the caller may fill is a name the caller chose.

    The interface used to send owner:local here, identically, for everyone.
    """

    client, headers = _client(tmp_path)
    response = client.post(
        FREEZE, headers=headers, json={**APPROVAL, "owner_actor_id": "owner:local"}
    )
    assert response.status_code == 422


def test_a_workspace_that_can_name_nobody_never_reaches_the_contract(tmp_path):
    """Identity is settled first, so the refusal is about who, not about what."""

    client, headers = _client(tmp_path)
    response = client.post(FREEZE, headers=headers, json=APPROVAL)
    body = response.json()
    assert response.status_code == 422
    assert body["error_code"] == "lock_approver_unknown"
    assert "enrol" in body["error"].lower()


def test_a_named_machine_gets_past_identity_and_on_to_the_contract(tmp_path):
    """With somebody to name, the approval fails on the contract instead."""

    (tmp_path / ".apatch").mkdir()
    _enrol(tmp_path / ".apatch")
    client, headers = _client(tmp_path)
    response = client.post(FREEZE, headers=headers, json=APPROVAL)
    assert response.json()["error_code"] == "sdd_contract_not_prepared"


def test_the_identity_is_read_where_enrolling_puts_it(tmp_path):
    """Enrolling writes to the machine's own state, not into the workspace.

    Looking for it in the workspace told an enrolled machine that it could name
    nobody, so no workspace but the one that happened to hold a copy could ever
    approve anything.
    """

    from fastapi.testclient import TestClient

    from apatch_studio.app import create_app

    workspace = tmp_path / "work"
    machine = tmp_path / "machine-state"
    (workspace / ".git").mkdir(parents=True)
    (workspace / ".apatch").mkdir()
    machine.mkdir()
    _enrol(machine, name="studio-laptop")

    app = create_app(
        str(workspace), frontend_root=workspace, identity_root=machine
    )
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    headers = {
        "x-apatch-studio-session": app.state.studio_guard.token,
        "origin": "http://127.0.0.1:8765",
    }

    response = client.post(FREEZE, headers=headers, json=APPROVAL)
    assert response.json()["error_code"] == "sdd_contract_not_prepared"
    assert app.state.lock_authority.identity_root == machine.resolve()
