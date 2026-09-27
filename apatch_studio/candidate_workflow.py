"""Owner review of a selected candidate; successor authority stays in Core."""
from pathlib import Path
import re
import threading

from apatch_studio.authoring_workflow import authoring_core
from apatch_studio.sdd_workflow import SddWorkflowError
from apatch_studio.state_io import read_json, write_json


def successor_core():
    core = authoring_core()
    if not all(callable(getattr(core, name, None)) for name in ("prepare_successor", "activate_successor")):
        raise SddWorkflowError("Installed APatch Core cannot promote reviewed implementation candidates yet", code="sdd_successor_unavailable", status_code=503)
    return core


class CandidateWorkflow:
    def __init__(self, workspace):
        self.root = Path(workspace).resolve()
        self._lock = threading.RLock()

    def _path(self, spec_id, requirement_id):
        if not re.fullmatch(r"SPEC-[A-Z0-9][A-Z0-9-]{1,95}", spec_id) or not re.fullmatch(r"[A-Z][A-Z0-9_-]{0,63}", requirement_id):
            raise SddWorkflowError("Invalid requirement reference", code="sdd_candidate_invalid", status_code=422)
        return self.root / ".apatch/sdd/candidate-reviews" / spec_id / (requirement_id + ".json")

    def review(self, spec_id, requirement_id):
        successor_core()
        try:
            result = read_json(self._path(spec_id, requirement_id), limit=1048576)
            review = result.get("review", {})
            if (result.get("status") not in {"awaiting_approval", "activated"}
                    or review.get("spec_id") != spec_id
                    or review.get("requirement_id") != requirement_id
                    or review.get("document_hash") != result.get("snapshot")):
                raise ValueError("Candidate review does not match the selected requirement")
            return result
        except FileNotFoundError:
            return {"status": "not_selected", "functional_acceptance": False}
        except (ValueError, OSError, AttributeError) as exc:
            raise SddWorkflowError("Candidate review is unavailable or invalid", code="sdd_candidate_invalid") from exc

    def _archive(self, spec_id, requirement_id, result):
        snapshot = result.get("snapshot", "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", snapshot):
            raise ValueError("Core did not seal the candidate review")
        path = self._path(spec_id, requirement_id).parent / requirement_id / "history" / (snapshot[7:] + "-" + result["status"] + ".json")
        try:
            old = read_json(path, limit=1048576)
        except FileNotFoundError:
            write_json(path, result)
        else:
            if old != result:
                raise ValueError("Immutable candidate review history differs")

    def select(self, spec_id, requirement_id, request):
        with self._lock:
            path = self._path(spec_id, requirement_id)
            try:
                previous = self.review(spec_id, requirement_id)
                review = successor_core().prepare_successor(self.root, candidate_path=request.candidate_path, previous_grant_hash=request.authoring_grant_hash)
                if review.get("spec_id") != spec_id or review.get("requirement_id") != requirement_id:
                    raise ValueError("Candidate belongs to another specification or release")
                result = {"status": "awaiting_approval", "review": review, "snapshot": review["document_hash"], "functional_acceptance": False}
                if previous.get("status") != "not_selected":
                    self._archive(spec_id, requirement_id, previous)
                self._archive(spec_id, requirement_id, result)
                write_json(path, result)
                return result
            except (ValueError, OSError, KeyError) as exc:
                raise SddWorkflowError("Candidate is not ready for owner review: " + str(exc), code="sdd_candidate_invalid", status_code=422) from exc

    def approve(self, spec_id, requirement_id, request, *, authority_id):
        with self._lock:
            result = self.review(spec_id, requirement_id)
            repeated = (result.get("status") == "activated"
                        and result.get("approved_by") == authority_id
                        and result.get("approval_request_id") == request.request_id)
            if result.get("snapshot") != request.snapshot or (result.get("status") != "awaiting_approval" and not repeated):
                raise SddWorkflowError("Review the current unapproved candidate before confirming", code="sdd_approval_drift")
            try:
                activation = successor_core().activate_successor(self.root, result["review"], authority_id=authority_id, expected_snapshot=request.snapshot)
                if (activation.get("functional_acceptance") is not False
                        or not re.fullmatch(r"sha256:[0-9a-f]{64}", activation.get("contract_hash", ""))):
                    raise SddWorkflowError("Core did not return a sealed successor activation", code="sdd_successor_unavailable", status_code=503)
                final = {**result, "status": "activated", "activation": activation,
                         "approved_by": authority_id, "approval_request_id": request.request_id}
                self._archive(spec_id, requirement_id, result)
                self._archive(spec_id, requirement_id, final)
                write_json(self._path(spec_id, requirement_id), final)
                return final
            except (ValueError, OSError) as exc:
                raise SddWorkflowError(str(exc), code="sdd_candidate_invalid") from exc
