"""A refusal is kept as fully as a consent, and stays readable afterwards."""

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


def _locked(root):
    authority = LockAuthority(
        root, clock=lambda: datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
    )
    authority.lock_team(SPEC, "R1", set_by=MANAGER, taken_by=TAKER)
    authority.request_release(
        SPEC, "R1", asked_by=TAKER, reason="the frozen test contradicts the agreed scope"
    )
    return authority


def test_a_refusal_carries_its_reason_and_keeps_the_lock(tmp_path):
    authority = _locked(tmp_path)

    record = authority.answer_release(
        SPEC,
        "R1",
        answered_by=MANAGER,
        decision="refuse",
        reason="the scope was agreed on Tuesday and the test matches it",
    )

    answer = record["release"]["answer"]
    assert record["release"]["state"] == "refused"
    assert answer["decision"] == "refuse"
    assert answer["reason"].startswith("the scope was agreed")
    assert answer["by"]["id"] == "rita@example.test"
    assert authority.is_locked(SPEC, "R1") is True


def test_a_consent_carries_its_reason_too(tmp_path):
    authority = _locked(tmp_path)

    record = authority.answer_release(
        SPEC,
        "R1",
        answered_by=MANAGER,
        decision="grant",
        reason="agreed, the test does contradict what we settled",
    )

    assert record["release"]["state"] == "granted"
    assert record["release"]["answer"]["reason"]
    assert authority.is_locked(SPEC, "R1") is False


def test_a_refused_request_survives_the_next_one(tmp_path):
    """Otherwise a denied request looks exactly like one nobody ever made."""

    authority = _locked(tmp_path)
    authority.answer_release(
        SPEC, "R1", answered_by=MANAGER, decision="refuse", reason="not this week, it is agreed"
    )
    authority.request_release(
        SPEC, "R1", asked_by=TAKER, reason="asking again, the deadline moved"
    )

    exchanges = authority.exchanges(SPEC, "R1")
    assert len(exchanges) == 2
    assert exchanges[0]["state"] == "refused"
    assert exchanges[0]["answer"]["reason"] == "not this week, it is agreed"
    assert exchanges[1]["state"] == "awaiting_answer"


def test_an_answer_without_a_reason_is_refused(tmp_path):
    authority = _locked(tmp_path)
    for empty in ("", "no", "   "):
        with pytest.raises(LockAuthorityError):
            authority.answer_release(
                SPEC, "R1", answered_by=MANAGER, decision="refuse", reason=empty
            )


def test_only_grant_or_refuse_are_answers(tmp_path):
    authority = _locked(tmp_path)
    with pytest.raises(LockAuthorityError):
        authority.answer_release(
            SPEC, "R1", answered_by=MANAGER, decision="maybe", reason="I am not sure yet"
        )


def test_answering_when_nothing_was_asked_is_refused(tmp_path):
    authority = LockAuthority(tmp_path)
    authority.lock_team(SPEC, "R2", set_by=MANAGER, taken_by=TAKER)
    with pytest.raises(LockAuthorityError):
        authority.answer_release(
            SPEC, "R2", answered_by=MANAGER, decision="grant", reason="nobody asked for this"
        )


APPROVAL = {"request_id": "apsreq_freeze_" + "1" * 32, "confirmed": True,
            "snapshot": "sha256:" + "1" * 64}
ASK = {
    "request_id": "apsreq_release_" + "2" * 32,
    "reason": "the frozen test contradicts the agreed scope",
}
LOOK = f"/api/v1/specs/{SPEC}/requirements/R1/lock"
FREEZE = f"/api/v1/specs/{SPEC}/requirements/R1/execution-contract/freeze"
ASK_URL = LOOK + "/release-request"
ANSWER_URL = LOOK + "/release-answer"


