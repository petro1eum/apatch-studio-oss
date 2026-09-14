"""Bounded local APatch policy workflow for Studio."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Literal

from pydantic import Field, model_validator

from apatch.policy_lock import POLICY_FILES, POLICY_LOCK_REL, sign_policy, verify_policy
from apatch_studio.action_facade import FixedPurposeRequest, StudioWorkflowError
from apatch_studio.state_io import StateDirectory, check_target, read_json, write_json


class PolicyActionRequest(FixedPurposeRequest):
    action: Literal["status", "preview", "apply", "sign", "verify", "restore"]
    mode: Literal["audit", "enforce"] | None = None
    governed_mode: Literal["auto_session", "strict"] | None = None
    watcher: Literal["audit", "revert"] | None = None
    lease_max_seconds: int | None = Field(default=None, ge=30, le=3600)
    confirmed: bool = False

    @model_validator(mode="after")
    def validate_policy_action(self):
        fields = (self.mode, self.governed_mode, self.watcher, self.lease_max_seconds)
        if self.action in {"preview", "apply"} and all(value is None for value in fields):
            raise ValueError("preview and apply require a bounded policy field")
        if self.action not in {"preview", "apply"} and any(value is not None for value in fields):
            raise ValueError("policy fields are accepted only by preview and apply")
        if self.action in {"apply", "sign", "restore"} and not self.confirmed:
            raise ValueError("policy mutation requires explicit confirmation")
        return self


def _load(path: Path) -> dict[str, Any]:
    try:
        value = read_json(path)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError, UnicodeError) as exc:
        raise StudioWorkflowError(
            "local policy configuration is unavailable",
            code="policy_configuration_unavailable",
            status_code=503,
        ) from exc
    if not isinstance(value, dict):
        raise StudioWorkflowError(
            "local policy configuration is invalid",
            code="policy_configuration_invalid",
            status_code=503,
        )
    return value


def _write(path: Path, value: dict[str, Any]) -> None:
    write_json(path, value)


def _policy_inputs(root: Path) -> dict[str, bytes]:
    inputs = {}
    for relative in (*POLICY_FILES, POLICY_LOCK_REL, ".apatch/agent-identity.json"):
        path = root / relative
        try:
            with StateDirectory(path.parent) as directory:
                inputs[relative] = directory.read_bytes(path.name)
        except FileNotFoundError:
            pass
    return inputs


def _core_policy_action(root: Path, *, sign: bool = False) -> dict[str, Any]:
    """Let Core operate on exact bytes in an operator-private temporary root.

    Core's path-based signature writer must never traverse workspace ancestry.
    The identity file contains a reference to the enrolled key, not a new key;
    copying the reference preserves both PEM and command-backed identity lookup.
    """
    inputs = _policy_inputs(root)
    with TemporaryDirectory(prefix="studio-policy-") as temporary:
        snapshot = Path(temporary).resolve()
        for relative, data in inputs.items():
            path = snapshot / relative
            with StateDirectory(path.parent, create=True) as directory:
                directory.write_bytes(path.name, data)
        result = sign_policy(str(snapshot)) if sign else verify_policy(str(snapshot))
        if sign and result.get("ok"):
            if _policy_inputs(root) != inputs:
                raise StudioWorkflowError("local policy changed while signing",
                                          code="policy_configuration_drift")
            _write(root / POLICY_LOCK_REL, read_json(snapshot / POLICY_LOCK_REL))
        return result


def _public(sandbox: dict[str, Any], enforcement: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": sandbox.get("mode") or "off",
        "governed_mode": enforcement.get("governed_mode") or "off",
        "watcher": sandbox.get("watcher") or "off",
        "lease_max_seconds": int(sandbox.get("lease_max_seconds") or 300),
        "block_commit_without_proof": bool(enforcement.get("block_commit_without_proof")),
    }


def run_policy_action(facade: Any, request: PolicyActionRequest) -> dict[str, Any]:
    root = facade.root
    sandbox_path = root / ".apatch/sandbox.json"
    enforcement_path = root / ".apatch/enforcement.json"
    history_path = root / ".apatch/studio/policy_history.json"

    def run() -> dict[str, Any]:
        if request.action in {"apply", "restore", "sign"}:
            targets = (root / POLICY_LOCK_REL,) if request.action == "sign" else (
                history_path, sandbox_path, enforcement_path,
            )
            for path in targets:
                check_target(path)
        sandbox = _load(sandbox_path)
        enforcement = _load(enforcement_path)
        current = _public(sandbox, enforcement)
        if request.action in {"status", "verify"}:
            verified = _core_policy_action(root)
            return {
                "ok": bool(verified.get("ok")),
                "action": request.action,
                "current": current,
                "signed": bool(verified.get("signed")),
                "signature_ok": bool(verified.get("signature_ok")),
                "secure": bool(verified.get("secure")),
                "has_drift": bool(verified.get("has_drift")),
                "signer_key_id": verified.get("signer_key_id"),
                "reason": str(verified.get("reason") or "")[:240] or None,
            }

        proposed_sandbox = dict(sandbox)
        proposed_enforcement = dict(enforcement)
        if request.mode is not None:
            proposed_sandbox["mode"] = request.mode
        if request.watcher is not None:
            proposed_sandbox["watcher"] = request.watcher
        if request.lease_max_seconds is not None:
            proposed_sandbox["lease_max_seconds"] = request.lease_max_seconds
        if request.governed_mode is not None:
            proposed_enforcement["governed_mode"] = request.governed_mode
        proposed = _public(proposed_sandbox, proposed_enforcement)
        changes = [
            {"field": key, "before": current[key], "after": proposed[key]}
            for key in ("mode", "governed_mode", "watcher", "lease_max_seconds")
            if current[key] != proposed[key]
        ]
        if request.action == "preview":
            return {
                "ok": True,
                "action": "preview",
                "current": current,
                "proposed": proposed,
                "changes": changes,
                "mutation_performed": False,
            }
        if request.action == "apply":
            history = _load(history_path)
            snapshots = list(history.get("snapshots") or [])
            snapshots.append({
                "sandbox": sandbox,
                "enforcement": enforcement,
                "captured_at": datetime.now(timezone.utc).isoformat(),
            })
            _write(history_path, {"version": 1, "snapshots": snapshots[-20:]})
            _write(sandbox_path, proposed_sandbox)
            _write(enforcement_path, proposed_enforcement)
            return {
                "ok": True,
                "action": "apply",
                "current": proposed,
                "changes": changes,
                "signed": False,
                "next_action": "sign",
            }
        if request.action == "sign":
            raw = _core_policy_action(root, sign=True)
            return {
                "ok": bool(raw.get("ok")),
                "action": "sign",
                "signed": bool(raw.get("ok")),
                "signer_key_id": raw.get("signer_key_id"),
                "anchor_secure": bool(raw.get("anchor_secure")),
                "reason": str(raw.get("error") or "")[:240] or None,
            }

        history = _load(history_path)
        snapshots = list(history.get("snapshots") or [])
        if not snapshots:
            raise StudioWorkflowError(
                "no previous local policy version is available",
                code="policy_restore_unavailable",
            )
        previous = snapshots.pop()
        _write(sandbox_path, dict(previous.get("sandbox") or {}))
        _write(enforcement_path, dict(previous.get("enforcement") or {}))
        _write(history_path, {"version": 1, "snapshots": snapshots})
        return {
            "ok": True,
            "action": "restore",
            "current": _public(
                dict(previous.get("sandbox") or {}),
                dict(previous.get("enforcement") or {}),
            ),
            "remaining_restore_points": len(snapshots),
            "signed": False,
            "next_action": "sign",
        }

    context = {
        "action": request.action,
        "mode": request.mode,
        "governed_mode": request.governed_mode,
        "watcher": request.watcher,
        "lease_max_seconds": request.lease_max_seconds,
    }
    def safe_run():
        try:
            return run()
        except OSError as exc:
            raise StudioWorkflowError("local policy configuration is unavailable",
                                      code="policy_configuration_unavailable", status_code=503) from exc

    return facade._complete(request, "policy_" + request.action, context, safe_run)
