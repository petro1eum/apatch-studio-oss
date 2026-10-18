"""Thin native Studio review/approve projection of Core document publication."""
from contextlib import contextmanager
from pathlib import Path
import re

from apatch.runtime.atomic_io import exclusive_file_lock
from apatch.sdd_integrity import canonical_hash
from apatch_studio.lock_authority import approver_for
from apatch_studio.sdd_workflow import SddWorkflowError
from apatch_studio.state_io import check_target, read_json, write_json
from pydantic import BaseModel, ConfigDict, Field, StrictBool


class DocumentPublicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(pattern=r"^apsreq_[a-z0-9_-]{8,96}$")
    spec_markdown: str = Field(min_length=1, max_length=1_048_576)
    rfp_markdown: str = Field(min_length=1, max_length=1_048_576)


class DocumentPublicationApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(pattern=r"^apsreq_[a-z0-9_-]{8,96}$")
    confirmed: StrictBool
    snapshot: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def publication_core():
    try:
        from apatch import sdd_publication
        if not all(callable(getattr(sdd_publication, name, None)) for name in (
                "prepare_document_publication", "publish_documents", "review_document_publication")):
            raise ImportError("exact document publication API absent")
        return sdd_publication
    except ImportError as exc:
        raise SddWorkflowError("Installed Core cannot publish already-frozen exact documents. Nothing was approved or written.",
                               code="sdd_document_publication_unavailable", status_code=503) from exc


class DocumentPublicationWorkflow:
    def __init__(self, workspace):
        self.root = Path(workspace).absolute()

    def _path(self, spec_id):
        if not isinstance(spec_id, str) or not re.fullmatch(r"SPEC-[A-Z0-9][A-Z0-9-]{1,95}", spec_id):
            raise SddWorkflowError("Invalid SPEC identity", code="sdd_document_publication_invalid", status_code=422)
        return self.root / ".apatch/sdd/document-publication-reviews" / (spec_id + ".json")

    @contextmanager
    def _guard(self):
        path = self.root / ".apatch/sdd/document-publication-reviews/transaction"
        check_target(path.with_suffix(".lock"))
        with exclusive_file_lock(str(path)):
            yield

    def review(self, spec_id):
        core = publication_core()
        try:
            value = read_json(self._path(spec_id), limit=8_388_608)
        except FileNotFoundError:
            return {"status": "not_prepared", "functional_acceptance": False}
        except (ValueError, OSError) as exc:
            raise SddWorkflowError("Publication review is unavailable", code="sdd_document_publication_invalid") from exc
        try:
            if value["review"]["spec_id"] != spec_id:
                raise ValueError("Publication belongs to another SPEC")
            return core.review_document_publication(self.root, value["review"])
        except (ValueError, OSError, KeyError, IndexError) as exc:
            raise SddWorkflowError(str(exc), code="sdd_document_publication_invalid") from exc

    def propose(self, spec_id, request):
        core = publication_core()
        with self._guard():
            try:
                path = self._path(spec_id)
                fingerprint = canonical_hash({"spec_id": spec_id, "request": request.model_dump()})
                try:
                    previous = read_json(path, limit=8_388_608)
                except FileNotFoundError:
                    previous = None
                if previous is not None and previous.get("request_id") == request.request_id:
                    if previous.get("fingerprint") != fingerprint:
                        raise ValueError("Publication request ID was reused with changed inputs")
                    return core.review_document_publication(self.root, previous["review"])
                review = core.prepare_document_publication(self.root, spec_id=spec_id,
                    spec_markdown=request.spec_markdown, rfp_markdown=request.rfp_markdown)
                if review.get("spec_id") != spec_id or review.get("functional_acceptance") is not False:
                    raise ValueError("Core returned another publication scope")
                if previous is not None:
                    self._archive(spec_id, previous)
                value = {"request_id": request.request_id, "fingerprint": fingerprint, "review": review}
                self._archive(spec_id, value)
                write_json(path, value)
                return core.review_document_publication(self.root, review)
            except (ValueError, OSError, KeyError) as exc:
                raise SddWorkflowError(str(exc), code="sdd_document_publication_invalid", status_code=422) from exc

    def _archive(self, spec_id, value):
        digest = value["review"]["document_hash"]
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("Core review must be sealed")
        path = self._path(spec_id).parent / spec_id / (digest[7:] + ".json")
        try:
            saved = read_json(path, limit=8_388_608)
        except FileNotFoundError:
            write_json(path, value)
        else:
            if saved["review"] != value["review"]:
                raise ValueError("Immutable publication review differs")

    def approve(self, spec_id, request, *, owner):
        core = publication_core()
        if request.confirmed is not True:
            raise SddWorkflowError("Explicit confirmation is required", code="sdd_owner_confirmation_required", status_code=422)
        with self._guard():
            try:
                value = read_json(self._path(spec_id), limit=8_388_608)
                review = value["review"]
                if review["spec_id"] != spec_id or review["document_hash"] != request.snapshot:
                    raise ValueError("Review the exact current publication before confirming")
                receipt = core.publish_documents(self.root, review, authority_id=owner["id"],
                    expected_snapshot=request.snapshot, confirmed=request.confirmed)
                if receipt.get("functional_acceptance") is not False:
                    raise ValueError("Document publication must not grant functional acceptance")
                return core.review_document_publication(self.root, review)
            except (ValueError, OSError, KeyError, IndexError) as exc:
                raise SddWorkflowError(str(exc), code="sdd_document_publication_invalid") from exc


def install_routes(app, workspace, *, identity_root):
    """Called once by create_app; existing session/same-origin middleware applies."""
    workflow = DocumentPublicationWorkflow(workspace)
    app.state.studio_document_publication = workflow
    previous_count = len(app.router.routes)

    @app.get("/api/v1/specs/{spec_id}/document-publication")
    def review_document_publication(spec_id: str):
        return workflow.review(spec_id)

    @app.post("/api/v1/specs/{spec_id}/document-publication")
    def propose_document_publication(spec_id: str, request: DocumentPublicationRequest):
        return workflow.propose(spec_id, request)

    @app.post("/api/v1/specs/{spec_id}/document-publication/approve")
    def approve_document_publication(spec_id: str, request: DocumentPublicationApprovalRequest):
        return workflow.approve(spec_id, request, owner=approver_for(identity_root))

    # Keep API extensions ahead of the SPA fallback even when an adapter is
    # installed on an already-built app (isolated compatibility tests).
    routes = app.router.routes[previous_count:]
    del app.router.routes[previous_count:]
    insertion = next((index for index, route in enumerate(app.router.routes)
                      if re.search(r"\{[^}]+:path\}", getattr(route, "path", ""))), len(app.router.routes))
    app.router.routes[insertion:insertion] = routes
