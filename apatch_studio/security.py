"""Loopback and browser-session boundary for the local Studio service."""

from __future__ import annotations

import hmac
import ipaddress
import secrets
from dataclasses import dataclass, field
from urllib.parse import urlsplit

from fastapi import Request
from fastapi.responses import JSONResponse, Response

SESSION_HEADER = "x-apatch-studio-session"
EXECUTION_INTENT_IMPORT_PATH = "/api/v1/execution-intents/import"
EXACT_CONTRACT_IMPORT_PATH = "/api/v1/exact-contract-handoffs/import"
TRUSTED_IMPORT_PATHS = frozenset({EXECUTION_INTENT_IMPORT_PATH, EXACT_CONTRACT_IMPORT_PATH})


def _host_without_port(value: str) -> str:
    raw = (value or "").strip().lower()
    if raw.startswith("["):
        return raw[1 : raw.find("]")] if "]" in raw else raw
    return raw.rsplit(":", 1)[0] if raw.count(":") == 1 else raw


def is_loopback_host(value: str) -> bool:
    host = _host_without_port(value)
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _normalized_origin(value: str) -> str | None:
    try:
        parsed = urlsplit(value)
        host, port_number = parsed.hostname, parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        return None
    if parsed.scheme == 'http' and not is_loopback_host(parsed.hostname):
        return None
    port = f":{port_number}" if port_number is not None else ""
    host = '[' + parsed.hostname.lower() + ']' if ':' in parsed.hostname else parsed.hostname.lower()
    return f"{parsed.scheme}://{host}{port}"


def _same_origin(request: Request) -> bool:
    origin = request.headers.get("origin")
    host = request.headers.get("host", "")
    if not origin or not host:
        return False
    parsed = urlsplit(origin)
    if parsed.scheme != "http" or not parsed.netloc or parsed.path not in ("", "/"):
        return False
    return parsed.netloc.lower() == host.lower() and is_loopback_host(parsed.hostname or "")


@dataclass
class StudioRequestGuard:
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32))
    trusted_execution_origins: frozenset[str] = field(default_factory=frozenset)

    def __post_init__(self) -> None:
        normalized = {_normalized_origin(value) for value in self.trusted_execution_origins}
        if None in normalized:
            raise ValueError("trusted execution origins must be exact HTTPS or HTTP loopback origins")
        self.trusted_execution_origins = frozenset(
            value for value in normalized if value is not None
        )

    def _trusted_execution_origin(self, request: Request) -> str | None:
        origin = _normalized_origin(request.headers.get("origin", ""))
        return origin if origin in self.trusted_execution_origins else None

    def preflight(self, request: Request) -> Response | None:
        if request.method != "OPTIONS" or request.url.path not in TRUSTED_IMPORT_PATHS:
            return None
        if self._trusted_execution_origin(request) is None:
            return JSONResponse(
                {"ok": False, "error": "trusted origin required"}, status_code=403
            )
        requested_method = request.headers.get("access-control-request-method", "").upper()
        requested_headers = {
            value.strip().lower()
            for value in request.headers.get("access-control-request-headers", "").split(",")
            if value.strip()
        }
        if requested_method != "POST" or not requested_headers.issubset({"content-type"}):
            return JSONResponse({"ok": False, "error": "preflight denied"}, status_code=403)
        return Response(status_code=204)

    def authenticate(self, request: Request) -> Response | None:
        host = request.headers.get("host", "")
        if not is_loopback_host(host):
            return JSONResponse(
                {"ok": False, "error": "loopback host required"}, status_code=400
            )

        path = request.url.path
        if not path.startswith("/api/") or path == "/api/v1/health":
            return None
        if path in TRUSTED_IMPORT_PATHS:
            content_type = request.headers.get("content-type", "").split(";", 1)[0].strip()
            if request.method != "POST" or content_type != "application/json":
                return JSONResponse(
                    {"ok": False, "error": "trusted execution-intent import required"},
                    status_code=403,
                )
            if self._trusted_execution_origin(request) is not None:
                return None
            if not _same_origin(request):
                return JSONResponse(
                    {"ok": False, "error": "same-origin request required"},
                    status_code=403,
                )
            # Manual Inbox import uses the normal local-session boundary below.
            # It still passes the same envelope signature and expiry checks.

        supplied = request.headers.get(SESSION_HEADER, "")
        if not supplied or not hmac.compare_digest(supplied, self.token):
            return JSONResponse(
                {"ok": False, "error": "studio session required"}, status_code=401
            )

        if request.method not in {"GET", "HEAD", "OPTIONS"} and not _same_origin(request):
            return JSONResponse(
                {"ok": False, "error": "same-origin request required"}, status_code=403
            )
        return None

    def cors_headers(self, response: Response, request: Request) -> None:
        if request.url.path not in TRUSTED_IMPORT_PATHS:
            return
        origin = self._trusted_execution_origin(request)
        if origin is None:
            return
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "POST"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        response.headers["Access-Control-Max-Age"] = "60"
        response.headers["Vary"] = "Origin"
        response.headers["Cross-Origin-Resource-Policy"] = "cross-origin"
        if request.headers.get("access-control-request-private-network") == "true":
            response.headers["Access-Control-Allow-Private-Network"] = "true"


def security_headers(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    response.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    )
