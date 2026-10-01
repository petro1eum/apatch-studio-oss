"""Native owner review for exact ownership-only amendments; not acceptance."""
from pydantic import BaseModel, ConfigDict, Field

from apatch.sdd_integrity import canonical_hash
from apatch_studio.document_publication_workflow import DocumentPublicationWorkflow, DocumentPublicationApprovalRequest
from apatch_studio.lock_authority import approver_for
from apatch_studio.sdd_workflow import SddWorkflowError
from apatch_studio.state_io import read_json, write_json


class OwnershipHandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(pattern=r"^apsreq_[a-z0-9_-]{8,96}$")
    source_spec: str = Field(pattern=r"^SPEC-[A-Z0-9][A-Z0-9-]{1,95}$")
    source_contract_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    paths: list[str] = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=8, max_length=4096)


def handoff_core():
    try:
        from apatch import sdd_ownership_handoff
        return sdd_ownership_handoff
    except ImportError as exc:
        raise SddWorkflowError("This Core cannot transfer ownership; no documents were changed.",
                               code="sdd_ownership_handoff_unavailable", status_code=503) from exc


class OwnershipHandoffWorkflow(DocumentPublicationWorkflow):
    def _path(self, spec_id):
        original = super()._path(spec_id)
        return self.root / ".apatch/sdd/ownership-handoff-reviews" / original.name

    def review(self, spec_id):
        core = handoff_core()
        try:
            value = read_json(self._path(spec_id), limit=8_388_608)
        except FileNotFoundError:
            return {"status": "not_prepared", "functional_acceptance": False}
        try:
            if value["review"]["destination_spec"] != spec_id:
                raise ValueError("Ownership review belongs to another destination")
            return core.review_ownership_handoff(self.root, value["review"])
        except (ValueError, OSError, KeyError) as exc:
            raise SddWorkflowError(str(exc), code="sdd_ownership_handoff_invalid") from exc

    def propose(self, spec_id, request):
        with self._guard():
            try:
                path = self._path(spec_id)
                fingerprint = canonical_hash({"spec_id": spec_id, "request": request.model_dump()})
                try:
                    previous = read_json(path, limit=8_388_608)
                except FileNotFoundError:
                    previous = None
                core = handoff_core()
                if previous is not None and previous.get("request_id") == request.request_id:
                    if previous.get("fingerprint") != fingerprint:
                        raise ValueError("Request ID was reused with different ownership inputs")
                    return core.review_ownership_handoff(self.root, previous["review"])
                review = core.prepare_ownership_handoff(self.root, destination_spec=spec_id,
                    **request.model_dump(exclude={"request_id"}))
                value = {"request_id": request.request_id, "fingerprint": fingerprint, "review": review}
                if previous is not None:
                    self._archive(spec_id, previous)
                self._archive(spec_id, value)
                write_json(path, value)
                return core.review_ownership_handoff(self.root, review)
            except (ValueError, OSError, KeyError) as exc:
                raise SddWorkflowError(str(exc), code="sdd_ownership_handoff_invalid", status_code=422) from exc

    def approve(self, spec_id, request, *, owner):
        if request.confirmed is not True:
            raise SddWorkflowError("Explicit confirmation is required", code="sdd_owner_confirmation_required", status_code=422)
        with self._guard():
            try:
                value = read_json(self._path(spec_id), limit=8_388_608)
                review = value["review"]
                if review["destination_spec"] != spec_id or review["document_hash"] != request.snapshot:
                    raise ValueError("Approve the exact current ownership review")
                handoff_core().execute_ownership_handoff(self.root, review, authority_id=owner["id"],
                    expected_snapshot=request.snapshot, confirmed=request.confirmed)
                return handoff_core().review_ownership_handoff(self.root, review)
            except (ValueError, OSError, KeyError) as exc:
                raise SddWorkflowError(str(exc), code="sdd_ownership_handoff_invalid") from exc


def install_routes(app, workspace, *, identity_root):
    workflow = OwnershipHandoffWorkflow(workspace)
    app.state.studio_ownership_handoff = workflow

    @app.get("/api/v1/specs/{spec_id}/ownership-handoff")
    def review_ownership_handoff(spec_id: str):
        return workflow.review(spec_id)

    @app.post("/api/v1/specs/{spec_id}/ownership-handoff")
    def propose_ownership_handoff(spec_id: str, request: OwnershipHandoffRequest):
        return workflow.propose(spec_id, request)

    @app.post("/api/v1/specs/{spec_id}/ownership-handoff/approve")
    def approve_ownership_handoff(spec_id: str, request: DocumentPublicationApprovalRequest):
        return workflow.approve(spec_id, request, owner=approver_for(identity_root))
