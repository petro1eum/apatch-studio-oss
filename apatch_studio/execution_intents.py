"""Signed, fixed-purpose Cowork execution-intent import for Studio OSS."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Self
from urllib.parse import urlsplit
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apatch_studio.governed_work_gateway import (
    APatchGovernedWorkGateway,
    GovernedWorkGateway,
)
from apatch_studio.intent_store import INTENT_RECORD_SCHEMA, IntentStore
from apatch_studio.operations import AgentRunRequest, ExecutionContext, RunnerId
from apatch_studio.result_delivery import (
    CoworkResultDelivery,
    ResultDeliveryError,
    ResultPreviewRequest,
    ResultSubmitRequest,
)

EXECUTION_INTENT_SCHEMA = "trustchain.apatch-studio.execution-intent.v1"
TRUST_SCHEMA = "apatch.studio.execution-intent-trust.v1"
SIGNING_DOMAIN = (
    b"TrustChain-Governed-Work\x00v1\x00"
    b"apatch_studio.execution_intent.issue\x00"
)
_HASH_PATTERN = r"^sha256:[0-9a-f]{64}$"
_KEY_ID_PATTERN = r"^ed25519:sha256:[0-9a-f]{64}$"
_TIMESTAMP_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
MAX_ENVELOPE_BYTES = 16 * 1024


class ExecutionIntentError(RuntimeError):
    """A stable, content-safe execution-intent failure."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "invalid_execution_intent",
        status_code: int = 422,
    ):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class IntentSignature(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    algorithm: Literal["Ed25519"]
    key_id: str = Field(pattern=_KEY_ID_PATTERN)
    value: str = Field(min_length=86, max_length=86)

    @field_validator("value")
    @classmethod
    def validate_signature(cls, value: str) -> str:
        _decode_base64url(value, expected_length=64)
        return value


class ExecutionIntentEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema: Literal["trustchain.apatch-studio.execution-intent.v1"]
    intent_id: str = Field(pattern=r"^tcapsei_[0-9a-f]{32}$")
    tenant_id: str = Field(
        pattern=(
            r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-"
            r"[0-9a-f]{4}-[0-9a-f]{12}$"
        )
    )
    project_group_id: str = Field(pattern=r"^tcpg_[0-9a-f]{32}$")
    work_item_id: str = Field(pattern=r"^tcpwi_[0-9a-f]{32}$")
    work_item_hash: str = Field(pattern=_HASH_PATTERN)
    authority_version: int = Field(ge=1, le=2_147_483_647)
    work_program_id: str = Field(pattern=r"^tcwp_[0-9a-f]{32}$")
    work_program_hash: str = Field(pattern=_HASH_PATTERN)
    mode: Literal["new_change"]
    objective: str = Field(min_length=3, max_length=2000)
    acceptance_criteria: list[str] = Field(min_length=1, max_length=12)
    audience: Literal["apatch-studio"]
    nonce: str = Field(min_length=43, max_length=43)
    issued_at: str
    expires_at: str
    signature: IntentSignature

    @field_validator("tenant_id")
    @classmethod
    def validate_tenant_id(cls, value: str) -> str:
        try:
            parsed = UUID(value)
        except ValueError as exc:
            raise ValueError("tenant_id must be a canonical UUID") from exc
        if str(parsed) != value:
            raise ValueError("tenant_id must be a canonical UUID")
        return value

    @field_validator("objective")
    @classmethod
    def validate_objective(cls, value: str) -> str:
        if value != value.strip() or "\x00" in value:
            raise ValueError("objective must be bounded plain text")
        return value

    @field_validator("acceptance_criteria")
    @classmethod
    def validate_criteria(cls, values: list[str]) -> list[str]:
        for value in values:
            if not isinstance(value, str) or not 3 <= len(value) <= 500:
                raise ValueError("acceptance criteria must contain 3..500 characters")
            if value != value.strip() or "\x00" in value:
                raise ValueError("acceptance criteria must be bounded plain text")
        return values

    @field_validator("nonce")
    @classmethod
    def validate_nonce(cls, value: str) -> str:
        _decode_base64url(value, expected_length=32)
        return value

    @field_validator("issued_at", "expires_at")
    @classmethod
    def validate_timestamp(cls, value: str) -> str:
        _parse_timestamp(value)
        return value

    @model_validator(mode="after")
    def validate_window(self) -> Self:
        issued = _parse_timestamp(self.issued_at)
        expires = _parse_timestamp(self.expires_at)
        duration = (expires - issued).total_seconds()
        if not 0 < duration <= 300:
            raise ValueError("execution intent lifetime must be in 1..300 seconds")
        return self


class ExecutionIntentConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    confirmed: Literal[True]
    workspace_id: str = Field(pattern=r"^[0-9a-f]{32}$")
    runner_id: RunnerId
    mode: Literal["new_change", "specification"] = "new_change"
    spec_id: str | None = Field(
        default=None,
        pattern=r"^SPEC-[A-Z0-9][A-Z0-9-]{1,95}$",
    )

    @model_validator(mode="after")
    def validate_local_execution_choice(self) -> Self:
        if self.mode == "specification" and self.spec_id is None:
            raise ValueError("specification mode requires a local spec_id")
        if self.mode == "new_change" and self.spec_id is not None:
            raise ValueError("new_change cannot select an existing spec_id")
        return self


def _parse_timestamp(value: str) -> datetime:
    if not isinstance(value, str) or not _TIMESTAMP_PATTERN.fullmatch(value):
        raise ValueError("timestamp must be UTC with six fractional digits")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)


