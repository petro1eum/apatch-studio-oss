"""Fixed-purpose outbound transport to one pinned Cowork origin (RFP-019).

Studio only ever speaks to an exact origin an operator named, only under the
compatibility path prefix, and never follows a redirect off that origin. The
sender is injectable so the contract can be exercised against the real router
without a network.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping
from urllib.parse import urlencode, urlsplit

ADDRESS_SCHEMA = "apatch.studio.control-plane-address.v1"
# Kept for compatibility with the current remote fixture. This public client does
# not publish or embed the server behind this path.
CONTROL_PLANE_PREFIX = "/api/v1/pro/"
MAX_RESPONSE_BYTES = 1_048_576
DEFAULT_TIMEOUT_SECONDS = 10.0
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})


class TransportUnavailable(RuntimeError):
    """The control plane could not be reached; the same request may be retried."""


class TransportRejected(RuntimeError):
    """The control plane refused the request; retrying it unchanged will not help."""

    def __init__(self, message: str, *, status: int) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ControlPlaneAddress:
    """One exact, pinned control-plane origin."""

    origin: str

    @classmethod
    def parse(cls, raw: str, *, allow_loopback: bool = False) -> "ControlPlaneAddress":
        if not isinstance(raw, str) or not 8 <= len(raw) <= 200:
            raise ValueError("control-plane address must be a bounded URL")
        parts = urlsplit(raw.strip())
        if parts.query or parts.fragment or parts.path not in ("", "/"):
            raise ValueError("control-plane address must be an origin without a path")
        if parts.username or parts.password:
            raise ValueError("control-plane address must not carry credentials")
        if not parts.hostname:
            raise ValueError("control-plane address must name a host")
        loopback = parts.hostname in _LOOPBACK_HOSTS
        if parts.scheme == "http":
            if not (loopback and allow_loopback):
                raise ValueError("control-plane address must use https")
        elif parts.scheme != "https":
            raise ValueError("control-plane address must use https")
        return cls(origin=f"{parts.scheme}://{parts.netloc}")

    def url(self, path: str) -> str:
        """Return the absolute URL for a control-plane path, refusing anything else."""

        if not isinstance(path, str) or not path.startswith(CONTROL_PLANE_PREFIX):
            raise ValueError("path must be under " + CONTROL_PLANE_PREFIX)
        if "?" in path or "#" in path or "//" in path[1:] or ".." in path:
            raise ValueError("path must be a plain control-plane path")
        return self.origin + path


@dataclass(frozen=True)
class Response:
    status: int
    body: dict[str, Any]
    set_cookies: tuple[str, ...] = field(default_factory=tuple, repr=False)


Sender = Callable[[str, Mapping[str, Any]], Response]


class _NoRedirects(urllib.request.HTTPRedirectHandler):
    """A redirect could move the request off the pinned origin, so refuse it."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D102
        raise TransportRejected(
            "the control plane attempted to redirect the request", status=code
        )


def _decode(raw: bytes, status: int) -> dict[str, Any]:
    if len(raw) > MAX_RESPONSE_BYTES:
        raise TransportRejected("the control plane response is too large", status=status)
    try:
        body = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise TransportRejected(
            "the control plane returned a response Studio cannot read", status=status
        ) from exc
    if not isinstance(body, dict):
        raise TransportRejected(
            "the control plane returned an unexpected response", status=status
        )
    return body


def https_sender(
    address: ControlPlaneAddress,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    authorize: Callable[[], Mapping[str, str]] | None = None,
    method: str = "POST",
) -> Sender:
    """Build a sender that posts JSON to the pinned origin over the standard library."""

    if method not in {"POST", "GET"}:
        raise ValueError("only typed POST operations and GET read models are supported")
    opener = urllib.request.build_opener(_NoRedirects())

    def send(path: str, payload: Mapping[str, Any]) -> Response:
        url = address.url(path)
        if method == "GET" and payload:
            if any(
                not isinstance(key, str) or not key or len(key) > 64
                or not all(character.isalnum() or character == "_" for character in key)
                or not isinstance(value, (str, int))
                for key, value in payload.items()
            ):
                raise ValueError("GET query values must be bounded scalar fields")
            url += "?" + urlencode(sorted((key, str(value)) for key, value in payload.items()))
        headers = {"content-type": "application/json", "accept": "application/json"}
        for key, value in (authorize() if authorize else {}).items():
            headers[str(key)] = str(value)
        request = urllib.request.Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8") if method == "POST" else None,
            headers=headers,
            method=method,
        )
        try:
            with opener.open(request, timeout=timeout_seconds) as response:
                return Response(
                    status=int(response.status),
                    body=_decode(response.read(MAX_RESPONSE_BYTES + 1), int(response.status)),
                    set_cookies=tuple(response.headers.get_all("Set-Cookie") or ()),
                )
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            detail = f"the control plane answered {status}"
            if status in _RETRYABLE_STATUS:
                raise TransportUnavailable(detail) from exc
            raise TransportRejected(detail, status=status) from exc
        except TransportRejected:
            raise
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TransportUnavailable("the control plane could not be reached") from exc

    return send
