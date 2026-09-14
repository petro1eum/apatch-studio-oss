"""Asking for a lock to be lifted is not lifting it."""

import json
from datetime import datetime, timezone
from pathlib import Path

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


def test_the_lock_still_stands_while_the_answer_is_awaited(tmp_path):
    authority = _authority(tmp_path)
    authority.lock_team(SPEC, "R1", set_by=MANAGER, taken_by=TAKER)

    record = authority.request_release(
        SPEC, "R1", asked_by=TAKER, reason="the frozen test contradicts the agreed scope"
    )

    assert record["release"]["state"] == "awaiting_answer"
    assert record["release"]["asked_by"]["id"] == "dana@example.test"
    assert record["release"]["answer"] is None
    assert authority.is_locked(SPEC, "R1") is True


def test_a_request_carries_a_reason_somebody_can_weigh(tmp_path):
    authority = _authority(tmp_path)
    authority.lock_team(SPEC, "R1", set_by=MANAGER, taken_by=TAKER)

    for empty in ("", "   ", "ok", "because"):
        with pytest.raises(LockAuthorityError):
            authority.request_release(SPEC, "R1", asked_by=TAKER, reason=empty)


def test_somebody_who_is_not_on_the_lock_cannot_ask(tmp_path):
    authority = _authority(tmp_path)
    authority.lock_team(SPEC, "R1", set_by=MANAGER, taken_by=TAKER)

    with pytest.raises(LockAuthorityError):
        authority.request_release(
            SPEC, "R1", asked_by=OUTSIDER, reason="I would like this lifted please"
        )


def test_a_second_request_cannot_jump_an_unanswered_one(tmp_path):
    authority = _authority(tmp_path)
    authority.lock_team(SPEC, "R1", set_by=MANAGER, taken_by=TAKER)
    authority.request_release(
        SPEC, "R1", asked_by=TAKER, reason="the frozen test contradicts the scope"
    )

    with pytest.raises(LockAuthorityError):
        authority.request_release(
            SPEC, "R1", asked_by=MANAGER, reason="changed my mind about the scope"
        )


def test_there_must_be_a_lock_to_ask_about(tmp_path):
    _enrol(tmp_path)
    with pytest.raises(LockAuthorityError):
        _authority(tmp_path).request_release(
            SPEC, "R1", reason="nothing is locked here at all"
        )


APPROVAL = {"request_id": "apsreq_freeze_" + "1" * 32, "confirmed": True,
            "snapshot": "sha256:" + "1" * 64}
ASK = {
    "request_id": "apsreq_release_" + "2" * 32,
    "reason": "the frozen test contradicts the agreed scope",
}
FREEZE = f"/api/v1/specs/{SPEC}/requirements/R1/execution-contract/freeze"
LOOK = f"/api/v1/specs/{SPEC}/requirements/R1/lock"
ASK_URL = LOOK + "/release-request"


class _Facade:
    def freeze_requirement(self, _spec, _requirement, **kwargs):
        return {"status": "frozen", "owner_actor_id": kwargs.get("owner_actor_id")}

    def requirement_status(self, *_args, **_kwargs):
        return {"status": "not_prepared"}


def _client(workspace: Path):
    from fastapi.testclient import TestClient

    from apatch_studio.app import create_app

    (workspace / ".git").mkdir()
    (workspace / ".apatch").mkdir(exist_ok=True)
    _enrol(workspace / ".apatch")
    app = create_app(
        str(workspace),
        sdd_facade=_Facade(),
        frontend_root=workspace,
        identity_root=workspace / ".apatch",
    )
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    return client, {
        "x-apatch-studio-session": app.state.studio_guard.token,
        "origin": "http://127.0.0.1:8765",
    }


def test_the_product_can_ask_and_the_boundary_still_holds(tmp_path):
    """A request that quietly took effect would make the answer decorative."""

    client, headers = _client(tmp_path)
    client.post(FREEZE, headers=headers, json=APPROVAL)

    asked = client.post(ASK_URL, headers=headers, json=ASK)
    assert asked.status_code == 200
    view = asked.json()
    assert view["state"] == "awaiting_answer"
    assert view["exchanges"][-1]["reason"] == ASK["reason"]
    assert view["exchanges"][-1]["answer"] is None
    assert view["exchanges"][-1]["asked_by"] == "studio-laptop"
    assert client.get(LOOK, headers=headers).json() == view


def test_the_request_carries_no_name_of_its_own(tmp_path):
    """Whoever calls must not be able to ask in somebody else's name."""

    client, headers = _client(tmp_path)
    client.post(FREEZE, headers=headers, json=APPROVAL)

    response = client.post(
        ASK_URL, headers=headers, json={**ASK, "asked_by": "rita@example.test"}
    )
    assert response.status_code == 422


def test_a_reason_too_thin_to_answer_is_refused(tmp_path):
    client, headers = _client(tmp_path)
    client.post(FREEZE, headers=headers, json=APPROVAL)

    response = client.post(ASK_URL, headers=headers, json={**ASK, "reason": "because"})
    assert response.status_code == 422
    assert client.get(LOOK, headers=headers).json()["state"] == "locked"


def test_asking_twice_before_an_answer_is_refused(tmp_path):
    """Two open requests would leave nobody able to say which was answered."""

    client, headers = _client(tmp_path)
    client.post(FREEZE, headers=headers, json=APPROVAL)
    client.post(ASK_URL, headers=headers, json=ASK)

    again = client.post(ASK_URL, headers=headers, json=ASK)
    assert again.status_code == 422
    assert again.json()["error_code"] == "lock_approver_unknown"
