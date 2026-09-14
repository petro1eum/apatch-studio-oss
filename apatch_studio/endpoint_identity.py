"""Whether this machine holds a verifiable identity (RFP-019).

Studio never creates a machine key. The Ed25519 key lives in the APatch runtime,
enrolled through the TrustChain Platform and certified by its root authority.
This module only reads that state and explains it, so one machine keeps one
identity instead of accumulating a second private authority.
"""

from __future__ import annotations

from typing import Any, Callable

IDENTITY_SCHEMA = "apatch.studio.endpoint-identity.v1"

_ENROLLED = (
    "This machine has a verifiable identity",
    "Work recorded here is signed by a key certified by your organization, so "
    "anyone holding the certificate can confirm which machine produced it.",
    "Nothing to do.",
)
_TEMPORARY = (
    "This machine signs with a temporary key",
    "Records made here are signed by a key this machine generated for itself, so "
    "nobody else can confirm where they came from. Team features need an identity "
    "your organization has issued.",
    "Enroll this machine with your organization, then restart Studio.",
)
_SELF_NAMED = (
    "This machine named itself",
    "Work recorded here says which machine produced it on that machine's own "
    "word, and nobody outside it vouched for the name. That is enough to know "
    "who acted in this workspace and worth nothing to anyone else.",
    "Enroll this machine with your organization when you have one, to get a name "
    "a stranger can check.",
)
_UNAVAILABLE = (
    "The identity of this machine is unknown",
    "Studio could not read the identity from the local runtime, so it must assume "
    "this machine is not enrolled.",
    "Check the local runtime in Admin, then restart Studio.",
)


def _default_status_provider(workspace: str) -> dict[str, Any]:
    from apatch.trust_identity import anchor_status

    return anchor_status(workspace)


def endpoint_identity_status(
    workspace: str,
    *,
    status_provider: Callable[[str], dict[str, Any]] | None = None,
    state_root: str | None = None,
) -> dict[str, Any]:
    """Report this machine's identity, failing closed when it cannot be read.

    There are three answers here, not two. A machine an organization certified
    and a machine that named itself are both usable, and only the first means
    anything to a stranger; collapsing them would let the weaker one borrow the
    words of the stronger, which is the one outcome worth preventing.
    """

    provider = status_provider or _default_status_provider
    try:
        raw = provider(str(workspace))
    except Exception:
        raw = None

    if not isinstance(raw, dict):
        headline, explanation, next_step = _UNAVAILABLE
        enrolled = False
        agent_id = None
        has_certificate = False
    else:
        enrolled = raw.get("secure") is True and raw.get("level") == "ca-issued"
        agent_id = raw.get("agent_id") if isinstance(raw.get("agent_id"), str) else None
        has_certificate = raw.get("has_cert") is True
        if enrolled:
            headline, explanation, next_step = _ENROLLED
        else:
            headline, explanation, next_step = _TEMPORARY

    self_named = None
    if not enrolled:
        self_named = _self_named_record(state_root)
        if self_named is not None:
            agent_id = self_named["machine_name"]
            headline, explanation, next_step = _SELF_NAMED

    return {
        "schema": IDENTITY_SCHEMA,
        "enrolled": enrolled,
        "self_named": self_named is not None,
        "certified": enrolled,
        "machine_name": agent_id,
        "has_certificate": has_certificate,
        "headline": headline,
        "explanation": explanation,
        "next_step": next_step,
    }


def _self_named_record(state_root: str | None) -> dict[str, Any] | None:
    """The name this machine gave itself, if it gave itself one."""

    from apatch_studio.endpoint_enrollment import stored_identity
    from apatch_studio.run_store import default_state_root

    try:
        record = stored_identity(state_root or default_state_root())
    except Exception:
        return None
    if not isinstance(record, dict) or record.get("certified") is not False:
        return None
    return record
