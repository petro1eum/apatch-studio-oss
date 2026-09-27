"""Studio adapter for Core's existing-run, pre-freeze repair transaction."""
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from apatch_studio.agent_runs import planning_contract_ids
from apatch_studio.sdd_workflow import SddWorkflowError
from apatch_studio.state_io import read_json, write_json


class DraftFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    path: str = Field(min_length=1, max_length=512)
    content: str = Field(max_length=1_048_576)


class DraftProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(pattern=r"^apsreq_[a-z0-9_-]{8,96}$")
    reason: str = Field(min_length=8, max_length=2000)
    files: list[DraftFile] = Field(min_length=1, max_length=64)


class DraftApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(pattern=r"^apsreq_[a-z0-9_-]{8,96}$")
    confirmed: Literal[True]
    snapshot: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def core():
    try:
        from apatch import sdd_draft_amendment
        return sdd_draft_amendment
    except ImportError as exc:
        raise SddWorkflowError("Installed Core cannot repair an existing draft yet", code="sdd_draft_unavailable", status_code=503) from exc


class DraftAmendmentWorkflow:
    def __init__(self, workspace, runs):
        self.root = Path(workspace).resolve()
        self.runs = runs

    def _lineage(self, run_id):
        import re
        if not re.fullmatch(r"apr_[a-f0-9]{12,64}", run_id):
            raise SddWorkflowError("Invalid Studio run", code="sdd_draft_invalid", status_code=422)
        seen = set()
        while True:
            if not isinstance(run_id, str) or not re.fullmatch(r"apr_[a-f0-9]{12,64}", run_id) or run_id in seen or len(seen) >= 64:
                raise SddWorkflowError("Planning lineage is unavailable", code="sdd_draft_invalid")
            seen.add(run_id)
            record = self.runs.get(run_id)
            if record.get("mode") != "new_change" or record.get("status") in {"queued", "running"}:
                raise SddWorkflowError("Stop the original planning run before repairing its draft", code="sdd_draft_run_active")
            parent = record.get("retry_of")
            if parent is None:
                return run_id
            run_id = parent

    def _proposal_path(self, run_id):
        return self.root / ".apatch/sdd/draft-reviews" / (run_id + ".json")

    def review(self, run_id):
        original = self._lineage(run_id)
        try:
            result = read_json(self._proposal_path(original), limit=3_145_728)
            core()._verify_seal(result, "draft review")
            if result.get("run_id") != original:
                raise ValueError("Draft belongs to another run")
            completed = core()._signed(self.root, result, "completed")
            if completed:
                return {"status": "completed", "snapshot": result["document_hash"],
                        "review": result, "result": completed["result"], "functional_acceptance": False}
            return {"status": "awaiting_approval", "snapshot": result["document_hash"],
                    "review": result, "functional_acceptance": False}
        except FileNotFoundError:
            return {"status": "not_prepared", "functional_acceptance": False}
        except (ValueError, OSError) as exc:
            raise SddWorkflowError("Draft review is invalid", code="sdd_draft_invalid") from exc

    def propose(self, run_id, request):
        original = self._lineage(run_id)
        rfp, spec = planning_contract_ids(original)
        try:
            with core().freeze_lock(self.root):
                core().assert_can_freeze(self.root)
                initial = ((self.root / ".apatch/sdd_verification_contract.json").exists()
                           and not (self.root / "docs/specs" / (spec + ".md")).exists())
                review = core().prepare(self.root, run_id=original, spec_id=spec, rfp_id=rfp,
                    files=[item.model_dump() for item in request.files], reason=request.reason,
                    **({"initial": True} if initial else {}))
                write_json(self._proposal_path(original), review)
                return {"status": "awaiting_approval", "snapshot": review["document_hash"],
                        "review": review, "functional_acceptance": False}
        except (ValueError, OSError) as exc:
            raise SddWorkflowError(str(exc), code="sdd_draft_invalid", status_code=409) from exc

    def approve(self, run_id, request, *, owner):
        original = self._lineage(run_id)
        try:
            review = read_json(self._proposal_path(original), limit=3_145_728)
            if review.get("run_id") != original:
                raise ValueError("Draft belongs to another run")
            return core().execute(self.root, review, owner=owner, expected_snapshot=request.snapshot)
        except (ValueError, OSError) as exc:
            raise SddWorkflowError(str(exc), code="sdd_draft_pending_or_invalid", status_code=409) from exc