def _decode_base64url(value: str, *, expected_length: int) -> bytes:
    if not isinstance(value, str) or "=" in value or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("invalid unpadded base64url value")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except ValueError as exc:
        raise ValueError("invalid unpadded base64url value") from exc
    encoded = base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=")
    if encoded != value or len(decoded) != expected_length:
        raise ValueError("invalid unpadded base64url length")
    return decoded


def _normalize_nfc(value: Any) -> Any:
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_normalize_nfc(item) for item in value]
    if isinstance(value, dict):
        return {
            _normalize_nfc(key): _normalize_nfc(item) for key, item in value.items()
        }
    return value


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        _normalize_nfc(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ExecutionIntentError("duplicate JSON member", code="noncanonical_envelope")
        result[key] = value
    return result


def _parse_canonical_envelope(raw: bytes) -> tuple[dict[str, Any], ExecutionIntentEnvelope]:
    if not raw or len(raw) > MAX_ENVELOPE_BYTES:
        raise ExecutionIntentError("execution intent body size is invalid")
    try:
        document = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicates)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ExecutionIntentError("execution intent must be canonical JSON") from exc
    try:
        canonical = _canonical_json(document)
    except UnicodeError as exc:
        raise ExecutionIntentError("execution intent must be canonical UTF-8 JSON") from exc
    if not isinstance(document, dict) or canonical != raw:
        raise ExecutionIntentError(
            "execution intent must use exact canonical JSON", code="noncanonical_envelope"
        )
    try:
        envelope = ExecutionIntentEnvelope.model_validate(document)
    except ValueError as exc:
        raise ExecutionIntentError("execution intent envelope is invalid") from exc
    return document, envelope


