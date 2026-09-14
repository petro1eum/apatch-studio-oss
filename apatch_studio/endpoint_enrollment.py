"""Enroll this machine once, and make the result survive a restart (RFP-019).

Enrollment itself belongs to the APatch runtime and the TrustChain Platform:
they create the key and issue the certificate. Studio's part is to run that
once, remember *where* the identity lives, and put it back in place the next
time it starts, so an enrolled machine does not quietly fall back to signing
with a temporary key because a shell variable was missing.

The invitation is a credential. It is passed straight through to the runtime
and is never written to disk, never projected and never kept in memory beyond
the call.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, MutableMapping

READINESS_SCHEMA = "apatch.studio.machine-enrollment-readiness.v1"
RESULT_SCHEMA = "apatch.studio.machine-enrollment-result.v1"
RECORD_SCHEMA = "apatch.studio.machine-identity.v1"
IDENTITY_FILE = "machine-identity.json"
IDENTITY_DIRECTORY = "machine-identity"
_ENV_KEYS = ("APATCH_AGENT_ID", "APATCH_AGENT_KEY", "APATCH_AGENT_CERT")
_MACHINE_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")


def default_machine_name(hostname: str | None = None) -> str:
    """Return a stable, plain name for this machine."""

    raw = (hostname if hostname is not None else socket.gethostname()) or "studio"
    cleaned = re.sub(r"[^a-z0-9-]+", "-", raw.strip().lower()).strip("-")
    return (cleaned or "studio")[:63].rstrip("-") or "studio"


def name_this_machine(
    *,
    state_root: str | os.PathLike[str],
    hostname: str | None = None,
) -> dict[str, Any]:
    """Let this machine say which machine it is, with nobody else involved.

    This is not enrolment and does not pretend to be. No key is created, no
    certificate is issued and nothing is sent anywhere. The name is read off
    the machine, so a caller cannot choose to be a different one, and the
    record says the name is this machine's own word and no one else's.
    """

    existing = stored_identity(state_root)
    if existing is not None and existing.get("certified") is True:
        raise ValueError(
            "This machine already holds an identity its organization issued. "
            "Naming it locally would replace a name a stranger can check with "
            "one only this machine vouches for."
        )
    name = default_machine_name(hostname)
    if not _MACHINE_NAME.fullmatch(name):
        raise ValueError("this machine's name is not usable; enrol it instead")
    record = {
        "schema": RECORD_SCHEMA,
        "machine_name": name,
        "certified": False,
        "key_path": None,
        "certificate_path": None,
        "named_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path = _identity_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return record


def enrollment_readiness(
    *,
    which: Callable[[str], str | None] = shutil.which,
) -> dict[str, Any]:
    """Report whether this machine can be enrolled right now."""

    tool = which("tc")
    if tool is None:
        return {
            "schema": READINESS_SCHEMA,
            "ready": False,
            "headline": "The enrollment tool is not installed",
            "explanation": (
                "Enrolling this machine needs the TrustChain command-line tool, "
                "which is not on this computer."
            ),
            "next_step": "Install it with `pip install trustchain`, then try again.",
        }
    return {
        "schema": READINESS_SCHEMA,
        "ready": True,
        "headline": "This machine can be enrolled",
        "explanation": "The enrollment tool is installed and ready to use.",
        "next_step": "Run enrollment with an invitation from your organization.",
    }


def _identity_path(state_root: str | os.PathLike[str]) -> Path:
    return Path(state_root).expanduser().resolve() / IDENTITY_FILE


def stored_identity(state_root: str | os.PathLike[str]) -> dict[str, Any] | None:
    """Return the recorded pointer to this machine's identity, if there is one."""

    path = _identity_path(state_root)
    try:
        if path.is_symlink() or not path.is_file():
            return None
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(record, dict) or record.get("schema") != RECORD_SCHEMA:
        return None
    if record.get("certified") is False:
        # A machine that named itself holds no key and no certificate. It is a
        # usable approver inside this workspace and evidence to nobody outside
        # it, which is the whole reason the flag is stored rather than guessed.
        return record if isinstance(record.get("machine_name"), str) and record["machine_name"] else None
    if not all(isinstance(record.get(key), str) and record[key] for key in ("machine_name", "key_path")):
        return None
    return record


