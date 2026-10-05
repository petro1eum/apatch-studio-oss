"""Owner-facing HTTP adapter for the native fixed-ID preparation transaction."""
from contextlib import contextmanager
from pathlib import Path
import re

from apatch.runtime.atomic_io import exclusive_file_lock
from apatch.sdd_integrity import _seal, _verify_seal, canonical_hash
from apatch.strict_existing_signer import ExistingSignerRefused
from apatch_studio.lock_authority import LockAuthorityError, approver_for
from apatch_studio.sdd_workflow import SddWorkflowError
from apatch_studio.state_io import check_target, read_json, write_json
from pydantic import BaseModel, ConfigDict, Field, StrictBool

PREPARATION = {"functional_acceptance": False, "implementation_allowed": False, "owner_freeze_required": True}
STORE_SCHEMA = "apatch.studio.contract-intake-selector.v1"


class IntakeFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    path: str = Field(min_length=1, max_length=1024)
    content: str = Field(min_length=1, max_length=1_048_576)


class ContractIntakeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    request_id: str = Field(pattern=r"^apsreq_[a-z0-9_-]{8,96}$")
    rfp_id: str = Field(pattern=r"^RFP-[A-Z0-9][A-Z0-9-]{1,95}$")
    actor_id: str = Field(min_length=1, max_length=4096)
    reason: str = Field(min_length=1, max_length=4096)
    files: list[IntakeFile] = Field(min_length=1, max_length=64)


class ContractIntakeApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    request_id: str = Field(pattern=r"^apsreq_[a-z0-9_-]{8,96}$")
    confirmed: StrictBool
    snapshot: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def intake_core():
    try:
        from apatch import sdd_contract_intake
        if not all(callable(getattr(sdd_contract_intake, name, None)) for name in (
                "prepare_contract_intake", "approve_contract_intake", "review_contract_intake")):
            raise ImportError("native fixed-ID owner intake API absent")
        return sdd_contract_intake
    except ImportError as exc:
        raise SddWorkflowError("Installed Core has no native owner contract intake. Nothing was approved or installed.",
                               code="sdd_contract_intake_unavailable", status_code=503) from exc


