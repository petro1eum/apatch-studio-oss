"""Signed delivery records composed from canonical APatch change facts."""

from __future__ import annotations

import base64
import getpass
import hashlib
import json
import math
import os
import re
import secrets
import stat
import threading
import unicodedata
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apatch_studio.projection import assert_projection_safe
from apatch_studio.run_store import _lock, _unlock, default_state_root, workspace_identity

_DELIVERY_DOMAIN = b"APatch-Studio-Delivery\x00v1\x00"
_REQUIRED_PERSPECTIVES = frozenset({"positive", "negative", "boundary", "regression"})
_REQUEST_ID = r"^apsreq_[a-z0-9][a-z0-9_-]{7,95}$"
_HASH = r"^sha256:[0-9a-f]{64}$"
_CHANGE_ID = re.compile(r"^apchg_[0-9a-f]{32}$")
_MAX_NOTE = 1000
_MAX_TEXT = 2000
_PROCESS_LOCK = threading.RLock()


class DeliveryPackError(RuntimeError):
    """A delivery record cannot be projected or changed safely."""

    def __init__(self, message: str, *, code: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class AcceptanceActRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(pattern=_REQUEST_ID)
    expected_basis_hash: str = Field(pattern=_HASH)
    decision: Literal[
        "accepted",
        "accepted_with_reservations",
        "changes_requested",
        "rejected",
    ]
    note: str = Field(default="", max_length=_MAX_NOTE)
    confirmed: bool = False

    @field_validator("note")
    @classmethod
    def bounded_note(cls, value: str) -> str:
        if "\x00" in value or value != value.strip():
            raise ValueError("note must be bounded plain text")
        return unicodedata.normalize("NFC", value)

    @model_validator(mode="after")
    def reservation_has_reason(self):
        if self.decision == "accepted_with_reservations" and len(self.note) < 3:
            raise ValueError("acceptance reservations require a reason")
        return self


class AcceptedTimeDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(pattern=_REQUEST_ID)
    expected_basis_hash: str = Field(pattern=_HASH)
    expected_effort_hash: str = Field(pattern=_HASH)
    decision: Literal["accepted", "rejected"]
    accepted_hours: float | None = Field(default=None, ge=0, le=100_000)
    note: str = Field(default="", max_length=_MAX_NOTE)
    confirmed: bool = False

    @field_validator("accepted_hours")
    @classmethod
    def finite_hours(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("accepted hours must be finite")
        return value

    @field_validator("note")
    @classmethod
    def bounded_note(cls, value: str) -> str:
        if "\x00" in value or value != value.strip():
            raise ValueError("note must be bounded plain text")
        return unicodedata.normalize("NFC", value)

    @model_validator(mode="after")
    def decision_shape(self):
        if self.decision == "accepted" and self.accepted_hours is None:
            raise ValueError("accepted time requires explicit hours")
        if self.decision == "rejected" and self.accepted_hours is not None:
            raise ValueError("rejected time cannot include accepted hours")
        return self


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize(item) for item in value]
    if isinstance(value, tuple):
        return [_normalize(item) for item in value]
    if isinstance(value, Mapping):
        return {_normalize(str(key)): _normalize(item) for key, item in value.items()}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    raise DeliveryPackError(
        f"unsupported canonical value: {type(value).__name__}",
        code="delivery_document_invalid",
        status_code=422,
    )


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            _normalize(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise DeliveryPackError(
            "delivery document is not canonical",
            code="delivery_document_invalid",
            status_code=422,
        ) from exc


def _canonical_roundtrip(value: Mapping[str, Any]) -> dict[str, Any]:
    return json.loads(_canonical_json(value))


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _document_hash(value: Mapping[str, Any]) -> str:
    payload = dict(value)
    payload.pop("document_hash", None)
    return _sha256(_canonical_json(payload))


def _request_hash(command: str, request: BaseModel) -> str:
    return _sha256(
        _canonical_json(
            {
                "schema": "apatch.studio.delivery-request.v1",
                "command": command,
                "payload": request.model_dump(mode="json"),
            }
        )
    )


def _b64e(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _b64d(value: Any, expected: int) -> bytes:
    if not isinstance(value, str) or "=" in value:
        raise DeliveryPackError(
            "delivery signature is invalid",
            code="delivery_signature_invalid",
            status_code=422,
        )
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (TypeError, ValueError) as exc:
        raise DeliveryPackError(
            "delivery signature is invalid",
            code="delivery_signature_invalid",
            status_code=422,
        ) from exc
    if len(decoded) != expected or _b64e(decoded) != value:
        raise DeliveryPackError(
            "delivery signature is invalid",
            code="delivery_signature_invalid",
            status_code=422,
        )
    return decoded


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        raise DeliveryPackError(
            "delivery clock must be timezone-aware",
            code="delivery_clock_invalid",
            status_code=500,
        )
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _plain(value: Any, *, limit: int = _MAX_TEXT, fallback: str = "") -> str:
    text = " ".join(str(value or "").split())
    return unicodedata.normalize("NFC", text[:limit]) or fallback


def _safe_hash(value: Any) -> str | None:
    text = str(value or "")
    return text if re.fullmatch(_HASH, text) else None


def _count(value: Any) -> int:
    return max(0, int(value or 0))


def _safe_ref(value: Any, *, limit: int = 192) -> str | None:
    text = _plain(value, limit=limit)
    if not text or text.startswith("/") or "://" in text or "\\" in text:
        return None
    return text


def _decision_id(prefix: str, request_id: str, basis_hash: str) -> str:
    digest = hashlib.sha256(f"{prefix}\x00{request_id}\x00{basis_hash}".encode()).hexdigest()
    return prefix + digest[:32]


@dataclass(frozen=True)
class DeliverySigner:
    """One purpose-separated Ed25519 signer for local or injected authority."""

    private_key: Ed25519PrivateKey
    actor_id: str
    label: str
    trust: Literal["local-self-signed", "organization-authority"]
    clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc)

    @classmethod
    def from_seed(
        cls,
        seed: bytes,
        *,
        actor_id: str,
        label: str,
        trust: Literal["local-self-signed", "organization-authority"],
        clock: Callable[[], datetime] | None = None,
    ) -> "DeliverySigner":
        if len(seed) != 32:
            raise ValueError("Ed25519 seed must contain 32 bytes")
        return cls(
            private_key=Ed25519PrivateKey.from_private_bytes(seed),
            actor_id=_plain(actor_id, limit=192),
            label=_plain(label, limit=192),
            trust=trust,
            clock=clock or (lambda: datetime.now(timezone.utc)),
        )

    @property
    def public_key_bytes(self) -> bytes:
        return self.private_key.public_key().public_bytes_raw()

    @property
    def key_id(self) -> str:
        return "ed25519:sha256:" + hashlib.sha256(self.public_key_bytes).hexdigest()

    def authority(self) -> dict[str, Any]:
        return {
            "schema": "apatch.studio.delivery-authority.v1",
            "actor_id": self.actor_id,
            "label": self.label,
            "trust": self.trust,
            "key_id": self.key_id,
            "public_key": _b64e(self.public_key_bytes),
        }

    def sign(self, document: Mapping[str, Any], *, purpose: str) -> dict[str, Any]:
        if not purpose or "\x00" in purpose or "signature" in document:
            raise DeliveryPackError(
                "delivery signing request is invalid",
                code="delivery_signing_invalid",
                status_code=422,
            )
        unsigned = _normalize(dict(document))
        signature = self.private_key.sign(
            _DELIVERY_DOMAIN + purpose.encode("ascii") + b"\x00" + _canonical_json(unsigned)
        )
        return _canonical_roundtrip(
            {
                **unsigned,
                "signature": {
                    "algorithm": "Ed25519",
                    "key_id": self.key_id,
                    "purpose": purpose,
                    "value": _b64e(signature),
                },
            }
        )

    @classmethod
    def load_or_create(cls, state_root: Path) -> "DeliverySigner":
        _private_directory(state_root)
        key_path = state_root / "owner-key.json"
        lock_path = state_root / "owner-key.lock"
        with _file_lock(lock_path):
            if key_path.exists() or key_path.is_symlink():
                try:
                    value = _read_private_json(key_path)
                    if not isinstance(value, dict) or value.get("schema") != "apatch.studio.delivery-owner-key.v1":
                        raise ValueError("unknown delivery key format")
                    seed = _b64d(value["seed"], 32)
                    public = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes_raw()
                    expected_actor = "owner:local:" + hashlib.sha256(public).hexdigest()[:24]
                    if value.get("actor_id") != expected_actor or not isinstance(value.get("label"), str):
                        raise ValueError("invalid local delivery identity")
                    return cls.from_seed(
                        seed,
                        actor_id=str(value["actor_id"]),
                        label=str(value["label"]),
                        trust="local-self-signed",
                    )
                except (KeyError, OSError, ValueError, DeliveryPackError) as exc:
                    raise DeliveryPackError(
                        "local delivery signer is unavailable",
                        code="delivery_signer_unavailable",
                        status_code=503,
                    ) from exc

            if (state_root / "decisions.json").exists() or (state_root / "decisions.json").is_symlink():
                raise DeliveryPackError(
                    "delivery signer is missing; restore private identity and journal together",
                    code="delivery_signer_unavailable",
                    status_code=503,
                )
            seed = secrets.token_bytes(32)
            public = Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes_raw()
            actor_id = "owner:local:" + hashlib.sha256(public).hexdigest()[:24]
            label = f"Local owner ({getpass.getuser()})"
            _atomic_json(
                key_path,
                {
                    "schema": "apatch.studio.delivery-owner-key.v1",
                    "actor_id": actor_id,
                    "label": label,
                    "seed": _b64e(seed),
                    "created_at": _utc_text(datetime.now(timezone.utc)),
                },
            )
            return cls.from_seed(
                seed,
                actor_id=actor_id,
                label=label,
                trust="local-self-signed",
            )


def verify_delivery_signature(
    document: Mapping[str, Any],
    *,
    purpose: str,
    expected_authority: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Check cryptographic integrity; callers asserting trust must pin authority."""
    signed = dict(document)
    signature = signed.pop("signature", None)
    authority = signed.get("authority")
    if (
        not isinstance(signature, Mapping)
        or set(signature) != {"algorithm", "key_id", "purpose", "value"}
        or signature.get("algorithm") != "Ed25519"
        or signature.get("purpose") != purpose
        or not isinstance(authority, Mapping)
        or (expected_authority is not None and authority != expected_authority)
    ):
        raise DeliveryPackError(
            "delivery signature is invalid",
            code="delivery_signature_invalid",
            status_code=422,
        )
    public_bytes = _b64d(authority.get("public_key"), 32)
    key_id = "ed25519:sha256:" + hashlib.sha256(public_bytes).hexdigest()
    if authority.get("key_id") != key_id or signature.get("key_id") != key_id:
        raise DeliveryPackError(
            "delivery signature is invalid",
            code="delivery_signature_invalid",
            status_code=422,
        )
    try:
        Ed25519PublicKey.from_public_bytes(public_bytes).verify(
            _b64d(signature.get("value"), 64),
            _DELIVERY_DOMAIN + purpose.encode("ascii") + b"\x00" + _canonical_json(signed),
        )
    except InvalidSignature as exc:
        raise DeliveryPackError(
            "delivery signature is invalid",
            code="delivery_signature_invalid",
            status_code=422,
        ) from exc
    return signed


def _store_error() -> DeliveryPackError:
    return DeliveryPackError(
        "delivery decision store is invalid or unavailable; no decision was accepted",
        code="delivery_store_invalid",
        status_code=503,
    )


def _check_private_stat(info: os.stat_result, *, directory: bool = False) -> None:
    kind_ok = stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode)
    if not kind_ok or (not directory and info.st_nlink != 1):
        raise _store_error()
    if os.name != "nt" and (info.st_uid != os.getuid() or info.st_mode & 0o077):
        raise _store_error()


def _private_directory(path: Path) -> None:
    try:
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        _check_private_stat(path.lstat(), directory=True)
    except OSError as exc:
        raise _store_error() from exc


def _read_private_json(path: Path) -> Any:
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        _check_private_stat(path.lstat())
        descriptor = os.open(path, flags)
        with os.fdopen(descriptor, "r", encoding="utf-8") as handle:
            _check_private_stat(os.fstat(handle.fileno()))
            return json.load(handle)
    except (OSError, ValueError) as exc:
        raise _store_error() from exc


@contextmanager
def _file_lock(path: Path):
    _private_directory(path.parent)
    with _PROCESS_LOCK:
        try:
            if path.exists() or path.is_symlink():
                _check_private_stat(path.lstat())
            flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags, 0o600)
            handle = os.fdopen(descriptor, "r+b")
        except OSError as exc:
            raise _store_error() from exc
        with handle:
            _check_private_stat(os.fstat(handle.fileno()))
            _lock(handle, blocking=True)
            try:
                yield
            finally:
                _unlock(handle)


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    _private_directory(path.parent)
    if path.exists() or path.is_symlink():
        _check_private_stat(path.lstat())
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.{secrets.token_hex(8)}.tmp"
    )
    descriptor = os.open(
        temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(_canonical_json(value))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory_fd = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
    finally:
        if temporary.exists():
            temporary.unlink()


def _test_protocol(detail: Mapping[str, Any]) -> dict[str, Any]:
    sdd = detail.get("sdd")
    if not isinstance(sdd, Mapping) or sdd.get("available") is not True:
        protocol = {
            "schema": "apatch.studio.test-protocol.v1",
            "status": "not_recorded",
            "meaningful": False,
            "counts": {
                "collected": 0,
                "executed": 0,
                "passed": 0,
                "failed": 0,
                "skipped": 0,
            },
            "perspectives": [],
            "missing_perspectives": sorted(_REQUIRED_PERSPECTIVES),
            "falsification": {"observed_red": False, "restored_green": False},
            "checks": [],
            "check_detail_status": "not_recorded",
            "contract_hash": None,
            "envelope_hash": None,
            "evidence_hash": None,
            "blockers": ["frozen_verification_not_recorded"],
        }
        protocol["protocol_hash"] = _document_hash(protocol)
        return protocol

    raw = sdd.get("verification")
    raw = raw if isinstance(raw, Mapping) else {}
    counts = {
        "collected": _count(raw.get("collected")),
        "executed": _count(raw.get("executed")),
        "passed": _count(raw.get("passed")),
        "failed": _count(raw.get("failed")),
        "skipped": _count(raw.get("skipped")),
    }
    perspectives = sorted(
        {
            item
            for item in (_plain(value, limit=64) for value in raw.get("perspectives") or [])
            if item
        }
    )
    missing = sorted(_REQUIRED_PERSPECTIVES - set(perspectives))
    falsification_raw = raw.get("falsification")
    falsification_raw = (
        falsification_raw if isinstance(falsification_raw, Mapping) else {}
    )
    falsification = {
        "observed_red": falsification_raw.get("observed_red") is True,
        "restored_green": falsification_raw.get("restored_green") is True,
    }
    blockers: list[str] = []
    if counts["collected"] == 0:
        blockers.append("no_tests_collected")
    if counts["executed"] == 0:
        blockers.append("no_tests_executed")
    if counts["executed"] > 0 and counts["passed"] == 0 and (
        counts["skipped"] >= counts["executed"]
    ):
        blockers.append("all_tests_skipped")
    if counts["failed"] > 0:
        blockers.append("tests_failed")
    if missing:
        blockers.append("missing_perspectives")
    if not all(falsification.values()):
        blockers.append("falsification_incomplete")
    if raw.get("gate_quality") != "meaningful" or raw.get("accepted") is not True:
        blockers.append("apatch_gate_incomplete")
    for reason in raw.get("reasons") or []:
        label = _plain(reason, limit=96)
        if label:
            blockers.append("apatch:" + label)

    checks = []
    for item in list(raw.get("checks") or [])[:64]:
        if not isinstance(item, Mapping):
            continue
        test_id = _safe_ref(item.get("test_id"), limit=300)
        oracle = _plain(item.get("oracle"), limit=500)
        acceptance_id = _safe_ref(item.get("acceptance_id"), limit=96)
        if not test_id and not oracle:
            continue
        checks.append(
            {
                "acceptance_id": acceptance_id,
                "test_id": test_id,
                "oracle": oracle,
                "perspectives": sorted(
                    {
                        _plain(value, limit=64)
                        for value in item.get("perspectives") or []
                        if _plain(value, limit=64)
                    }
                ),
            }
        )

    proof = sdd.get("proof")
    proof = proof if isinstance(proof, Mapping) else {}
    meaningful = not blockers
    protocol = {
        "schema": "apatch.studio.test-protocol.v1",
        "status": "passed" if meaningful else ("failed" if counts["failed"] else "incomplete"),
        "meaningful": meaningful,
        "counts": counts,
        "perspectives": perspectives,
        "missing_perspectives": missing,
        "falsification": falsification,
        "checks": checks,
        "check_detail_status": "recorded" if checks else "not_recorded",
        "contract_hash": _safe_hash(proof.get("contract_hash")),
        "envelope_hash": _safe_hash(proof.get("envelope_hash")),
        "evidence_hash": _safe_hash(proof.get("evidence_hash")),
        "blockers": list(dict.fromkeys(blockers)),
    }
    protocol["protocol_hash"] = _document_hash(protocol)
    return protocol


def _effort(detail: Mapping[str, Any]) -> dict[str, Any]:
    sdd = detail.get("sdd")
    raw = (
        sdd.get("effort")
        if isinstance(sdd, Mapping) and sdd.get("available")
        else None
    )
    raw = raw if isinstance(raw, Mapping) else {}
    raw_verification = raw.get("verification")
    raw_verification = (
        raw_verification if isinstance(raw_verification, Mapping) else {}
    )
    verification = {
        "ok": raw_verification.get("ok") is True,
        "status": _plain(
            raw_verification.get("status"),
            limit=64,
            fallback="not_recorded",
        ),
        "checked": _count(raw_verification.get("checked")),
        "signed_event_count": _count(
            raw_verification.get("signed_event_count")
        ),
        "event_ids": [
            item
            for item in (
                _safe_ref(value)
                for value in list(raw_verification.get("event_ids") or [])[:8]
            )
            if item
        ],
        "key_ids": [
            item
            for item in (
                _safe_ref(value)
                for value in list(raw_verification.get("key_ids") or [])[:8]
            )
            if item
        ],
        "ledger_drift_count": _count(
            raw_verification.get("ledger_drift_count")
        ),
        "unsigned_count": _count(raw_verification.get("unsigned_count")),
    }
    available = (
        raw.get("derivation") == "signed_event_op_spacing"
        and verification["ok"]
        and verification["status"] == "verified"
    )
    hours = float(raw.get("draft_hours") or 0) if available else None
    if hours is not None and (not math.isfinite(hours) or hours < 0):
        available, hours = False, None
        verification["ok"] = False
        verification["status"] = "hours_invalid"
    reason = (
        None
        if available
        else _plain(
            raw.get("reason"),
            limit=96,
            fallback="signed_event_not_verified",
        )
    )
    effort = {
        "schema": "apatch.studio.effort-draft.v1",
        "available": available,
        "source": "apatch.run_timesheet",
        "derivation": (
            "signed_event_op_spacing" if available else "not_recorded"
        ),
        "draft_hours": round(hours, 6) if hours is not None else None,
        "quality": _plain(
            raw.get("quality"),
            limit=64,
            fallback="not_recorded",
        ),
        "accepted_time": False,
        "reason": reason,
        "signed_event_count": verification["signed_event_count"],
        "verification": verification,
        "method_note": _plain(
            raw.get("method_note"),
            limit=500,
            fallback=(
                "Signed-event effort detail was not recorded for this change."
            ),
        ),
        "disclaimer": (
            "Hours are APatch operation-spacing estimates, not a stopwatch, payroll "
            "record or accepted time."
        ),
    }
    effort["effort_hash"] = _document_hash(effort)
    return effort


def _recorded_files_hash(detail: Mapping[str, Any]) -> str:
    # Bind the exact available file projection, including patch bytes and metadata.
    # Do not normalize source Unicode: canonically equivalent text can differ in code.
    files = detail.get("files", [])
    if not isinstance(files, list):
        raise DeliveryPackError(
            "recorded file projection is invalid", code="delivery_files_invalid", status_code=422
        )
    try:
        raw = json.dumps(files, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return _sha256(raw.encode("utf-8"))
    except (TypeError, ValueError, UnicodeError) as exc:
        raise DeliveryPackError(
            "recorded file projection is invalid", code="delivery_files_invalid", status_code=422
        ) from exc


def _basis(detail: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    change_id = str(detail.get("change_id") or "")
    if not _CHANGE_ID.fullmatch(change_id):
        raise DeliveryPackError(
            "delivery change id is invalid",
            code="delivery_change_invalid",
            status_code=400,
        )
    project = detail.get("project")
    project = project if isinstance(project, Mapping) else {}
    summary = detail.get("summary")
    summary = summary if isinstance(summary, Mapping) else {}
    sdd = detail.get("sdd")
    sdd = sdd if isinstance(sdd, Mapping) else {}
    scope = sdd.get("scope")
    scope = scope if isinstance(scope, Mapping) else {}
    proof = sdd.get("proof")
    proof = proof if isinstance(proof, Mapping) else {}

    protocol = _test_protocol(detail)
    effort = _effort(detail)
    change = {
        "schema": "apatch.studio.delivery-change.v1",
        "change_id": change_id,
        "objective": _plain(detail.get("objective"), fallback="Recorded APatch change"),
        "status": _plain(detail.get("status"), limit=64, fallback="recorded"),
        "result_kind": _plain(detail.get("result_kind"), limit=64, fallback="code_change"),
        "updated_at": _plain(detail.get("updated_at"), limit=64),
        "spec_id": _safe_ref(detail.get("spec_id"), limit=96),
        "requirement_id": _safe_ref(detail.get("requirement_id"), limit=64),
        "project": {
            "name": _plain(project.get("name"), limit=192, fallback="Local project"),
            "repository": _safe_ref(project.get("repository"), limit=192),
            "branch": _safe_ref(project.get("branch"), limit=192),
            "head": _safe_ref(project.get("head"), limit=192),
        },
        "summary": {
            "file_count": _count(summary.get("file_count")),
            "insertions": _count(summary.get("insertions")),
            "deletions": _count(summary.get("deletions")),
            "mutation_count": _count(summary.get("mutation_count")),
            "attestation_count": _count(summary.get("attestation_count")),
            "signed_event_count": _count(summary.get("signed_event_count")),
        },
    }
    basis = {
        "schema": "apatch.studio.delivery-basis.v1",
        "recorded_files_hash": _recorded_files_hash(detail),
        "change": change,
        "scope": {
            "containment": _plain(scope.get("containment"), limit=64, fallback="not_recorded"),
            "allowed": [_plain(item, limit=500) for item in list(scope.get("allowed") or [])[:64]],
            "forbidden": [
                _plain(item, limit=500) for item in list(scope.get("forbidden") or [])[:64]
            ],
            "violation_count": len(list(scope.get("violations") or [])),
        },
        "test_protocol_hash": protocol["protocol_hash"],
        "proof": {
            "status": _plain(proof.get("status"), limit=64, fallback="not_recorded"),
            "contract_hash": _safe_hash(proof.get("contract_hash")),
            "envelope_hash": _safe_hash(proof.get("envelope_hash")),
            "evidence_hash": _safe_hash(proof.get("evidence_hash")),
            "adherence": _plain(proof.get("adherence"), limit=64, fallback="unknown"),
            "mutation_count": _count(proof.get("mutation_count")),
        },
        "effort_hash": effort["effort_hash"],
    }
    basis["basis_hash"] = _document_hash(basis)
    return basis, protocol, effort


class DeliveryPackWorkflow:
    """Compose APatch facts and persist only signed human decisions."""

    def __init__(
        self,
        workspace: str | os.PathLike[str],
        *,
        signer: DeliverySigner | None = None,
        state_root: str | os.PathLike[str] | None = None,
    ):
        self.root = Path(workspace).expanduser().resolve()
        if not self.root.is_dir():
            raise ValueError(f"workspace does not exist: {self.root}")
        base = (Path(state_root).expanduser() if state_root is not None else default_state_root()).resolve()
        if base.is_relative_to(self.root):
            raise ValueError("delivery identity and journal must be outside the workspace")
        self.workspace_id = workspace_identity(self.root)
        private_root = base / "delivery-pack"
        self.state_root = private_root / self.workspace_id
        _private_directory(private_root)
        _private_directory(self.state_root)
        self.legacy_path = self.root / ".apatch" / "studio" / "delivery-pack" / "decisions.json"
        self.state_path = self.state_root / "decisions.json"
        self.lock_path = self.state_root / "decisions.lock"
        self.signer = signer or DeliverySigner.load_or_create(self.state_root)

    def _empty_store(self) -> dict[str, Any]:
        return {
            "schema": "apatch.studio.delivery-decisions.v2",
            "workspace_id": self.workspace_id,
            "authority": self.signer.authority(),
            "changes": {},
        }

    def _load(self) -> dict[str, Any]:
        if not self.state_path.exists() and not self.state_path.is_symlink():
            return self._empty_store()
        try:
            signed = _read_private_json(self.state_path)
            if not isinstance(signed, dict):
                raise _store_error()
            value = verify_delivery_signature(
                signed, purpose="delivery.decisions.store", expected_authority=self.signer.authority()
            )
            self._validate_store(value)
            return value
        except (DeliveryPackError, KeyError, TypeError, ValueError) as exc:
            raise _store_error() from exc

    def _save(self, store: dict[str, Any]) -> None:
        self._validate_store(store)
        signed = self.signer.sign(store, purpose="delivery.decisions.store")
        _atomic_json(self.state_path, signed)

    def _validate_store(self, store: Mapping[str, Any]) -> None:
        if (
            set(store) != {"schema", "workspace_id", "authority", "changes"}
            or store.get("schema") != "apatch.studio.delivery-decisions.v2"
            or store.get("workspace_id") != self.workspace_id
            or store.get("authority") != self.signer.authority()
            or not isinstance(store.get("changes"), dict)
        ):
            raise _store_error()
        for change_id, record in store["changes"].items():
            if not isinstance(change_id, str) or not _CHANGE_ID.fullmatch(change_id):
                raise _store_error()
            self._validate_record(change_id, record)

    def _validate_record(self, change_id: str, record: Any) -> None:
        if (
            not isinstance(record, dict)
            or set(record) != {"requests", "acceptance", "time_decisions"}
            or not isinstance(record["requests"], dict)
            or not isinstance(record["acceptance"], list)
            or not isinstance(record["time_decisions"], list)
        ):
            raise _store_error()
        documents = {}
        common = {"schema", "revision", "change_id", "basis_hash", "decision", "note", "recorded_at", "authority", "signature"}
        for history, command, purpose, schema, id_field, extra in (
            ("acceptance", "acceptance.record", "delivery.acceptance.record", "apatch.studio.acceptance-act.v1",
             "act_id", {"act_id", "test_protocol_hash", "technical_gaps", "result_status"}),
            ("time_decisions", "time.record", "delivery.time.record", "apatch.studio.accepted-time-decision.v1",
             "decision_id", {"decision_id", "effort_hash", "accepted_hours", "draft_hours"}),
        ):
            for revision, document in enumerate(record[history], 1):
                if not isinstance(document, dict) or set(document) != common | extra:
                    raise _store_error()
                verify_delivery_signature(document, purpose=purpose, expected_authority=self.signer.authority())
                if (
                    document["schema"] != schema
                    or type(document["revision"]) is not int or document["revision"] != revision
                    or document["change_id"] != change_id
                    or _safe_hash(document["basis_hash"]) is None
                    or not isinstance(document["recorded_at"], str)
                    or not isinstance(document[id_field], str)
                    or document[id_field] in documents
                ):
                    raise _store_error()
                datetime.strptime(document["recorded_at"], "%Y-%m-%dT%H:%M:%S.%fZ")
                if command == "acceptance.record":
                    if (
                        _safe_hash(document["test_protocol_hash"]) is None
                        or not isinstance(document["technical_gaps"], list)
                        or not all(isinstance(item, str) for item in document["technical_gaps"])
                        or not isinstance(document["result_status"], str)
                    ):
                        raise _store_error()
                else:
                    draft = document["draft_hours"]
                    if (
                        _safe_hash(document["effort_hash"]) is None
                        or type(draft) not in (float, int) or not math.isfinite(draft) or draft < 0
                    ):
                        raise _store_error()
                documents[document[id_field]] = (command, document)
        if len(record["requests"]) != len(documents):
            raise _store_error()
        seen = set()
        for request_id, receipt in record["requests"].items():
            if not isinstance(receipt, dict) or set(receipt) != {"request_hash", "command", "payload", "result"}:
                raise _store_error()
            command = receipt["command"]
            if command not in {"acceptance.record", "time.record"} or not isinstance(receipt["result"], dict):
                raise _store_error()
            model = AcceptanceActRequest if command == "acceptance.record" else AcceptedTimeDecisionRequest
            request = model.model_validate(receipt["payload"], strict=True)
            if (
                request.request_id != request_id or request.confirmed is not True
                or request.model_dump(mode="json") != receipt["payload"]
                or _request_hash(command, request) != receipt["request_hash"]
            ):
                raise _store_error()
            is_acceptance = command == "acceptance.record"
            identity = _decision_id("apsact_" if is_acceptance else "apstime_", request_id, request.expected_basis_hash)
            if identity in seen or identity not in documents:
                raise _store_error()
            seen.add(identity)
            stored_command, document = documents[identity]
            if (
                stored_command != command or receipt["result"] != document
                or document["basis_hash"] != request.expected_basis_hash
                or document["decision"] != request.decision or document["note"] != request.note
            ):
                raise _store_error()
            if not is_acceptance:
                expected_hours = round(float(request.accepted_hours), 6) if request.accepted_hours is not None else None
                if (
                    document["effort_hash"] != request.expected_effort_hash
                    or document["accepted_hours"] != expected_hours
                    or (request.accepted_hours is not None and request.accepted_hours > document["draft_hours"] + 1e-9)
                ):
                    raise _store_error()

    @staticmethod
    def _record(store: dict[str, Any], change_id: str) -> dict[str, Any]:
        # Only _load-validated private state reaches readers and retry consumers.
        return store["changes"].setdefault(
            change_id, {"requests": {}, "acceptance": [], "time_decisions": []}
        )

    def _legacy_history(self, change_id: str) -> dict[str, Any]:
        """Preserve old files without admitting their workspace-controlled key."""
        result = {"status": "not_recorded", "acceptance_count": 0, "time_decision_count": 0}
        try:
            # Never follow project-controlled links, including parent directories.
            relative = self.legacy_path.relative_to(self.root)
            cursor = self.root
            for part in relative.parts:
                cursor = cursor / part
                if cursor.is_symlink():
                    return {**result, "status": "unverified"}
            if not self.legacy_path.exists():
                return result
            result["status"] = "unverified"
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
            descriptor = os.open(self.legacy_path, flags)
            with os.fdopen(descriptor, "rb") as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    return result
                # Legacy bytes are informational only, never imported or rewritten.
                raw = handle.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                return result
            value = json.loads(raw)
            record = value.get("changes", {}).get(change_id, {}) if isinstance(value, dict) else {}
            if isinstance(record, dict):
                for source, target in (("acceptance", "acceptance_count"), ("time_decisions", "time_decision_count")):
                    if isinstance(record.get(source), list):
                        result[target] = len(record[source])
            return result
        except (OSError, ValueError, AttributeError, TypeError):
            return {**result, "status": "unverified"}

    @staticmethod
    def _current(history: list[dict[str, Any]], basis_hash: str, effort_hash: str | None = None) -> dict[str, Any]:
        latest = history[-1] if history else None
        current = latest is not None and latest["basis_hash"] == basis_hash
        if current and effort_hash is not None:
            current = latest["effort_hash"] == effort_hash
        return {
            "latest": latest if current else None,
            "history_count": len(history),
            "history": history,
            "status": "current" if current else "stale" if latest else "not_recorded",
        }

    def project(self, detail: Mapping[str, Any]) -> dict[str, Any]:
        basis, protocol, effort = _basis(detail)
        with _file_lock(self.lock_path):
            record = self._record(self._load(), basis["change"]["change_id"])
            acceptance = deepcopy(record["acceptance"])
            time_decisions = deepcopy(record["time_decisions"])

        pack = {
            "schema": "apatch.studio.delivery-pack.v1",
            "ownership": {
                "execution": "apatch",
                "verification": "apatch",
                "effort": "apatch.run_timesheet",
                "acceptance": "studio_owner_decision",
                "accepted_time": "separate_owner_decision",
            },
            "change": basis["change"],
            "scope": basis["scope"],
            "basis_hash": basis["basis_hash"],
            "recorded_files_hash": basis["recorded_files_hash"],
            "test_protocol": protocol,
            "proof": basis["proof"],
            "effort": effort,
            "acceptance": self._current(acceptance, basis["basis_hash"]),
            "time_decision": self._current(time_decisions, basis["basis_hash"], effort["effort_hash"]),
            "legacy_history": self._legacy_history(basis["change"]["change_id"]),
            "authority": self.signer.authority(),
        }
        pack["document_hash"] = _document_hash(pack)
        pack = _canonical_roundtrip(pack)
        assert_projection_safe(pack)
        return pack

    def _existing_request(
        self,
        record: Mapping[str, Any],
        *,
        request_id: str,
        request_hash: str,
    ) -> dict[str, Any] | None:
        existing = record["requests"].get(request_id)
        if existing is None:
            return None
        if existing.get("request_hash") != request_hash:
            raise DeliveryPackError(
                "request id was already used with different bytes",
                code="delivery_request_replay_mismatch",
            )
        return deepcopy(existing["result"])

    def record_acceptance(
        self,
        detail: Mapping[str, Any],
        request: AcceptanceActRequest,
    ) -> dict[str, Any]:
        if not request.confirmed:
            raise DeliveryPackError(
                "acceptance requires explicit confirmation",
                code="delivery_confirmation_required",
            )
        command = "acceptance.record"
        hashed_request = _request_hash(command, request)
        basis, protocol, _effort_draft = _basis(detail)
        if request.expected_basis_hash != basis["basis_hash"]:
            raise DeliveryPackError(
                "delivery basis changed; refresh before deciding",
                code="delivery_basis_stale",
            )
        if request.decision == "accepted" and not protocol["meaningful"]:
            raise DeliveryPackError(
                "unconditional acceptance requires a meaningful test protocol",
                code="delivery_protocol_incomplete",
            )
        if (
            basis["change"]["status"] == "rolled_back"
            and request.decision in {"accepted", "accepted_with_reservations"}
        ):
            raise DeliveryPackError(
                "a rolled-back result cannot be accepted",
                code="delivery_result_unacceptable",
            )

        with _file_lock(self.lock_path):
            store = self._load()
            record = self._record(store, basis["change"]["change_id"])
            existing = self._existing_request(
                record,
                request_id=request.request_id,
                request_hash=hashed_request,
            )
            if existing is not None:
                return existing

            act = self.signer.sign(
                {
                    "schema": "apatch.studio.acceptance-act.v1",
                    "act_id": _decision_id(
                        "apsact_", request.request_id, basis["basis_hash"]
                    ),
                    "revision": len(record["acceptance"]) + 1,
                    "change_id": basis["change"]["change_id"],
                    "basis_hash": basis["basis_hash"],
                    "test_protocol_hash": protocol["protocol_hash"],
                    "decision": request.decision,
                    "note": request.note,
                    "technical_gaps": list(protocol["blockers"]),
                    "result_status": basis["change"]["status"],
                    "recorded_at": _utc_text(self.signer.clock()),
                    "authority": self.signer.authority(),
                },
                purpose="delivery.acceptance.record",
            )
            record["acceptance"].append(act)
            record["requests"][request.request_id] = {
                "request_hash": hashed_request,
                "command": command,
                "payload": request.model_dump(mode="json"),
                "result": act,
            }
            self._save(store)
            assert_projection_safe(act)
            return deepcopy(act)

    def record_time_decision(
        self,
        detail: Mapping[str, Any],
        request: AcceptedTimeDecisionRequest,
    ) -> dict[str, Any]:
        if not request.confirmed:
            raise DeliveryPackError(
                "time decision requires explicit confirmation",
                code="delivery_confirmation_required",
            )
        command = "time.record"
        hashed_request = _request_hash(command, request)
        basis, _protocol, effort = _basis(detail)
        if request.expected_basis_hash != basis["basis_hash"]:
            raise DeliveryPackError(
                "delivery basis changed; refresh before deciding",
                code="delivery_basis_stale",
            )
        if request.expected_effort_hash != effort["effort_hash"]:
            raise DeliveryPackError(
                "effort draft changed; refresh before deciding",
                code="delivery_effort_stale",
            )
        if not effort["available"]:
            raise DeliveryPackError(
                "a verified effort draft is not available",
                code="delivery_effort_unavailable",
            )
        if request.decision == "accepted" and (
            request.accepted_hours is None
            or request.accepted_hours > float(effort["draft_hours"]) + 1e-9
        ):
            raise DeliveryPackError(
                "accepted hours cannot exceed the APatch draft",
                code="delivery_time_exceeds_draft",
            )

        with _file_lock(self.lock_path):
            store = self._load()
            record = self._record(store, basis["change"]["change_id"])
            existing = self._existing_request(
                record,
                request_id=request.request_id,
                request_hash=hashed_request,
            )
            if existing is not None:
                return existing

            decision = self.signer.sign(
                {
                    "schema": "apatch.studio.accepted-time-decision.v1",
                    "decision_id": _decision_id(
                        "apstime_", request.request_id, basis["basis_hash"]
                    ),
                    "revision": len(record["time_decisions"]) + 1,
                    "change_id": basis["change"]["change_id"],
                    "basis_hash": basis["basis_hash"],
                    "effort_hash": effort["effort_hash"],
                    "decision": request.decision,
                    "accepted_hours": (
                        round(float(request.accepted_hours), 6)
                        if request.accepted_hours is not None
                        else None
                    ),
                    "draft_hours": effort["draft_hours"],
                    "note": request.note,
                    "recorded_at": _utc_text(self.signer.clock()),
                    "authority": self.signer.authority(),
                },
                purpose="delivery.time.record",
            )
            record["time_decisions"].append(decision)
            record["requests"][request.request_id] = {
                "request_hash": hashed_request,
                "command": command,
                "payload": request.model_dump(mode="json"),
                "result": decision,
            }
            self._save(store)
            assert_projection_safe(decision)
            return deepcopy(decision)
