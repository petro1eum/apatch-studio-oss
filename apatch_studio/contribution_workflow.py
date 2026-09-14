"""Canonical APatch contribution and timesheet projections for Studio."""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Literal

from apatch.avatar_delivery import (
    avatar_runtime_compatibility,
    default_evidence_outbox_dir,
    pending_evidence_count,
    tracker_config_from_env,
)
from apatch.avatar_runtime_config import load_avatar_sync_config
from apatch.contribution import project_identity
from apatch.contribution_export import default_sync_receipt_dir, sync_to_trustchain_avatar
from apatch.timesheet import run_timesheet
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from apatch_studio.projection import assert_projection_safe

_REQUEST_ID = r"^apsreq_[a-z0-9][a-z0-9_-]{7,95}$"
_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:@#-]{0,191}$")
_GROUP_DIMENSIONS = {"project", "spec", "day"}


class TimesheetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(pattern=_REQUEST_ID)
    action: Literal["draft", "verify"]
    group_by: list[Literal["project", "spec", "day"]] = Field(
        default_factory=lambda: ["project", "spec", "day"],
        min_length=1,
        max_length=3,
    )
    since: date | None = Field(
        default_factory=lambda: datetime.now(timezone.utc).date() - timedelta(days=6)
    )
    until: date | None = Field(default_factory=lambda: datetime.now(timezone.utc).date())

    @field_validator("group_by")
    @classmethod
    def unique_dimensions(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)) or any(
            item not in _GROUP_DIMENSIONS for item in values
        ):
            raise ValueError("timesheet dimensions must be unique")
        return values

    @model_validator(mode="after")
    def ordered_period(self):
        if self.since and self.until and self.since > self.until:
            raise ValueError("timesheet start must not follow its end")
        return self


def _clean_token(value: Any, limit: int = 192) -> str | None:
    text = str(value or "").strip()
    if not text or len(text) > limit or not _SAFE_ID.fullmatch(text):
        return None
    return text


def extract_attestation_delivery(value: Any) -> dict[str, Any] | None:
    """Extract only allowlisted receipt fields from a structured runner event."""
    candidates: list[dict[str, Any]] = []
    stack: list[tuple[Any, int]] = [(value, 0)]
    while stack:
        current, depth = stack.pop()
        if depth > 12:
            continue
        if isinstance(current, dict):
            if "contribution_receipt" in current or "avatar_sync" in current:
                candidates.append(current)
            stack.extend((child, depth + 1) for child in list(current.values())[:64])
        elif isinstance(current, list):
            stack.extend((child, depth + 1) for child in current[:64])
    if not candidates:
        return None

    candidate = candidates[-1]
    result: dict[str, Any] = {"contribution_receipt": None, "avatar_sync": None}
    receipt = candidate.get("contribution_receipt")
    if isinstance(receipt, dict):
        result["contribution_receipt"] = {
            key: item
            for key, item in {
                "status": _clean_token(receipt.get("status"), 64),
                "code": _clean_token(receipt.get("code"), 96),
                "event_id": _clean_token(receipt.get("event_id")),
            }.items()
            if item is not None
        }
    sync = candidate.get("avatar_sync")
    if isinstance(sync, dict):
        action_required = [
            item
            for item in (
                _clean_token(item, 96)
                for item in list(sync.get("action_required") or [])[:16]
            )
            if item is not None
        ]
        result["avatar_sync"] = {
            key: item
            for key, item in {
                "ok": sync.get("ok") if isinstance(sync.get("ok"), bool) else None,
                "status": _clean_token(sync.get("status"), 96),
                "retryable": sync.get("retryable") if isinstance(sync.get("retryable"), bool) else None,
                "outbox_preserved": sync.get("outbox_preserved") if isinstance(sync.get("outbox_preserved"), bool) else None,
                "pending_outbox_items": max(0, sync["pending_outbox_items"]) if isinstance(sync.get("pending_outbox_items"), int) else None,
                "complete": sync.get("complete") if isinstance(sync.get("complete"), bool) else None,
                "action_required": action_required,
            }.items()
            if item is not None
        }
    if result["contribution_receipt"] is None and result["avatar_sync"] is None:
        return None
    assert_projection_safe(result)
    return result


