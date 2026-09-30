"""Exact owner-reviewed corrections; Core owns judge and profile mutations."""
from pathlib import Path
import re
from contextlib import contextmanager
from apatch.runtime.atomic_io import exclusive_file_lock
from apatch.sdd_integrity import canonical_hash
from apatch.sdd_successor import _immutable
from apatch_studio.state_io import check_target
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from apatch_studio.sdd_workflow import SddWorkflowError
from apatch_studio.state_io import read_json, write_json

class JudgeAmendmentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(pattern=r"^apsreq_[a-z0-9_-]{8,96}$")
    acceptance_id: str = Field(min_length=1, max_length=128)
    judge_path: str = Field(min_length=1, max_length=512)
    replacement_text: str = Field(min_length=1, max_length=1048576)
    reason: str = Field(min_length=1, max_length=8192)
    disable_pytest_conftest_autoload: StrictBool = False

def amendment_core():
    try:
        from importlib import import_module
        sdd_judge_amendment = import_module("apatch.sdd_judge_amendment")
        if not all(callable(getattr(sdd_judge_amendment, name, None)) for name in ("prepare_judge_amendment", "activate_judge_amendment")):
            raise ImportError("judge amendment capability absent")
        return sdd_judge_amendment
    except ImportError as exc:
        raise SddWorkflowError("Installed Core cannot process exact judge amendments. This request has not been approved or applied.", code="sdd_judge_amendment_unavailable", status_code=503) from exc

