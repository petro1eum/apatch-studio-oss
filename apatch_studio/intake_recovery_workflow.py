"""Guarded Studio projection of Core's existing uncommitted-intake recovery."""
from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, StrictBool

from apatch.sdd_integrity import canonical_hash
from apatch.strict_existing_signer import ExistingSignerRefused
from apatch_studio.contract_intake_workflow import (
    PREPARATION,
    STORE_SCHEMA,
    ContractIntakeWorkflow,
)
from apatch_studio.lock_authority import LockAuthorityError, approver_for
from apatch_studio.sdd_workflow import SddWorkflowError
from apatch_studio.state_io import write_json


class IntakeCancellationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    request_id: str = Field(pattern=r"^apsreq_[a-z0-9_-]{8,96}$")
    confirmed: StrictBool
    snapshot: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def recovery_core():
    try:
        from apatch import sdd_intake_recovery
        if not all(callable(getattr(sdd_intake_recovery, name, None)) for name in (
            "review_cancellation", "cancel_uncommitted_intake"
        )):
            raise ImportError("native owner intake cancellation API absent")
        return sdd_intake_recovery
    except ImportError as exc:
        raise SddWorkflowError(
            "Installed Core cannot cancel an uncommitted intake. Nothing was changed.",
            code="sdd_intake_recovery_unavailable", status_code=503,
        ) from exc


class IntakeRecoveryWorkflow:
    def __init__(self, workspace):
        self.intake = ContractIntakeWorkflow(workspace)
        self.root = self.intake.root

    def _original(self, spec_id):
        value = self.intake._read(self.intake._path(spec_id))
        if (value is None or value.get("schema") != STORE_SCHEMA
                or value.get("workspace") != str(self.root)
                or value.get("spec_id") != spec_id
                or not isinstance(value.get("review"), dict)
                or value["review"].get("spec_id") != spec_id):
            raise ValueError("An original stored intake review for this SPEC is required")
        return value["review"]

    def review(self, spec_id):
        try:
            reviewed = recovery_core().review_cancellation(self.root, self._original(spec_id))
            return {"status": "awaiting_cancellation", "snapshot": reviewed["document_hash"],
                    "review": reviewed, **PREPARATION}
        except (ValueError, OSError, KeyError, TypeError, ExistingSignerRefused) as exc:
            raise SddWorkflowError(
                str(exc), code="sdd_intake_recovery_invalid", status_code=409,
            ) from exc

    def cancel(self, spec_id, request, *, owner):
        if request.confirmed is not True:
            raise SddWorkflowError(
                "Explicit owner confirmation is required",
                code="sdd_owner_confirmation_required", status_code=422,
            )
        if not isinstance(owner, dict) or owner.get("certified") is not True:
            raise SddWorkflowError(
                "A certified native owner is required",
                code="sdd_intake_owner_unavailable", status_code=403,
            )
        core = recovery_core()
        try:
            # Serialize with the ordinary intake routes, not a separate approval.
            with self.intake._guard():
                original = self._original(spec_id)
                path = self.intake._request_path(spec_id, request.request_id)
                saved = self.intake._read(path)
                fingerprint = canonical_hash({
                    "kind": "cancellation", "spec_id": spec_id,
                    "request": request.model_dump(),
                })
                if saved is not None and (
                        saved.get("kind") != "cancellation"
                        or saved.get("fingerprint") != fingerprint
                        or saved.get("review") != original):
                    raise ValueError("Cancellation request ID was reused with a different decision")
                # Core rechecks the pending incarnation and original ledger,
                # signs once, and verifies the saved receipt on an exact retry.
                result = core.cancel_uncommitted_intake(
                    self.root, original, owner=owner, expected_snapshot=request.snapshot,
                )
                if (result.get("status") != "cancelled"
                        or any(result.get(key) is not value for key, value in PREPARATION.items())):
                    raise ValueError("Cancellation cannot grant implementation or acceptance")
                if saved is None:
                    write_json(path, self.intake._value(spec_id, "cancellation", request, original))
                return result
        except (ValueError, OSError, KeyError, TypeError, ExistingSignerRefused) as exc:
            raise SddWorkflowError(
                str(exc), code="sdd_intake_recovery_invalid", status_code=409,
            ) from exc


def install_routes(app, workspace, *, identity_root):
    """The existing Studio loopback/session/same-origin middleware remains authoritative."""
    workflow = IntakeRecoveryWorkflow(workspace)
    app.state.studio_intake_recovery = workflow
    previous_count = len(app.router.routes)

    @app.get("/api/v1/contract-intake/{spec_id}/recovery")
    def review_intake_recovery(spec_id: str):
        return workflow.review(spec_id)

    @app.post("/api/v1/contract-intake/{spec_id}/recovery/cancel")
    def cancel_intake_recovery(spec_id: str, request: IntakeCancellationRequest):
        try:
            owner = approver_for(identity_root)
        except LockAuthorityError as exc:
            raise SddWorkflowError(
                str(exc), code="sdd_intake_owner_unavailable", status_code=403,
            ) from exc
        return workflow.cancel(spec_id, request, owner=owner)

    routes = app.router.routes[previous_count:]
    del app.router.routes[previous_count:]
    insertion = next((index for index, route in enumerate(app.router.routes)
                      if re.search(r"\{[^}]+:path\}", getattr(route, "path", ""))),
                     len(app.router.routes))
    app.router.routes[insertion:insertion] = routes
