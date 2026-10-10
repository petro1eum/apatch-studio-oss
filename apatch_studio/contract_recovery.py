"""Read verified owner-approved successor history without changing active Core state."""
from __future__ import annotations

import re
from pathlib import Path

from apatch_studio.state_io import StateDirectory, read_json
from apatch_studio.sdd_workflow import SddWorkflowError

_LIMIT = 1_048_576
_HASH = re.compile(r"sha256:[0-9a-f]{64}")
_HISTORY = re.compile(r"[0-9a-f]{64}-activated\.json")


def _read(root, relative):
    from apatch.sdd_authoring import _path
    value = read_json(_path(root, relative), limit=_LIMIT)
    if not isinstance(value, dict):
        raise ValueError("Approved history must contain one object")
    return value


def _bytes(root, relative):
    from apatch.sdd_authoring import _path
    path = _path(root, relative)
    with StateDirectory(path.parent) as directory:
        return directory.read_bytes(path.name, limit=_LIMIT)


def _records(root, spec_id):
    folder = root / ".apatch/sdd/candidate-reviews" / spec_id
    try:
        with StateDirectory(folder) as directory:
            requirements = directory.names()
    except FileNotFoundError:
        return []
    records = []
    with StateDirectory(folder) as directory:
        for name in sorted(requirements):
            if re.fullmatch(r"R[0-9]+\.json", name):
                value = directory.read_json(name, limit=_LIMIT)
                if value.get("status") == "activated":
                    records.append(value)
    for requirement in sorted(requirements):
        if not re.fullmatch(r"R[0-9]+", requirement):
            continue
        history = folder / requirement / "history"
        try:
            with StateDirectory(history) as directory:
                names = directory.names()
                for name in sorted(names):
                    if _HISTORY.fullmatch(name):
                        value = directory.read_json(name, limit=_LIMIT)
                        if value.get("snapshot") != "sha256:" + name[:64]:
                            raise ValueError("Approved history filename differs from its snapshot")
                        records.append(value)
                        if len(records) > 128:
                            raise ValueError("Narrow the approved successor history")
        except FileNotFoundError:
            continue
    return records


def _amendments(root):
    """Immutable receipts signal history that must not disappear with a bad signature."""
    folder = root / ".apatch/sdd/judge-amendments"
    try:
        with StateDirectory(folder) as directory:
            names = directory.names()
    except FileNotFoundError:
        return []
    records = []
    for name in sorted(names):
        if not re.fullmatch(r"[0-9a-f]{64}", name):
            continue
        relative = ".apatch/sdd/judge-amendments/" + name
        try:
            receipt = _read(root, relative + "/receipt.json")
        except FileNotFoundError:
            continue  # A review that has not activated is not resume authority.
        records.append((_read(root, relative + "/review.json"), receipt))
        if len(records) > 128:
            raise ValueError("Narrow the activated amendment history")
    return records


def _preparation_files(root, grant_hash, signed, depth=0):
    """Resolve completed preparation revisions without admitting stale authoring."""
    from apatch.sdd_integrity import _verify_seal
    from apatch.runtime.finalization import load_finalization
    if depth > 32 or not _HASH.fullmatch(grant_hash):
        raise ValueError("Invalid preparation revision lineage")
    grant = _read(root, ".apatch/sdd/authoring/" + grant_hash[7:] + ".json")
    scope = grant["scope"]
    _verify_seal(grant, "preparation revision grant")
    _verify_seal(scope, "preparation revision scope")
    if (grant["document_hash"] != grant_hash or grant.get("approved_by") != scope.get("authority_id")
            or scope.get("actor_id") == scope.get("authority_id")):
        raise ValueError("Preparation revision authority changed")
    session = _bytes(root, ".apatch/sdd/authoring/" + scope["document_hash"][7:] + ".claim").decode()
    final = load_finalization(str(root), session)
    if not final or final.get("status") != "complete":
        raise ValueError("Preparation revision is not complete")
    proofs = [row["payload"].get("sdd_evidence") for row in signed
              if row.get("tool_id") == "apatch_attest"]
    proofs = [item for item in proofs if isinstance(item, dict)
              and item.get("schema") == "apatch.sdd.preparation-evidence.v1"
              and item.get("grant_hash") == grant_hash and item.get("session_id") == session
              and item.get("contract_hash") == scope["contract_hash"]
              and item.get("functional_acceptance") is False
              and set(item.get("files", {})) == set(scope["files"])]
    if not proofs or any(item != proofs[0] for item in proofs):
        raise ValueError("Preparation revision lacks exact signed completion")
    previous = scope.get("previous_grant_hash")
    files = _preparation_files(root, previous, signed, depth + 1) if previous else {}
    return {**files, **proofs[0]["files"]}


