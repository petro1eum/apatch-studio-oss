"""Native owner review for exact ownership-only amendments; not acceptance."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from apatch.sdd_integrity import canonical_hash
from apatch_studio.document_publication_workflow import DocumentPublicationWorkflow, DocumentPublicationApprovalRequest
from apatch_studio.lock_authority import approver_for
from apatch_studio.sdd_workflow import SddWorkflowError
from apatch_studio.state_io import read_json, write_json


class OwnershipHandoffRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(pattern=r"^apsreq_[a-z0-9_-]{8,96}$")
    source_spec: str = Field(pattern=r"^SPEC-[A-Z0-9][A-Z0-9-]{1,95}$")
    source_kind: Literal["frozen_contract", "unfrozen_spec"] = "frozen_contract"
    source_contract_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    source_document_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")
    paths: list[str] = Field(min_length=1, max_length=32)
    reason: str = Field(min_length=8, max_length=4096)


    @model_validator(mode="after")
    def exact_source_variant(self):
        if self.source_kind == "unfrozen_spec":
            if self.source_contract_hash is not None or self.source_document_hash is None:
                raise ValueError("unfrozen predecessor requires only its exact document hash")
        elif self.source_contract_hash is None or self.source_document_hash is not None:
            raise ValueError("frozen predecessor requires only its exact contract hash")
        return self


def handoff_core(source_kind="frozen_contract"):
    try:
        if source_kind == "unfrozen_spec":
            from apatch import sdd_unfrozen_ownership_handoff
            return sdd_unfrozen_ownership_handoff
        if source_kind != "frozen_contract":
            raise ValueError("unsupported ownership predecessor kind")
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
        try:
            value = read_json(self._path(spec_id), limit=8_388_608)
        except FileNotFoundError:
            return {"status": "not_prepared", "functional_acceptance": False}
        try:
            if value["review"]["destination_spec"] != spec_id:
                raise ValueError("Ownership review belongs to another destination")
            return handoff_core(value["review"].get("source_kind", "frozen_contract")).review_ownership_handoff(self.root, value["review"])
        except (ValueError, OSError, KeyError) as exc:
            raise SddWorkflowError(str(exc), code="sdd_ownership_handoff_invalid") from exc

    def propose(self, spec_id, request):
        with self._guard():
            try:
                path = self._path(spec_id)
                fingerprint = canonical_hash({"spec_id": spec_id, "request": request.model_dump(exclude_defaults=True, exclude_none=True)})
                try:
                    previous = read_json(path, limit=8_388_608)
                except FileNotFoundError:
                    previous = None
                core = handoff_core(request.source_kind)
                if previous is not None and previous.get("request_id") == request.request_id:
                    if previous.get("fingerprint") != fingerprint:
                        raise ValueError("Request ID was reused with different ownership inputs")
                    return core.review_ownership_handoff(self.root, previous["review"])
                excluded = {"request_id"}
                if request.source_kind == "frozen_contract":
                    excluded.update({"source_kind", "source_document_hash"})
                review = core.prepare_ownership_handoff(self.root, destination_spec=spec_id,
                    **request.model_dump(exclude=excluded, exclude_none=True))
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
                core = handoff_core(review.get("source_kind", "frozen_contract"))
                core.execute_ownership_handoff(self.root, review, authority_id=owner["id"],
                    expected_snapshot=request.snapshot, confirmed=request.confirmed)
                return core.review_ownership_handoff(self.root, review)
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
