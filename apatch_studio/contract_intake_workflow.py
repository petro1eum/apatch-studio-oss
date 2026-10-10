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

    def _historical_amendment_assets(self, core, old, active):
        """Verify exact signed owner amendments; never grant or accept Source."""
        from apatch.external_dependency import _signed_rows
        from apatch.sdd_integrity import validate_task_envelope
        signed = _signed_rows(self.root, tool_ids={"apatch_sdd_judge_amendment"})
        chain, seen, current = [], set(), active
        for _ in range(32):
            if current == old:
                break
            identity = current.get("document_hash")
            if identity in seen or core.freeze_contract(current) != current:
                raise ValueError("Historical amendment profile is invalid or cyclic")
            seen.add(identity)
            parent_hash = current.get("supersedes_hash")
            if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(parent_hash)):
                raise ValueError("Historical amendment has no exact predecessor")
            parent = core._json(core._capture(self.root, ".apatch/sdd/frozen/" + parent_hash[7:] + ".json"), "amendment predecessor")
            _verify_seal(parent, "amendment predecessor")
            if (parent.get("document_hash") != parent_hash or core.freeze_contract(parent) != parent
                    or parent.get("authority") != old.get("authority")
                    or current.get("authority") != old.get("authority")):
                raise ValueError("Historical amendment owner or predecessor changed")
            details = current.get("judge_amendment")
            if not details:
                if not all(item in current["obligations"] for item in parent["obligations"]):
                    raise ValueError("Unsigned historical obligation replacement")
            else:
                matches = [row["payload"] for row in signed
                           if row["payload"].get("schema") == "apatch.sdd.judge-amendment-activation.v1"
                           and row["payload"].get("stage") == "activated"
                           and row["payload"].get("contract_hash") == identity
                           and row["payload"].get("previous_contract_hash") == parent_hash
                           and row["payload"].get("authority_id") == old["authority"]["actor_id"]
                           and row["payload"].get("functional_acceptance") is False]
                if len(matches) != 1:
                    raise ValueError("Historical amendment lacks exact signed activation")
                proof = matches[0]
                amendment = proof.get("amendment_id")
                if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(amendment)):
                    raise ValueError("Historical amendment identity is invalid")
                folder = ".apatch/sdd/judge-amendments/" + amendment[7:]
                review = core._json(core._capture(self.root, folder + "/review.json"), "amendment review")
                receipt = core._json(core._capture(self.root, folder + "/receipt.json"), "amendment receipt")
                archive = core._json(core._capture(self.root, folder + "/old-judge.json"), "archived judge")
                for value, label in ((review, "review"), (receipt, "receipt")):
                    _verify_seal(value, "historical amendment " + label)
                if (review.get("document_hash") != amendment
                        or review.get("schema") != "apatch.sdd.judge-amendment-review.v1"
                        or review.get("previous_contract") != parent or review.get("new_contract") != current
                        or review.get("authority_id") != old["authority"]["actor_id"]
                        or receipt.get("review_hash") != amendment
                        or receipt.get("result", {}).get("contract_hash") != identity
                        or receipt.get("result", {}).get("functional_acceptance") is not False
                        or any(proof.get(key) != review.get(key) for key in ("judge_path", "old_judge_hash", "new_judge_hash"))):
                    raise ValueError("Historical amendment receipt or Source binding changed")
                import base64
                raw = base64.b64decode(archive["base64"], validate=True)
                if (archive.get("path") != review["judge_path"]
                        or archive.get("sha256") != review["old_judge_hash"]
                        or core._hash(raw) != review["old_judge_hash"]
                        or raw != review["old_judge_text"].encode()
                        or core._hash(review["replacement_text"].encode()) != review["new_judge_hash"]):
                    raise ValueError("Historical amendment archived judge changed")
                chain.append(review)
            current = parent
        else:
            raise ValueError("Historical amendment lineage exceeds its bound")
        if current != old:
            raise ValueError("Historical amendment does not reach the signed intake predecessor")
        assets = {}
        for review in reversed(chain):
            relative, previous, successor = review["judge_path"], review["old_judge_hash"], review["new_judge_hash"]
            assets = {key: successor if key[0] == relative and value == previous else value
                      for key, value in assets.items()}
            assets[(relative, previous)] = successor
            # Amendment changes only the contract binding of canonical envelopes.
            # Compare both complete sealed objects before recognizing native writer bytes.
            import json
            for relative, prior in review["previous_envelopes"].items():
                following = review["envelopes"].get(relative)
                if (not isinstance(following, dict)
                        or following != validate_task_envelope({
                            **{key: value for key, value in prior.items() if key != "document_hash"},
                            "contract_hash": review["new_contract"]["document_hash"]})):
                    raise ValueError("Historical amendment changed task scope")
                def forms(value):
                    return [(json.dumps(value, ensure_ascii=False, indent=2,
                                       allow_nan=False) + "\n").encode(),
                            json.dumps(value, ensure_ascii=False, sort_keys=True,
                                       separators=(",", ":"), allow_nan=False).encode(),
                            (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2,
                                       allow_nan=False) + "\n").encode(),
                            json.dumps(value, ensure_ascii=False, sort_keys=True,
                                       allow_nan=False).encode()]
                actual = core._capture(self.root, relative, optional=True)
                if actual is not None and core._json(actual, "current amended envelope") == following:
                    for raw in forms(prior):
                        assets[(relative, core._hash(raw))] = core._hash(actual)
        return assets

    def _validate_previous(self, core, spec_id, value):
        """A completed prior preparation may be archived after profile growth.

        This is a public verification of history, never approval or a grant.
        Current reviews and approvals continue through the native live checker.
        """
        if (value.get("schema") != STORE_SCHEMA or value.get("workspace") != str(self.root)
                or value.get("spec_id") != spec_id or not isinstance(value.get("review"), dict)
                or value["review"].get("spec_id") != spec_id):
            raise ValueError("Intake selector belongs to another SPEC or workspace")
        review = value["review"]
        _verify_seal(review, "historical native intake review")
        current = core._context(self.root)
        if review.get("active_contract_hash") == current["active_contract_hash"]:
            return self._validate(core, spec_id, value)
        if (review.get("schema") != core.SCHEMA or review.get("workspace") != str(self.root)
                or any(review.get(key) is not expected for key, expected in PREPARATION.items())
                or review.get("authority_id") != current["authority_id"]
                or review.get("actor_id") == current["authority_id"]):
            raise ValueError("Historical preparation has another owner or authority surface")
        core._identifier(review.get("spec_id"), "SPEC")
        core._identifier(review.get("rfp_id"), "RFP")
        core._text(review.get("actor_id"), "historical preparation requester")
        old_hash = review.get("active_contract_hash")
        if not isinstance(old_hash, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", old_hash):
            raise ValueError("Historical profile identity is invalid")
        old_raw = core._capture(self.root, ".apatch/sdd/frozen/" + old_hash[7:] + ".json")
        old = core._json(old_raw, "historical frozen profile")
        active = core._json(core._capture(self.root, core.PROFILE), "current frozen profile")
        _verify_seal(old, "historical frozen profile")
        if (core.freeze_contract(old) != old or old.get("document_hash") != old_hash
                or old.get("authority") != active.get("authority")):
            raise ValueError("Current profile does not preserve the historical owner and obligations")
        amended_assets = ({} if all(item in active["obligations"] for item in old["obligations"])
                          else self._historical_amendment_assets(core, old, active))
        pins = review.get("input_hashes")
        if not isinstance(pins, dict):
            raise ValueError("Historical receipt does not bind its exact archived profile")
        if pins.get(core.PROFILE) != core._hash(old_raw):
            # Native Studio and Core persist the same sealed profile with two
            # exact writers. The signed intake still binds the original bytes.
            import json
            archive_bytes = json.dumps(old, ensure_ascii=False, sort_keys=True,
                                       allow_nan=False).encode("utf-8")
            active_bytes = (json.dumps(old, ensure_ascii=False, sort_keys=True,
                                      indent=2, allow_nan=False) + "\n").encode("utf-8")
            if old_raw != archive_bytes or pins.get(core.PROFILE) != core._hash(active_bytes):
                raise ValueError("Historical receipt does not bind its exact archived profile")
        for relative, expected in pins.items():
            if relative == core.PROFILE:
                continue
            raw = core._capture(self.root, relative, optional=True)
            if raw is None:
                self._historical_envelope(core, relative, expected, old, active)
            elif core._hash(raw) != expected:
                if amended_assets.get((relative, expected)) != core._hash(raw):
                    raise ValueError("An original historical intake input drifted: " + relative)
        history = self._path(spec_id).parent / spec_id / (review["document_hash"][7:] + ".json")
        if self._read(history) != value:
            raise ValueError("Historical selector does not match its immutable review archive")
        if core._capture(self.root, core.PENDING, optional=True) is not None:
            raise ValueError("An intake preparation transaction is incomplete")
        expected = {"ok": True, "review_hash": review["document_hash"],
                    "files": core._outputs(self.root, review), **PREPARATION}
        self._verify_historical_receipts(core, review, expected)
        return {"status": "historical_prepared", "snapshot": review["document_hash"],
                "review": review, "result": expected, "current_context": current, **PREPARATION}

    def _historical_envelope(self, core, relative, expected, old, active):
        """Verify a missing canonical envelope from closed, signed source history.

        No file is restored, signer invoked, or capability granted. Only the
        original intake's exact raw pin may use this public historical reader.
        All other missing inputs and every present-but-drifted input still fail.
        """
        import base64, hashlib, json, math
        from datetime import datetime, timezone
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from apatch.external_dependency import _workspace_verifier, _public_key, _public_file
        from apatch.sdd_integrity import freeze_contract, validate_task_envelope, _path_matches, evaluate_verification
        from apatch_studio.state_io import StateDirectory
        from trustchain.v2.chain_store import verify_record_signature, reconstruct_signed_response
        from trustchain.v2.signer import _canonical_json_from_response

        match = re.fullmatch(r"\.apatch/sdd/envelopes/(SPEC-[A-Z0-9][A-Z0-9-]{1,95})/(R[0-9]+)\.json", relative)
        if not match or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(expected)):
            raise ValueError("Only an exact historical task envelope may be read from SDK history")
        requirement = match[1] + "#" + match[2]
        subject, verifier = _workspace_verifier(self.root)
        identity = core._json(core._capture(self.root, ".apatch/agent-identity.json"), "public signer identity")
        if identity.get("public_key") is not None:
            public_bytes = _public_key(identity["public_key"])
        else:
            from cryptography import x509
            public_bytes = x509.load_pem_x509_certificate(_public_file(identity["cert"])).public_key().public_bytes_raw()
        public = Ed25519PublicKey.from_public_bytes(public_bytes)

        def sdk(name):
            if not re.fullmatch(r"op_[0-9]+", str(name)):
                raise ValueError("Historical source locator is not a canonical SDK object")
            value = core._json(core._capture(self.root, ".trustchain/objects/" + name + ".json"), "historical source SDK receipt")
            record = value.get("value") if isinstance(value.get("value"), dict) else value
            if record.get("key_id") != subject or verify_record_signature(record, verifier) is not True:
                raise ValueError("Historical source receipt fails enrolled public SDK verification")
            response = reconstruct_signed_response(record)
            if response is None:
                raise ValueError("Historical source receipt has no canonical signed response")
            signature = base64.b64decode(response.signature, validate=True)
            for include in (True, False):
                try:
                    public.verify(signature, _canonical_json_from_response(response, include_signature_id=include).encode())
                    break
                except InvalidSignature:
                    continue
            else:
                raise ValueError("Historical source receipt fails independent Ed25519 verification")
            timestamp = record.get("response_timestamp")
            if type(timestamp) not in (int, float) or not math.isfinite(timestamp) or timestamp <= 0:
                raise ValueError("Historical source receipt chronology is invalid")
            return record

        def closed_proof(name):
            record = sdk(name)
            payload = record.get("data")
            proof = payload.get("sdd_evidence") if isinstance(payload, dict) else None
            if record.get("tool") != "apatch_attest" or not isinstance(proof, dict):
                raise ValueError("Historical envelope needs an ordinary source SDD attestation")
            _verify_seal(proof, "historical source SDD proof")
            envelope = proof.get("task_envelope")
            if not isinstance(envelope, dict) or validate_task_envelope(envelope) != envelope:
                raise ValueError("Historical source envelope is invalid")
            # These are the native Studio and Core JSON encodings. The raw
            # intake hash must match one exact encoding, never a semantic hash.
            encodings = (
                json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(),
                json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False).encode(),
            )
            if envelope.get("requirement") != requirement or not any(core._hash(raw) == expected for raw in encodings):
                raise ValueError("Historical source envelope differs from the original raw intake pin")
            digest = envelope.get("contract_hash")
            if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
                raise ValueError("Historical source profile identity is invalid")
            profile = core._json(core._capture(self.root, ".apatch/sdd/frozen/" + digest[7:] + ".json"), "historical source profile")
            _verify_seal(profile, "historical source profile")
            if (freeze_contract(profile) != profile or profile.get("document_hash") != digest
                    or profile.get("authority") != old.get("authority")
                    or profile.get("authority") != active.get("authority")
                    or not all(item in old["obligations"] and item in active["obligations"] for item in profile["obligations"])
                    or envelope.get("baseline_hash") != profile.get("baseline_hash")
                    or proof.get("schema") != "apatch.sdd.attestation-evidence.v1"
                    or proof.get("contract_hash") != digest
                    or proof.get("envelope_hash") != envelope.get("document_hash")):
                raise ValueError("Historical source profile, owner, or preserved obligations differ")
            for obligation in profile["obligations"]:
                for asset in obligation["judge_assets"]:
                    if core._hash(core._capture(self.root, asset["path"])) != asset["sha256"]:
                        raise ValueError("Historical source judge drifted")
            selected = [item for item in profile["obligations"] if item["acceptance_id"] in envelope["checks"]]
            if (not selected or {item["acceptance_id"] for item in selected} != set(envelope["checks"])
                    or not any(item.get("material") is True for item in selected)
                    or proof.get("actor", {}).get("role") != "implementation"
                    or not proof.get("actor", {}).get("actor_id")
                    or proof["actor"]["actor_id"] == profile["authority"]["actor_id"]
                    or proof.get("adherence") != {"status": "compliant", "violations": []}):
                raise ValueError("Historical source capability is not a material implementation scope")
            verification, falsification = proof.get("verification"), proof.get("falsification")
            if not isinstance(verification, dict) or not isinstance(falsification, dict):
                raise ValueError("Historical source material verification is absent")
            _verify_seal(verification, "historical source verification")
            _verify_seal(falsification, "historical source falsification")
            decision = verification.get("decision") or {}
            result = verification.get("result") or {}
            aggregate = {"acceptance_id": "+".join(item["acceptance_id"] for item in selected),
                         "perspectives": sorted({value for item in selected for value in item["perspectives"]}),
                         "material": True}
            commands = result.get("commands")
            if (verification.get("obligation_id") != aggregate["acceptance_id"]
                    or evaluate_verification(aggregate, result) != decision
                    or not isinstance(commands, list) or len(commands) != len(selected)
                    or any(not isinstance(row, dict) or row.get("acceptance_id") != obligation["acceptance_id"]
                           or row.get("command_hash") != obligation["command_hash"]
                           or row.get("ok") is not True or row.get("returncode") != 0
                           for row, obligation in zip(commands, selected))
                    or len(falsification.get("result_hashes", [])) != 2 * sum(item.get("material") is True for item in selected)):
                raise ValueError("Historical source verifier result does not match its native frozen obligations")
            if (decision.get("accepted") is not True or type(decision.get("executed")) is not int
                    or decision["executed"] <= 0 or decision.get("failed") != 0 or decision.get("skipped") != 0
                    or falsification.get("observed_red") is not True or falsification.get("restored_green") is not True
                    or falsification.get("verification_run_id") != verification.get("verification_run_id")):
                raise ValueError("Historical source material verification did not accept RED and restored GREEN")
            artifacts = payload.get("artifacts")
            anchors = [item for item in artifacts if isinstance(item, dict)
                       and item.get("kind") == "spec" and item.get("id") == requirement] if isinstance(artifacts, list) else []
            if len(anchors) != 1:
                raise ValueError("Historical source attestation has no unique exact signed SPEC purpose")
            anchor = anchors[0]
            if "content_hash" in anchor and not re.fullmatch(r"sha256:(?:[0-9a-f]{16}|[0-9a-f]{64})", str(anchor["content_hash"])):
                raise ValueError("Historical source attestation artifact hash is invalid")
            sid = payload.get("governed_session_id")
            if (not isinstance(sid, str) or not re.fullmatch(r"apatch_sess_[a-zA-Z0-9_]+", sid)
                    or payload.get("session_id") != sid):
                raise ValueError("Historical source session identity differs")
            mutation_ids = proof.get("mutation_ids")
            if (not isinstance(mutation_ids, list) or not 1 <= len(mutation_ids) <= 64
                    or len(set(mutation_ids)) != len(mutation_ids)):
                raise ValueError("Historical envelope has no bounded genuine source mutation lineage")
            covered = set()
            for op in mutation_ids:
                mutation = sdk(op)
                data = mutation.get("data") or {}
                if (mutation.get("tool") not in {"apatch", "apatch_expert"} or data.get("action") != "chunk"
                        or data.get("governed_session_id") != sid
                        or data.get("session_id") not in proof.get("checkpoint_refs", [])
                        or mutation["response_timestamp"] > record["response_timestamp"]
                        or not any(item == anchor for item in data.get("artifacts", []) if isinstance(item, dict))):
                    raise ValueError("Historical source mutation has another purpose, session, or requirement")
                files = data.get("files")
                if not isinstance(files, dict) or not files:
                    raise ValueError("Historical source mutation has no exact source hashes")
                for path, item in files.items():
                    if (not any(_path_matches(path, pattern) for pattern in envelope["allowed_writes"])
                            or any(_path_matches(path, pattern) for pattern in envelope["forbidden_paths"])):
                        raise ValueError("Historical source mutation exceeds its task envelope")
                    pin = item.get("sha256") if isinstance(item, dict) else item
                    if not isinstance(pin, str) or not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", pin):
                        raise ValueError("Historical source mutation hash is invalid")
                    if core._hash(core._capture(self.root, path)) != (pin if pin.startswith("sha256:") else "sha256:" + pin):
                        raise ValueError("Historical source mutation differs from the current source")
                    covered.add(path)
            if any(item["falsification"]["target_path"] not in covered for item in selected if item.get("material") is True):
                raise ValueError("Historical source lineage does not cover the actual material target")
            finalizations = core._json(core._capture(self.root, ".apatch/state/finalizations.json"), "native source finalization")
            final = (finalizations.get("records") or {}).get(sid)
            if (not isinstance(final, dict) or final.get("session_id") != sid or final.get("status") != "complete"
                    or not isinstance(final.get("steps"), dict) or "state_ended" not in final["steps"]):
                raise ValueError("Historical source session did not complete native finalization")
            ended = datetime.fromisoformat(final["completed_at"].replace("Z", "+00:00"))
            if (ended.tzinfo is None or not record["response_timestamp"] <= ended.timestamp() <= datetime.now(timezone.utc).timestamp()):
                raise ValueError("Historical source finalization chronology differs")
            return envelope

        # Bounded public history; an older unavailable proof is refused. Names
        # are storage locators, never an unsigned record.id authority alias.
        with StateDirectory(self.root / ".trustchain/objects") as directory:
            names = [name for name in directory.names() if re.fullmatch(r"op_[0-9]+\.json", name)]
        names.sort(key=lambda name: int(name[3:-5]), reverse=True)
        proofs = []
        for name in names[:4096]:
            raw = core._json(core._capture(self.root, ".trustchain/objects/" + name), "SDK history object")
            row = raw.get("value") if isinstance(raw.get("value"), dict) else raw
            data = row.get("data") or {}
            proof = data.get("sdd_evidence") if isinstance(data, dict) else None
            envelope = proof.get("task_envelope") if isinstance(proof, dict) else None
            if row.get("tool") == "apatch_attest" and isinstance(envelope, dict) and envelope.get("requirement") == requirement:
                encodings = (json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode(),
                             json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False).encode())
                if any(core._hash(raw) == expected for raw in encodings):
                    try:
                        proofs.append(closed_proof(name[:-5]))
                    except (TypeError, AttributeError, IndexError) as exc:
                        raise ValueError("Malformed signed historical source proof") from exc
        if not proofs or any(item != proofs[0] for item in proofs):
            raise ValueError("Missing envelope has no unambiguous closed signed source proof")
        return proofs[0]

    def _verify_historical_receipts(self, core, review, result):
        """Verify exact persisted SDK records without resolving a signing provider."""
        from apatch.external_dependency import _workspace_verifier, _public_key
        from trustchain.v2.chain_store import verify_record_signature
        import hashlib, math
        agent, verifier = _workspace_verifier(self.root)
        identity = core._json(core._capture(self.root, ".apatch/agent-identity.json"), "public signer identity")
        if identity.get("public_key") is not None:
            public = _public_key(identity["public_key"])
        else:
            from cryptography import x509
            from apatch.external_dependency import _public_file
            public = x509.load_pem_x509_certificate(_public_file(identity["cert"])).public_key().public_bytes_raw()
        expected = {"schema": core.SCHEMA, "review_hash": review["document_hash"],
            "workspace": str(self.root), "spec_id": review["spec_id"], "rfp_id": review["rfp_id"],
            "authority_id": review["authority_id"], "actor_id": review["actor_id"],
            "active_contract_hash": review["active_contract_hash"], "input_hashes": review["input_hashes"],
            "files": result["files"], **PREPARATION,
            "native_signer": {"agent_id": agent, "public_key_sha256": hashlib.sha256(public).hexdigest()}}
        previous = None
        objects = set()
        for stage in ("approved", "completed"):
            locator = core._json(core._capture(self.root, core._folder(review) + stage + ".json"),
                                 "historical receipt selector")
            _verify_seal(locator, "historical receipt selector")
            relative = locator.get("object_path")
            if not isinstance(relative, str) or not re.fullmatch(r"objects/op_[0-9]+\.json", relative):
                raise ValueError("Historical native receipt locator refused")
            if relative in objects:
                raise ValueError("Historical approval and completion must be distinct records")
            objects.add(relative)
            raw = core._json(core._capture(self.root, ".trustchain/" + relative), "historical SDK receipt")
            record = raw.get("value") if isinstance(raw.get("value"), dict) else raw
            payload = record.get("data")
            if (not isinstance(payload, dict) or record.get("tool") != core.TOOL
                    or record.get("key_id") != agent or record.get("signature") != locator.get("signature")
                    or canonical_hash(payload) != locator.get("payload_hash")
                    or verify_record_signature(record, verifier) is not True
                    or payload.get("stage") != stage
                    or any(payload.get(key) != value for key, value in expected.items())):
                raise ValueError("Historical intake SDK signature or exact receipt binding differs")
            timestamp = record.get("response_timestamp")
            if type(timestamp) not in (int, float) or not math.isfinite(timestamp) or timestamp <= 0 or previous is not None and timestamp < previous:
                raise ValueError("Historical receipt chronology differs")
            previous = timestamp
            if stage == "approved":
                owner = payload.get("owner")
                if not isinstance(owner, dict) or owner.get("id") != review["authority_id"] or owner.get("certified") is not True:
                    raise ValueError("Historical receipt lacks its native certified owner decision")
            elif payload.get("result") != result:
                raise ValueError("Historical intake completion result differs")

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
                previous_projection = None
                if previous is not None:
                    previous_projection = self._validate_previous(core, spec_id, previous)
                reviewed = core.prepare_contract_intake(self.root, spec_id=spec_id, rfp_id=request.rfp_id,
                    actor_id=request.actor_id, reason=request.reason,
                    files=[item.model_dump() for item in request.files])
                if previous_projection is not None and previous_projection.get("status") == "historical_prepared":
                    if any(reviewed.get(key) != expected for key, expected in previous_projection["current_context"].items()):
                        raise ValueError("Current intake authority inputs changed after historical verification")
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