class ContributionWorkflow:
    """Read APatch-owned contribution truth without re-aggregating its event ledger."""

    def __init__(
        self,
        workspace: str | os.PathLike[str],
        *,
        timesheet_runner: Callable[..., Any] = run_timesheet,
        compatibility_supplier: Callable[[], dict[str, Any]] = avatar_runtime_compatibility,
        tracker_supplier: Callable[[], dict[str, Any]] = tracker_config_from_env,
        evidence_pending_supplier: Callable[[], int] = pending_evidence_count,
        contribution_preview_supplier: Callable[[], dict[str, Any]] | None = None,
        last_ack_supplier: Callable[[], str | None] | None = None,
        project_supplier: Callable[[str], dict[str, Any]] = project_identity,
    ):
        self.root = Path(workspace).expanduser().resolve()
        if not self.root.is_dir():
            raise ValueError(f"workspace does not exist: {self.root}")
        self._timesheet = timesheet_runner
        self._compatibility = compatibility_supplier
        self._tracker = tracker_supplier
        self._evidence_pending = evidence_pending_supplier
        self._contribution_preview = contribution_preview_supplier or self._preview
        self._last_ack = last_ack_supplier or self._last_acknowledgement
        project = project_supplier(str(self.root))
        self.project_id = _clean_token(project.get("id")) or "unknown-project"
        self.project_name = str(project.get("name") or self.root.name).strip()[:192] or self.root.name

    def timesheet(self, request: TimesheetRequest) -> dict[str, Any]:
        common = {
            "target_dir": str(self.root),
            "by": ",".join(request.group_by),
            "since": request.since.isoformat() if request.since else None,
            "until": request.until.isoformat() if request.until else None,
            "project": self.project_id,
            "fmt": "json",
            "include_audit": True,
        }
        if request.action == "verify":
            raw = self._timesheet(**common, do_verify=True)
            verified = raw.get("verify") if isinstance(raw, dict) else {}
            drift_count = len((verified or {}).get("drift") or [])
            unsigned_count = len((verified or {}).get("unsigned") or [])
            signature_status = "complete" if unsigned_count == 0 else "partial"
            integrity_status = "matched" if drift_count == 0 else "drifted"
            if drift_count:
                summary = (
                    f"{drift_count} signed record"
                    + ("s no longer match" if drift_count != 1 else " no longer matches")
                    + " the recorded volumes."
                )
                next_action = "Inspect the changed ledger record before using this draft."
            elif unsigned_count:
                summary = (
                    f"{unsigned_count} older audit record"
                    + ("s are" if unsigned_count != 1 else " is")
                    + " unsigned; signed record volumes still match."
                )
                next_action = "Keep this as a draft or exclude legacy audit history."
            else:
                summary = "All checked signed records match their recorded volumes."
                next_action = "Submit the draft separately if human acceptance is required."
            result = {
                "schema": "apatch.studio.timesheet-verification.v1",
                "request_id": request.request_id,
                "source": "apatch.run_timesheet",
                "project": {"id": self.project_id, "name": self.project_name},
                "period": {
                    "since": request.since.isoformat() if request.since else None,
                    "until": request.until.isoformat() if request.until else None,
                },
                "ok": bool((verified or {}).get("ok")),
                "checked": int((verified or {}).get("checked") or 0),
                "drift_count": drift_count,
                "unsigned_count": unsigned_count,
                "signature_status": signature_status,
                "integrity_status": integrity_status,
                "accepted_time": False,
                "summary": summary,
                "next_action": next_action,
            }
            assert_projection_safe(result)
            return result

        raw = self._timesheet(**common, do_verify=False)
        groups = []
        for row in list((raw or {}).get("groups") or [])[:500]:
            if not isinstance(row, dict):
                continue
            groups.append({
                "key": [str(item)[:192] for item in list(row.get("key") or [])[:3]],
                "sessions": int(row.get("sessions") or 0),
                "hours": float(row.get("hours") or 0),
                "active_sec": float(row.get("active_sec") or 0),
                "ops": int(row.get("ops") or 0),
                "files_touched": int(row.get("files_touched") or 0),
                "insertions": int(row.get("insertions") or 0),
                "deletions": int(row.get("deletions") or 0),
            })
        warnings = []
        if any(row["ops"] > 0 and row["insertions"] == 0 and row["deletions"] == 0 for row in groups):
            warnings.append("line_volume_unavailable")
        result = {
            "schema": "apatch.studio.timesheet-draft.v1",
            "request_id": request.request_id,
            "source": "apatch.run_timesheet",
            "project": {"id": self.project_id, "name": self.project_name},
            "period": {
                "since": request.since.isoformat() if request.since else None,
                "until": request.until.isoformat() if request.until else None,
            },
            "basis": "operation_spacing_estimate",
            "accepted_time": False,
            "group_by": list(request.group_by),
            "groups": groups,
            "warnings": warnings,
            "disclaimer": "Hours are APatch operation-spacing estimates, not a stopwatch, payroll record or accepted time.",
        }
        assert_projection_safe(result)
        return result

    def health(self) -> dict[str, Any]:
        try:
            compatibility = self._compatibility()
        except Exception:
            compatibility = {"ok": False, "status": "dependency_incompatible"}
        try:
            tracker = self._tracker()
            durable = load_avatar_sync_config()
        except Exception:
            tracker, durable = {}, {}
        try:
            evidence_pending = max(0, int(self._evidence_pending()))
        except Exception:
            evidence_pending = 0
        try:
            contribution_pending = max(0, int(self._contribution_preview().get("pending") or 0))
        except Exception:
            contribution_pending = 0
        configured = bool(tracker.get("base_url") or durable.get("tracker_base_url"))
        credential_channel = bool(
            tracker.get("service_token") or tracker.get("avatar_token") or durable.get("secret_binding")
        )
        last_ack = self._last_ack()
        if not compatibility.get("ok"):
            state = "dependency_unavailable"
        elif not configured:
            state = "unconfigured"
        elif last_ack and not evidence_pending and not contribution_pending:
            state = "acknowledged"
        else:
            state = "configured"
        result = {
            "schema": "apatch.studio.contribution-health.v1",
            "timesheet_available": True,
            "tracker_state": state,
            "tracker_configured": configured,
            "tracker_auth_configured": credential_channel,
            "contract_status": str(compatibility.get("status") or "unknown")[:96],
            "evidence_pending": evidence_pending,
            "contribution_pending": contribution_pending,
            "pending_total": evidence_pending + contribution_pending,
            "last_acknowledgement": last_ack,
        }
        assert_projection_safe(result)
        return result

    @staticmethod
    def _preview() -> dict[str, Any]:
        return sync_to_trustchain_avatar(dry_run=True)

    @staticmethod
    def _last_acknowledgement() -> str | None:
        latest = 0.0
        for root, pattern in (
            (Path(default_evidence_outbox_dir()), "*.ack.json"),
            (Path(default_sync_receipt_dir()), "*.json"),
        ):
            if root.is_dir():
                for candidate in root.rglob(pattern):
                    try:
                        latest = max(latest, candidate.stat().st_mtime)
                    except OSError:
                        continue
        return datetime.fromtimestamp(latest, tz=timezone.utc).isoformat() if latest else None