class ContractIntakeWorkflow:
    def __init__(self, workspace):
        self.root = Path(workspace).resolve()

    def _path(self, spec_id):
        if not isinstance(spec_id, str) or not re.fullmatch(r"SPEC-[A-Z0-9][A-Z0-9-]{1,95}", spec_id):
            raise SddWorkflowError("Invalid exact SPEC identity", code="sdd_contract_intake_invalid", status_code=422)
        return self.root / ".apatch/sdd/contract-intake-reviews" / (spec_id + ".json")

    @contextmanager
    def _guard(self):
        target = self.root / ".apatch/sdd/contract-intake-reviews/transaction"
        check_target(target.with_suffix(".lock"))
        with exclusive_file_lock(str(target)):
            yield

    @staticmethod
    def _read(path):
        try:
            value = read_json(path, limit=8_388_608)
        except FileNotFoundError:
            return None
        if not isinstance(value, dict):
            raise ValueError("Intake selector must be one object")
        _verify_seal(value, "Studio intake selector")
        return value

    def _validate(self, core, spec_id, value):
        if (value.get("schema") != STORE_SCHEMA or value.get("workspace") != str(self.root)
                or value.get("spec_id") != spec_id or not isinstance(value.get("review"), dict)
                or value["review"].get("spec_id") != spec_id):
            raise ValueError("Intake selector belongs to another SPEC or workspace")
        return core.review_contract_intake(self.root, value["review"])

    def _request_path(self, spec_id, request_id):
        return self._path(spec_id).parent / ".requests" / spec_id / (request_id + ".json")

    def _value(self, spec_id, kind, request, review):
        return _seal({"schema": STORE_SCHEMA, "workspace": str(self.root), "spec_id": spec_id,
                      "kind": kind, "request_id": request.request_id,
                      "fingerprint": canonical_hash({"kind": kind, "spec_id": spec_id,
                                                     "request": request.model_dump()}),
                      "review": review})

    def _archive(self, spec_id, value):
        digest = value["review"]["document_hash"]
        if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("Core intake review must be sealed")
        target = self._path(spec_id).parent / spec_id / (digest[7:] + ".json")
        saved = self._read(target)
        if saved is None:
            write_json(target, value)
        elif saved.get("review") != value["review"]:
            raise ValueError("Immutable intake review history changed")

    def review(self, spec_id):
        core = intake_core()
        try:
            value = self._read(self._path(spec_id))
            if value is None:
                return {"status": "not_prepared", **PREPARATION}
            return self._validate(core, spec_id, value)
        except (ValueError, OSError, KeyError, ExistingSignerRefused) as exc:
            raise SddWorkflowError(str(exc), code="sdd_contract_intake_invalid", status_code=409) from exc

    def propose(self, spec_id, request):
        core = intake_core()
        try:
            selector = self._path(spec_id)
            with self._guard():
                request_path = self._request_path(spec_id, request.request_id)
                saved_request = self._read(request_path)
                fingerprint = canonical_hash({"kind": "proposal", "spec_id": spec_id,
                                              "request": request.model_dump()})
                if saved_request is not None:
                    if saved_request.get("kind") != "proposal" or saved_request.get("fingerprint") != fingerprint:
                        raise ValueError("Intake request ID was reused with different inputs")
                    return self._validate(core, spec_id, saved_request)
                previous = self._read(selector)
                if previous is not None:
                    self._validate(core, spec_id, previous)
                reviewed = core.prepare_contract_intake(self.root, spec_id=spec_id, rfp_id=request.rfp_id,
                    actor_id=request.actor_id, reason=request.reason,
                    files=[item.model_dump() for item in request.files])
                if (reviewed.get("spec_id") != spec_id or reviewed.get("workspace") != str(self.root)
                        or any(reviewed.get(key) is not value for key, value in PREPARATION.items())):
                    raise ValueError("Core returned another intake scope")
                value = self._value(spec_id, "proposal", request, reviewed)
                # Validate the sealed native review before persisting selectors.
                projection = self._validate(core, spec_id, value)
                if previous is not None:
                    self._archive(spec_id, previous)
                self._archive(spec_id, value)
                write_json(request_path, value)
                write_json(selector, value)
                return projection
        except (ValueError, OSError, KeyError, ExistingSignerRefused) as exc:
            raise SddWorkflowError(str(exc), code="sdd_contract_intake_invalid", status_code=409) from exc

    def approve(self, spec_id, request, *, owner):
        core = intake_core()
        if request.confirmed is not True:
            raise SddWorkflowError("Explicit owner confirmation is required",
                                   code="sdd_owner_confirmation_required", status_code=422)
        try:
            with self._guard():
                value = self._read(self._path(spec_id))
                if value is None:
                    raise ValueError("Review this exact preparation package before approving")
                self._validate(core, spec_id, value)
                reviewed = value["review"]
                if reviewed["document_hash"] != request.snapshot:
                    raise ValueError("Review the current exact intake snapshot before confirming")
                request_path = self._request_path(spec_id, request.request_id)
                saved_request = self._read(request_path)
                fingerprint = canonical_hash({"kind": "approval", "spec_id": spec_id,
                                              "request": request.model_dump()})
                if saved_request is not None:
                    if (saved_request.get("kind") != "approval"
                            or saved_request.get("fingerprint") != fingerprint
                            or saved_request.get("review") != reviewed):
                        raise ValueError("Approval request ID was reused with a different decision")
                result = core.approve_contract_intake(self.root, reviewed, owner=owner,
                                                     expected_snapshot=request.snapshot)
                if any(result.get(key) is not item for key, item in PREPARATION.items()):
                    raise ValueError("Core preparation cannot grant execution authority")
                projection = core.review_contract_intake(self.root, reviewed)
                if projection.get("status") != "prepared" or projection.get("result") != result:
                    raise ValueError("Native preparation completion is not independently verified")
                if saved_request is None:
                    write_json(request_path, self._value(spec_id, "approval", request, reviewed))
                return projection
        except (ValueError, OSError, KeyError, ExistingSignerRefused) as exc:
            raise SddWorkflowError(str(exc), code="sdd_contract_intake_invalid", status_code=409) from exc


def install_routes(app, workspace, *, identity_root):
    """Extension endpoints retain create_app's loopback session/origin guards."""
    workflow = ContractIntakeWorkflow(workspace)
    app.state.studio_contract_intake = workflow
    previous_count = len(app.router.routes)

    @app.get("/api/v1/contract-intake/{spec_id}")
    def review_contract_intake(spec_id: str):
        return workflow.review(spec_id)

    @app.post("/api/v1/contract-intake/{spec_id}")
    def propose_contract_intake(spec_id: str, request: ContractIntakeRequest):
        return workflow.propose(spec_id, request)

    @app.post("/api/v1/contract-intake/{spec_id}/approve")
    def approve_contract_intake(spec_id: str, request: ContractIntakeApprovalRequest):
        try:
            owner = approver_for(identity_root)
        except LockAuthorityError as exc:
            raise SddWorkflowError(str(exc), code="sdd_intake_owner_unavailable", status_code=403) from exc
        return workflow.approve(spec_id, request, owner=owner)

    routes = app.router.routes[previous_count:]
    del app.router.routes[previous_count:]
    insertion = next((index for index, route in enumerate(app.router.routes)
                      if re.search(r"\{[^}]+:path\}", getattr(route, "path", ""))), len(app.router.routes))
    app.router.routes[insertion:insertion] = routes
