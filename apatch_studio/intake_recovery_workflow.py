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

    def diagnostic(self, spec_id, operation_id, artifact):
        """Read only an exact Core-written diagnostic in this guarded workspace."""
        import json
        import os
        import stat
        from apatch.diagnostics.schema import SCHEMA_VERSION

        try:
            self._original(spec_id)
            if (not re.fullmatch(r"apsreq_[a-z0-9_-]{8,96}", operation_id or "")
                    or artifact != f".apatch/diagnostics/{operation_id}.json"):
                raise ValueError("Exact operation diagnostic required")
            # Pin each directory handle: symlink/path replacement cannot redirect
            # this read outside the enrolled workspace. Never follow a supplied path.
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            try:
                for name in (".apatch", "diagnostics"):
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                    dir_fd=directory)
                    os.close(directory)
                    directory = child
                fd = os.open(operation_id + ".json", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
                with os.fdopen(fd, "rb") as stream:
                    info = os.fstat(stream.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > 1024 * 1024:
                        raise ValueError("Diagnostic is not a bounded private regular file")
                    raw = stream.read(1024 * 1024 + 1)
                    if len(raw) > 1024 * 1024:
                        raise ValueError("Diagnostic exceeds read bound")
            finally:
                os.close(directory)
            document = json.loads(raw)
            if not isinstance(document, dict):
                raise ValueError("Diagnostic document must be an object")
            rows = document.get("diagnostics")
            if (document.get("schema_version") != SCHEMA_VERSION
                    or document.get("session_id") != operation_id
                    or not isinstance(rows, list) or not rows
                    or document.get("diagnostic_count") != len(rows)
                    or any(not isinstance(row, dict) or row.get("operation_id") != operation_id
                           for row in rows)):
                raise ValueError("Diagnostic operation binding differs")
            cause = rows[-1].get("cause_code")
            if not isinstance(cause, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]{0,127}", cause):
                raise ValueError("Diagnostic cause code missing")
            # Project messages, never arbitrary payload/capability/key fields.
            messages = [row.get("message", "") for row in rows]
            if not all(isinstance(message, str) for message in messages):
                raise ValueError("Diagnostic messages malformed")
            detail = "\n".join(messages)
            detail = re.sub(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----",
                            "[REDACTED KEY]", detail, flags=re.DOTALL)
            detail = re.sub(r"(?i)\bBearer\s+[^\s,;]+", "Bearer [REDACTED]", detail)
            detail = re.sub(r"(?i)\b(session_token|access_token|refresh_token|api_key|password|secret)"
                            r"\s*[:=]\s*(?:\"[^\"]*\"|'[^']*'|[^\s,;]+)",
                            r"\1=[REDACTED]", detail)
            return {"status": "diagnostic_available", "diagnostic": {
                "operation_id": operation_id, "cause_code": cause,
                "redacted_detail": detail,
            }, **PREPARATION}
        except (ValueError, OSError, KeyError, TypeError) as exc:
            raise SddWorkflowError(
                "Protected operation diagnostic is unavailable or invalid",
                code="sdd_intake_diagnostic_invalid", status_code=409,
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
    def review_intake_recovery(spec_id: str, operation_id: str | None = None,
                               diagnostic_artifact: str | None = None):
        if operation_id is not None or diagnostic_artifact is not None:
            return workflow.diagnostic(spec_id, operation_id, diagnostic_artifact)
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
