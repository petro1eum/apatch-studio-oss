"""Human-facing projection and commands for the frozen APatch SDD lifecycle.

Studio never owns execution, proof, specifications, or time.  The default
backend reads and invokes APatch Core; tests and integrations may inject the
same narrow facts interface.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import math
import os
import re
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Callable, Protocol

from apatch_studio.change_details import change_id_for_session
from apatch_studio.projection import assert_projection_safe
from apatch_studio.state_io import StateDirectory, check_target, read_json, write_json

_REQUIRED_PERSPECTIVES = frozenset({"positive", "negative", "boundary", "regression"})
_INTEGRITY_FLOOR = frozenset(
    {"strict_envelope", "locked_judge", "meaningful_verification", "falsification"}
)

_SPEC_ID = re.compile(r"^SPEC-[A-Z0-9][A-Z0-9-]{1,95}$")
_REQUIREMENT_ID = re.compile(r"^[A-Z][A-Z0-9_-]{0,63}$")
_MAX_PREPARED_BYTES = 1_048_576


class SddWorkflowError(RuntimeError):
    """A fixed-purpose Studio SDD action cannot proceed safely."""

    def __init__(self, message: str, *, code: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


def _utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _atomic_json(path: Path, value: Mapping[str, Any]) -> None:
    write_json(path, value)


class SddFactsBackend(Protocol):
    def preview_assignment(self, request: dict[str, Any]) -> dict[str, Any]: ...
    def freeze_contract(self, request: dict[str, Any]) -> dict[str, Any]: ...
    def project_change(self, change_id: str) -> dict[str, Any]: ...
    def propose_amendment(self, request: dict[str, Any]) -> dict[str, Any]: ...


def _core():
    try:
        from apatch import sdd_integrity
    except ImportError as exc:
        raise RuntimeError(
            "This Studio build requires an APatch Core with SDD integrity support"
        ) from exc
    return sdd_integrity


def _clean_text(value: Any, *, fallback: str = "") -> str:
    return " ".join(str(value or "").split())[:500] or fallback


def _hash_label(value: Any) -> str | None:
    text = str(value or "")
    return text if text.startswith("sha256:") and len(text) == 71 else None


def _string_list_or_empty(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_text(item) for item in value if _clean_text(item)]


def _sha256_file(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _named_judge_paths(obligation: Mapping[str, Any]) -> list[str]:
    """Workspace files this obligation already names, in the order it names them.

    ``test_id`` and the verification command both spell out judge files, often
    with a ``::node`` suffix or joined by ``+``. Reading them first means the
    common case never has to search the workspace.
    """

    found: list[str] = []
    for raw in [obligation.get("test_id"), *(obligation.get("command") or [])]:
        text = _clean_text(raw)
        if not text:
            continue
        for part in text.split("+"):
            candidate = part.split("::", 1)[0].strip()
            if candidate and "/" in candidate and candidate not in found:
                found.append(candidate)
    return found


def _entry_payload(entry: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = entry.get("payload")
    return payload if isinstance(payload, Mapping) else {}


def _session_id(payload: Mapping[str, Any]) -> str:
    return str(payload.get("governed_session_id") or payload.get("session_id") or "")


def _timestamp(entry: Mapping[str, Any]) -> str:
    value = entry.get("timestamp")
    if value in (None, ""):
        return ""
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
    except (TypeError, ValueError, OSError):
        return _clean_text(value)


def _logical_label(pattern: str) -> str:
    value = _clean_text(pattern)
    if value.startswith("tests"):
        return "Approved verification assets"
    if value.startswith("docs/RFP") or value.startswith("docs/spec"):
        return "Approved requirements and specifications"
    if value.startswith("schemas"):
        return "Approved data contracts"
    return value or "Declared project area"


def _allowed_scope(envelope: Mapping[str, Any]) -> list[str]:
    rows: list[str] = []
    rows.extend(f"Read {_logical_label(item)}" for item in envelope.get("allowed_reads") or [])
    rows.extend(f"Change {_logical_label(item)}" for item in envelope.get("allowed_writes") or [])
    rows.extend(f"Use {item}" for item in envelope.get("tools") or [])
    rows.extend(f"Connect only to {item}" for item in envelope.get("network") or [])
    rows.extend(f"Use remote target {item}" for item in envelope.get("remote") or [])
    rows.extend(f"Operate service {item}" for item in envelope.get("services") or [])
    return rows or ["No external effect has been authorized"]


def _forbidden_scope(envelope: Mapping[str, Any]) -> list[str]:
    rows = [
        f"Do not change {_logical_label(item)}"
        for item in envelope.get("forbidden_paths") or []
    ]
    if envelope.get("containment") == "mediated_only":
        rows.append("Direct shell or network access outside APatch is not contained")
    return rows or ["Anything not explicitly listed for this change"]


def _verification_projection(evidence: Mapping[str, Any]) -> dict[str, Any]:
    record = evidence.get("verification")
    record = record if isinstance(record, Mapping) else {}
    result = record.get("result")
    result = result if isinstance(result, Mapping) else {}
    decision = record.get("decision")
    decision = decision if isinstance(decision, Mapping) else {}
    falsification = evidence.get("falsification")
    falsification = falsification if isinstance(falsification, Mapping) else {}
    accepted = decision.get("accepted") is True
    contract = evidence.get("contract")
    contract = contract if isinstance(contract, Mapping) else {}
    raw_checks = (
        evidence.get("judge_assets")
        or evidence.get("obligations")
        or contract.get("obligations")
        or []
    )
    checks = []
    for item in list(raw_checks)[:64]:
        if not isinstance(item, Mapping):
            continue
        checks.append(
            {
                "acceptance_id": _clean_text(item.get("acceptance_id")),
                "test_id": _clean_text(item.get("test_id")),
                "oracle": _clean_text(item.get("oracle")),
                "perspectives": list(item.get("perspectives") or []),
            }
        )
    return {
        "capability": "non_mutating",
        "collected": int(result.get("collected") or 0),
        "executed": int(result.get("executed") or 0),
        "passed": int(result.get("passed") or 0),
        "failed": int(result.get("failed") or 0),
        "skipped": int(result.get("skipped") or 0),
        "perspectives": list(result.get("perspectives") or []),
        "falsification": {
            "observed_red": falsification.get("observed_red") is True,
            "restored_green": falsification.get("restored_green") is True,
        },
        "gate_quality": "meaningful" if accepted else "incomplete",
        "accepted": accepted,
        "reasons": list(decision.get("reasons") or []),
        "checks": checks,
    }


def _proof_projection(evidence: Mapping[str, Any]) -> dict[str, Any]:
    adherence = evidence.get("adherence")
    adherence = adherence if isinstance(adherence, Mapping) else {}
    verification = _verification_projection(evidence)
    compliant = adherence.get("status") == "compliant"
    return {
        "status": "proven" if compliant and verification["accepted"] else "needs_attention",
        "contract_hash": _hash_label(evidence.get("contract_hash")),
        "envelope_hash": _hash_label(evidence.get("envelope_hash")),
        "actor": _clean_text((evidence.get("actor") or {}).get("actor_id")),
        "mutation_count": len(evidence.get("mutation_ids") or []),
        "adherence": _clean_text(adherence.get("status"), fallback="unknown"),
        "checkpoint_refs": list(evidence.get("checkpoint_refs") or []),
        "ledger_refs": list(evidence.get("ledger_refs") or []),
        "evidence_hash": _hash_label(evidence.get("document_hash")),
    }


def _timeline(
    *,
    objective: str,
    evidence: Mapping[str, Any],
    at: str,
) -> list[dict[str, str]]:
    verification = _verification_projection(evidence)
    proof = _proof_projection(evidence)
    return [
        {
            "kind": "request",
            "label": "You asked",
            "reason": objective,
            "at": at,
        },
        {
            "kind": "decision",
            "label": "The exact scope and checks were approved",
            "reason": "The verification contract was frozen before implementation",
            "at": at,
        },
        {
            "kind": "execution",
            "label": (
                "The agent stayed inside the approved scope"
                if proof["adherence"] == "compliant"
                else "APatch blocked an out-of-scope attempt"
            ),
            "reason": f"{proof['mutation_count']} signed mutation record(s)",
            "at": at,
        },
        {
            "kind": "verification",
            "label": (
                "Independent checks passed"
                if verification["accepted"]
                else "Verification is incomplete"
            ),
            "reason": (
                f"{verification['passed']} of {verification['executed']} checks passed"
            ),
            "at": at,
        },
        {
            "kind": "attestation",
            "label": "The result and its causes were recorded",
            "reason": "Exact contract, scope, checks and ledger references are hash-bound",
            "at": at,
        },
    ]


class APatchSddFacts:
    """Default adapter over canonical APatch Core state and signed ledger."""

    def __init__(self, workspace: str | os.PathLike[str]):
        self.root = Path(workspace).expanduser().resolve()

    def _entries(self) -> list[dict[str, Any]]:
        from apatch.spec import _ledger_entries

        entries, _active = _ledger_entries(str(self.root))
        return list(entries)

    def preview_assignment(self, request: dict[str, Any]) -> dict[str, Any]:
        brief = _core().build_brief(request)
        projected = {
            **brief,
            "brief_id": "brief_" + brief["document_hash"].split(":", 1)[1][:32],
            "content_hash": brief["document_hash"],
            "parent_hash": brief.get("supersedes_hash"),
        }
        return {
            "brief": projected,
            "coverage": {
                "complete": False,
                "missing": [],
                "ambiguous": [],
                "status": "awaiting_rfp_and_spec",
            },
        }

    def freeze_contract(self, request: dict[str, Any]) -> dict[str, Any]:
        core_request = request.get("core_contract")
        if not isinstance(core_request, Mapping):
            raise ValueError(
                "core_contract with exact brief/RFP/SPEC/plan/baseline hashes is required"
            )
        frozen = _core().freeze_contract(core_request)
        envelope_request = request.get("task_envelope")
        if not isinstance(envelope_request, Mapping):
            raise ValueError("task_envelope is required")
        envelope = _core().validate_task_envelope(
            {**dict(envelope_request), "contract_hash": frozen["document_hash"]}
        )
        return {
            **frozen,
            "contract_hash": frozen["document_hash"],
            "envelope_hash": envelope["document_hash"],
            "task_envelope": envelope,
            "judge_assets": list(request.get("judge_assets") or []),
        }

    def _selected(self, change_id: str) -> tuple[str, list[dict[str, Any]]]:
        selected_session = ""
        selected: list[dict[str, Any]] = []
        for entry in self._entries():
            payload = _entry_payload(entry)
            session_id = _session_id(payload)
            if session_id and change_id_for_session(session_id) == change_id:
                selected_session = session_id
                selected.append(entry)
        if not selected_session:
            raise LookupError("change not found")
        return selected_session, selected

    def project_change(self, change_id: str) -> dict[str, Any]:
        _session, entries = self._selected(change_id)
        entries.sort(key=lambda row: float(row.get("timestamp") or 0))
        attestation = next(
            (
                entry
                for entry in reversed(entries)
                if isinstance(_entry_payload(entry).get("sdd_evidence"), Mapping)
            ),
            None,
        )
        if attestation is None:
            raise LookupError("change has no SDD evidence")
        payload = _entry_payload(attestation)
        evidence = payload["sdd_evidence"]
        envelope = evidence.get("task_envelope")
        envelope = envelope if isinstance(envelope, Mapping) else {}
        adherence = evidence.get("adherence")
        adherence = adherence if isinstance(adherence, Mapping) else {}
        violations = [
            {
                "effect": _clean_text((item or {}).get("reasons"), fallback="scope"),
                "status": "blocked",
                "count": 1,
            }
            for item in adherence.get("violations") or []
            if isinstance(item, Mapping)
        ]
        objective = _clean_text(payload.get("intent") or payload.get("message"), fallback="Recorded change")
        proof = _proof_projection(evidence)
        verification = _verification_projection(evidence)
        at = _timestamp(attestation)
        result = {
            "schema": "apatch.studio.sdd-change.v1",
            "change_id": change_id,
            "objective": objective,
            "authority": {"label": "Approved by the recorded project authority"},
            "scope": {
                "containment": envelope.get("containment") or "mediated_only",
                "allowed": _allowed_scope(envelope),
                "forbidden": _forbidden_scope(envelope),
                "budgets": dict(envelope.get("budgets") or {}),
                "violations": violations,
                "amendment": {"status": "required" if violations else "not_requested"},
            },
            "verification": verification,
            "proof": proof,
            "timeline": _timeline(objective=objective, evidence=evidence, at=at),
            "effort": self._effort(_session),
        }
        assert_projection_safe(result)
        return result

    def _effort(self, session_id: str) -> dict[str, Any]:
        def safe_id(value: Any) -> str:
            text = str(value or "")
            return (
                text
                if re.fullmatch(r"[A-Za-z0-9:._-]{1,192}", text)
                else ""
            )

        def unavailable(
            reason: str,
            status: str,
            events: list[dict[str, Any]],
            *,
            signed_event_count: int = 0,
            ledger_drift_count: int = 0,
            unsigned_count: int = 0,
        ) -> dict[str, Any]:
            event_ids = sorted(
                {
                    safe_id(event.get("event_id"))
                    for event in events
                    if safe_id(event.get("event_id"))
                }
            )
            key_ids = sorted(
                {
                    safe_id((event.get("identity") or {}).get("key_id"))
                    for event in events
                    if isinstance(event.get("identity"), Mapping)
                    and safe_id((event.get("identity") or {}).get("key_id"))
                }
            )
            return {
                "derivation": "unavailable",
                "draft_hours": None,
                "quality": "unavailable",
                "accepted_time": False,
                "reason": reason,
                "signed_event_count": signed_event_count,
                "verification": {
                    "ok": False,
                    "status": status,
                    "checked": len(events),
                    "signed_event_count": signed_event_count,
                    "event_ids": event_ids,
                    "key_ids": key_ids,
                    "ledger_drift_count": ledger_drift_count,
                    "unsigned_count": unsigned_count,
                },
                "method_note": (
                    "APatch could not produce a verified effort estimate for "
                    "this exact governed session."
                ),
            }

        try:
            from apatch.contribution import verify_event
            from apatch.timesheet import aggregate, load_events, verify_events

            events = [
                dict(event)
                for event in load_events()
                if isinstance(event, Mapping)
                and str((event.get("session") or {}).get("session_id") or "")
                == session_id
            ]
        except Exception:
            return unavailable(
                "signed_event_verification_unavailable",
                "unavailable",
                [],
            )

        if not events:
            return unavailable("signed_event_missing", "missing", events)
        if len(events) != 1:
            return unavailable("signed_event_ambiguous", "ambiguous", events)

        event = events[0]
        identity = event.get("identity")
        identity = identity if isinstance(identity, Mapping) else {}
        if event.get("trust_level") not in {"attested", "verified"}:
            return unavailable("signed_event_untrusted", "untrusted", events)
        if not event.get("signature"):
            return unavailable(
                "signed_event_unsigned",
                "unsigned",
                events,
                unsigned_count=1,
            )

        event_id = safe_id(event.get("event_id"))
        key_id = safe_id(identity.get("key_id"))
        public_key_text = str(identity.get("public_key") or "")
        if not re.fullmatch(r"[0-9a-f]{32}", event_id):
            return unavailable(
                "signed_event_identity_invalid",
                "identity_invalid",
                events,
            )
        if not re.fullmatch(r"[0-9a-f]{32}", key_id) or not public_key_text:
            return unavailable(
                "signed_event_key_unavailable",
                "key_unavailable",
                events,
            )
        try:
            public_key = base64.b64decode(public_key_text, validate=True)
        except (binascii.Error, TypeError, ValueError):
            return unavailable(
                "signed_event_key_invalid",
                "key_invalid",
                events,
            )
        if (
            len(public_key) != 32
            or hashlib.sha256(public_key).hexdigest()[:32] != key_id
        ):
            return unavailable(
                "signed_event_key_mismatch",
                "key_mismatch",
                events,
            )
        if not verify_event(event, public_key):
            return unavailable(
                "signed_event_signature_invalid",
                "signature_invalid",
                events,
            )

        try:
            ledger = verify_events(events, str(self.root))
        except Exception:
            return unavailable(
                "signed_event_verification_unavailable",
                "unavailable",
                events,
                signed_event_count=1,
            )
        drift_count = len(ledger.get("drift") or [])
        unsigned_count = len(ledger.get("unsigned") or [])
        if ledger.get("ok") is not True:
            if unsigned_count:
                return unavailable(
                    "signed_event_unsigned",
                    "unsigned",
                    events,
                    unsigned_count=unsigned_count,
                )
            return unavailable(
                "signed_event_ledger_drift",
                "ledger_drift",
                events,
                signed_event_count=1,
                ledger_drift_count=drift_count,
            )

        groups = aggregate(
            events,
            by=("identity",),
            idle_gap_min=30.0,
            ramp_up_min=15.0,
        )
        hours = round(
            sum(float(group.get("hours") or 0) for group in groups),
            3,
        )
        if not math.isfinite(hours) or hours < 0:
            return unavailable(
                "signed_event_hours_invalid",
                "hours_invalid",
                events,
                signed_event_count=1,
            )
        return {
            "derivation": "signed_event_op_spacing",
            "draft_hours": hours,
            "quality": "verified_estimate",
            "accepted_time": False,
            "reason": None,
            "signed_event_count": 1,
            "verification": {
                "ok": True,
                "status": "verified",
                "checked": 1,
                "signed_event_count": 1,
                "event_ids": [event_id],
                "key_ids": [key_id],
                "ledger_drift_count": 0,
                "unsigned_count": 0,
            },
            "method_note": (
                "Estimate from this exact session's signed APatch event and "
                "ledger operation spacing, not a stopwatch"
            ),
        }

    def propose_amendment(self, request: dict[str, Any]) -> dict[str, Any]:
        contract = request.get("contract")
        if not isinstance(contract, Mapping):
            raise ValueError("the superseded frozen contract is required")
        return {
            **_core().amend_contract(
                contract,
                reason=str(request.get("reason") or ""),
                authority=request.get("authority") or {},
                changed_acceptance_ids=request.get("changed_acceptance_ids") or [],
                affected_requirements=request.get("affected_requirements") or [],
                all_requirements=request.get("all_requirements") or [],
            ),
            "status": "proposed",
            "approval_required": True,
        }


def project_admission(fact: Mapping[str, Any]) -> dict[str, Any]:
    allowed = fact.get("allowed") is True and fact.get("plan_match", True) is not False
    return {
        "schema": "apatch.studio.admission-projection.v1",
        "decision": "allowed" if allowed else "denied",
        "blocks_proof": not allowed,
        "effect": _clean_text(fact.get("effect"), fallback="effect"),
    }


def project_verifier_quality(fact: Mapping[str, Any]) -> dict[str, Any]:
    required = set(fact.get("required_perspectives") or _REQUIRED_PERSPECTIVES)
    observed = set(fact.get("perspectives") or [])
    collected = int(fact.get("collected") or 0)
    executed = int(fact.get("executed") or 0)
    skipped = int(fact.get("skipped") or 0)
    reasons: list[str] = []
    if collected <= 0:
        reasons.append("zero_collected")
    if executed <= 0 or skipped >= collected:
        reasons.append("all_skipped")
    if fact.get("asset_drift") is True:
        reasons.append("asset_drift")
    if fact.get("tautological") is True:
        reasons.append("tautological")
    if not required.issubset(observed):
        reasons.append("missing_perspectives")
    return {
        "schema": "apatch.studio.verifier-quality.v1",
        "accepted": not reasons,
        "reasons": reasons,
    }


def role_separation(authority: str, contributor: str, verifier: str) -> dict[str, Any]:
    actors = [str(authority), str(contributor), str(verifier)]
    return {
        "schema": "apatch.studio.role-separation.v1",
        "separated": len(set(actors)) == len(actors),
        "actors": {
            "authority": actors[0],
            "contributor": actors[1],
            "verifier": actors[2],
        },
    }


def integrity_floor(edition: str) -> list[str]:
    requested = str(edition).lower()
    if requested not in ("oss", "cowork"):
        raise ValueError("mode must be oss or cowork")
    try:
        # Cowork coordination cannot select a weaker runtime floor. Core owns the
        # local integrity profile, so both modes intentionally request OSS rules.
        return sorted(_core().integrity_floor("oss"))
    except RuntimeError:
        return sorted(_INTEGRITY_FLOOR)


class SddWorkflowFacade:
    """Narrow Studio surface over canonical Core facts."""

    def __init__(
        self,
        workspace: str | os.PathLike[str],
        *,
        backend: SddFactsBackend | None = None,
        clock: Callable[[], str] | None = None,
    ):
        self.root = Path(workspace).expanduser().resolve()
        self.backend = backend or APatchSddFacts(self.root)
        self.clock = clock or _utc_now
        self._freeze_lock = threading.RLock()

    @staticmethod
    def _validated_ids(spec_id: str, requirement_id: str) -> tuple[str, str]:
        if not _SPEC_ID.fullmatch(spec_id):
            raise SddWorkflowError("The specification id is invalid", code="invalid_spec_id", status_code=422)
        if not _REQUIREMENT_ID.fullmatch(requirement_id):
            raise SddWorkflowError("The requirement id is invalid", code="invalid_requirement_id", status_code=422)
        return spec_id, requirement_id

    def _prepared_path(self, spec_id: str) -> Path:
        return self.root / ".apatch" / "sdd" / "prepared" / f"{spec_id}.json"

    def _envelope_path(self, spec_id: str, requirement_id: str) -> Path:
        return self.root / ".apatch" / "sdd" / "envelopes" / spec_id / f"{requirement_id}.json"

    @staticmethod
    def _read_document(path: Path, *, missing_code: str) -> dict[str, Any]:
        try:
            value = read_json(path, limit=_MAX_PREPARED_BYTES)
        except FileNotFoundError as exc:
            raise SddWorkflowError("The prepared execution contract is not available", code=missing_code) from exc
        except (OSError, UnicodeError, ValueError) as exc:
            raise SddWorkflowError("The prepared execution contract is not valid JSON", code="sdd_contract_invalid", status_code=422) from exc
        if not isinstance(value, dict):
            raise SddWorkflowError("The prepared execution contract must be one object", code="sdd_contract_invalid", status_code=422)
        return value

    def _prepared(self, spec_id: str, requirement_id: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        spec_id, requirement_id = self._validated_ids(spec_id, requirement_id)
        package = self._read_document(self._prepared_path(spec_id), missing_code="sdd_contract_not_prepared")
        required_keys = {"schema", "spec_id", "objective", "prepared_at", "source_mutation_count", "contract_request", "task_envelopes"}
        if set(package) != required_keys:
            raise SddWorkflowError("The prepared execution contract has an unsupported shape", code="sdd_contract_invalid", status_code=422)
        if package.get("schema") != "apatch.studio.sdd-preparation.v1" or package.get("spec_id") != spec_id:
            raise SddWorkflowError("The prepared execution contract is for another specification", code="sdd_contract_invalid", status_code=422)
        if int(package.get("source_mutation_count") or 0) != 0:
            raise SddWorkflowError("Application source changed before owner confirmation", code="sdd_contract_late")
        contract_request = package.get("contract_request")
        envelopes = package.get("task_envelopes")
        if not isinstance(contract_request, dict) or not isinstance(envelopes, dict):
            raise SddWorkflowError("The prepared contract and task envelopes are required", code="sdd_contract_invalid", status_code=422)
        forbidden_contract_fields = {"authority", "document_hash", "frozen_at", "implementation_allowed", "source_mutation_count", "status"}
        if forbidden_contract_fields.intersection(contract_request):
            raise SddWorkflowError("The preparation actor cannot preselect owner authority or frozen state", code="sdd_contract_invalid", status_code=422)
        envelope = envelopes.get(requirement_id)
        if not isinstance(envelope, dict):
            raise SddWorkflowError("This requirement has no prepared task envelope", code="sdd_requirement_not_prepared")
        if "contract_hash" in envelope or "document_hash" in envelope:
            raise SddWorkflowError("The preparation actor cannot prebind a frozen contract hash", code="sdd_contract_invalid", status_code=422)
        if envelope.get("requirement") != f"{spec_id}#{requirement_id}":
            raise SddWorkflowError("The task envelope targets another requirement", code="sdd_contract_invalid", status_code=422)
        return package, dict(contract_request), dict(envelope)

    @staticmethod
    def _review_projection(
        package: Mapping[str, Any],
        contract_request: Mapping[str, Any],
        envelope: Mapping[str, Any],
        *,
        status: str,
        contract_hash: str | None = None,
        envelope_hash: str | None = None,
        owner_actor_id: str | None = None,
        frozen_at: str | None = None,
    ) -> dict[str, Any]:
        checks = []
        for item in contract_request.get("obligations") or []:
            if not isinstance(item, Mapping):
                continue
            baseline = item.get("baseline")
            falsification = item.get("falsification")
            checks.append({
                "acceptance_id": _clean_text(item.get("acceptance_id")),
                "test_id": _clean_text(item.get("test_id")),
                "oracle": _clean_text(item.get("oracle")),
                "perspectives": list(item.get("perspectives") or []),
                "observed_red": isinstance(baseline, Mapping) and baseline.get("kind") == "observed_red",
                "falsification_expected": falsification.get("expected") if isinstance(falsification, Mapping) else None,
                "material": item.get("material") is True,
            })
        result = {
            "schema": "apatch.studio.sdd-contract-review.v1",
            "status": status,
            "spec_id": package["spec_id"],
            "requirement_id": str(envelope["requirement"]).split("#", 1)[1],
            "objective": _clean_text(package.get("objective")),
            "prepared_at": _clean_text(package.get("prepared_at")),
            "owner_confirmation_required": status != "frozen",
            "owner_actor_id": owner_actor_id,
            "frozen_at": frozen_at,
            "contract_hash": contract_hash,
            "envelope_hash": envelope_hash,
            "scope": {field: list(envelope.get(field) or []) for field in ("allowed_reads", "allowed_writes", "allowed_symbols", "forbidden_paths", "tools", "commands", "network", "remote", "services", "checks")},
            "budgets": dict(envelope.get("budgets") or {}),
            "containment": envelope.get("containment"),
            "rollback_owner": envelope.get("rollback_owner"),
            "checks": checks,
        }
        assert_projection_safe(result)
        return result

    def contract_review(
        self, spec_id: str, requirement_id: str, *, with_snapshot: bool = False,
    ) -> dict[str, Any]:
        if not with_snapshot:
            return self._review_prepared(spec_id, requirement_id, self._prepared(spec_id, requirement_id))
        with self._freeze_lock:
            prepared = self._prepared(spec_id, requirement_id)
            snapshot = self._snapshot_of_preparation(prepared[0], spec_id, requirement_id)
            review = self._review_prepared(spec_id, requirement_id, prepared)
            if self.approval_snapshot(spec_id, requirement_id) != snapshot:
                raise SddWorkflowError("The task changed during review; review it again", code="sdd_approval_drift")
            return {**review, "approval_snapshot": snapshot}

    def _freeze_input(
        self, package: Mapping[str, Any], contract_request: Mapping[str, Any],
        *, owner: str, frozen_at: str,
    ) -> dict[str, Any]:
        """Build the exact Core input for both sealing and frozen-review checks."""
        obligations = []
        for item in contract_request.get("obligations") or []:
            if not isinstance(item, Mapping):
                raise SddWorkflowError("Every verification obligation must be an object", code="sdd_contract_invalid", status_code=422)
            entry = {**dict(item), "approver": owner}
            entry["judge_assets"] = self._bind_judge_assets(entry, package)
            if bool(entry.get("material")):
                falsification = dict(entry.get("falsification") or {})
                falsification["target_path"] = self._falsification_target(
                    entry, package
                )
                entry["falsification"] = falsification
            obligations.append(entry)
        return {
            **contract_request,
            "obligations": obligations,
            "authority": {"actor_id": owner, "role": "authority"},
            "source_mutation_count": 0,
            "frozen_at": frozen_at,
        }

    def _review_prepared(
        self, spec_id: str, requirement_id: str,
        prepared: tuple[dict[str, Any], dict[str, Any], dict[str, Any]],
    ) -> dict[str, Any]:
        package, contract_request, prepared_envelope = prepared
        manifest_path = self.root / ".apatch" / "sdd_verification_contract.json"
        envelope_path = self._envelope_path(spec_id, requirement_id)
        if manifest_path.is_file() and envelope_path.is_file():
            try:
                binding = self.execution_binding(spec_id, requirement_id, actor_id="agent:review")
            except SddWorkflowError:
                pass
            else:
                contract = binding["contract"]
                try:
                    candidate = _core().freeze_contract(self._freeze_input(
                        package, contract_request,
                        owner=str((contract.get("authority") or {}).get("actor_id") or ""),
                        frozen_at=str(contract.get("frozen_at") or ""),
                    ))
                    envelope = _core().validate_task_envelope({
                        **prepared_envelope, "contract_hash": candidate["document_hash"],
                    })
                except (RuntimeError, ValueError) as exc:
                    raise SddWorkflowError(
                        "The preparation no longer matches the frozen contract; review an amendment",
                        code="sdd_approval_drift",
                    ) from exc
                if (candidate["document_hash"] != binding["contract_hash"]
                        or envelope["document_hash"] != binding["envelope_hash"]):
                    raise SddWorkflowError(
                        "The preparation no longer matches the frozen contract; review an amendment",
                        code="sdd_approval_drift",
                    )
                return self._review_projection(
                    package, contract, binding["task_envelope"], status="frozen",
                    contract_hash=binding["contract_hash"], envelope_hash=binding["envelope_hash"],
                    owner_actor_id=str((contract.get("authority") or {}).get("actor_id") or ""),
                    frozen_at=str(contract.get("frozen_at") or ""),
                )
        return self._review_projection(package, contract_request, prepared_envelope, status="ready_for_owner")

    def requirement_status(self, spec_id: str, requirement_id: str) -> dict[str, Any]:
        try:
            review = self.contract_review(spec_id, requirement_id)
        except SddWorkflowError as exc:
            return {
                "schema": "apatch.studio.sdd-contract-status.v1",
                "status": "not_prepared" if exc.code in {"sdd_contract_not_prepared", "sdd_requirement_not_prepared"} else "invalid",
                "reason": exc.code,
                "contract_hash": None,
                "envelope_hash": None,
            }
        return {
            "schema": "apatch.studio.sdd-contract-status.v1",
            "status": review["status"],
            "reason": None,
            "contract_hash": review["contract_hash"],
            "envelope_hash": review["envelope_hash"],
        }

    def _readable_files(self, package: Mapping[str, Any]):
        """Every file this SPEC's requirements are allowed to read.

        A judge belongs to the contract, not to whichever requirement happened
        to trigger the freeze, so its files are looked for across every
        envelope's reads rather than one requirement's.
        """

        seen: set[Path] = set()
        reads = [
            raw
            for _rk, envelope in sorted((package.get("task_envelopes") or {}).items())
            if isinstance(envelope, Mapping)
            for raw in envelope.get("allowed_reads") or []
        ]
        for raw in reads:
            pattern = _clean_text(raw)
            if not pattern:
                continue
            if pattern.endswith("/**"):
                pattern = pattern + "/*"
            for path in sorted(self.root.glob(pattern)):
                if path.is_file() and path not in seen:
                    seen.add(path)
                    yield path

    def _bind_judge_assets(
        self, obligation: Mapping[str, Any], package: Mapping[str, Any]
    ) -> list[dict[str, str]]:
        """Name the exact file behind every frozen judge hash.

        APatch re-reads each judge file and re-hashes it before it will trust a
        verdict, so a contract that pins hashes without saying which files they
        came from can be frozen and then never executed. Resolve it now, while
        the owner is still here to close a gap, rather than at implementation
        time when the freeze is immutable.
        """

        acceptance_id = _clean_text(obligation.get("acceptance_id")) or "this check"
        wanted = [_clean_text(item) for item in obligation.get("asset_hashes") or []]
        declared = obligation.get("judge_assets")
        if isinstance(declared, list) and declared:
            assets = [
                {
                    "path": _clean_text(item.get("path")),
                    "sha256": _clean_text(item.get("sha256")),
                }
                for item in declared
                if isinstance(item, Mapping)
            ]
        else:
            assets = self._resolve_judge_assets(wanted, obligation, package)
        if sorted(item["sha256"] for item in assets) != sorted(wanted):
            raise SddWorkflowError(
                f"{acceptance_id}: every frozen judge file must be named and match its "
                "hash before this contract can be frozen",
                code="sdd_contract_invalid",
                status_code=422,
            )
        return assets

    def _resolve_judge_assets(
        self,
        wanted: list[str],
        obligation: Mapping[str, Any],
        package: Mapping[str, Any],
    ) -> list[dict[str, str]]:
        remaining = list(wanted)
        found: list[dict[str, str]] = []
        for relative in _named_judge_paths(obligation):
            if not remaining:
                break
            path = self.root / relative
            if not path.is_file():
                continue
            digest = _sha256_file(path)
            if digest in remaining:
                remaining.remove(digest)
                found.append({"path": relative, "sha256": digest})
        for path in self._readable_files(package) if remaining else ():
            digest = _sha256_file(path)
            if digest in remaining:
                remaining.remove(digest)
                found.append(
                    {"path": str(path.relative_to(self.root)), "sha256": digest}
                )
            if not remaining:
                break
        return found

    def _falsification_target(
        self, obligation: Mapping[str, Any], package: Mapping[str, Any]
    ) -> str:
        """The file the falsification mutant edits to prove the judge can fail.

        The target belongs to the obligation, so it is read from the package and
        not from whichever requirement is being frozen. Where the package leaves
        it out, the requirement that owns this check can still settle it, but
        only when that requirement writes exactly one file.
        """

        acceptance_id = _clean_text(obligation.get("acceptance_id")) or "this check"
        falsification = obligation.get("falsification")
        if isinstance(falsification, Mapping):
            declared = _clean_text(falsification.get("target_path"))
            if declared:
                return declared
        for _rk, envelope in sorted((package.get("task_envelopes") or {}).items()):
            if not isinstance(envelope, Mapping):
                continue
            if acceptance_id not in _string_list_or_empty(envelope.get("checks")):
                continue
            concrete = [
                _clean_text(item)
                for item in envelope.get("allowed_writes") or []
                if _clean_text(item) and not any(ch in _clean_text(item) for ch in "*?[")
            ]
            if len(concrete) == 1:
                return concrete[0]
            break
        raise SddWorkflowError(
            f"{acceptance_id}: name the file the falsification mutant edits "
            "(falsification.target_path); its requirement may write more than one",
            code="sdd_contract_invalid",
            status_code=422,
        )

    def _existing_frozen_at(self, contract_request: Mapping[str, Any]) -> str | None:
        """Keep the freeze time this SPEC's contract already carries.

        One contract covers the whole SPEC, so every requirement's envelope has
        to bind to one document. Stamping a fresh time per requirement minted a
        new contract on each call, and the workspace ended up holding several
        that each claimed to be the frozen one.
        """

        path = self.root / ".apatch" / "sdd_verification_contract.json"
        try:
            frozen = read_json(path, limit=_MAX_PREPARED_BYTES)
        except FileNotFoundError:
            return None
        except (OSError, ValueError) as exc:
            raise SddWorkflowError("The frozen contract store is unavailable", code="sdd_contract_invalid") from exc
        if not isinstance(frozen, Mapping):
            return None
        if frozen.get("spec_hash") != contract_request.get("spec_hash"):
            return None
        frozen_at = frozen.get("frozen_at")
        return frozen_at if isinstance(frozen_at, str) and frozen_at else None

    def _drop_superseded_envelopes(self, spec_id: str, contract_hash: str) -> None:
        """An envelope bound to a replaced contract cannot be executed."""

        folder = self._envelope_path(spec_id, "R0").parent
        try:
            with StateDirectory(folder) as directory:
                for name in directory.names():
                    if not name.endswith(".json"):
                        continue
                    try:
                        envelope = directory.read_json(name, limit=_MAX_PREPARED_BYTES)
                    except (FileNotFoundError, ValueError):
                        continue
                    if (isinstance(envelope, Mapping)
                            and envelope.get("schema") == "apatch.sdd.task-envelope.v1"
                            and envelope.get("requirement") == f"{spec_id}#{name[:-5]}"
                            and envelope.get("contract_hash") != contract_hash):
                        directory.unlink(name)
        except FileNotFoundError:
            return

    def approval_snapshot(self, spec_id: str, requirement_id: str) -> str:
        """Fingerprint the reviewed preparation and actual source/judge inputs.

        Runtime journals and frozen outputs are not input files. Including them
        would make recording the agreement invalidate its own recovery snapshot.
        """
        with self._freeze_lock:
            package, _contract, _envelope = self._prepared(spec_id, requirement_id)
            return self._snapshot_of_preparation(package, spec_id, requirement_id)

    def _snapshot_of_preparation(
        self, package: Mapping[str, Any], spec_id: str, requirement_id: str,
    ) -> str:
        """Hash the same captured preparation that will be reviewed or frozen."""
        patterns = {
            str(pattern)
            for envelope in package["task_envelopes"].values()
            for key in ("allowed_reads", "allowed_writes")
            for pattern in envelope.get(key, [])
        }
        files = {}
        total_bytes = 0
        for pattern in sorted(patterns):
            if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
                raise SddWorkflowError("Snapshot scope escapes the workspace", code="sdd_contract_invalid", status_code=422)
            glob = pattern + "/*" if pattern.endswith("/**") else pattern
            for path in sorted(self.root.glob(glob)):
                relative = path.relative_to(self.root).as_posix()
                if relative.split("/", 1)[0] in {".apatch", ".git", "node_modules"}:
                    continue
                if path.is_symlink() or not path.resolve().is_relative_to(self.root):
                    raise SddWorkflowError("Snapshot input uses a symbolic link", code="sdd_contract_invalid", status_code=422)
                if not path.is_file() or relative in files:
                    continue
                total_bytes += path.stat().st_size
                if len(files) >= 4096 or total_bytes > 64 * 1024 * 1024:
                    raise SddWorkflowError("Narrow the reviewed input scope", code="sdd_contract_invalid", status_code=422)
                files[relative] = _sha256_file(path)
        return _core().canonical_hash({
            "schema": "apatch.studio.approval-snapshot.v2",
            "spec_id": spec_id, "requirement_id": requirement_id,
            "preparation": package, "files": files,
        })

    def freeze_requirement(self, spec_id: str, requirement_id: str, *, owner_actor_id: str, confirmed: bool, expected_snapshot: str | None = None) -> dict[str, Any]:
        if confirmed is not True:
            raise SddWorkflowError("Owner confirmation is required", code="sdd_owner_confirmation_required", status_code=422)
        owner = _clean_text(owner_actor_id)
        if not 3 <= len(owner) <= 128:
            raise SddWorkflowError("A named local owner is required", code="sdd_owner_required", status_code=422)
        with self._freeze_lock:
            package, contract_request, prepared_envelope = self._prepared(spec_id, requirement_id)
            try:
                # Validate every destination before calling Core or writing any
                # frozen output. Each actual I/O also pins its own ancestry.
                with StateDirectory(self.root / ".apatch/sdd/frozen", create=True):
                    pass
                for path in (
                    self._envelope_path(spec_id, requirement_id),
                    self.root / ".apatch/sdd_verification_contract.json",
                ):
                    check_target(path)
            except OSError as exc:
                raise SddWorkflowError("The frozen contract store is unavailable", code="sdd_contract_invalid") from exc
            if expected_snapshot is not None and self._snapshot_of_preparation(package, spec_id, requirement_id) != expected_snapshot:
                raise SddWorkflowError("The reviewed task changed before freezing", code="sdd_approval_drift")
            review = self._review_prepared(spec_id, requirement_id, (package, contract_request, prepared_envelope))
            if review["status"] == "frozen":
                if expected_snapshot is not None and self.approval_snapshot(spec_id, requirement_id) != expected_snapshot:
                    raise SddWorkflowError("The reviewed task changed during freezing", code="sdd_approval_drift")
                return review
            frozen_at = self._existing_frozen_at(contract_request) or self.clock()
            core_contract = self._freeze_input(
                package, contract_request, owner=owner, frozen_at=frozen_at,
            )
            try:
                result = self.backend.freeze_contract({"core_contract": core_contract, "task_envelope": prepared_envelope, "judge_assets": core_contract["obligations"]})
            except (RuntimeError, ValueError) as exc:
                raise SddWorkflowError(str(exc), code="sdd_contract_invalid", status_code=422) from exc
            task_envelope = result.get("task_envelope")
            if not isinstance(task_envelope, Mapping):
                raise SddWorkflowError("APatch Core did not return the exact task envelope", code="sdd_runtime_incompatible", status_code=503)
            frozen_contract = {key: value for key, value in result.items() if key not in {"contract_hash", "envelope_hash", "task_envelope", "judge_assets"}}
            contract_hash = frozen_contract.get("document_hash")
            envelope_hash = task_envelope.get("document_hash")
            if not _hash_label(contract_hash) or not _hash_label(envelope_hash):
                raise SddWorkflowError("APatch Core returned an unsealed execution contract", code="sdd_runtime_incompatible", status_code=503)
            if expected_snapshot is not None and self.approval_snapshot(spec_id, requirement_id) != expected_snapshot:
                raise SddWorkflowError("The reviewed task changed during freezing", code="sdd_approval_drift")
            digest = str(contract_hash).split(":", 1)[1]
            try:
                _atomic_json(self.root / ".apatch" / "sdd" / "frozen" / f"{digest}.json", frozen_contract)
                _atomic_json(self._envelope_path(spec_id, requirement_id), dict(task_envelope))
                _atomic_json(self.root / ".apatch" / "sdd_verification_contract.json", frozen_contract)
                self._drop_superseded_envelopes(spec_id, str(contract_hash))
            except OSError as exc:
                raise SddWorkflowError("The frozen contract store is unavailable", code="sdd_contract_invalid") from exc
            return self._review_projection(
                package, contract_request, prepared_envelope, status="frozen",
                contract_hash=str(contract_hash), envelope_hash=str(envelope_hash),
                owner_actor_id=owner, frozen_at=frozen_at,
            )

    def execution_binding(self, spec_id: str, requirement_id: str, *, actor_id: str) -> dict[str, Any]:
        spec_id, requirement_id = self._validated_ids(spec_id, requirement_id)
        actor = _clean_text(actor_id)
        if not 3 <= len(actor) <= 128:
            raise SddWorkflowError("A fixed implementation actor is required", code="sdd_actor_required", status_code=422)
        manifest_path = self.root / ".apatch" / "sdd_verification_contract.json"
        envelope_path = self._envelope_path(spec_id, requirement_id)
        try:
            contract = self._read_document(manifest_path, missing_code="sdd_contract_not_frozen")
            if contract.get("schema") != "apatch.sdd.verification-contract.v1":
                raise ValueError("frozen contract schema is invalid")
            stored_envelope = self._read_document(
                envelope_path,
                missing_code="sdd_contract_not_frozen",
            )
            task_envelope = _core().validate_task_envelope(stored_envelope)
            if stored_envelope.get("document_hash") != task_envelope.get("document_hash"):
                raise ValueError("task envelope hash does not match its content")
            if contract is None:
                raise ValueError("frozen contract is missing")
            if task_envelope.get("requirement") != f"{spec_id}#{requirement_id}":
                raise ValueError("task envelope targets another requirement")
            _core().issue_capability(contract, task_envelope, actor_id=actor, role="implementation")
        except (RuntimeError, ValueError) as exc:
            if isinstance(exc, SddWorkflowError) and exc.code == "sdd_contract_not_frozen":
                raise
            raise SddWorkflowError("The frozen contract or task envelope changed after owner confirmation", code="sdd_contract_tampered") from exc
        result = {
            "schema": "apatch.studio.sdd-execution-context.v1",
            "spec_id": spec_id,
            "requirement_id": requirement_id,
            "actor_id": actor,
            "contract_hash": contract["document_hash"],
            "envelope_hash": task_envelope["document_hash"],
            "contract": contract,
            "task_envelope": task_envelope,
        }
        assert_projection_safe(result)
        return result

    @staticmethod
    def ownership() -> dict[str, Any]:
        return {
            "schema": "apatch.studio.sdd-ownership.v1",
            "execution_runtime": "apatch",
            "studio_role": "human_projection_and_commands",
            "duplicate_state_forbidden": True,
            "proof_source": "apatch_signed_ledger",
            "effort_source": "apatch_timesheet",
        }

    def preview_assignment(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if not _clean_text(request.get("objective")):
            raise ValueError("objective is required")
        result = self.backend.preview_assignment(dict(request))
        assert_projection_safe(result)
        return result

    def freeze_contract(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if int(request.get("source_mutation_count") or 0) != 0:
            raise ValueError("contract must freeze before source mutation")
        judge_assets = request.get("judge_assets")
        if not isinstance(judge_assets, list) or not judge_assets:
            raise ValueError("judge_assets are required")
        for asset in judge_assets:
            if not isinstance(asset, Mapping):
                raise ValueError("judge asset must be an object")
            perspectives = set(asset.get("perspectives") or [])
            if not _REQUIRED_PERSPECTIVES.issubset(perspectives):
                raise ValueError(
                    "perspectives must include positive, negative, boundary and regression"
                )
            falsification = asset.get("falsification")
            if not isinstance(falsification, Mapping) or falsification.get("expected") != "red":
                raise ValueError("material judge asset requires red falsification")
        authority = request.get("authority")
        if not isinstance(authority, Mapping) or authority.get("role") not in (
            "owner",
            "authority",
        ):
            raise ValueError("named owner or authority is required")
        result = self.backend.freeze_contract(dict(request))
        assert_projection_safe(result)
        return result

    def change(self, change_id: str) -> dict[str, Any]:
        result = self.backend.project_change(change_id)
        assert_projection_safe(result)
        return result

    def scope_contour(self, change_id: str) -> dict[str, Any]:
        scope = self.change(change_id)["scope"]
        return {
            "schema": "apatch.studio.scope-contour.v1",
            "title": "What the agent can do",
            "allowed_label": "Allowed for this change",
            "forbidden_label": "Not allowed",
            "violations_label": "Blocked attempts",
            **scope,
        }

    def causal_replay(self, change_id: str) -> list[dict[str, Any]]:
        return list(self.change(change_id).get("timeline") or [])

    def propose_amendment(self, request: Mapping[str, Any]) -> dict[str, Any]:
        if len(_clean_text(request.get("reason"))) < 12:
            raise ValueError("amendment reason must explain the changed decision")
        result = self.backend.propose_amendment(dict(request))
        assert_projection_safe(result)
        return result
