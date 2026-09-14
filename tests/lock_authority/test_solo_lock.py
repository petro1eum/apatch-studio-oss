"""OSS locks name the machine that approved, and never imply a person did."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from apatch_studio.lock_authority import LockAuthority, LockAuthorityError

SPEC = "SPEC-DEMO-1"


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


def test_the_record_names_the_machine_and_denies_being_a_person(tmp_path):
    _enrol(tmp_path)
    record = _authority(tmp_path).lock_solo(SPEC, "R1")

    assert record["edition"] == "oss"
    assert record["approved_by_a_person"] is False
    assert [party["role"] for party in record["parties"]] == ["approver"]
    approver = record["parties"][0]
    assert approver["kind"] == "machine"
    assert approver["id"] == "studio-laptop"
    assert approver["is_person"] is False


def test_the_lock_survives_and_reads_back(tmp_path):
    _enrol(tmp_path)
    authority = _authority(tmp_path)
    written = authority.lock_solo(SPEC, "R1")
    assert LockAuthority(tmp_path).read(SPEC, "R1") == written


def test_approval_after_source_work_is_refused(tmp_path):
    """Approving a boundary after the code exists approves the code, not the boundary."""

    _enrol(tmp_path)
    with pytest.raises(LockAuthorityError):
        _authority(tmp_path).lock_solo(
            SPEC, "R1", source_changed_at="2026-09-04T11:00:00+00:00"
        )
    assert LockAuthority(tmp_path).read(SPEC, "R1") is None


def test_locking_twice_is_refused_rather_than_silently_replacing(tmp_path):
    _enrol(tmp_path)
    authority = _authority(tmp_path)
    authority.lock_solo(SPEC, "R1")
    with pytest.raises(LockAuthorityError):
        authority.lock_solo(SPEC, "R1")


def test_an_unenrolled_machine_cannot_lock(tmp_path):
    with pytest.raises(LockAuthorityError):
        _authority(tmp_path).lock_solo(SPEC, "R1")


APPROVAL = {"request_id": "apsreq_freeze_" + "1" * 32, "confirmed": True,
            "snapshot": "sha256:" + "1" * 64}
FREEZE = f"/api/v1/specs/{SPEC}/requirements/R1/execution-contract/freeze"
LOOK = f"/api/v1/specs/{SPEC}/requirements/R1/lock"


class _Facade:
    """Stands in for the contract machinery, which this requirement is not about."""

    def __init__(self, *, refuse=False):
        self.refuse = refuse
        self.calls = []

    def freeze_requirement(self, spec_id, requirement_id, **kwargs):
        self.calls.append((spec_id, requirement_id, kwargs))
        if self.refuse:
            from apatch_studio.sdd_workflow import SddWorkflowError

            raise SddWorkflowError(
                "nothing is prepared here",
                code="sdd_contract_not_prepared",
                status_code=409,
            )
        return {"status": "frozen", "owner_actor_id": kwargs.get("owner_actor_id")}

    def requirement_status(self, *_args, **_kwargs):
        return {"status": "not_prepared"}

    def contract_review(self, *_args, **_kwargs):
        return {"status": "frozen"}


def _client(workspace: Path, facade):
    from fastapi.testclient import TestClient

    from apatch_studio.app import create_app

    (workspace / ".git").mkdir()
    (workspace / ".apatch").mkdir(exist_ok=True)
    app = create_app(
        str(workspace),
        sdd_facade=facade,
        frontend_root=workspace,
        identity_root=workspace / ".apatch",
    )
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    return client, {
        "x-apatch-studio-session": app.state.studio_guard.token,
        "origin": "http://127.0.0.1:8765",
    }


def test_approving_in_the_product_records_the_machine_that_approved(tmp_path):
    """The lock the screen shows is the lock the approval actually set."""

    (tmp_path / ".apatch").mkdir()
    _enrol(tmp_path / ".apatch")
    facade = _Facade()
    client, headers = _client(tmp_path, facade)

    assert client.get(LOOK, headers=headers).json()["state"] == "unlocked"
    approved = client.post(FREEZE, headers=headers, json=APPROVAL)
    assert approved.status_code == 200
    assert facade.calls[0][2]["owner_actor_id"] == "studio-laptop"

    view = client.get(LOOK, headers=headers).json()
    assert view["state"] == "locked"
    assert [party["name"] for party in view["agreed_by"]] == ["studio-laptop"]
    assert view["approved_by_a_person"] is False


def test_an_approval_that_did_not_take_leaves_no_lock_behind(tmp_path):
    """A lock over a contract that was never frozen would read as a broken one."""

    (tmp_path / ".apatch").mkdir()
    _enrol(tmp_path / ".apatch")
    client, headers = _client(tmp_path, _Facade(refuse=True))

    assert client.post(FREEZE, headers=headers, json=APPROVAL).status_code == 409
    assert client.get(LOOK, headers=headers).json()["state"] == "unlocked"


def test_approving_twice_does_not_disturb_the_lock_already_recorded(tmp_path):
    """The interface can send the same approval twice; the record has one lock."""

    (tmp_path / ".apatch").mkdir()
    _enrol(tmp_path / ".apatch")
    client, headers = _client(tmp_path, _Facade())

    client.post(FREEZE, headers=headers, json=APPROVAL)
    first = client.get(LOOK, headers=headers).json()
    client.post(FREEZE, headers=headers, json=APPROVAL)
    assert client.get(LOOK, headers=headers).json() == first
