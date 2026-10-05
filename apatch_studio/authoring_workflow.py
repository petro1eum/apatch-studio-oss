"""Exact owner-reviewed preparation grants; never functional acceptance."""
import hashlib
from pathlib import Path
import re
import threading
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from apatch_studio.sdd_workflow import SddWorkflowError
from apatch_studio.state_io import read_json, write_json


class AuthoringProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(pattern=r"^apsreq_[a-z0-9_-]{8,96}$")
    actor_id: str = Field(min_length=3, max_length=128)
    files: list[str] = Field(min_length=1, max_length=64)
    previous_grant_hash: str | None = Field(default=None, pattern=r"^sha256:[0-9a-f]{64}$")


class AuthoringApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(pattern=r"^apsreq_[a-z0-9_-]{8,96}$")
    confirmed: Literal[True]
    snapshot: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


class ImplementationCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    request_id: str = Field(pattern=r"^apsreq_[a-z0-9_-]{8,96}$")
    candidate_path: str = Field(min_length=1, max_length=512)
    authoring_grant_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")


def authoring_core():
    try:
        from apatch import sdd_authoring
        if not callable(getattr(sdd_authoring, "prepare_scope", None)) or not callable(getattr(sdd_authoring, "approve_scope", None)):
            raise ImportError("authoring capability absent")
        return sdd_authoring
    except ImportError as exc:
        raise SddWorkflowError("Installed APatch Core cannot authorize preparation yet. Update the Core runtime before approving this scope.", code="sdd_authoring_unavailable", status_code=503) from exc


