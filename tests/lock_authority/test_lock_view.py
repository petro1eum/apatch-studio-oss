"""The exchange is readable beside the work, not only through the API."""

import json
from datetime import datetime, timezone
from pathlib import Path

from apatch_studio.lock_authority import LockAuthority
from apatch_studio.projection import assert_projection_safe

SPEC = "SPEC-DEMO-1"
TENANT = "11111111-1111-4111-8111-111111111111"


class _Principal:
    def __init__(self, subject, membership):
        self.subject = subject
        self.membership_id = "apsmem_" + membership * 32
        self.tenant_id = TENANT


MANAGER = _Principal("rita@example.test", "a")
TAKER = _Principal("dana@example.test", "b")


def _authority(root):
    return LockAuthority(
        root, clock=lambda: datetime(2026, 9, 4, 12, tzinfo=timezone.utc)
    )


def _refused_then_asked_again(root):
    authority = _authority(root)
    authority.lock_team(SPEC, "R1", set_by=MANAGER, taken_by=TAKER)
    authority.request_release(
        SPEC, "R1", asked_by=TAKER, reason="the frozen test contradicts the agreed scope"
    )
    authority.answer_release(
        SPEC, "R1", answered_by=MANAGER, decision="refuse", reason="the scope stands for now"
    )
    authority.request_release(
        SPEC, "R1", asked_by=TAKER, reason="asking again, the deadline moved"
    )
    return authority


def test_the_view_shows_who_agreed_and_when(tmp_path):
    authority = _authority(tmp_path)
    authority.lock_team(SPEC, "R1", set_by=MANAGER, taken_by=TAKER)

    view = authority.view(SPEC, "R1")
    assert view["state"] == "locked"
    assert view["headline"]
    assert view["agreed_at"]
    assert [party["role"] for party in view["agreed_by"]] == ["set_by", "taken_by"]
    assert [party["name"] for party in view["agreed_by"]] == [
        "rita@example.test",
        "dana@example.test",
    ]


def test_the_view_shows_every_request_its_reason_and_the_answer(tmp_path):
    view = _refused_then_asked_again(tmp_path).view(SPEC, "R1")

    assert len(view["exchanges"]) == 2
    first, second = view["exchanges"]
    assert first["asked_by"] == "dana@example.test"
    assert first["reason"].startswith("the frozen test")
    assert first["answer"] == "refuse"
    assert first["answered_by"] == "rita@example.test"
    assert first["answer_reason"] == "the scope stands for now"
    assert second["outcome"] == "awaiting_answer"
    assert second["answer"] is None


def test_the_view_carries_nothing_that_should_not_leave_the_machine(tmp_path):
    view = _refused_then_asked_again(tmp_path).view(SPEC, "R1")
    assert_projection_safe(view)
    assert "membership_id" not in json.dumps(view)


def test_a_broken_lock_explains_itself_in_the_view(tmp_path):
    authority = _authority(tmp_path)
    authority.lock_team(SPEC, "R1", set_by=MANAGER, taken_by=TAKER)
    (tmp_path / "locks" / SPEC / "R1.json").unlink()

    view = authority.view(SPEC, "R1")
    assert view["state"] == "broken"
    assert view["explanation"]


def test_the_workspace_serves_the_exchange(tmp_path):
    from fastapi.testclient import TestClient

    from apatch_studio.app import create_app

    (tmp_path / ".git").mkdir()
    _authority(tmp_path / ".apatch").lock_team(
        SPEC, "R1", set_by=MANAGER, taken_by=TAKER
    )
    app = create_app(str(tmp_path), frontend_root=tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    headers = {
        "x-apatch-studio-session": app.state.studio_guard.token,
        "origin": "http://127.0.0.1:8765",
    }

    response = client.get(
        f"/api/v1/specs/{SPEC}/requirements/R1/lock", headers=headers
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "locked"
    assert [party["name"] for party in body["agreed_by"]] == [
        "rita@example.test",
        "dana@example.test",
    ]


def test_the_exchange_is_reachable_where_no_contract_can_be_reviewed(tmp_path):
    """The screen must not reach the exchange only through the contract review.

    A workspace whose contract is gone is precisely the workspace whose lock
    most needs reading, and it is the one workspace a contract review can never
    open. The first version of this requirement was proven by searching the
    component source for words, which stayed green while the panel was
    unreachable; this drives the workspace instead.
    """

    from fastapi.testclient import TestClient

    from apatch_studio.app import create_app

    (tmp_path / ".git").mkdir()
    _authority(tmp_path / ".apatch").lock_team(
        SPEC, "R1", set_by=MANAGER, taken_by=TAKER
    )
    app = create_app(str(tmp_path), frontend_root=tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    headers = {
        "x-apatch-studio-session": app.state.studio_guard.token,
        "origin": "http://127.0.0.1:8765",
    }

    review = client.get(
        f"/api/v1/specs/{SPEC}/requirements/R1/execution-contract", headers=headers
    )
    assert review.json()["ok"] is False

    exchange = client.get(f"/api/v1/specs/{SPEC}/requirements/R1/lock", headers=headers)
    assert exchange.status_code == 200
    assert exchange.json()["state"] == "locked"


def test_the_screen_loads_the_exchange_beside_the_requirement():
    """Source shape, deliberately: nothing here renders React.

    This asserts where the load happens, not that a word appears somewhere in
    the file. It is still an inspection of the component rather than of a
    rendered screen, and it is written to fail if the load moves back behind
    the contract review.
    """

    view = Path("frontend/src/ProjectPlanView.tsx").read_text(encoding="utf-8")
    effect = view.split("useEffect(", 1)
    assert len(effect) == 2, "the requirement card loads nothing on its own"
    assert "loadLockExchange" in effect[1].split("}, [", 1)[0], (
        "the exchange is not loaded with the requirement"
    )
    review_body = view.split("async function loadContractReview", 1)[1].split(
        "async function", 1
    )[0]
    assert "loadLockExchange" not in review_body, (
        "the exchange is reachable only by opening the contract review"
    )


def test_the_screen_can_ask_and_answer_rather_than_only_read():
    """Both sides act on this screen; a read-only panel is half the mechanism."""

    api = Path("frontend/src/api.ts").read_text(encoding="utf-8")
    view = Path("frontend/src/ProjectPlanView.tsx").read_text(encoding="utf-8")
    assert "lock/release-request" in api
    assert "lock/release-answer" in api
    for handler in ("askForRelease", "answerRelease"):
        assert f"void {handler}(" in view, f"nothing on the screen calls {handler}"
    for field in ("agreed_by", "exchanges", "answer_reason", "headline", "one_sided"):
        assert field in view, f"the screen never shows {field}"