def normalize_trusted_origin(value: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("trusted execution-intent origins must be exact HTTPS origins")
    host = parsed.hostname.lower()
    port = f":{parsed.port}" if parsed.port is not None else ""
    return f"https://{host}{port}"


@dataclass(frozen=True)
class ExecutionIntentTrust:
    """Public, rotatable execution-intent authority pins."""

    keys: Mapping[str, Ed25519PublicKey]
    origins: frozenset[str]

    @classmethod
    def empty(cls) -> "ExecutionIntentTrust":
        return cls(keys={}, origins=frozenset())

    @classmethod
    def from_document(cls, document: dict[str, Any]) -> "ExecutionIntentTrust":
        if not isinstance(document, dict) or set(document) != {
            "schema",
            "trusted_origins",
            "keys",
        }:
            raise ValueError("execution-intent trust document shape is invalid")
        if document["schema"] != TRUST_SCHEMA:
            raise ValueError("unsupported execution-intent trust schema")
        raw_origins = document["trusted_origins"]
        raw_keys = document["keys"]
        if not isinstance(raw_origins, list) or not 1 <= len(raw_origins) <= 16:
            raise ValueError("trusted_origins must contain 1..16 exact origins")
        if not isinstance(raw_keys, list) or not 1 <= len(raw_keys) <= 32:
            raise ValueError("keys must contain 1..32 public keys")
        origins = frozenset(normalize_trusted_origin(str(origin)) for origin in raw_origins)
        keys: dict[str, Ed25519PublicKey] = {}
        for row in raw_keys:
            if not isinstance(row, dict) or set(row) != {"key_id", "public_key"}:
                raise ValueError("execution-intent public key shape is invalid")
            key_id = row["key_id"]
            if not isinstance(key_id, str) or not re.fullmatch(_KEY_ID_PATTERN, key_id):
                raise ValueError("invalid execution-intent key_id")
            raw_key = _decode_base64url(str(row["public_key"]), expected_length=32)
            expected = "ed25519:sha256:" + hashlib.sha256(raw_key).hexdigest()
            if key_id != expected or key_id in keys:
                raise ValueError("execution-intent public key identity mismatch")
            keys[key_id] = Ed25519PublicKey.from_public_bytes(raw_key)
        return cls(keys=keys, origins=origins)

    @classmethod
    def from_path(cls, path: str | os.PathLike[str]) -> "ExecutionIntentTrust":
        source = Path(path).expanduser().resolve()
        if not source.is_file() or source.stat().st_size > 128 * 1024:
            raise ValueError("execution-intent trust file is unavailable")
        try:
            document = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("execution-intent trust file is invalid") from exc
        return cls.from_document(document)


class ExecutionIntentManager:
    """Validate, journal and consume one-time external work intents."""

    def __init__(
        self,
        workspace: str | os.PathLike[str],
        *,
        run_manager: Any,
        trust: ExecutionIntentTrust | None = None,
        state_root: str | os.PathLike[str] | None = None,
        clock: Callable[[], datetime] | None = None,
        governed_work_gateway: GovernedWorkGateway | None = None,
        result_delivery: Any | None = None,
    ):
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace_id = hashlib.sha256(str(self.workspace).encode("utf-8")).hexdigest()[:32]
        self.run_manager = run_manager
        self.trust = trust or ExecutionIntentTrust.empty()
        self.store = IntentStore(self.workspace, state_root=state_root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.governed_work_gateway = (
            governed_work_gateway or APatchGovernedWorkGateway(self.workspace)
        )
        self.result_delivery = result_delivery or CoworkResultDelivery(self.workspace)
        self._reconcile_inflight()

    @property
    def trusted_origins(self) -> frozenset[str]:
        return self.trust.origins

    @property
    def cowork_connected(self) -> bool:
        return self.governed_work_gateway.connected

    def summary(self) -> dict[str, Any]:
        items = self.list()
        return {
            "schema": "apatch.studio.execution-intent-summary.v1",
            "available": True,
            "configured": bool(self.trust.keys and self.trust.origins),
            "workspace_id": self.workspace_id,
            "cowork_connected": self.cowork_connected,
            "pending": sum(
                item["status"] == "awaiting_local_confirmation" for item in items
            ),
            "attention": sum(
                item["status"] == "manual_review"
                or item["cowork"]["status"] == "acceptance_failed"
                for item in items
            ),
        }

    def import_raw(self, raw: bytes) -> dict[str, Any]:
        document, envelope = _parse_canonical_envelope(raw)
        unsigned = dict(document)
        signature_document = unsigned.pop("signature")
        canonical_unsigned = _canonical_json(unsigned)
        document_hash = _sha256(canonical_unsigned)
        envelope_hash = _sha256(raw)
        public_key = self.trust.keys.get(envelope.signature.key_id)
        if public_key is None:
            raise ExecutionIntentError(
                "execution-intent authority is not trusted",
                code="untrusted_execution_intent_authority",
                status_code=403,
            )
        try:
            public_key.verify(
                _decode_base64url(signature_document["value"], expected_length=64),
                SIGNING_DOMAIN + canonical_unsigned,
            )
        except InvalidSignature as exc:
            raise ExecutionIntentError(
                "execution-intent signature is invalid",
                code="invalid_execution_intent_signature",
                status_code=403,
            ) from exc

        now = self._utc_now()
        issued = _parse_timestamp(envelope.issued_at)
        expires = _parse_timestamp(envelope.expires_at)
        if now < issued or now > expires:
            raise ExecutionIntentError(
                "execution intent is not currently valid",
                code="execution_intent_expired",
                status_code=410,
            )
        nonce_digest = _sha256(_decode_base64url(envelope.nonce, expected_length=32))
        new_record = {
            "schema": INTENT_RECORD_SCHEMA,
            "intent_id": envelope.intent_id,
            "tenant_id": envelope.tenant_id,
            "project_group_id": envelope.project_group_id,
            "work_item_id": envelope.work_item_id,
            "work_item_hash": envelope.work_item_hash,
            "authority_version": envelope.authority_version,
            "work_program_id": envelope.work_program_id,
            "work_program_hash": envelope.work_program_hash,
            "objective": envelope.objective,
            "acceptance_criteria": list(envelope.acceptance_criteria),
            "issued_at": envelope.issued_at,
            "expires_at": envelope.expires_at,
            "received_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "status": "awaiting_local_confirmation",
            "document_hash": document_hash,
            "envelope_hash": envelope_hash,
            "nonce_digest": nonce_digest,
            "run_id": None,
            "consumed_at": None,
            "cowork_status": (
                "awaiting_local_acceptance"
                if self.cowork_connected
                else "not_connected"
            ),
            "cowork_change_id": None,
            "cowork_source_binding_id": None,
            "cowork_result_state": "not_submitted",
            "cowork_result_plan_hash": None,
            "cowork_result_outcome_ref": None,
            "cowork_result_evidence_bundle_id": None,
            "cowork_result_evidence_bundle_hash": None,
            "cowork_result_release_id": None,
            "cowork_result_release_hash": None,
            "cowork_result_updated_at": None,
        }

        def admit(records: list[dict[str, Any]]) -> dict[str, Any]:
            for record in records:
                same_id = record["intent_id"] == envelope.intent_id
                same_nonce = record["nonce_digest"] == nonce_digest
                if same_id:
                    if (
                        same_nonce
                        and record["envelope_hash"] == envelope_hash
                        and record["status"] == "awaiting_local_confirmation"
                    ):
                        return self._project(record)
                    code = (
                        "execution_intent_replay"
                        if same_nonce
                        else "execution_intent_equivocation"
                    )
                    raise ExecutionIntentError(
                        "execution intent was already used or conflicts with a prior import",
                        code=code,
                        status_code=409,
                    )
                if same_nonce:
                    raise ExecutionIntentError(
                        "execution-intent nonce was already observed",
                        code="execution_intent_replay",
                        status_code=409,
                    )
            records.append(new_record)
            return self._project(new_record)

        return self.store.update_with_envelope(envelope.intent_id, raw, admit)

    def list(self) -> list[dict[str, Any]]:
        self._expire_pending()
        return [self._project(record) for record in reversed(self.store.load())]

    def get(self, intent_id: str) -> dict[str, Any]:
        self._expire_pending()
        return self._project(self._find(self.store.load(), intent_id))

    def preview_result(
        self,
        intent_id: str,
        request: ResultPreviewRequest,
    ) -> dict[str, Any]:
        record = self._find(self.store.load(), intent_id)
        if record["cowork_result_state"] == "submitted":
            raise ResultDeliveryError("this assignment result is already submitted")
        return self.result_delivery.preview(
            record,
            relative_path=request.relative_path,
        )

    def submit_result(
        self,
        intent_id: str,
        request: ResultSubmitRequest,
    ) -> dict[str, Any]:
        snapshot = self._find(self.store.load(), intent_id)
        plan_hash = str(request.plan.get("plan_hash") or "")
        if snapshot["cowork_result_state"] == "submitted":
            if (
                plan_hash != snapshot["cowork_result_plan_hash"]
                or request.confirmation != f"submit:{plan_hash}"
            ):
                raise ResultDeliveryError("result retry conflicts with the submitted receipt")
            return self._result_projection(snapshot)

        receipt = self.result_delivery.submit(
            snapshot,
            relative_path=request.relative_path,
            plan=request.plan,
            confirmation=request.confirmation,
        )
        result = request.plan.get("result")
        evidence = request.plan.get("evidence")
        if (
            not isinstance(result, dict)
            or not isinstance(evidence, dict)
            or not re.fullmatch(_HASH_PATTERN, plan_hash)
            or not re.fullmatch(_HASH_PATTERN, str(result.get("outcome_ref") or ""))
            or not re.fullmatch(r"^apweb_[0-9a-f]{32}$", str(evidence.get("bundle_id") or ""))
            or not re.fullmatch(_HASH_PATTERN, str(evidence.get("bundle_hash") or ""))
            or not isinstance(receipt, dict)
            or receipt.get("schema") != "trustchain.apatch-studio.result-delivery.v1"
            or receipt.get("project_group_id") != snapshot["project_group_id"]
            or receipt.get("work_item_id") != snapshot["work_item_id"]
            or not re.fullmatch(r"^tcwr_[0-9a-f]{32}$", str(receipt.get("release_id") or ""))
            or not re.fullmatch(_HASH_PATTERN, str(receipt.get("release_hash") or ""))
            or receipt.get("state") != "submitted"
        ):
            raise ResultDeliveryError("Cowork returned an invalid submitted receipt")
        now = self._utc_now().isoformat()

        def persist(records: list[dict[str, Any]]) -> dict[str, Any]:
            current = self._find(records, intent_id)
            if current["cowork_result_state"] == "submitted":
                if current["cowork_result_plan_hash"] != plan_hash:
                    raise ResultDeliveryError(
                        "result retry conflicts with the submitted receipt"
                    )
                return self._result_projection(current)
            if current["status"] != "consumed" or current["cowork_status"] != "source_bound":
                raise ResultDeliveryError("assignment is not ready for result submission")
            current.update(
                {
                    "cowork_result_state": "submitted",
                    "cowork_result_plan_hash": plan_hash,
                    "cowork_result_outcome_ref": result["outcome_ref"],
                    "cowork_result_evidence_bundle_id": evidence["bundle_id"],
                    "cowork_result_evidence_bundle_hash": evidence["bundle_hash"],
                    "cowork_result_release_id": receipt["release_id"],
                    "cowork_result_release_hash": receipt["release_hash"],
                    "cowork_result_updated_at": now,
                    "updated_at": now,
                }
            )
            return self._result_projection(current)

        return self.store.update(persist)

    def cancel(self, intent_id: str) -> dict[str, Any]:
        now = self._utc_now().isoformat()

        def cancel_record(records: list[dict[str, Any]]) -> dict[str, Any]:
            record = self._find(records, intent_id)
            if record["status"] != "awaiting_local_confirmation":
                raise ExecutionIntentError(
                    "execution intent cannot be cancelled in its current state",
                    code="execution_intent_terminal",
                    status_code=409,
                )
            record["status"] = "cancelled"
            record["updated_at"] = now
            return self._project(record)

        result = self.store.update(cancel_record)
        try:
            self.store.delete_envelope(intent_id)
        except Exception:
            pass
        return result

    def confirm(
        self,
        intent_id: str,
        confirmation: ExecutionIntentConfirmation,
    ) -> dict[str, Any]:
        if confirmation.workspace_id != self.workspace_id:
            raise ExecutionIntentError(
                "selected workspace does not match this Studio instance",
                code="workspace_identity_mismatch",
                status_code=409,
            )
        self._expire_pending()
        snapshot = self._find(self.store.load(), intent_id)
        connected = self.cowork_connected
        cowork_required = connected or snapshot["cowork_status"] not in {
            "not_connected",
            "local_only",
        }
        already_bound = snapshot["cowork_status"] == "source_bound"
        if cowork_required and confirmation.mode != "specification":
            raise ExecutionIntentError(
                "Cowork assignments require one exact existing local SPEC",
                code="cowork_requires_existing_spec",
                status_code=409,
            )
        if cowork_required and not connected and not already_bound:
            raise ExecutionIntentError(
                "Cowork connection is required before accepting this assignment",
                code="cowork_connection_required",
                status_code=503,
            )
        now = self._utc_now().isoformat()

        def begin(records: list[dict[str, Any]]) -> dict[str, Any]:
            record = self._find(records, intent_id)
            if record["status"] != "awaiting_local_confirmation":
                raise ExecutionIntentError(
                    "execution intent cannot be consumed in its current state",
                    code="execution_intent_replay",
                    status_code=409,
                )
            record["status"] = "consuming"
            if cowork_required and record["cowork_status"] != "source_bound":
                record["cowork_status"] = "accepting"
            elif not cowork_required:
                record["cowork_status"] = "local_only"
            record["updated_at"] = now
            return dict(record)

        record = self.store.update(begin)
        if cowork_required and not already_bound:
            try:
                raw = self.store.load_envelope(intent_id)
                if _sha256(raw) != record["envelope_hash"]:
                    raise RuntimeError("private envelope hash mismatch")
                proposal_document, _proposal = _parse_canonical_envelope(raw)
                receipt = self.governed_work_gateway.accept_and_bind(
                    proposal_document,
                    spec_id=confirmation.spec_id or "",
                )
                if receipt.get("status") != "source_bound":
                    raise RuntimeError("source binding acknowledgement missing")
            except Exception as exc:
                self._restore_pending(intent_id, cowork_status="acceptance_failed")
                raise ExecutionIntentError(
                    "Cowork acceptance or source binding was not acknowledged",
                    code="cowork_acceptance_incomplete",
                    status_code=502,
                ) from exc

            bound_at = self._utc_now().isoformat()

            def mark_bound(records: list[dict[str, Any]]) -> dict[str, Any]:
                current = self._find(records, intent_id)
                if current["status"] != "consuming":
                    raise ExecutionIntentError(
                        "execution-intent consume state changed unexpectedly",
                        code="execution_intent_state_conflict",
                        status_code=409,
                    )
                current["cowork_status"] = "source_bound"
                current["cowork_change_id"] = receipt["change_id"]
                current["cowork_source_binding_id"] = receipt["source_binding_id"]
                current["updated_at"] = bound_at
                return dict(current)

            record = self.store.update(mark_bound)

        if confirmation.mode == "specification":
            request = AgentRunRequest(
                mode="specification",
                runner=confirmation.runner_id,
                objective=record["objective"],
                spec_id=confirmation.spec_id,
            )
        else:
            request = AgentRunRequest(
                mode="new_change",
                runner=confirmation.runner_id,
                objective=record["objective"],
                acceptance_criteria=record["acceptance_criteria"],
            )
        context = ExecutionContext(
            intent_id=record["intent_id"],
            tenant_id=record["tenant_id"],
            project_group_id=record["project_group_id"],
            work_item_id=record["work_item_id"],
            work_item_hash=record["work_item_hash"],
            authority_version=record["authority_version"],
            work_program_id=record["work_program_id"],
            work_program_hash=record["work_program_hash"],
            document_hash=record["document_hash"],
            envelope_hash=record["envelope_hash"],
        )
        try:
            run = self.run_manager.start(request, execution_context=context)
            run_id = run.get("run_id")
            if not isinstance(run_id, str):
                raise RuntimeError("local run manager returned no run id")
        except Exception:
            self._restore_pending(intent_id)
            raise

        consumed_at = self._utc_now().isoformat()

        def finish(records: list[dict[str, Any]]) -> dict[str, Any]:
            current = self._find(records, intent_id)
            if current["status"] != "consuming":
                raise ExecutionIntentError(
                    "execution-intent consume state changed unexpectedly",
                    code="execution_intent_state_conflict",
                    status_code=409,
                )
            current["status"] = "consumed"
            current["run_id"] = run_id
            current["consumed_at"] = consumed_at
            current["updated_at"] = consumed_at
            return self._project(current)

        result = self.store.update(finish)
        try:
            self.store.delete_envelope(intent_id)
        except Exception:
            pass
        return result

    def _restore_pending(
        self,
        intent_id: str,
        *,
        cowork_status: str | None = None,
    ) -> None:
        now = self._utc_now().isoformat()

        def restore(records: list[dict[str, Any]]) -> None:
            record = self._find(records, intent_id)
            if record["status"] == "consuming":
                record["status"] = "awaiting_local_confirmation"
                if cowork_status is not None and record["cowork_status"] != "source_bound":
                    record["cowork_status"] = cowork_status
                record["updated_at"] = now

        self.store.update(restore)

    def _reconcile_inflight(self) -> None:
        now = self._utc_now().isoformat()

        def reconcile(records: list[dict[str, Any]]) -> None:
            for record in records:
                if record["status"] == "consuming":
                    record["status"] = "manual_review"
                    record["updated_at"] = now

        self.store.update(reconcile)

    def _expire_pending(self) -> None:
        now = self._utc_now()
        stamp = now.isoformat()

        def expire(records: list[dict[str, Any]]) -> list[str]:
            expired_ids = []
            for record in records:
                if (
                    record["status"] == "awaiting_local_confirmation"
                    and now > _parse_timestamp(record["expires_at"])
                ):
                    record["status"] = "expired"
                    record["updated_at"] = stamp
                    expired_ids.append(record["intent_id"])
            return expired_ids

        for expired_id in self.store.update(expire):
            try:
                self.store.delete_envelope(expired_id)
            except Exception:
                pass

    def _utc_now(self) -> datetime:
        value = self.clock()
        if value.tzinfo is None:
            raise RuntimeError("execution-intent clock must be timezone-aware")
        return value.astimezone(timezone.utc)

    @staticmethod
    def _find(records: list[dict[str, Any]], intent_id: str) -> dict[str, Any]:
        for record in records:
            if record["intent_id"] == intent_id:
                return record
        raise ExecutionIntentError(
            "execution intent not found",
            code="execution_intent_not_found",
            status_code=404,
        )

    @staticmethod
    def _result_projection(record: Mapping[str, Any]) -> dict[str, Any]:
        submitted = record["cowork_result_state"] == "submitted"
        return {
            "schema": "apatch.studio.cowork-result-delivery.v1",
            "intent_id": record["intent_id"],
            "state": record["cowork_result_state"],
            "plan_hash": record["cowork_result_plan_hash"],
            "result": {
                "outcome_ref": record["cowork_result_outcome_ref"],
            },
            "evidence": {
                "bundle_id": record["cowork_result_evidence_bundle_id"],
                "bundle_hash": record["cowork_result_evidence_bundle_hash"],
            },
            "release": {
                "release_id": record["cowork_result_release_id"],
                "release_hash": record["cowork_result_release_hash"],
                "state": "submitted" if submitted else None,
            },
            "updated_at": record["cowork_result_updated_at"],
        }

    def _project(self, record: dict[str, Any]) -> dict[str, Any]:
        connected = self.cowork_connected
        cowork_status = record["cowork_status"]
        if (
            connected
            and cowork_status == "not_connected"
            and record["status"] == "awaiting_local_confirmation"
        ):
            cowork_status = "awaiting_local_acceptance"
        return {
            "schema": "apatch.studio.execution-intent-preview.v1",
            "intent_id": record["intent_id"],
            "tenant_id": record["tenant_id"],
            "project_group_id": record["project_group_id"],
            "work_item_id": record["work_item_id"],
            "work_item_hash": record["work_item_hash"],
            "authority_version": record["authority_version"],
            "work_program_id": record["work_program_id"],
            "work_program_hash": record["work_program_hash"],
            "objective": record["objective"],
            "acceptance_criteria": list(record["acceptance_criteria"]),
            "issued_at": record["issued_at"],
            "expires_at": record["expires_at"],
            "received_at": record["received_at"],
            "status": record["status"],
            "document_hash": record["document_hash"],
            "envelope_hash": record["envelope_hash"],
            "run_id": record["run_id"],
            "cowork": {
                "connected": connected,
                "required": connected
                or record["cowork_status"] not in {"not_connected", "local_only"},
                "status": cowork_status,
                "change_id": record["cowork_change_id"],
                "source_binding_id": record["cowork_source_binding_id"],
            },
            "result_delivery": {
                **self._result_projection(record),
                "can_prepare": (
                    record["status"] == "consumed"
                    and record["cowork_status"] == "source_bound"
                    and record["cowork_result_state"] == "not_submitted"
                ),
            },
            "can_confirm": record["status"] == "awaiting_local_confirmation",
            "can_cancel": record["status"] == "awaiting_local_confirmation",
        }