class AuthoringWorkflow:
    def __init__(self, workspace):
        self.root = Path(workspace).resolve()
        self._lock = threading.RLock()

    def _path(self, spec_id, requirement_id):
        if not re.fullmatch(r"SPEC-[A-Z0-9][A-Z0-9-]{1,95}", spec_id) or not re.fullmatch(r"[A-Z][A-Z0-9_-]{0,63}", requirement_id):
            raise SddWorkflowError("Invalid requirement reference", code="sdd_authoring_invalid", status_code=422)
        return self.root / ".apatch/sdd/authoring-proposals" / spec_id / (requirement_id + ".json")

    def review(self, spec_id, requirement_id):
        authoring_core()
        try:
            result = read_json(self._path(spec_id, requirement_id), limit=1048576)
            if not isinstance(result, dict) or result.get("status") not in {"awaiting_approval", "approved"}:
                raise ValueError("invalid proposal")
            scope = result.get("scope")
            if not isinstance(scope, dict) or scope.get("spec_id") != spec_id or scope.get("requirement_id") != requirement_id or scope.get("document_hash") != result.get("snapshot"):
                raise ValueError("proposal belongs to another requirement or changed")
            return result
        except FileNotFoundError:
            return {"status": "not_prepared", "functional_acceptance": False}
        except (ValueError, OSError) as exc:
            raise SddWorkflowError("Preparation proposal is unavailable or invalid", code="sdd_authoring_invalid") from exc

    def _archive(self, spec_id, requirement_id, proposal):
        """Keep the exact reviewed/approved record before moving the latest pointer."""
        digest = proposal.get("snapshot", "")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
            raise ValueError("invalid proposal snapshot")
        name = digest[7:] + "-" + proposal["status"] + ".json"
        path = self._path(spec_id, requirement_id).parent / requirement_id / "history" / name
        try:
            existing = read_json(path, limit=1048576)
        except FileNotFoundError:
            write_json(path, proposal)
        else:
            if existing != proposal:
                raise ValueError("immutable proposal history differs")

    def _activated_successor_of(self, proposal, *, contract=None, signed_rows=None):
        """Follow only archived, signed judge amendments of the approved wave."""
        from apatch.sdd_integrity import canonical_hash, _verify_seal, load_profile_contract
        from apatch.sdd_authoring import _path
        contract = load_profile_contract(self.root) if contract is None else contract
        if contract is None:
            return False
        expected_grant = proposal.get("grant_hash")
        expected_parent = proposal.get("scope", {}).get("contract_hash")
        visited = set()
        signed = signed_rows
        for _ in range(32):
            digest = contract.get("document_hash")
            if (not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
                    or digest in visited):
                raise ValueError("Invalid or cyclic activated contract lineage")
            visited.add(digest)
            if (contract.get("schema") != "apatch.sdd.verification-contract.v1"
                    or contract.get("status") != "frozen"
                    or contract.get("implementation_allowed") is not True
                    or digest != canonical_hash({key: value for key, value in contract.items() if key != "document_hash"})):
                raise ValueError("Invalid active contract seal")
            archived = read_json(_path(self.root, ".apatch/sdd/frozen/" + digest[7:] + ".json"), limit=1048576)
            if archived != contract:
                raise ValueError("Contract differs from its immutable archive")
            if contract.get("authoring_grant_hash") != expected_grant:
                return False
            parent_hash = contract.get("supersedes_hash")
            if parent_hash == expected_parent:
                return True
            details = contract.get("judge_amendment")
            if (not isinstance(details, dict) or details.get("supersedes_hash") != parent_hash
                    or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(parent_hash))):
                return False
            if signed is None:
                # Reconstruct and verify Ed25519 bytes using this workspace's enrolled key.
                try:
                    from apatch.external_dependency import _signed_rows
                except ImportError as exc:
                    raise ValueError("Verified signed lineage reader is unavailable") from exc
                signed = _signed_rows(self.root)
            candidates = [row["payload"] for row in signed
                if row.get("tool_id") == "apatch_sdd_judge_amendment"
                and row["payload"].get("schema") == "apatch.sdd.judge-amendment-activation.v1"
                and row["payload"].get("stage") == "activated"
                and row["payload"].get("contract_hash") == digest
                and row["payload"].get("previous_contract_hash") == parent_hash]
            if not candidates:
                raise ValueError("Judge amendment has no unambiguous signed activation")
            proof = candidates[0]
            amendment_id = proof.get("amendment_id")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(amendment_id)):
                raise ValueError("Invalid amendment reference")
            folder = ".apatch/sdd/judge-amendments/" + amendment_id[7:]
            review = read_json(_path(self.root, folder + "/review.json"), limit=1048576)
            receipt = read_json(_path(self.root, folder + "/receipt.json"), limit=1048576)
            parent = read_json(_path(self.root, ".apatch/sdd/frozen/" + parent_hash[7:] + ".json"), limit=1048576)
            for label, document in (("review", review), ("receipt", receipt), ("predecessor", parent)):
                _verify_seal(document, "judge amendment " + label)
            if any("requirement_ref" in item for item in candidates):
                # One immutable review may have one signed debt projection per
                # requirement. Admit only the complete, identical common receipt.
                refs = review.get("affected_requirement_refs")
                checks = review.get("invalidated_checks_by_requirement")
                if (not isinstance(refs, list) or not refs or len(set(refs)) != len(refs)
                        or not isinstance(checks, dict) or set(checks) != set(refs)):
                    raise ValueError("Shared judge amendment has no exact projection map")
                projected = {}
                scoped = {"requirement_ref", "affected_requirement_refs",
                          "affected_requirements", "invalidated_acceptance_ids"}
                common = {key: value for key, value in proof.items() if key not in scoped}
                for item in candidates:
                    ref = item.get("requirement_ref")
                    if (ref not in checks or not checks[ref]
                            or item.get("affected_requirement_refs") != [ref]
                            or item.get("affected_requirements") != [ref.split("#", 1)[1]]
                            or item.get("invalidated_acceptance_ids") != checks[ref]
                            or item.get("invalidated_checks_by_requirement") != checks
                            or item.get("review_invalidated_acceptance_ids") != review.get("invalidated_acceptance_ids")
                            or item.get("review_affected_requirement_refs") != refs
                            or item.get("functional_acceptance") is not False
                            or {key: value for key, value in item.items() if key not in scoped} != common
                            or (ref in projected and projected[ref] != item)):
                        raise ValueError("Signed shared judge projection differs from exact owner review")
                    projected[ref] = item
                if set(projected) != set(refs):
                    raise ValueError("Signed shared judge projection set is incomplete")
            elif any(item != proof for item in candidates):
                raise ValueError("Judge amendment has no unambiguous signed activation")
            owner = parent.get("authority", {}).get("actor_id")
            if (review.get("document_hash") != amendment_id
                    or review.get("schema") != "apatch.sdd.judge-amendment-review.v1"
                    or review.get("previous_contract") != parent or review.get("new_contract") != contract
                    or review.get("contract_hash") != parent_hash
                    or review.get("authority_id") != owner or proof.get("authority_id") != owner
                    or contract.get("authority") != parent.get("authority")
                    or receipt.get("review_hash") != amendment_id
                    or receipt.get("result", {}).get("contract") != contract
                    or receipt.get("result", {}).get("contract_hash") != digest
                    or proof.get("judge_path") != details.get("judge_path")
                    or proof.get("old_judge_hash") != details.get("old_judge_hash")
                    or proof.get("new_judge_hash") != details.get("new_judge_hash")):
                raise ValueError("Judge amendment lineage or approval differs from its exact receipt")
            contract = parent
        raise ValueError("Activated contract lineage exceeds the bounded history limit")

    def _owner_refrozen_base_of(self, proposal):
        """Allow a fresh CREATE-only wave after the owner re-froze the canonical base.

        The previous approval remains immutable history. Recovery is allowed only
        when the active contract is a sealed, archived, owner-matching canonical
        base for the same SPEC and has no candidate/grant lineage of its own.
        """
        from apatch.sdd_integrity import canonical_hash, load_profile_contract
        from apatch.sdd_authoring import _path

        contract = load_profile_contract(self.root)
        scope = proposal.get("scope") or {}
        if contract is None or contract.get("document_hash") == scope.get("contract_hash"):
            return False
        digest = contract.get("document_hash")
        if (contract.get("schema") != "apatch.sdd.verification-contract.v1"
                or contract.get("status") != "frozen"
                or contract.get("implementation_allowed") is not True
                or contract.get("candidate_path") is not None
                or contract.get("authoring_grant_hash") is not None
                or not isinstance(digest, str)
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
                or digest != canonical_hash({key: value for key, value in contract.items()
                                             if key != "document_hash"})):
            return False
        archived = read_json(
            _path(self.root, ".apatch/sdd/frozen/" + digest[7:] + ".json"),
            limit=1048576,
        )
        if archived != contract:
            return False
        grant_hash = proposal.get("grant_hash")
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(grant_hash)):
            return False
        grant = read_json(
            _path(self.root, ".apatch/sdd/authoring/" + grant_hash[7:] + ".json"),
            limit=1048576,
        )
        owner = (contract.get("authority") or {}).get("actor_id")
        grant_owner = (grant.get("scope") or {}).get("authority_id")
        if (grant.get("approved_by") != owner
                or grant_owner not in (None, owner)):
            return False
        spec_id = scope.get("spec_id")
        package = read_json(
            _path(self.root, f".apatch/sdd/prepared/{spec_id}.json"),
            limit=1048576,
        )
        request = package.get("contract_request") or {}
        pinned = ("baseline_hash", "brief_hash", "rfp_hash", "spec_hash")
        return (package.get("spec_id") == spec_id
                and all(request.get(key) == contract.get(key) for key in pinned))

    def _completed_create_wave_of(self, proposal):
        """Accept a new CREATE-only wave after exact signed preparation completion."""
        from apatch.sdd_authoring import completed_preparation
        from apatch.sdd_integrity import SddContractError, load_profile_contract

        contract = load_profile_contract(self.root)
        scope = proposal.get("scope") or {}
        grant_hash = proposal.get("grant_hash")
        if (contract is None
                or contract.get("document_hash") != scope.get("contract_hash")
                or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(grant_hash))):
            return False
        try:
            completed = completed_preparation(self.root, grant_hash)
        except (SddContractError, OSError, ValueError):
            return False
        grant = completed.get("grant") or {}
        grant_scope = grant.get("scope") or {}
        owner = (contract.get("authority") or {}).get("actor_id")
        files = completed.get("files") or {}
        if (grant.get("approved_by") != owner
                or grant_scope.get("contract_hash") != contract.get("document_hash")
                or grant_scope.get("spec_id") != scope.get("spec_id")
                or grant_scope.get("requirement_id") != scope.get("requirement_id")
                or grant_scope.get("previous_grant_hash") is not None
                or grant_scope.get("effects") != ["create"]
                or set(files) != set(grant_scope.get("files") or [])):
            return False
        for relative, expected in files.items():
            path = self.root / relative
            if (not path.is_file()
                    or "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != expected):
                return False
        return True

    def propose(self, spec_id, requirement_id, request):
        with self._lock:
            path = self._path(spec_id, requirement_id)
            try:
                existing = self.review(spec_id, requirement_id)
                if existing.get("status") == "approved":
                    starts_next_wave = request.previous_grant_hash is None and (
                        self._completed_create_wave_of(existing)
                        or self._activated_successor_of(existing)
                        or self._owner_refrozen_base_of(existing)
                    )
                    if not starts_next_wave and request.previous_grant_hash != existing.get("grant_hash"):
                        raise ValueError("Name the completed prior grant when proposing a preparation revision")
                elif request.previous_grant_hash and existing.get("scope", {}).get("previous_grant_hash") != request.previous_grant_hash:
                    raise ValueError("The prior grant does not match this requirement's history")
                arguments = dict(spec_id=spec_id, requirement_id=requirement_id, actor_id=request.actor_id, files=request.files)
                if request.previous_grant_hash:
                    import inspect
                    if "previous_grant_hash" not in inspect.signature(authoring_core().prepare_scope).parameters:
                        raise SddWorkflowError("Installed Core cannot authorize preparation revisions yet", code="sdd_authoring_unavailable", status_code=503)
                    arguments["previous_grant_hash"] = request.previous_grant_hash
                scope = authoring_core().prepare_scope(self.root, **arguments)
                result = {"status": "awaiting_approval", "scope": scope, "snapshot": scope["document_hash"], "functional_acceptance": False}
                if existing.get("status") != "not_prepared":
                    self._archive(spec_id, requirement_id, existing)
                self._archive(spec_id, requirement_id, result)
                write_json(path, result)
                return result
            except (ValueError, OSError) as exc:
                raise SddWorkflowError(str(exc), code="sdd_authoring_invalid", status_code=409) from exc

    def approve(self, spec_id, requirement_id, request, *, authority_id):
        with self._lock:
            proposal = self.review(spec_id, requirement_id)
            if proposal.get("snapshot") != request.snapshot:
                raise SddWorkflowError("The preparation scope changed. Review it again before approving.", code="sdd_approval_drift")
            if proposal.get("status") == "approved":
                raise SddWorkflowError("This preparation was already approved", code="sdd_authoring_already_approved")
            try:
                grant = authoring_core().approve_scope(self.root, proposal["scope"], authority_id=authority_id, expected_snapshot=request.snapshot)
                digest = grant.get("document_hash", "")
                if not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) or grant.get("functional_acceptance") is not False:
                    raise SddWorkflowError("Core returned an invalid preparation grant", code="sdd_authoring_unavailable", status_code=503)
                grant_path = self.root / ".apatch/sdd/authoring" / (digest[7:] + ".json")
                if grant_path.exists():
                    raise ValueError("This grant already exists")
                write_json(grant_path, grant)
                result = {**proposal, "status": "approved", "grant_hash": digest}
                self._archive(spec_id, requirement_id, proposal)
                self._archive(spec_id, requirement_id, result)
                write_json(self._path(spec_id, requirement_id), result)
                return result
            except (ValueError, OSError) as exc:
                raise SddWorkflowError(str(exc), code="sdd_authoring_invalid") from exc