def approved_successor(root: Path, spec_id: str):
    """Select the unique approved lineage tip, never a caller or global pointer.

    Core's immutable receipts and reconstructed Ed25519 evidence are the authority.
    Archived predecessors may have obsolete assets; only the selected tip must
    match current judge bytes. Nothing is installed or re-approved by this read.
    """
    try:
        records = _records(root, spec_id)
        if not records:
            try:
                with StateDirectory(root / ".apatch/sdd/successor-receipts") as directory:
                    for name in directory.names():
                        if not re.fullmatch(r"[0-9a-f]{64}\.json", name):
                            continue
                        receipt = directory.read_json(name, limit=_LIMIT)
                        envelopes = receipt.get("result", {}).get("envelopes", {})
                        if any(value.get("requirement", "").startswith(spec_id + "#")
                               for value in envelopes.values()):
                            raise ValueError("Activated successor approval history is missing")
            except FileNotFoundError:
                pass
            return None
        from apatch import sdd_integrity as core
        from apatch.external_dependency import _signed_rows
        from apatch_studio.authoring_workflow import AuthoringWorkflow
        import hashlib

        active = core.load_profile_contract(root)
        signed = _signed_rows(root)
        documents = {}
        authoring = AuthoringWorkflow(root)
        for record in records:
            review = record["review"]
            core._verify_seal(review, "approved successor review")
            snapshot = review["document_hash"]
            if (record.get("status") != "activated" or record.get("snapshot") != snapshot
                    or review.get("schema") != "apatch.sdd.successor-review.v1"
                    or review.get("spec_id") != spec_id or review.get("candidate_spec_id") != spec_id
                    or record.get("approved_by") != review.get("authority_id")):
                raise ValueError("Successor approval differs from its exact review")
            receipt = _read(root, ".apatch/sdd/successor-receipts/" + snapshot[7:] + ".json")
            core._verify_seal(receipt, "successor receipt")
            contract = review["successor_contract"]
            core._verify_seal(contract, "approved successor contract")
            digest = contract["document_hash"]
            archived = _read(root, ".apatch/sdd/frozen/" + digest[7:] + ".json")
            if (archived != contract or record.get("activation") != receipt.get("result")
                    or receipt.get("scope_snapshot") != snapshot
                    or receipt.get("contract_hash") != digest
                    or receipt["result"].get("contract") != contract
                    or receipt["result"].get("envelopes") != review["task_envelopes"]
                    or contract.get("authority", {}).get("actor_id") != review["authority_id"]
                    or contract.get("candidate_path") != review["candidate_path"]
                    or contract.get("candidate_hash") != review["candidate_hash"]
                    or contract.get("authoring_grant_hash") != review["previous_grant_hash"]):
                raise ValueError("Successor differs from its immutable activation receipt")
            grant_hash = review["previous_grant_hash"]
            if not _HASH.fullmatch(grant_hash):
                raise ValueError("Successor grant is invalid")
            grant = _read(root, ".apatch/sdd/authoring/" + grant_hash[7:] + ".json")
            core._verify_seal(grant, "approved preparation grant")
            scope = grant["scope"]
            core._verify_seal(scope, "approved preparation scope")
            if (grant["document_hash"] != grant_hash
                    or grant.get("approved_by") != review["authority_id"]
                    or scope.get("authority_id") != review["authority_id"]
                    or scope.get("actor_id") == review["authority_id"]
                    or scope.get("spec_id") != spec_id
                    or scope.get("requirement_id") != review["requirement_id"]
                    or scope.get("contract_hash") != review["contract_hash"]
                    or review["candidate_path"] not in scope.get("files", [])):
                raise ValueError("Successor preparation was not independently approved")
            proofs = [row["payload"].get("sdd_evidence") for row in signed
                      if row.get("tool_id") == "apatch_attest"
                      and (row["payload"].get("sdd_evidence") or {}).get("grant_hash") == grant_hash]
            proofs = [item for item in proofs
                      if item.get("schema") == "apatch.sdd.preparation-evidence.v1"
                      and item.get("functional_acceptance") is False
                      and item.get("contract_hash") == review["contract_hash"]
                      and core.canonical_hash(item) == review["previous_preparation_hash"]]
            if not proofs or any(item != proofs[0] for item in proofs):
                raise ValueError("Successor has no exact signed preparation evidence")
            files = _preparation_files(root, grant_hash, signed)
            if files.get(review["candidate_path"]) != review["candidate_hash"]:
                raise ValueError("Successor candidate has no exact completed preparation")
            # A seal alone is not approval. Reconstruct the original successor
            # from the candidate bytes bound by signed preparation, so coordinated
            # resealing cannot change its checks or effect envelope.
            candidate_bytes = _bytes(root, review["candidate_path"])
            if "sha256:" + hashlib.sha256(candidate_bytes).hexdigest() != review["candidate_hash"]:
                raise ValueError("Signed successor preparation candidate drift")
            candidate = _read(root, review["candidate_path"])
            parent = _read(root, ".apatch/sdd/frozen/" + scope["contract_hash"][7:] + ".json")
            core._verify_seal(parent, "successor predecessor")
            baseline = {item["acceptance_id"]: item for item in parent["obligations"]}
            obligations = []
            pins = set()
            for item in candidate["contract_request"]["obligations"]:
                acceptance = item["acceptance_id"]
                if acceptance in baseline and item != baseline[acceptance]:
                    raise ValueError("Successor changed an original verification obligation")
                entry = item if acceptance in baseline else {**item, "approver": review["authority_id"]}
                obligations.append(entry)
                pins.update(asset["path"] for asset in entry["judge_assets"])
            if not set(baseline).issubset({item["acceptance_id"] for item in obligations}):
                raise ValueError("Successor removed an original verification obligation")
            expected = core.freeze_contract({
                **candidate["contract_request"], "obligations": obligations,
                "authority": {"actor_id": review["authority_id"], "role": "authority"},
                "source_mutation_count": 0, "supersedes_hash": parent["document_hash"],
                "frozen_at": parent["frozen_at"] if review.get("amendment_kind") == "frozen-probe-scope"
                             else review["reviewed_at"],
                "authoring_grant_hash": grant_hash, "candidate_hash": review["candidate_hash"],
                "candidate_path": review["candidate_path"],
            })
            expected_envelopes = {rid: core.validate_task_envelope({
                **value, "contract_hash": expected["document_hash"],
                "forbidden_paths": sorted(set(value.get("forbidden_paths", [])) |
                                          pins | {".apatch/**", ".trustchain/**", ".git/**"}),
            }) for rid, value in candidate["task_envelopes"].items()}
            if contract != expected or review["task_envelopes"] != expected_envelopes:
                raise ValueError("Approved successor differs from signed candidate effects")
            proposal = {"grant_hash": grant_hash, "scope": scope}
            if not authoring._activated_successor_of(
                    proposal, contract=contract, signed_rows=signed):
                raise ValueError("Successor approval lineage is invalid")
            item = {"contract": contract, "envelopes": review["task_envelopes"],
                    "proposal": proposal}
            if digest in documents and documents[digest] != item:
                raise ValueError("Approved successor history conflicts")
            documents[digest] = item

        # Follow activated, signed amendments only. The existing Studio validator
        # checks every shared projection against the immutable Core review.
        amendments = [row["payload"] for row in signed
                      if row.get("tool_id") == "apatch_sdd_judge_amendment"
                      and row["payload"].get("stage") == "activated"]
        receipts = _amendments(root)
        for _ in range(32):
            added = False
            for review, receipt in receipts:
                parent = review.get("contract_hash")
                digest = review.get("new_contract", {}).get("document_hash")
                if parent not in documents or digest in documents:
                    continue
                if (not isinstance(digest, str) or not _HASH.fullmatch(digest)
                        or not any(proof.get("previous_contract_hash") == parent
                                   and proof.get("contract_hash") == digest
                                   and proof.get("amendment_id") == review.get("document_hash")
                                   for proof in amendments)):
                    raise ValueError("Activated amendment has no exact signed proof")
                core._verify_seal(review, "activated amendment review")
                core._verify_seal(receipt, "activated amendment receipt")
                contract = _read(root, ".apatch/sdd/frozen/" + digest[7:] + ".json")
                proposal = documents[parent]["proposal"]
                if not authoring._activated_successor_of(
                        proposal, contract=contract, signed_rows=signed):
                    raise ValueError("Signed amendment does not retain successor authority")
                if (review.get("spec_id") != spec_id
                        or receipt["result"].get("envelopes") != review["envelopes"]):
                    raise ValueError("Amended envelopes differ from the exact owner review")
                envelopes = {}
                for relative, envelope in review["envelopes"].items():
                    requirement = envelope.get("requirement", "")
                    if (not requirement.startswith(spec_id + "#")
                            or relative != ".apatch/sdd/envelopes/" + requirement.replace("#", "/") + ".json"):
                        raise ValueError("Amended envelope belongs to another specification")
                    envelopes[requirement.split("#", 1)[1]] = envelope
                documents[digest] = {"contract": contract, "envelopes": envelopes,
                                     "proposal": proposal}
                added = True
            if not added:
                break
        else:
            raise ValueError("Approved contract history exceeds the bounded lineage limit")
        replaced = {item["contract"].get("supersedes_hash") for item in documents.values()}
        tips = [item for digest, item in documents.items() if digest not in replaced]
        if len(tips) != 1:
            raise ValueError("Approved successor history has ambiguous branches")
        selected = tips[0]
        contract = selected["contract"]
        if core.freeze_contract(contract) != contract:
            raise ValueError("Approved contract is not canonical")
        if ("sha256:" + hashlib.sha256(_bytes(root, contract["candidate_path"])).hexdigest()
                != contract["candidate_hash"]):
            raise ValueError("Approved successor candidate changed")
        package = _read(root, contract["candidate_path"])
        if package.get("spec_id") != spec_id:
            raise ValueError("Approved candidate belongs to another specification")
        for obligation in contract["obligations"]:
            for asset in obligation["judge_assets"]:
                if "sha256:" + hashlib.sha256(_bytes(root, asset["path"])).hexdigest() != asset["sha256"]:
                    raise ValueError("Approved successor judge asset drift")
        spec_path = root / "docs/specs" / (spec_id + ".md")
        if (spec_path.exists() or spec_path.is_symlink()) and (
                "sha256:" + hashlib.sha256(_bytes(root, spec_path.relative_to(root).as_posix())).hexdigest()
                != contract["spec_hash"]):
            raise ValueError("Approved successor specification drift")
        for requirement, envelope in selected["envelopes"].items():
            if (not re.fullmatch(r"R[0-9]+", requirement)
                    or envelope.get("requirement") != spec_id + "#" + requirement
                    or core.validate_task_envelope(envelope) != envelope):
                raise ValueError("Approved successor envelope is invalid")
            core.issue_capability(contract, envelope, actor_id="agent:review", role="implementation")
            path = root / ".apatch/sdd/envelopes" / spec_id / (requirement + ".json")
            try:
                stored = read_json(path, limit=_LIMIT)
            except FileNotFoundError:
                if active == contract:
                    raise ValueError("Active successor envelope is missing")
                continue
            if ((active == contract or stored.get("contract_hash") == contract["document_hash"])
                    and stored != envelope):
                raise ValueError("Approved successor envelope changed")
        return {"contract": contract, "envelopes": selected["envelopes"]}
    except (KeyError, AttributeError, TypeError, ValueError, OSError) as exc:
        raise SddWorkflowError("Approved successor recovery is unavailable: " + str(exc),
                               code="sdd_contract_tampered") from exc
