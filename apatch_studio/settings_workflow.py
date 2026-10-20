"""Bounded local workspace onboarding actions for APatch Studio."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from apatch.workflows import (
    workspace_inspect_workspace,
    workspace_list_workspace,
    workspace_register_workspace,
    workspace_remove_workspace,
)
from apatch_studio.action_facade import FixedPurposeRequest, StudioWorkflowError
from apatch_studio.run_store import workspace_identity
from apatch_studio.state_io import StateDirectory

_ALIAS = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")


class WorkspaceActionRequest(FixedPurposeRequest):
    action: Literal["list", "register", "remove", "setup_status", "setup_review", "setup_confirm", "setup_retry"]
    alias: str | None = Field(default=None, max_length=64)
    confirmed: bool = False
    scope_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("alias")
    @classmethod
    def normalize_alias(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lstrip("@").lower()
        if not _ALIAS.fullmatch(normalized):
            raise ValueError("invalid workspace alias")
        return normalized

    @model_validator(mode="after")
    def validate_action(self):
        if self.action in {"list", "setup_status", "setup_retry"}:
            if self.alias is not None or self.confirmed or self.scope_hash is not None:
                raise ValueError("this action accepts no alias, confirmation or scope hash")
            return self
        if self.action == "setup_review":
            if self.alias is None or self.confirmed or self.scope_hash is not None:
                raise ValueError("scope review requires only an alias")
            return self
        if self.action == "setup_confirm":
            if self.alias is None or not self.confirmed or self.scope_hash is None:
                raise ValueError("setup confirmation requires the reviewed alias and scope hash")
            return self
        if self.scope_hash is not None:
            raise ValueError("scope hash is accepted only for setup confirmation")
        if self.alias is None:
            raise ValueError("workspace alias is required")
        if not self.confirmed:
            raise ValueError("workspace registry mutation requires confirmation")
        return self


def _entry(raw: dict[str, Any]) -> dict[str, Any]:
    drift = raw.get("drift") or []
    ready = bool(raw.get("ready")) and not drift
    return {
        "alias": str(raw.get("alias") or ""),
        "ready": ready,
        "drift_count": len(drift),
        "registered_at": raw.get("registered_at"),
        "error_type": raw.get("error_type"),
        "recommended_action": None if ready else "Repair local workspace readiness",
    }


def _require_ok(raw: dict[str, Any]) -> None:
    if raw.get("ok"):
        return
    code = str(raw.get("error_type") or "workspace_registry_action_failed").lower()
    raise StudioWorkflowError(
        "local workspace registry action could not be completed",
        code=code,
    )


_SETUP_FILE = "workspace_setup.json"
_STAGES = ("configured", "loaded", "authorized", "verified")
_STATE_STATUSES = {"satisfied", "not_observed", "stale", "failed"}


def _code(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,95}", value) else fallback


def _setup_scope(root: Path, alias: str | None) -> dict[str, Any]:
    def digest(parent: Path, name: str) -> str | None:
        try:
            with StateDirectory(parent) as store:
                return hashlib.sha256(store.read_bytes(name, limit=262144)).hexdigest()
        except FileNotFoundError:
            return None
    identity = workspace_identity(root)
    info = root.stat()
    scope = {
        "workspace_id": identity, "alias": alias,
        "config_sha256": digest(root / ".apatch", "mcp.json"),
        "contract_sha256": digest(root, "AGENTS.md"),
    }
    binding = {**scope, "device": int(info.st_dev), "inode": int(info.st_ino)}
    scope["scope_hash"] = hashlib.sha256(json.dumps(binding, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    return scope


def _registered(root: Path, alias: str | None, *, require_current: bool = False) -> bool:
    if alias is None:
        return False
    raw = workspace_inspect_workspace(str(root), alias=alias, include_contract=False)
    if raw.get("error_type") == "WORKSPACE_ALIAS_UNKNOWN":
        return False
    if not raw.get("ok"):
        if require_current:
            _require_ok(raw)
        return False
    if Path(str(raw.get("path") or "")).expanduser().resolve() != root:
        if require_current:
            raise StudioWorkflowError("alias belongs to another project", code="workspace_alias_not_current")
        return False
    return bool(raw.get("ready")) and not raw.get("drift")


def _probe_metadata(raw: Any) -> dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    return {
        "ok": raw.get("ok") is True,
        "status": _code(raw.get("status"), "failed"),
        "scope": "configured_command_in_disposable_workspace",
        "host_tool_availability": "not_observable",
        "config_sha256": raw.get("config_sha256") if isinstance(raw.get("config_sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", raw["config_sha256"]) else None,
        "handshake_performed": raw.get("handshake_performed") is True,
        "child_reaped": raw.get("child_reaped") is True,
        "tool_count": min(10000, max(0, raw.get("tool_count", 0)))
            if type(raw.get("tool_count", 0)) is int else 0,
    }


def _runtime_checked(scope: dict[str, Any], probe: dict[str, Any]) -> bool:
    return bool(scope["config_sha256"]) and probe["config_sha256"] == scope["config_sha256"] and probe["ok"] and probe["handshake_performed"] and probe["child_reaped"] and probe["tool_count"] > 0


def _setup_view(root: Path, state: dict[str, Any], scope: dict[str, Any]) -> dict[str, Any]:
    try:
        from apatch.mcp.project_admission import project_readiness
    except ModuleNotFoundError as exc:
        if exc.name != "apatch.mcp.project_admission":
            raise
        project_readiness = None

    probe = _probe_metadata(state.get("configured_runtime"))
    current = bool(scope["config_sha256"]) and probe["config_sha256"] == scope["config_sha256"]
    observed = project_readiness(str(root), configured_runtime=probe if current else None) if project_readiness else {
        "ready": False, "blocked_step": "configured", "states": {},
    }
    # No browser value or local checkpoint supplies host, signing or work proofs.
    states = {}
    for stage in _STAGES:
        item = (observed.get("states") or {}).get(stage) or {}
        states[stage] = {
            "status": item.get("status") if item.get("status") in _STATE_STATUSES else "not_observed",
            "reason": _code(item.get("reason"), "not_observed") if item.get("reason") else None,
        }
    confirmed = bool(scope["alias"]) and state.get("confirmed_scope_hash") == scope["scope_hash"]
    registered = _registered(root, scope["alias"])
    runtime_checked = _runtime_checked(scope, probe)
    # Connection readiness never requires manufacturing a source mutation or attestation.
    connection_ready = confirmed and registered and observed.get("ready") is True and all(
        states[name]["status"] == "satisfied" for name in ("configured", "loaded", "authorized"))
    blocked = observed.get("blocked_step")
    blocked = blocked if blocked in _STAGES else None
    error = state.get("last_error")
    error = {"code": _code(error.get("code"), "workspace_setup_failed"),
             "step": _code(error.get("step"), "connection_pending"),
             "retryable": error.get("retryable") is True} if isinstance(error, dict) else None
    if project_readiness is None and error is None:
        error = {"code": "project_readiness_unavailable", "step": "configured", "retryable": True}
    if confirmed and state.get("configured_runtime") is None and error is None:
        error = {"code": "configured_runtime_interrupted", "step": "configured", "retryable": True}
    return {
        **scope, "schema": "apatch.studio.project-setup.v1", "registered": registered,
        "confirmation_required": not confirmed,
        "confirmed_scope_hash": state.get("confirmed_scope_hash"),
        "step": "choose_project" if not scope["alias"] else "review_scope" if not confirmed
            else "ready" if connection_ready else "connection_pending",
        "blocked_step": "review_scope" if not confirmed else blocked,
        "states": states, "runtime_checked": runtime_checked,
        "connection_ready": connection_ready,
        "host_tool_availability": "observed" if states["loaded"]["status"] == "satisfied" else "not_observable",
        "retry_available": confirmed and not runtime_checked and bool(error and error["retryable"]),
        "last_error": error,
    }


def _run_setup(facade: Any, request: WorkspaceActionRequest) -> dict[str, Any]:
    from apatch.mcp.runtime_probe import probe_configured_server

    try:
        with StateDirectory(facade._receipts.parent, create=True) as store:
            try:
                state = store.read_json(_SETUP_FILE, limit=32768)
            except FileNotFoundError:
                state = {}
            if not isinstance(state, dict) or (state and (
                state.get("schema") != "apatch.studio.project-setup-checkpoint.v1"
                or state.get("workspace_id") != workspace_identity(facade.root)
                or not isinstance(state.get("alias"), str) or not _ALIAS.fullmatch(state["alias"])
            )):
                raise StudioWorkflowError("saved project setup is invalid", code="workspace_setup_state_invalid", status_code=503)
            alias = request.alias if request.action == "setup_review" else state.get("alias")
            scope = _setup_scope(facade.root, alias)
            if state.get("scope_hash") not in {None, scope["scope_hash"]}:
                state["configured_runtime"] = None
                state["last_error"] = {"code": "workspace_setup_scope_changed", "step": "review_scope", "retryable": False}
            if request.action == "setup_review":
                if state.get("scope_hash") != scope["scope_hash"]:
                    state["confirmed_scope_hash"] = None
                state["last_error"] = None
            state.update(scope, schema="apatch.studio.project-setup-checkpoint.v1")
            try:
                if request.action == "setup_confirm":
                    if request.alias != alias or request.scope_hash != scope["scope_hash"]:
                        raise StudioWorkflowError("project scope changed; review it again", code="workspace_setup_scope_changed")
                    state["confirmed_scope_hash"] = scope["scope_hash"]
                if request.action in {"setup_confirm", "setup_retry"} and not (
                    request.action == "setup_retry" and _runtime_checked(scope, _probe_metadata(state.get("configured_runtime")))
                ):
                    if state.get("confirmed_scope_hash") != scope["scope_hash"] or alias is None:
                        raise StudioWorkflowError("review the selected project scope", code="workspace_setup_scope_changed")
                    state["last_error"] = None
                    state["configured_runtime"] = None
                    # Save confirmed scope before the bounded probe. Reopening preserves it.
                    store.write_json(_SETUP_FILE, state)
                    if not _registered(facade.root, alias, require_current=True):
                        _require_ok(workspace_register_workspace(alias, str(facade.root), force=False))
                    try:
                        raw = probe_configured_server(str(facade.root), timeout=15.0)
                    except (OSError, ValueError, RuntimeError):
                        raw = {"ok": False, "status": "failed"}
                    state["configured_runtime"] = _probe_metadata(raw)
                    if not raw.get("ok"):
                        state["last_error"] = {
                            "code": "configured_runtime_" + _code(raw.get("status"), "failed"),
                            "step": "configured", "retryable": True,
                        }
                    # An edit during a probe invalidates this attempt's scope too.
                    after = _setup_scope(facade.root, alias)
                    if after["scope_hash"] != scope["scope_hash"]:
                        scope = after
                        state.update(scope, configured_runtime=None,
                            last_error={"code": "workspace_setup_scope_changed", "step": "review_scope", "retryable": False})
            except StudioWorkflowError as exc:
                state["last_error"] = {"code": _code(exc.code, "workspace_setup_failed"),
                                       "step": "review_scope", "retryable": False}
            view = _setup_view(facade.root, state, scope)
            state["step"] = view["step"]
            if alias is not None:
                store.write_json(_SETUP_FILE, state)
            return {"ok": view["last_error"] is None,
                    "action": request.action, "setup": view}
    except (OSError, ValueError, UnicodeError) as exc:
        raise StudioWorkflowError("saved project setup is unavailable",
                                  code="workspace_setup_state_unavailable", status_code=503) from exc


def run_workspace_action(facade: Any, request: WorkspaceActionRequest) -> dict[str, Any]:
    def run() -> dict[str, Any]:
        if request.action.startswith("setup_"):
            return _run_setup(facade, request)
        if request.action == "list":
            raw = workspace_list_workspace(str(facade.root), include_contract=False)
            _require_ok(raw)
            items = [_entry(item) for item in (raw.get("workspaces") or [])[:128]]
            return {"ok": True, "action": "list", "count": len(items), "items": items}

        alias = str(request.alias)
        if request.action == "register":
            raw = workspace_register_workspace(alias, str(facade.root), force=False)
            _require_ok(raw)
            return {
                "ok": True,
                "action": "register",
                "alias": alias,
                "current_workspace": True,
                "ready": bool(raw.get("ready")),
            }

        inspected = workspace_inspect_workspace(
            str(facade.root), alias=alias, include_contract=False
        )
        _require_ok(inspected)
        registered = Path(str(inspected.get("path") or "")).expanduser().resolve()
        if registered != facade.root:
            raise StudioWorkflowError(
                "Studio can remove only an alias for the current workspace",
                code="workspace_alias_not_current",
            )
        removed = workspace_remove_workspace(alias)
        _require_ok(removed)
        return {"ok": True, "action": "remove", "alias": alias, "removed": True}

    return facade._complete(
        request,
        "workspace_" + request.action,
        {"action": request.action, "alias": request.alias},
        run,
    )
