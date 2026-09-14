"""Bounded local workspace onboarding actions for APatch Studio."""

from __future__ import annotations

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

_ALIAS = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")


class WorkspaceActionRequest(FixedPurposeRequest):
    action: Literal["list", "register", "remove"]
    alias: str | None = Field(default=None, max_length=64)
    confirmed: bool = False

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
        if self.action == "list":
            if self.alias is not None or self.confirmed:
                raise ValueError("list accepts no alias or confirmation")
            return self
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


def run_workspace_action(facade: Any, request: WorkspaceActionRequest) -> dict[str, Any]:
    def run() -> dict[str, Any]:
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