class JudgeAmendmentWorkflow:
    def __init__(self, workspace):
        self.root = Path(workspace).resolve()


    @contextmanager
    def _guard(self):
        path = self.root / ".apatch/sdd/judge-amendment-reviews/transaction"
        check_target(path.with_suffix(".lock"))
        with exclusive_file_lock(str(path)):
            yield

    def _request_path(self, request_id):
        return self.root / ".apatch/sdd/judge-amendment-requests" / (request_id + ".json")

    def _persist_request(self, path, fingerprint, result):
        _immutable(self.root, path.relative_to(self.root).as_posix(),
                   {"fingerprint": fingerprint, "result": result})

    def _path(self, spec_id, requirement_id):
        if not re.fullmatch(r"SPEC-[A-Z0-9][A-Z0-9-]{1,95}", spec_id) or not re.fullmatch(r"R[0-9]+", requirement_id):
            raise SddWorkflowError("Invalid requirement reference", code="sdd_judge_amendment_invalid", status_code=422)
        return self.root / ".apatch/sdd/judge-amendment-reviews" / spec_id / (requirement_id + ".json")

    def review(self, spec_id, requirement_id):
        amendment_core()
        try:
            result = read_json(self._path(spec_id, requirement_id), limit=8388608)
            review = result.get("review", {})
            if (result.get("status") not in {"awaiting_approval", "activated"}
                or review.get("spec_id") != spec_id or review.get("requirement_id") != requirement_id
                or result.get("snapshot") != review.get("document_hash")
                or review.get("functional_acceptance") is not False):
                raise ValueError("Amendment review does not match the selected requirement")
            return result
        except FileNotFoundError:
            return {"status": "not_proposed", "functional_acceptance": False}
        except (ValueError, OSError, AttributeError) as exc:
            raise SddWorkflowError("Judge amendment review is unavailable or invalid", code="sdd_judge_amendment_invalid") from exc

    def _archive(self, spec_id, requirement_id, result):
        snapshot = result.get("snapshot", "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", snapshot):
            raise ValueError("Core did not seal the amendment review")
        path = self._path(spec_id, requirement_id).parent / requirement_id / "history" / (snapshot[7:] + "-" + result["status"] + ".json")
        _immutable(self.root, path.relative_to(self.root).as_posix(), result)

    def propose(self, spec_id, requirement_id, request):
        with self._guard():
            try:
                fingerprint = canonical_hash({"spec_id": spec_id, "requirement_id": requirement_id,
                                               "request": request.model_dump(exclude_defaults=True)})
                request_path = self._request_path(request.request_id)
                try:
                    recorded = read_json(request_path, limit=8388608)
                except FileNotFoundError:
                    recorded = None
                if recorded is not None:
                    if recorded["fingerprint"] != fingerprint:
                        raise SddWorkflowError("Request ID was already used for different amendment inputs",
                                               code="sdd_request_conflict")
                    return recorded["result"]
                previous = self.review(spec_id, requirement_id)
                if previous.get("proposal_request_id") == request.request_id:
                    if previous.get("request_fingerprint") != fingerprint:
                        raise SddWorkflowError("Request ID was already used for different amendment inputs",
                                               code="sdd_request_conflict")
                    self._persist_request(request_path, fingerprint, previous)
                    return previous
                core = amendment_core()
                options = {}
                if request.disable_pytest_conftest_autoload:
                    if getattr(core, "PYTEST_BOOTSTRAP_AMENDMENT", False) is not True:
                        raise SddWorkflowError("Installed Core cannot review this exact pytest bootstrap correction.",
                                               code="sdd_pytest_bootstrap_unavailable", status_code=503)
                    options["disable_pytest_conftest_autoload"] = True
                review = core.prepare_judge_amendment(
                    self.root, spec_id=spec_id, requirement_id=requirement_id, acceptance_id=request.acceptance_id,
                    judge_path=request.judge_path, replacement_text=request.replacement_text, reason=request.reason, **options)
                if (review.get("spec_id") != spec_id or review.get("requirement_id") != requirement_id
                    or review.get("functional_acceptance") is not False):
                    raise ValueError("Core returned an amendment for another scope")
                result = {"status": "awaiting_approval", "review": review, "snapshot": review["document_hash"], "functional_acceptance": False,
                          "proposal_request_id": request.request_id, "request_fingerprint": fingerprint}
                if previous.get("status") != "not_proposed":
                    self._archive(spec_id, requirement_id, previous)
                self._archive(spec_id, requirement_id, result)
                write_json(self._path(spec_id, requirement_id), result)
                self._persist_request(request_path, fingerprint, result)
                return result
            except (ValueError, OSError, KeyError) as exc:
                raise SddWorkflowError("Judge amendment is not ready for review: " + str(exc), code="sdd_judge_amendment_invalid", status_code=422) from exc

    def approve(self, spec_id, requirement_id, request, *, authority_id):
        with self._guard():
            result = self.review(spec_id, requirement_id)
            repeated = (result.get("status") == "activated" and result.get("approved_by") == authority_id
                        and result.get("approval_request_id") == request.request_id)
            if result.get("snapshot") != request.snapshot or (result.get("status") != "awaiting_approval" and not repeated):
                raise SddWorkflowError("Review the current amendment before confirming", code="sdd_approval_drift")
            try:
                activation = amendment_core().activate_judge_amendment(self.root, result["review"], authority_id=authority_id, expected_snapshot=request.snapshot)
                if activation.get("functional_acceptance") is not False or not re.fullmatch(r"sha256:[0-9a-f]{64}", activation.get("contract_hash", "")):
                    raise SddWorkflowError("Core did not return a sealed amendment activation", code="sdd_judge_amendment_unavailable", status_code=503)
                final = {**result, "status": "activated", "activation": activation, "approved_by": authority_id, "approval_request_id": request.request_id}
                history = self._path(spec_id, requirement_id).parent / requirement_id / "history" / (request.snapshot[7:] + "-activated.json")
                try:
                    recorded = read_json(history, limit=8388608)
                except FileNotFoundError:
                    recorded = None
                if recorded is not None:
                    # Core has revalidated the exact activation; recover its original
                    # Studio receipt after a lost latest-pointer write, even when
                    # the browser generated a new transport request identifier.
                    if (set(recorded) != set(final)
                        or any(recorded[key] != value for key, value in final.items() if key != "approval_request_id")
                        or not re.fullmatch(r"apsreq_[a-z0-9_-]{8,96}", recorded.get("approval_request_id", ""))):
                        raise SddWorkflowError("Recorded activation does not match the confirmed amendment",
                                               code="sdd_approval_drift")
                    final = recorded
                self._archive(spec_id, requirement_id, result)
                self._archive(spec_id, requirement_id, final)
                write_json(self._path(spec_id, requirement_id), final)
                return final
            except (ValueError, OSError) as exc:
                raise SddWorkflowError(str(exc), code="sdd_judge_amendment_invalid") from exc
