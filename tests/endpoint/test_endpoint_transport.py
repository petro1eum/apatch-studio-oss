"""Studio speaks only to one pinned origin, under one path prefix (RFP-019)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from apatch_studio.endpoint_transport import (
    CONTROL_PLANE_PREFIX,
    ControlPlaneAddress,
    TransportRejected,
    TransportUnavailable,
    https_sender,
)


def test_only_https_origins_are_accepted() -> None:
    assert ControlPlaneAddress.parse("https://control.example.com").origin == (
        "https://control.example.com"
    )
    assert ControlPlaneAddress.parse("https://control.example.com/").origin == (
        "https://control.example.com"
    )
    for rejected in (
        "http://control.example.com",
        "ftp://control.example.com",
        "control.example.com",
        "https://user:pass@control.example.com",
        "https://control.example.com/api",
        "https://control.example.com?a=1",
        "https://",
        "",
    ):
        with pytest.raises(ValueError):
            ControlPlaneAddress.parse(rejected)


def test_loopback_http_is_allowed_only_when_asked_for() -> None:
    with pytest.raises(ValueError):
        ControlPlaneAddress.parse("http://127.0.0.1:8765")
    assert ControlPlaneAddress.parse(
        "http://127.0.0.1:8765", allow_loopback=True
    ).origin == "http://127.0.0.1:8765"
    with pytest.raises(ValueError):
        ControlPlaneAddress.parse("http://control.example.com", allow_loopback=True)


def test_requests_are_confined_to_the_control_plane_prefix() -> None:
    address = ControlPlaneAddress.parse("https://control.example.com")
    assert address.url(CONTROL_PLANE_PREFIX + "policies/current") == (
        "https://control.example.com/api/v1/pro/policies/current"
    )
    for rejected in (
        "/api/v1/other",
        "/",
        CONTROL_PLANE_PREFIX + "../../admin",
        CONTROL_PLANE_PREFIX + "policies?x=1",
        CONTROL_PLANE_PREFIX + "policies#x",
        "https://elsewhere.example.com/api/v1/pro/policies",
    ):
        with pytest.raises(ValueError):
            address.url(rejected)


def _serve(*, status: int = 200, body: bytes = b'{"ok": true}', location: str | None = None,
           record: dict | None = None):
    """Start a throwaway server whose behaviour belongs to this test alone."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def do_POST(self):  # noqa: N802
            if record is not None:
                record.update({k.lower(): v for k, v in self.headers.items()})
                record["_body"] = self.rfile.read(
                    int(self.headers.get("content-length", 0))
                ).decode("utf-8")
            self.send_response(status)
            if location:
                self.send_header("location", location)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_args):  # keep the suite quiet
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def _sender_for(server, **kwargs):
    address = ControlPlaneAddress.parse(
        f"http://127.0.0.1:{server.server_address[1]}", allow_loopback=True
    )
    return https_sender(address, timeout_seconds=5.0, **kwargs)


def test_a_successful_answer_is_returned_as_data() -> None:
    server = _serve()
    try:
        response = _sender_for(server)(CONTROL_PLANE_PREFIX + "policies/current", {"a": 1})
        assert response.status == 200 and response.body == {"ok": True}
    finally:
        server.shutdown()


def test_a_busy_control_plane_is_retryable_and_a_refusal_is_not() -> None:
    for status in (500, 503, 429, 408):
        server = _serve(status=status, body=b"{}")
        try:
            with pytest.raises(TransportUnavailable):
                _sender_for(server)(CONTROL_PLANE_PREFIX + "policies/current", {})
        finally:
            server.shutdown()
    for status in (400, 401, 403, 404, 422):
        server = _serve(status=status, body=b"{}")
        try:
            with pytest.raises(TransportRejected):
                _sender_for(server)(CONTROL_PLANE_PREFIX + "policies/current", {})
        finally:
            server.shutdown()


def test_a_redirect_never_moves_the_request_off_the_pinned_origin() -> None:
    server = _serve(
        status=302,
        body=b"{}",
        location="https://elsewhere.example.com/api/v1/pro/policies/current",
    )
    try:
        with pytest.raises(TransportRejected):
            _sender_for(server)(CONTROL_PLANE_PREFIX + "policies/current", {})
    finally:
        server.shutdown()


def test_an_unreadable_success_is_refused_rather_than_guessed() -> None:
    for body in (b"<html>not json</html>", b"[1,2,3]", b"null"):
        server = _serve(body=body)
        try:
            with pytest.raises(TransportRejected):
                _sender_for(server)(CONTROL_PLANE_PREFIX + "policies/current", {})
        finally:
            server.shutdown()


def test_an_unreachable_host_is_retryable() -> None:
    address = ControlPlaneAddress.parse("http://127.0.0.1:9", allow_loopback=True)
    with pytest.raises(TransportUnavailable):
        https_sender(address, timeout_seconds=2.0)(
            CONTROL_PLANE_PREFIX + "policies/current", {}
        )


def test_supplied_headers_reach_the_control_plane() -> None:
    seen: dict[str, str] = {}
    server = _serve(body=b"{}", record=seen)
    try:
        _sender_for(server, authorize=lambda: {"x-machine": "studio-01"})(
            CONTROL_PLANE_PREFIX + "policies/current", {"hello": "world"}
        )
    finally:
        server.shutdown()

    assert seen["x-machine"] == "studio-01"
    assert seen["content-type"] == "application/json"
    assert json.loads(seen["_body"]) == {"hello": "world"}
