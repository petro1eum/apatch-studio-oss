"""Queued work is delivered once, kept in order, and never dropped in silence (RFP-019)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from apatch_studio.endpoint_outbox import (
    MAX_ATTEMPTS,
    MAX_PENDING,
    EndpointOutbox,
    OutboxFull,
)
from apatch_studio.endpoint_transport import (
    CONTROL_PLANE_PREFIX,
    TransportRejected,
    TransportUnavailable,
)
from apatch_studio.projection import UnsafeProjectionError

REQUEST_ID = re.compile(r"^[A-Za-z0-9_.:-]{16,128}$")
PATH = CONTROL_PLANE_PREFIX + "endpoints/challenges"


class _Clock:
    def __init__(self) -> None:
        self.moment = datetime(2026, 9, 3, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.moment

    def advance(self, seconds: int) -> None:
        self.moment += timedelta(seconds=seconds)


def _outbox(tmp_path: Path, clock: _Clock | None = None) -> EndpointOutbox:
    return EndpointOutbox(tmp_path / "state", now=clock or _Clock())


def test_a_queued_item_gets_an_identifier_the_control_plane_accepts(tmp_path: Path) -> None:
    request_id = _outbox(tmp_path).enqueue("endpoint.challenge", PATH, {"label": "laptop"})
    assert REQUEST_ID.fullmatch(request_id)


def test_a_retry_repeats_the_same_identifier(tmp_path: Path) -> None:
    """The control plane recognises a repeat only when the identifier is stable."""

    clock = _Clock()
    outbox = _outbox(tmp_path, clock)
    outbox.enqueue("endpoint.challenge", PATH, {"label": "laptop"})
    seen: list[str] = []

    def failing(_path, payload):
        seen.append(payload["request_id"])
        raise TransportUnavailable("offline")

    outbox.drain(failing)
    clock.advance(3600)
    outbox.drain(failing)

    assert len(seen) == 2 and seen[0] == seen[1]


def test_delivery_marks_the_item_done_and_stops_resending_it(tmp_path: Path) -> None:
    clock = _Clock()
    outbox = _outbox(tmp_path, clock)
    outbox.enqueue("endpoint.challenge", PATH, {"label": "laptop"})
    calls: list[str] = []

    def ok(_path, payload):
        calls.append(payload["request_id"])
        return {"ok": True}

    first = outbox.drain(ok)
    clock.advance(3600)
    second = outbox.drain(ok)

    assert first["delivered"] == 1 and second["delivered"] == 0
    assert len(calls) == 1
    assert outbox.summary()["pending"] == 0


def test_order_is_kept_and_an_unreachable_plane_stops_the_run(tmp_path: Path) -> None:
    outbox = _outbox(tmp_path)
    for index in range(3):
        outbox.enqueue("endpoint.challenge", PATH, {"label": f"machine-{index}"})
    seen: list[str] = []

    def first_then_offline(_path, payload):
        seen.append(payload["label"])
        if len(seen) > 1:
            raise TransportUnavailable("offline")
        return {"ok": True}

    report = outbox.drain(first_then_offline)

    assert seen == ["machine-0", "machine-1"]
    assert report["delivered"] == 1 and report["stopped"] == "unreachable"
    assert report["pending"] == 2


def test_a_refused_item_is_kept_visible_and_the_rest_still_go(tmp_path: Path) -> None:
    outbox = _outbox(tmp_path)
    outbox.enqueue("endpoint.challenge", PATH, {"label": "bad"})
    outbox.enqueue("endpoint.challenge", PATH, {"label": "good"})
    delivered: list[str] = []

    def refuse_first(_path, payload):
        if payload["label"] == "bad":
            raise TransportRejected("the control plane answered 422", status=422)
        delivered.append(payload["label"])
        return {"ok": True}

    report = outbox.drain(refuse_first)

    assert delivered == ["good"]
    assert report["blocked"] == 1 and report["delivered"] == 1
    assert outbox.summary()["blocked"] == 1


def test_an_item_that_never_gets_through_is_blocked_not_discarded(tmp_path: Path) -> None:
    clock = _Clock()
    outbox = _outbox(tmp_path, clock)
    outbox.enqueue("endpoint.challenge", PATH, {"label": "laptop"})

    def offline(_path, _payload):
        raise TransportUnavailable("offline")

    for _ in range(MAX_ATTEMPTS):
        outbox.drain(offline)
        clock.advance(MAX_ATTEMPTS * 3600)

    summary = outbox.summary()
    assert summary["pending"] == 0
    assert summary["blocked"] == 1


def test_a_failed_item_waits_before_it_is_tried_again(tmp_path: Path) -> None:
    clock = _Clock()
    outbox = _outbox(tmp_path, clock)
    outbox.enqueue("endpoint.challenge", PATH, {"label": "laptop"})
    attempts: list[int] = []

    def offline(_path, _payload):
        attempts.append(1)
        raise TransportUnavailable("offline")

    outbox.drain(offline)
    outbox.drain(offline)
    assert len(attempts) == 1

    clock.advance(10)
    outbox.drain(offline)
    assert len(attempts) == 2


def test_queued_work_survives_a_restart(tmp_path: Path) -> None:
    request_id = _outbox(tmp_path).enqueue("endpoint.challenge", PATH, {"label": "laptop"})
    seen: list[str] = []

    _outbox(tmp_path).drain(lambda _p, payload: seen.append(payload["request_id"]))

    assert seen == [request_id]


def test_forbidden_content_never_enters_the_queue(tmp_path: Path) -> None:
    outbox = _outbox(tmp_path)
    for payload in (
        {"diff": "--- a/x"},
        {"access_token": "abc"},
        {"secret": "s"},
        {"full_diff": "x"},
        {"nested": {"private_key": "k"}},
        {"stdout": "..."},
        {"prompt": "..."},
    ):
        with pytest.raises(UnsafeProjectionError):
            outbox.enqueue("endpoint.challenge", PATH, payload)
    assert outbox.summary()["pending"] == 0


def test_the_queue_is_bounded_and_says_so(tmp_path: Path) -> None:
    outbox = _outbox(tmp_path)
    for index in range(MAX_PENDING):
        outbox.enqueue("endpoint.challenge", PATH, {"label": f"m{index}"})
    with pytest.raises(OutboxFull):
        outbox.enqueue("endpoint.challenge", PATH, {"label": "one too many"})


def test_an_oversized_payload_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        _outbox(tmp_path).enqueue("endpoint.challenge", PATH, {"label": "x" * 300_000})


def test_the_queue_lives_outside_the_git_workspace(tmp_path: Path) -> None:
    outbox = _outbox(tmp_path)
    assert outbox.path.parent == (tmp_path / "state").resolve()
    assert outbox.path.exists()
