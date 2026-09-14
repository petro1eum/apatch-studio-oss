"""One machine keeps one identity, read from the runtime and never minted (RFP-019)."""

from __future__ import annotations

import json
from pathlib import Path

from apatch_studio.endpoint_identity import (
    IDENTITY_SCHEMA,
    endpoint_identity_status,
)

ROOT = Path(__file__).resolve().parents[2]
MODULE = (ROOT / "apatch_studio/endpoint_identity.py").read_text(encoding="utf-8")
TYPES = (ROOT / "frontend/src/types.ts").read_text(encoding="utf-8")
ADMIN = (ROOT / "frontend/src/OutsideInAdmin.tsx").read_text(encoding="utf-8")
VOCABULARY = json.loads(
    (ROOT / "frontend/src/vocabulary.contract.json").read_text(encoding="utf-8")
)


def _provider(payload):
    def load(_workspace: str):
        if isinstance(payload, Exception):
            raise payload
        return payload

    return load


def test_enrolled_machine_is_reported_as_verifiable() -> None:
    status = endpoint_identity_status(
        "/tmp/workspace",
        status_provider=_provider(
            {
                "level": "ca-issued",
                "secure": True,
                "agent_id": "studio-laptop-01",
                "has_cert": True,
                "backend": "pem",
                "hint": None,
            }
        ),
    )

    assert status["schema"] == IDENTITY_SCHEMA
    assert status["enrolled"] is True
    assert status["machine_name"] == "studio-laptop-01"
    assert status["has_certificate"] is True
    assert status["next_step"] == "Nothing to do."


def test_temporary_key_is_explained_with_one_next_step(tmp_path) -> None:
    """A machine that has not been named at all, stated rather than assumed.

    The empty state root is the point: without it this reads whichever name the
    machine running the tests happens to hold, so the test would describe the
    developer's laptop instead of the case it is about.
    """

    status = endpoint_identity_status(
        "/tmp/workspace",
        status_provider=_provider(
            {
                "level": "ephemeral",
                "secure": False,
                "agent_id": None,
                "has_cert": False,
                "backend": None,
                "hint": "…",
            }
        ),
        state_root=str(tmp_path),
    )

    assert status["enrolled"] is False
    assert status["self_named"] is False
    assert status["machine_name"] is None
    assert "temporary key" in status["headline"]
    assert status["next_step"].startswith("Enroll this machine")


def test_an_unreadable_runtime_fails_closed() -> None:
    for payload in (RuntimeError("no apatch"), None, "ca-issued", []):
        status = endpoint_identity_status(
            "/tmp/workspace", status_provider=_provider(payload)
        )
        assert status["enrolled"] is False, payload
        assert status["has_certificate"] is False
        assert status["next_step"].strip()


def test_a_partial_claim_never_counts_as_enrolled() -> None:
    """Both the level and the secure flag must agree before Studio trusts it."""

    for raw in (
        {"level": "ca-issued", "secure": False, "agent_id": "x", "has_cert": True},
        {"level": "ephemeral", "secure": True, "agent_id": "x", "has_cert": True},
        {"level": "ca-issued", "secure": "yes", "agent_id": "x", "has_cert": True},
        {},
    ):
        status = endpoint_identity_status("/tmp/workspace", status_provider=_provider(raw))
        assert status["enrolled"] is False, raw


def test_studio_never_generates_a_machine_key() -> None:
    """RFP-019: custody stays in the runtime; Studio only reads it."""

    for forbidden in (
        "Ed25519PrivateKey",
        "from_private_bytes",
        "token_bytes",
        "urandom",
        "cryptography",
    ):
        assert forbidden not in MODULE, forbidden
    assert "import cryptography" not in MODULE


def test_identity_copy_uses_product_language_only() -> None:
    for payload in (
        {"level": "ca-issued", "secure": True, "agent_id": "a", "has_cert": True},
        {"level": "ephemeral", "secure": False, "agent_id": None, "has_cert": False},
        None,
    ):
        status = endpoint_identity_status(
            "/tmp/workspace", status_provider=_provider(payload)
        )
        for field in ("headline", "explanation", "next_step"):
            lowered = status[field].lower()
            for term in VOCABULARY["forbidden_primary_terms"]:
                assert term not in lowered, (term, status[field])


def test_identity_is_visible_in_the_projection_and_in_admin() -> None:
    assert "export interface EndpointIdentity" in TYPES
    assert "endpoint_identity: EndpointIdentity;" in TYPES
    assert "<dt>Machine identity</dt>" in ADMIN
    assert "data.runtime.endpoint_identity.headline" in ADMIN
