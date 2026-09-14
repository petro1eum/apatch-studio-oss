"""Typed, content-safe APatch operations used by Studio workflow tabs."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apatch.doctor import run_doctor
from apatch.gc import run_gc
from apatch.inclusion import verify_inclusion
from apatch.probe import ratify
from apatch.reality import reality_status_workspace
from apatch.spec import spec_lint_workspace, spec_next_workspace, spec_status_workspace
from apatch.rfp_coverage import rfp_spec_coverage_workspace
from apatch.spec_interference import spec_interference_workspace, spec_schedule_workspace
from apatch.spec_plan import show_plan_workspace
from apatch.spec_rebind import rebind_stale_requirements
from apatch.trustchain_helper import TrustChainHelper
from apatch.work_asset_suggest import build_recall_bundle, suggest_work_assets
from apatch.work_assets import search_work_assets, show_work_asset

from apatch_studio.projection import assert_projection_safe
from apatch_studio.capabilities import apatch_python_command, apatch_python_startup_env
from apatch_studio.state_io import StateDirectory, read_json, write_json


_REQUEST_ID = r"^apsreq_[a-z0-9][a-z0-9_-]{7,95}$"
_SPEC_ID = re.compile(r"^SPEC-[A-Z0-9][A-Z0-9-]{1,95}$")
_REQUIREMENT_ID = re.compile(r"^[A-Z][A-Z0-9_-]{0,63}$")
_ASSET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{2,127}$")
_ARTIFACT_REF = re.compile(
    r"^[A-Za-z][A-Za-z0-9_.-]{0,31}:[A-Za-z0-9][A-Za-z0-9_.:#@-]{1,191}$"
)


class StudioWorkflowError(RuntimeError):
    def __init__(self, message: str, *, code: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class FixedPurposeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(pattern=_REQUEST_ID)


class SpecInspectRequest(FixedPurposeRequest):
    action: Literal[
        "lint",
        "coverage",
        "next",
        "plan",
        "interference",
        "schedule",
        "status",
        "reality",
    ]


class SpecRebindRequest(FixedPurposeRequest):
    requirement_ids: list[str] = Field(min_length=1, max_length=64)
    exclude_requirement_ids: list[str] = Field(default_factory=list, max_length=64)
    confirmed: Literal[True]

    @field_validator("requirement_ids", "exclude_requirement_ids")
    @classmethod
    def valid_requirement_ids(cls, values: list[str]) -> list[str]:
        values = list(dict.fromkeys(values))
        if any(not _REQUIREMENT_ID.fullmatch(value) for value in values):
            raise ValueError("invalid requirement id")
        return values

    @model_validator(mode="after")
    def disjoint_ids(self):
        if set(self.requirement_ids) & set(self.exclude_requirement_ids):
            raise ValueError("included and excluded requirement ids must be disjoint")
        return self


class EvidenceActionRequest(FixedPurposeRequest):
    action: Literal[
        "history", "verify", "coverage", "inclusion", "ratify", "reality", "export"
    ]
    scope: Literal["working_tree", "staged"] = "working_tree"
    artifact: str | None = Field(default=None, max_length=224)

    @field_validator("artifact")
    @classmethod
    def valid_artifact(cls, value: str | None) -> str | None:
        if value is not None and not _ARTIFACT_REF.fullmatch(value):
            raise ValueError("invalid artifact reference")
        return value

    @model_validator(mode="after")
    def ratify_requires_requirement(self):
        if self.action == "ratify" and (
            self.artifact is None
            or not self.artifact.startswith("spec:")
            or "#" not in self.artifact
        ):
            raise ValueError("ratify requires an exact spec requirement artifact")
        return self


class AssetSearchRequest(FixedPurposeRequest):
    query: str = Field(default="", max_length=200)
    limit: int = Field(default=20, ge=1, le=50)

    @field_validator("query")
    @classmethod
    def clean_query(cls, value: str) -> str:
        return " ".join(value.split())


class AssetSuggestRequest(FixedPurposeRequest):
    objective: str = Field(min_length=3, max_length=500)
    limit: int = Field(default=3, ge=1, le=10)

    @field_validator("objective")
    @classmethod
    def clean_objective(cls, value: str) -> str:
        return " ".join(value.split())


class AssetActionRequest(FixedPurposeRequest):
    action: Literal["show", "recall", "export"]
    intent: str = Field(default="", max_length=500)

    @field_validator("intent")
    @classmethod
    def clean_intent(cls, value: str) -> str:
        return " ".join(value.split())


class SystemActionRequest(FixedPurposeRequest):
    action: Literal[
        "doctor", "hygiene", "gc_preview", "gc_execute", "policy_verify"
    ]
    confirmed: bool = False

    @model_validator(mode="after")
    def confirm_cleanup(self):
        if self.action == "gc_execute" and not self.confirmed:
            raise ValueError("safe cleanup requires explicit confirmation")
        if self.action != "gc_execute" and self.confirmed:
            raise ValueError("confirmation is accepted only for safe cleanup")
        return self


def _document_hash(value: Any) -> str:
    canonical = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(canonical).hexdigest()


def _text(value: Any, limit: int = 500) -> str:
    raw = "" if value is None else str(value)
    return " ".join(raw.split())[:limit]


def present_action(command: str, result: dict[str, Any]) -> dict[str, Any]:
    """Translate a fixed-purpose result into a safe human-first outcome."""

    ok = bool(result.get("ok", True))
    tone = "success" if ok else "attention"
    title = "Action completed" if ok else "Action needs attention"
    summary = (
        "The requested local operation completed and was recorded."
        if ok
        else "The operation stopped safely. Review the result before continuing."
    )
    next_action: str | None = None

    if command == "system_doctor":
        title = "Runtime is ready" if ok else "Runtime needs attention"
        summary = (
            "The local APatch runtime can govern agent work."
            if ok
            else "The local runtime is not ready to govern a new change."
        )
        next_action = None if ok else "Open storage health or update the local runtime."
    elif command == "system_hygiene":
        title = "Storage is healthy" if ok else "Storage needs attention"
        summary = (
            "No blocking local-state issue was found."
            if ok
            else "Local APatch state needs maintenance before more work is recorded."
        )
        next_action = None if ok else "Preview safe cleanup before deleting anything."
    elif command == "system_gc_preview":
        title = "Cleanup preview is ready"
        summary = "Nothing was deleted. The reclaimable local records were counted."
        next_action = "Review the candidates before cleaning up."
    elif command == "system_gc_execute":
        title = "Safe cleanup completed" if ok else "Cleanup needs attention"
        summary = (
            f"{int(result.get('deleted_count') or 0)} safe local records were removed."
            if ok
            else "Cleanup stopped without widening its allowed scope."
        )
    elif command == "evidence_verify":
        violations = int(result.get("violation_count") or 0)
        title = "Proof check passed" if ok else "Proof needs attention"
        summary = (
            f"All {int(result.get('checked') or 0)} checked files have recorded proof."
            if ok
            else f"{violations} files need proof before this change can be trusted."
        )
        next_action = None if ok else "Open the affected change and complete or restore its governed record."
    elif command.startswith("evidence_"):
        action = command.removeprefix("evidence_")
        names = {
            "history": "Evidence history is ready",
            "coverage": "Coverage check completed",
            "inclusion": "Independent log check completed",
            "ratify": "Policy gate was re-checked",
            "reality": "Current state was checked",
            "export": "Evidence package is ready",
        }
        title = names.get(action, title)
        summary = (
            "The requested proof view completed and the technical record remains available below."
            if ok
            else "The proof view found an issue that needs review."
        )
    elif command.startswith("policy_"):
        action = command.removeprefix("policy_")
        names = {
            "status": "Protection status is ready",
            "preview": "Rule preview is ready",
            "apply": "Protection rules were updated",
            "sign": "Protection rules were signed",
            "verify": "Protection rules were checked",
            "restore": "Previous protection rules were restored",
        }
        title = names.get(action, title)
        summary = (
            "The workspace protection operation completed as requested."
            if ok
            else "The workspace protection operation stopped without an unverified change."
        )
    facts: list[dict[str, str]] = []
    labels = (
        ("version", "Version"),
        ("profile", "Agent profile"),
        ("tool_count", "Agent tools"),
        ("checked", "Checked"),
        ("verified", "Verified"),
        ("violation_count", "Needs proof"),
        ("covered_count", "Covered"),
        ("uncovered_count", "Uncovered"),
        ("deleted_count", "Removed"),
        ("reclaimed_bytes", "Bytes reclaimed"),
    )
    for key, label in labels:
        value = result.get(key)
        if value is not None:
            facts.append({"label": label, "value": _text(value, 80)})
    counts = result.get("counts")
    if isinstance(counts, dict):
        for key, value in list(counts.items())[:6]:
            if isinstance(value, (int, float)):
                facts.append(
                    {
                        "label": key.replace("_", " ").title(),
                        "value": _text(value, 80),
                    }
                )

    return {
        "title": title,
        "summary": summary,
        "tone": tone,
        "facts": facts[:10],
        "next_action": next_action,
    }


def _asset(raw: dict[str, Any]) -> dict[str, Any]:
    value = raw.get("asset") if isinstance(raw.get("asset"), dict) else raw
    reuse = value.get("reuse") or {}
    applicability = value.get("applicability") or {}
    owner = value.get("owner") or {}
    source = value.get("source_evidence") or {}
    portability = value.get("portability_policy") or {}
    return {
        "id": value.get("asset_id"),
        "title": _text(value.get("title"), 240),
        "kind": value.get("asset_kind"),
        "lifecycle": value.get("lifecycle") or "unknown",
        "recallable": bool(value.get("recallable")),
        "reuse_count": int(reuse.get("count") or 0),
        "last_used_at": reuse.get("last_used_at"),
        "signals": [_text(item, 80) for item in (value.get("trigger_signals") or [])[:12]],
        "applicability": {
            "scope": _text(applicability.get("scope"), 240),
            "required_context": [
                _text(item, 160)
                for item in (applicability.get("required_context") or [])[:12]
            ],
        },
        "spec_refs": list(value.get("spec_refs") or [])[:32],
        "rfp_refs": list(value.get("rfp_refs") or [])[:32],
        "verification_count": len(value.get("verification_refs") or []),
        "provenance": {
            "owner_key_id": owner.get("key_id"),
            "trust_level": owner.get("trust_level"),
            "mutation_count": int(source.get("mutation_count") or 0),
            "attestation_count": int(source.get("attestation_count") or 0),
            "confidentiality_class": value.get("confidentiality_class"),
            "rights_claim": _text(portability.get("rights_claim"), 240),
        },
    }


class StudioWorkflowFacade:
    """No browser value can select a command, path, argv, environment or MCP tool."""

    def __init__(self, workspace: str | Path):
        self.root = Path(workspace).expanduser().resolve()
        self._lock = threading.RLock()
        self._receipts = self.root / ".apatch/studio/action_receipts.json"

    def _load(self, store: StateDirectory | None = None) -> dict[str, dict[str, Any]]:
        try:
            value = (store.read_json(self._receipts.name) if store is not None
                     else read_json(self._receipts))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, UnicodeError) as exc:
            raise StudioWorkflowError(
                "local action receipt store is unavailable",
                code="action_receipt_store_unavailable",
                status_code=503,
            ) from exc
        if not isinstance(value, dict):
            raise StudioWorkflowError(
                "local action receipt store is invalid",
                code="action_receipt_store_invalid",
                status_code=503,
            )
        return {key: item for key, item in value.items() if isinstance(item, dict)}

    def _save(self, receipts: dict[str, dict[str, Any]], store: StateDirectory | None = None) -> None:
        try:
            if store is None:
                write_json(self._receipts, receipts)
            else:
                store.write_json(self._receipts.name, receipts)
        except OSError as exc:
            raise StudioWorkflowError(
                "local action receipt store is unavailable",
                code="action_receipt_store_unavailable", status_code=503,
            ) from exc

    def _complete(
        self,
        request: FixedPurposeRequest,
        command: str,
        context: dict[str, Any],
        operation: Callable[[], dict[str, Any]],
    ) -> dict[str, Any]:
        request_hash = _document_hash(
            {
                "command": command,
                "context": context,
                "request": request.model_dump(mode="json"),
            }
        )
        with self._lock:
            try:
                store = StateDirectory(self._receipts.parent, create=True)
                store.__enter__()
            except OSError as exc:
                raise StudioWorkflowError(
                    "local action receipt store is unavailable",
                    code="action_receipt_store_unavailable", status_code=503,
                ) from exc
            try:
                try:
                    store.check_file(self._receipts.name)
                except OSError as exc:
                    raise StudioWorkflowError(
                        "local action receipt store is unavailable",
                        code="action_receipt_store_unavailable", status_code=503,
                    ) from exc
                return self._complete_stored(request, command, request_hash, operation, store)
            finally:
                store.__exit__(None, None, None)

    def _complete_stored(self, request, command, request_hash, operation, store):
        receipts = self._load(store)
        existing = receipts.get(request.request_id)
        if existing is not None:
            if existing.get("request_hash") != request_hash:
                raise StudioWorkflowError(
                    "request id was already used for a different action",
                    code="action_idempotency_conflict",
                )
            return existing
        result = operation()
        receipt = {
            "schema": "apatch.studio.action-receipt.v1",
            "action_id": "apsact_" + request_hash[7:39],
            "request_id": request.request_id,
            "request_hash": request_hash,
            "command": command,
            "status": "complete" if result.get("ok", True) else "attention",
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "presentation": present_action(command, result),
            "result": result,
        }
        assert_projection_safe(receipt)
        receipts[request.request_id] = receipt
        self._save(receipts, store)
        return receipt

    @staticmethod
    def _spec_id(value: str) -> str:
        if not _SPEC_ID.fullmatch(value):
            raise StudioWorkflowError(
                "invalid specification id", code="invalid_spec_id", status_code=422
            )
        return value

    @staticmethod
    def _asset_id(value: str) -> str:
        if not _ASSET_ID.fullmatch(value):
            raise StudioWorkflowError(
                "invalid WorkAsset id", code="invalid_asset_id", status_code=422
            )
        return value

    def inspect_spec(self, spec_id: str, request: SpecInspectRequest) -> dict[str, Any]:
        spec_id = self._spec_id(spec_id)

        def run() -> dict[str, Any]:
            if request.action == "lint":
                raw = spec_lint_workspace(
                    str(self.root),
                    spec=spec_id,
                    include_needles_scaffold=False,
                    include_rfp_gates=True,
                )
                counts = raw.get("counts") or {}
                return {
                    "ok": bool(raw.get("passed")),
                    "spec_id": spec_id,
                    "action": "lint",
                    "counts": {
                        key: int(counts.get(key) or 0)
                        for key in ("errors", "warnings", "info")
                    },
                    "requirement_count": int(raw.get("requirements") or 0),
                }
            if request.action == "next":
                raw = spec_next_workspace(str(self.root), spec=spec_id)
                item = raw.get("next") or {}
                return {
                    "ok": bool(raw.get("ok")),
                    "spec_id": spec_id,
                    "action": "next",
                    "done": bool(raw.get("done")),
                    "next": {
                        "id": item.get("id"),
                        "title": _text(item.get("title"), 180),
                        "state": item.get("state"),
                        "content_hash": item.get("content_hash"),
                    } if item else None,
                    "remaining_count": len(raw.get("remaining") or []),
                }
            if request.action == "coverage":
                raw = rfp_spec_coverage_workspace(str(self.root), spec=spec_id)
                counts = raw.get("counts") or {}
                return {
                    "ok": bool(raw.get("passed")),
                    "spec_id": spec_id,
                    "action": "coverage",
                    "counts": {
                        key: int(counts.get(key) or 0)
                        for key in ("acceptance", "covered", "gaps", "errors", "warnings")
                    },
                }
            if request.action == "plan":
                raw = show_plan_workspace(str(self.root), spec=spec_id)
                plan = raw.get("plan") or {}
                execution = plan.get("execution_plan") or {}
                decision = plan.get("decision_plan") or {}
                return {
                    "ok": bool(raw.get("ok")),
                    "spec_id": spec_id,
                    "action": "plan",
                    "available": bool(plan),
                    "version": raw.get("version"),
                    "counts": {
                        "requirements": len(execution),
                        "assumptions": len(decision.get("assumptions") or []),
                        "risks": len(decision.get("risks") or []),
                    },
                }
            if request.action in {"interference", "schedule"}:
                raw = (
                    spec_schedule_workspace(str(self.root), strategy="safe")
                    if request.action == "schedule"
                    else spec_interference_workspace(str(self.root), level=2)
                )
                return {
                    "ok": bool(raw.get("ok", True)),
                    "spec_id": spec_id,
                    "action": request.action,
                    "counts": {
                        "conflicts": len(raw.get("conflicts") or []),
                        "blocked_pairs": len(raw.get("blocked_pairs") or []),
                        "scheduled": len(raw.get("safe_order") or raw.get("schedule") or []),
                    },
                    "has_cycle": bool(raw.get("has_cycle")),
                }
            if request.action == "reality":
                raw = reality_status_workspace(str(self.root), spec=spec_id)
                return {
                    "ok": True,
                    "spec_id": spec_id,
                    "action": "reality",
                    "counts": dict(raw.get("counts") or {}),
                    "records": [
                        {
                            "id": item.get("id"),
                            "summary": _text(item.get("summary"), 800),
                            "kind": item.get("kind"),
                            "status": item.get("status"),
                            "observed_at": item.get("observed_at"),
                            "discharged_by": list(
                                (raw.get("discharge_map") or {}).get(item.get("id"), [])
                            )[:16],
                        }
                        for item in (raw.get("records") or [])[:50]
                    ],
                }
            raw = spec_status_workspace(str(self.root), spec=spec_id)
            requirements = raw.get("requirements") or []
            return {
                "ok": bool(raw.get("ok")),
                "spec_id": spec_id,
                "action": "status",
                "done": bool(raw.get("done")),
                "summary": dict(raw.get("summary") or {}),
                "requirements": [
                    {
                        "id": item.get("id"),
                        "title": _text(item.get("title"), 180),
                        "state": item.get("state"),
                        "content_hash": item.get("content_hash"),
                        "stale": bool(item.get("stale")),
                    }
                    for item in requirements[:250]
                    if isinstance(item, dict)
                ],
            }

        return self._complete(request, "spec_" + request.action, {"spec_id": spec_id}, run)

    def rebind_spec(self, spec_id: str, request: SpecRebindRequest) -> dict[str, Any]:
        spec_id = self._spec_id(spec_id)

        def run() -> dict[str, Any]:
            raw = rebind_stale_requirements(
                str(self.root),
                spec=spec_id,
                run_verify=True,
                requirement_ids=request.requirement_ids,
                exclude_requirement_ids=request.exclude_requirement_ids,
            )
            return {
                "ok": bool(raw.get("ok")),
                "spec_id": spec_id,
                "action": "rebind_stale",
                "rebound": list(raw.get("rebound") or raw.get("attested") or []),
                "preserved_stale": list(
                    raw.get("preserved_stale") or raw.get("stale") or []
                ),
                "failed": list(raw.get("failed") or []),
            }

        return self._complete(
            request,
            "spec_rebind_stale",
            {
                "spec_id": spec_id,
                "requirement_ids": request.requirement_ids,
                "exclude_requirement_ids": request.exclude_requirement_ids,
            },
            run,
        )

    def _cli(self, args: list[str], timeout: int = 120) -> dict[str, Any]:
        completed = subprocess.run(
            [*apatch_python_command("apatch.cli"), *args, "--json"],
            cwd=self.root,
            env={**os.environ, **apatch_python_startup_env()},
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=timeout,
            check=False,
        )
        try:
            value = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise StudioWorkflowError(
                "APatch returned no structured result",
                code="runtime_result_unavailable",
                status_code=503,
            ) from exc
        if not isinstance(value, dict):
            raise StudioWorkflowError(
                "APatch returned an invalid result",
                code="runtime_result_invalid",
                status_code=503,
            )
        return value

    def evidence_action(self, request: EvidenceActionRequest) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            helper = TrustChainHelper(str(self.root))
            if request.action == "inclusion":
                raw = verify_inclusion(str(self.root))
                return {
                    "ok": bool(raw.get("ok")),
                    "action": "inclusion",
                    "checked": int(raw.get("checked") or 0),
                    "verified": int(raw.get("verified") or 0),
                    "missing_count": len(raw.get("missing") or []),
                    "inconsistent_count": len(raw.get("inconsistent") or []),
                    "error_count": len(raw.get("errors") or []),
                    "degraded": bool(raw.get("degraded")),
                    "skipped": _text(raw.get("skipped"), 240) or None,
                }
            if request.action == "reality":
                spec_id = None
                if request.artifact and request.artifact.startswith("spec:"):
                    spec_id = request.artifact[5:].split("#", 1)[0]
                raw = reality_status_workspace(str(self.root), spec=spec_id)
                return {
                    "ok": True,
                    "action": "reality",
                    "artifact": request.artifact,
                    "counts": dict(raw.get("counts") or {}),
                    "records": [
                        {
                            "id": item.get("id"),
                            "summary": _text(item.get("summary"), 500),
                            "kind": item.get("kind"),
                            "status": item.get("status"),
                        }
                        for item in (raw.get("records") or [])[:50]
                        if isinstance(item, dict)
                    ],
                }
            if request.action == "ratify":
                assert request.artifact is not None
                spec_id, requirement_id = request.artifact[5:].split("#", 1)
                spec_id = self._spec_id(spec_id)
                status = spec_status_workspace(str(self.root), spec=spec_id)
                requirement = next(
                    (item for item in (status.get("requirements") or []) if item.get("id") == requirement_id),
                    None,
                )
                if requirement is None:
                    raise StudioWorkflowError(
                        "requirement is not present in the selected specification",
                        code="requirement_not_found",
                        status_code=404,
                    )
                raw = ratify(str(self.root), requirement.get("verify"))
                return {
                    "ok": raw.get("verdict") == "ratified",
                    "action": "ratify",
                    "artifact": request.artifact,
                    "verdict": raw.get("verdict"),
                    "current_rc": raw.get("current_rc"),
                    "new_failure_count": len(raw.get("new_failures") or []),
                }
            if request.action == "verify":
                args = ["verify", "notarization", "--target-dir", str(self.root)]
                args.append("--staged" if request.scope == "staged" else "--working-tree")
                raw = self._cli(args)
                return {
                    "ok": bool(raw.get("ok")),
                    "action": "verify",
                    "scope": request.scope,
                    "checked": int(raw.get("checked") or 0),
                    "violation_count": len(raw.get("violations") or []),
                    "notarized_file_count": int(raw.get("notarized_file_count") or 0),
                    "ledger_entries": int(raw.get("ledger_entries") or 0),
                    "trustchain_active": bool(raw.get("trustchain_active")),
                }
            if request.action == "coverage":
                raw = helper.artifact_coverage(artifact=request.artifact)
                rows = raw.get("coverage") or raw.get("items") or []
                return {
                    "ok": bool(raw.get("ok", True)),
                    "action": "coverage",
                    "artifact": request.artifact,
                    "covered_count": int(raw.get("covered_count") or len(rows)),
                    "uncovered_count": int(raw.get("uncovered_count") or 0),
                }
            raw = helper.list_intent_history(artifact=request.artifact, limit=50)
            rows = raw.get("items") or raw.get("history") or raw.get("entries") or []
            items = [
                {
                    "id": item.get("op_id") or item.get("id"),
                    "role": item.get("role"),
                    "tool": item.get("tool_id") or item.get("tool"),
                    "at": item.get("timestamp") or item.get("at"),
                    "signed_by": item.get("signed_by"),
                    "session_id": item.get("governed_session_id"),
                }
                for item in rows[:50]
                if isinstance(item, dict)
            ]
            result = {
                "ok": True,
                "action": request.action,
                "artifact": request.artifact,
                "count": len(items),
                "items": items,
            }
            if request.action == "export":
                result["bundle_hash"] = _document_hash(
                    {
                        "schema": "apatch.studio.safe-evidence-export.v1",
                        "artifact": request.artifact,
                        "items": items,
                    }
                )
                result["bounded"] = True
            return result

        return self._complete(
            request,
            "evidence_" + request.action,
            {"scope": request.scope, "artifact": request.artifact},
            run,
        )

    def search_assets(self, request: AssetSearchRequest) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            raw = search_work_assets(
                str(self.root), query=request.query, limit=request.limit
            )
            rows = raw.get("assets") or raw.get("items") or []
            return {
                "ok": bool(raw.get("ok", True)),
                "action": "search",
                "query": request.query,
                "count": int(raw.get("asset_count") or raw.get("count") or len(rows)),
                "items": [_asset(item) for item in rows[: request.limit]],
            }

        return self._complete(
            request, "asset_search", {"query": request.query, "limit": request.limit}, run
        )

    def suggest_assets(self, request: AssetSuggestRequest) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            raw = suggest_work_assets(
                str(self.root), intent=request.objective, limit=request.limit
            )
            rows = raw.get("assets") or raw.get("suggestions") or raw.get("items") or []
            return {
                "ok": bool(raw.get("ok", True)),
                "action": "suggest",
                "objective": request.objective,
                "count": len(rows),
                "items": [_asset(item) for item in rows[: request.limit]],
            }

        return self._complete(
            request,
            "asset_suggest",
            {"objective": request.objective, "limit": request.limit},
            run,
        )

    def asset_action(self, asset_id: str, request: AssetActionRequest) -> dict[str, Any]:
        asset_id = self._asset_id(asset_id)

        def run() -> dict[str, Any]:
            if request.action == "recall":
                raw = build_recall_bundle(
                    str(self.root), asset_id=asset_id, intent=request.intent
                )
                return {
                    "ok": bool(raw.get("ok")),
                    "action": "recall",
                    "asset_id": asset_id,
                    "recallable": bool(raw.get("recallable") or raw.get("ok")),
                    "reason": _text(raw.get("reason") or raw.get("error"), 240) or None,
                }
            raw = show_work_asset(str(self.root), asset_id=asset_id)
            projected = _asset(raw)
            return {
                "ok": bool(raw.get("ok", True)),
                "action": request.action,
                "asset": projected,
                "bundle_hash": (
                    _document_hash(projected) if request.action == "export" else None
                ),
                "bounded": request.action == "export",
            }

        return self._complete(
            request,
            "asset_" + request.action,
            {"asset_id": asset_id, "intent": request.intent},
            run,
        )

    def policy_action(self, request: Any) -> dict[str, Any]:
        from apatch_studio.policy_workflow import run_policy_action

        return run_policy_action(self, request)

    def workspace_action(self, request: Any) -> dict[str, Any]:
        from apatch_studio.settings_workflow import run_workspace_action

        return run_workspace_action(self, request)

    def system_action(self, request: SystemActionRequest) -> dict[str, Any]:
        def run() -> dict[str, Any]:
            if request.action in {"gc_preview", "gc_execute"}:
                execute = request.action == "gc_execute"
                raw = run_gc(
                    str(self.root),
                    mode="safe" if execute else "report",
                    dry_run=not execute,
                )
                if execute:
                    return {
                        "ok": bool(raw.get("ok")),
                        "action": "gc_execute",
                        "dry_run": False,
                        "deleted_count": int(raw.get("deleted_count") or 0),
                        "reclaimed_bytes": int(raw.get("reclaimed_bytes") or 0),
                        "skipped_count": len(raw.get("skipped") or []),
                    }
                report = raw.get("report") or raw
                counts = {
                    key: int(report.get(key) or 0)
                    for key in (
                        "artifact_count",
                        "orphan_count",
                        "unclassified_count",
                        "inferred_count",
                    )
                }
                return {
                    "ok": bool(raw.get("ok", True)),
                    "action": "gc_preview",
                    "dry_run": True,
                    "counts": counts,
                    "action_required": str(report.get("status") or "") != "clean",
                }
            if request.action == "policy_verify":
                raw = self._cli(["policy", "verify", "--target-dir", str(self.root)])
                return {
                    "ok": bool(raw.get("ok")),
                    "action": "policy_verify",
                    "valid": bool(raw.get("valid") or raw.get("ok")),
                    "signed": bool(raw.get("signed") or raw.get("signature_valid")),
                    "drift": bool(raw.get("drift") or raw.get("drifted")),
                }
            raw = run_doctor(str(self.root))
            health = raw.get("mcp_health") or {}
            fingerprint = health.get("stored_mcp_fingerprint") or {}
            catalog = health.get("mcp_tool_catalog") or {}
            writer = raw.get("writer_protocol") or {}
            result = {
                "ok": bool(raw.get("ok", True)),
                "action": request.action,
                "version": raw.get("version"),
                "profile": fingerprint.get("mcp_profile") or raw.get("mcp_profile"),
                "tool_count": int(catalog.get("count") or 0),
                "writer_protocol": writer.get("protocol"),
                "concurrent_writers": bool(writer.get("disjoint_concurrency")),
                "trust_mode": (raw.get("trustchain") or {}).get("mode"),
                "enforcement": bool((raw.get("enforcement") or {}).get("active")),
            }
            if request.action == "hygiene":
                hygiene = raw.get("hygiene") or raw.get("runtime_hygiene") or {}
                hygiene_status = hygiene.get("status") or "unknown"
                result["ok"] = result["ok"] and hygiene_status == "clean"
                result["hygiene"] = {
                    "status": hygiene_status,
                    "issue_count": len(hygiene.get("issues") or []),
                }
            return result

        return self._complete(request, "system_" + request.action, {}, run)