class _Facade:
    def freeze_requirement(self, _spec, _requirement, **kwargs):
        return {"status": "frozen", "owner_actor_id": kwargs.get("owner_actor_id")}

    def requirement_status(self, *_args, **_kwargs):
        return {"status": "not_prepared"}


def _asked(workspace: Path):
    """A workspace with an agreed boundary and a release waiting on an answer."""

    from fastapi.testclient import TestClient

    from apatch_studio.app import create_app

    (workspace / ".git").mkdir()
    state = workspace / ".apatch"
    state.mkdir(exist_ok=True)
    (state / "machine-identity.json").write_text(
        json.dumps(
            {
                "schema": "apatch.studio.machine-identity.v1",
                "machine_name": "studio-laptop",
                "key_path": str(state / "agent.key"),
            }
        ),
        encoding="utf-8",
    )
    app = create_app(
        str(workspace),
        sdd_facade=_Facade(),
        frontend_root=workspace,
        identity_root=workspace / ".apatch",
    )
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    headers = {
        "x-apatch-studio-session": app.state.studio_guard.token,
        "origin": "http://127.0.0.1:8765",
    }
    client.post(FREEZE, headers=headers, json=APPROVAL)
    client.post(ASK_URL, headers=headers, json=ASK)
    return client, headers


def test_the_product_records_a_refusal_with_its_reason(tmp_path):
    client, headers = _asked(tmp_path)

    answered = client.post(
        ANSWER_URL,
        headers=headers,
        json={
            "request_id": "apsreq_answer_" + "3" * 32,
            "decision": "refuse",
            "reason": "the scope stands until the release note is written",
        },
    )
    assert answered.status_code == 200
    view = answered.json()
    assert view["state"] == "locked"
    assert view["exchanges"][-1]["answer"] == "refuse"
    assert view["exchanges"][-1]["answered_by"] == "studio-laptop"
    assert "release note" in view["exchanges"][-1]["answer_reason"]


def test_a_refused_request_stays_readable_after_the_next_one(tmp_path):
    """Otherwise a request that was denied looks like one nobody ever made."""

    client, headers = _asked(tmp_path)
    client.post(
        ANSWER_URL,
        headers=headers,
        json={
            "request_id": "apsreq_answer_" + "3" * 32,
            "decision": "refuse",
            "reason": "the scope stands until the release note is written",
        },
    )
    client.post(
        ASK_URL,
        headers=headers,
        json={**ASK, "reason": "asking again, the release note is written now"},
    )

    exchanges = client.get(LOOK, headers=headers).json()["exchanges"]
    assert len(exchanges) == 2
    assert exchanges[0]["answer"] == "refuse"
    assert exchanges[0]["answer_reason"]
    assert exchanges[1]["answer"] is None


def test_a_consent_lifts_the_boundary_and_says_so(tmp_path):
    client, headers = _asked(tmp_path)

    view = client.post(
        ANSWER_URL,
        headers=headers,
        json={
            "request_id": "apsreq_answer_" + "4" * 32,
            "decision": "grant",
            "reason": "agreed, the contradiction is real and the scope must move",
        },
    ).json()
    assert view["state"] == "released"
    assert view["exchanges"][-1]["answer"] == "grant"


def test_an_answer_carries_no_name_and_no_third_decision(tmp_path):
    client, headers = _asked(tmp_path)

    named = client.post(
        ANSWER_URL,
        headers=headers,
        json={
            "request_id": "apsreq_answer_" + "5" * 32,
            "decision": "refuse",
            "reason": "the scope stands until the release note is written",
            "answered_by": "rita@example.test",
        },
    )
    assert named.status_code == 422

    hedged = client.post(
        ANSWER_URL,
        headers=headers,
        json={
            "request_id": "apsreq_answer_" + "6" * 32,
            "decision": "maybe",
            "reason": "I would rather not commit either way today",
        },
    )
    assert hedged.status_code == 422
    assert client.get(LOOK, headers=headers).json()["state"] == "awaiting_answer"