def apply_stored_identity(
    state_root: str | os.PathLike[str],
    *,
    environ: MutableMapping[str, str] | None = None,
) -> bool:
    """Put a previously enrolled identity back in place for this process.

    An identity an operator set explicitly always wins; this only fills gaps.
    """

    env = os.environ if environ is None else environ
    record = stored_identity(state_root)
    if record is None:
        return False
    if any(env.get(key) for key in _ENV_KEYS):
        return False
    values = {
        "APATCH_AGENT_ID": record.get("machine_name"),
        "APATCH_AGENT_KEY": record.get("key_path"),
        "APATCH_AGENT_CERT": record.get("certificate_path"),
    }
    applied = False
    for key, value in values.items():
        if isinstance(value, str) and value:
            env[key] = value
            applied = True
    return applied



def _write_record(
    state_root: str | os.PathLike[str],
    *,
    machine_name: str,
    key_path: str,
    certificate_path: str | None,
) -> dict[str, Any]:
    record = {
        "schema": RECORD_SCHEMA,
        "machine_name": machine_name,
        "certified": True,
        "key_path": key_path,
        "certificate_path": certificate_path,
        "enrolled_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    path = _identity_path(state_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return record


def _apply(record: dict[str, Any], environ: MutableMapping[str, str] | None) -> None:
    env = os.environ if environ is None else environ
    for key, value in (
        ("APATCH_AGENT_ID", record["machine_name"]),
        ("APATCH_AGENT_KEY", record["key_path"]),
        ("APATCH_AGENT_CERT", record["certificate_path"]),
    ):
        if isinstance(value, str) and value:
            env[key] = value


def enroll_machine(
    *,
    state_root: str | os.PathLike[str],
    invitation: str,
    platform_url: str,
    machine_name: str | None = None,
    enroll: Callable[..., dict[str, Any]] | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, Any]:
    """Enroll this machine through the runtime and remember where the identity is."""

    name = machine_name or default_machine_name()
    if not _MACHINE_NAME.fullmatch(name):
        raise ValueError("machine name must be plain lowercase letters, digits and dashes")
    if not isinstance(invitation, str) or not invitation.strip():
        raise ValueError("an invitation from your organization is required")
    if not isinstance(platform_url, str) or not platform_url.startswith("https://"):
        raise ValueError("the organization address must be an https URL")

    root = Path(state_root).expanduser().resolve()
    out_dir = root / IDENTITY_DIRECTORY
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(out_dir, 0o700)
    except OSError:
        pass

    runner = enroll or _default_enroll
    outcome = runner(
        invitation=invitation.strip(),
        platform_url=platform_url,
        out_dir=str(out_dir),
        agent_id=name,
    )

    if not isinstance(outcome, dict) or not outcome.get("ok") or not outcome.get("key_path"):
        return {
            "schema": RESULT_SCHEMA,
            "enrolled": False,
            "machine_name": name,
            "headline": "This machine was not enrolled",
            "explanation": (
                "The organization did not issue an identity for this machine. The "
                "invitation may have been used already or may have expired."
            ),
            "next_step": "Ask your organization for a new invitation, then try again.",
        }

    record = _write_record(
        root,
        machine_name=name,
        key_path=str(outcome.get("key_path")),
        certificate_path=str(outcome.get("cert_path") or "") or None,
    )
    _apply(record, environ)

    return {
        "schema": RESULT_SCHEMA,
        "enrolled": True,
        "machine_name": name,
        "headline": "This machine now has a verifiable identity",
        "explanation": (
            "Your organization issued a certificate for this machine. Studio will "
            "use it every time it starts, without any further setup."
        ),
        "next_step": "Nothing to do.",
    }


def _default_enroll(**kwargs: Any) -> dict[str, Any]:
    from apatch.trust_identity import enroll_agent

    return enroll_agent(**kwargs)



def certificate_validity(
    certificate_path: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Report whether a certificate is inside its own validity window.

    The runtime's anchor check proves the chain, the revocation list and the key
    binding, but it does not look at dates: an expired certificate passes it.
    Studio therefore checks the window itself before calling a machine verifiable.
    """

    from cryptography.x509 import load_pem_x509_certificate

    moment = now or datetime.now(timezone.utc)
    try:
        raw = Path(certificate_path).expanduser().read_bytes()
        certificate = load_pem_x509_certificate(raw)
        start = certificate.not_valid_before_utc
        end = certificate.not_valid_after_utc
    except Exception:
        return {"valid": False, "reason": "the certificate could not be read"}
    if moment < start:
        return {"valid": False, "reason": "the certificate is not valid yet"}
    if moment > end:
        return {
            "valid": False,
            "reason": f"the certificate expired on {end.date().isoformat()}",
        }
    return {"valid": True, "reason": None, "expires_on": end.date().isoformat()}


def adopt_identity(
    *,
    state_root: str | os.PathLike[str],
    machine_name: str,
    key_path: str,
    certificate_path: str,
    platform_url: str | None = None,
    root_ca: str | None = None,
    intermediate: str | None = None,
    verify: Callable[..., dict[str, Any]] | None = None,
    validity: Callable[[str], dict[str, Any]] | None = None,
    environ: MutableMapping[str, str] | None = None,
) -> dict[str, Any]:
    """Point Studio at an identity this machine already holds.

    The certificate is only adopted when it is proved to chain to the authority
    that issued it and to match the key on disk. An identity that cannot be
    proved is refused: claiming a machine is verifiable when nobody can check it
    is the one failure this product must not have.
    """

    if not _MACHINE_NAME.fullmatch(machine_name or ""):
        raise ValueError("machine name must be plain lowercase letters, digits and dashes")
    for label, candidate in (("key", key_path), ("certificate", certificate_path)):
        path = Path(candidate).expanduser()
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"the {label} file does not exist")
    if not (root_ca and intermediate) and not platform_url:
        raise ValueError(
            "adoption needs either the issuing authority files or the organization address"
        )

    window = validity or certificate_validity
    lifetime = window(str(Path(certificate_path).expanduser()))
    if not lifetime.get("valid"):
        return {
            "schema": RESULT_SCHEMA,
            "enrolled": False,
            "machine_name": machine_name,
            "headline": "This certificate cannot be used",
            "explanation": (
                "The certificate is outside the dates it was issued for: "
                f"{lifetime.get('reason')}."
            ),
            "next_step": "Ask your organization for a new invitation and enroll again.",
        }

    checker = verify or _default_verify
    arguments: dict[str, Any] = {
        "leaf_cert": str(Path(certificate_path).expanduser()),
        "signer_key": str(Path(key_path).expanduser()),
        "agent_id": machine_name,
    }
    if root_ca and intermediate:
        arguments["root_ca"] = root_ca
        arguments["intermediate"] = intermediate
    else:
        arguments["registry_base"] = platform_url
    try:
        proof = checker(**arguments)
    except Exception:
        proof = {"ok": False, "errors": ["the identity could not be checked"]}

    if not isinstance(proof, dict) or not proof.get("ok"):
        reasons = proof.get("errors") if isinstance(proof, dict) else None
        detail = "; ".join(str(item) for item in (reasons or []))[:200]
        return {
            "schema": RESULT_SCHEMA,
            "enrolled": False,
            "machine_name": machine_name,
            "headline": "This certificate could not be proved",
            "explanation": (
                "The certificate on this machine does not check out against the "
                "authority that should have issued it, so nobody else could confirm "
                "work signed with it." + (f" Reported: {detail}" if detail else "")
            ),
            "next_step": "Ask your organization for a new invitation and enroll again.",
        }

    record = _write_record(
        state_root,
        machine_name=machine_name,
        key_path=str(Path(key_path).expanduser()),
        certificate_path=str(Path(certificate_path).expanduser()),
    )
    _apply(record, environ)
    return {
        "schema": RESULT_SCHEMA,
        "enrolled": True,
        "machine_name": machine_name,
        "headline": "This machine now has a verifiable identity",
        "explanation": (
            "The certificate this machine already held was checked against the "
            "authority that issued it. Studio will use it every time it starts."
        ),
        "next_step": "Nothing to do.",
    }


def _default_verify(**kwargs: Any) -> dict[str, Any]:
    from apatch.trust_identity import verify_anchor

    return verify_anchor(**kwargs)
