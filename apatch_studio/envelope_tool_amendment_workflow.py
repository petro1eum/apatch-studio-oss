"""Owner-only singleton tool amendment; not functional acceptance or a source writer.

The trusted boot caller selects workspace, native identity, CA pins and the
separately qualified Studio source admission. HTTP callers can select only an
existing SPEC/Rk and a public expected signer. No self-issued source grant,
ephemeral signer, ambient principal or replacement task envelope is accepted.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field

from apatch.external_dependency import _ledger_paths, _signed_rows, _workspace_verifier
from apatch.ledger_actor import enrich_payload_with_actor
from apatch.path_leases import acquire_path_lease, load_active_leases, release_path_leases, PathLeaseConflict
from apatch.sdd_draft_amendment import assert_can_freeze, freeze_lock
from apatch.sdd_integrity import _seal, _verify_seal, canonical_hash, freeze_contract, validate_task_envelope
from apatch.strict_existing_signer import ExistingSignerBinding, ExistingSignerRefused
from apatch.trustchain_helper import TrustChainHelper
from apatch_studio.endpoint_enrollment import IDENTITY_FILE
from apatch_studio.lock_authority import approver_for
from apatch_studio.security import StudioRequestGuard, security_headers
from trustchain import TrustChainVerifier
from trustchain.v2.chain_store import verify_record_signature

TOOL = "apatch_studio_envelope_tool_amendment"
ADDED_TOOL = "apatch_apply_session"
MODULE = "apatch_studio/envelope_tool_amendment_workflow.py"
PROFILE = ".apatch/sdd_verification_contract.json"
# The existing native workers already refuse this shared fence. A new marker
# name would leave an unsafe window in unmodified execution consumers.
PENDING = ".apatch/sdd/draft-amendment-pending.json"
MAX_BYTES = 4_194_304
SPEC_PATTERN = r"^SPEC-[A-Z0-9][A-Z0-9-]{1,95}$"
REQUIREMENT_PATTERN = r"^R[0-9]{1,5}$"
HASH_PATTERN = r"^sha256:[0-9a-f]{64}$"


class Refused(ValueError):
    """Exact owner snapshot or native transaction safety could not be proved."""

    def __init__(self, message, *, error_type="ENVELOPE_TOOL_AMENDMENT_REFUSED"):
        super().__init__(message)
        self.error_type = error_type


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _json_bytes(value: dict) -> bytes:
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, indent=2) + "\n").encode()


def _identity(value: os.stat_result) -> list[int]:
    return [value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns,
            value.st_ctime_ns, value.st_mode, value.st_uid, value.st_gid, value.st_nlink]


def _canonical_root(value) -> Path:
    root = Path(value).absolute()
    if root != root.resolve() or not root.is_dir():
        raise Refused("canonical trusted boot directory required")
    for parent in [root, *root.parents]:
        item = parent.lstat()
        if not stat.S_ISDIR(item.st_mode) or item.st_uid not in (0, os.getuid()):
            raise Refused("untrusted workspace ancestry")
        if item.st_mode & 0o022 and not (item.st_mode & stat.S_ISVTX and parent != root):
            raise Refused("workspace ancestry writable by another principal")
    return root


@contextmanager
def _directory(root, relative, *, create=False):
    """Hold directory descriptors; never follow replacement parents during I/O."""
    root = _canonical_root(root)
    if not isinstance(relative, str) or not relative:
        raise Refused("exact canonical relative file required")
    parts = Path(relative).parts
    if (Path(relative).is_absolute()
            or str(Path(relative)) != relative or ".." in parts or "\\" in relative
            or any(c in relative for c in "*?[]")):
        raise Refused("exact canonical relative file required")
    ancestry = [(path, (path.lstat().st_dev, path.lstat().st_ino)) for path in [root, *root.parents]]
    descriptors = [os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)]
    edges = []

    def pinned():
        for path, identity in ancestry:
            actual = path.lstat()
            if not stat.S_ISDIR(actual.st_mode) or (actual.st_dev, actual.st_ino) != identity:
                raise Refused("workspace ancestry changed during transaction")
        for parent, name, child in edges:
            named, held = os.stat(name, dir_fd=parent, follow_symlinks=False), os.fstat(child)
            if not stat.S_ISDIR(named.st_mode) or (named.st_dev, named.st_ino) != (held.st_dev, held.st_ino):
                raise Refused("metadata parent replaced during transaction")

    try:
        for part in parts[:-1]:
            parent = descriptors[-1]
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=parent)
                    os.fsync(parent)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            value = os.fstat(child)
            if value.st_uid != os.getuid() or value.st_mode & 0o022:
                os.close(child)
                raise Refused("metadata directory is not privately controlled")
            descriptors.append(child)
            edges.append((parent, part, child))
        pinned()
        yield descriptors[-1], parts[-1], pinned
        pinned()
    finally:
        for descriptor in reversed(descriptors):
            os.close(descriptor)


def capture(root, relative):
    with _directory(root, relative) as (parent, name, pinned):
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            before = os.fstat(descriptor)
            if (not stat.S_ISREG(before.st_mode) or before.st_nlink != 1
                    or before.st_size > MAX_BYTES or before.st_uid != os.getuid()
                    or before.st_mode & 0o022):
                raise Refused("canonical bounded single-link privately controlled file required")
            with os.fdopen(os.dup(descriptor), "rb") as stream:
                raw = stream.read(MAX_BYTES + 1)
            after, named = os.fstat(descriptor), os.stat(name, dir_fd=parent, follow_symlinks=False)
            pinned()
            if len(raw) != before.st_size or _identity(before) != _identity(after) or _identity(after) != _identity(named):
                raise Refused("canonical input changed during capture")
            return raw, {"hash": digest(raw), "identity": _identity(named)}
        finally:
            os.close(descriptor)


def _read(root, relative):
    value = json.loads(capture(root, relative)[0])
    if not isinstance(value, dict):
        raise Refused("native document must be one JSON object")
    return value


def _exists(root, relative):
    try:
        capture(root, relative)
        return True
    except FileNotFoundError:
        return False


def _write(root, relative, raw, *, expected=None, mode=0o600, immutable=False):
    """Native lease + named inode CAS, descriptor-pinned atomic replacement."""
    if len(raw) > MAX_BYTES or mode & 0o022:
        raise Refused("bounded private metadata bytes required")
    with _directory(root, relative, create=True) as (parent, name, pinned):
        temporary = ".tool-amendment-" + secrets.token_hex(16)
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode, dir_fd=parent)
        owned = os.fstat(descriptor)
        try:
            with os.fdopen(os.dup(descriptor), "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.fchmod(descriptor, mode)
            pinned()
            if immutable:
                try:
                    os.link(temporary, name, src_dir_fd=parent, dst_dir_fd=parent, follow_symlinks=False)
                    # Remove only our temporary hard link before validating the
                    # final single-link history file. The open descriptor keeps
                    # the created inode available for the readback comparison.
                    linked = os.stat(temporary, dir_fd=parent, follow_symlinks=False)
                    final = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    if (linked.st_dev, linked.st_ino) != (owned.st_dev, owned.st_ino) or (final.st_dev, final.st_ino) != (owned.st_dev, owned.st_ino):
                        raise Refused("immutable history path was replaced")
                    os.unlink(temporary, dir_fd=parent)
                except FileExistsError:
                    if capture(root, relative)[0] != raw:
                        raise Refused("immutable amendment history conflicts")
            else:
                if expected is not None and capture(root, relative)[1] != expected:
                    raise Refused("metadata compare-and-swap conflict; retain fence")
                pinned()
                os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
            os.fsync(parent)
            pinned()
            result, fingerprint = capture(root, relative)
            if result != raw:
                raise Refused("written metadata was replaced; retain fence")
            return fingerprint
        finally:
            os.close(descriptor)
            try:
                value = os.stat(temporary, dir_fd=parent, follow_symlinks=False)
                if (value.st_dev, value.st_ino) == (owned.st_dev, owned.st_ino):
                    os.unlink(temporary, dir_fd=parent)
                    os.fsync(parent)
            except FileNotFoundError:
                pass


def _save(root, relative, value):
    return _write(root, relative, _json_bytes(value), immutable=True)


def _unlink(root, relative, expected):
    with _directory(root, relative) as (parent, name, pinned):
        if capture(root, relative)[1] != expected:
            raise Refused("pending fence changed; do not clear foreign state")
        pinned()
        os.unlink(name, dir_fd=parent)
        os.fsync(parent)


_LOADED_HASH = digest(Path(__file__).read_bytes())


def _extend_tools(old, added_tools=None):
    """Preserve all task fields and tool order; insert only the internal apply."""
    current = validate_task_envelope(old)
    tools = current["tools"]
    selected = [ADDED_TOOL] if added_tools is None else added_tools
    if (not isinstance(selected, list) or len(selected) != 1
            or not isinstance(selected[0], str)
            or not re.fullmatch(r"apatch_[a-z][a-z0-9_]{1,95}", selected[0])):
        raise Refused("one exact named native tool is required")
    if selected != [ADDED_TOOL]:
        from apatch.mcp_health import mcp_tool_catalog
        if selected[0] not in mcp_tool_catalog()["tools"]:
            raise Refused("requested tool is not available in this native runtime")
    if selected[0] in tools or tools.count("apatch_execute_next") != 1 or len(tools) != len(set(tools)):
        raise Refused("exact single execute_next predecessor and absent selected tool required")
    body = {key: value for key, value in current.items() if key != "document_hash"}
    at = tools.index("apatch_execute_next") + 1
    body["tools"] = [*tools[:at], selected[0], *tools[at:]]
    result = validate_task_envelope(body)
    if {key: value for key, value in result.items() if key not in {"tools", "document_hash"}} != {key: value for key, value in current.items() if key not in {"tools", "document_hash"}}:
        raise Refused("singleton tool repair cannot change any other envelope field")
    return result


@dataclass(frozen=True)
class SourceAdmission:
    spec_id: str
    requirement_id: str
    module_hash: str

    def __post_init__(self):
        if (not re.fullmatch(SPEC_PATTERN, self.spec_id) or not re.fullmatch(REQUIREMENT_PATTERN, self.requirement_id)
                or not re.fullmatch(HASH_PATTERN, self.module_hash)):
            raise Refused("exact trusted boot source admission descriptor required")


@dataclass(frozen=True)
class TrustBundle:
    root_ca_path: str
    root_ca_hash: str
    intermediate_path: str
    intermediate_hash: str
    crl_path: str
    crl_hash: str

    def __post_init__(self):
        for role in ("root_ca", "intermediate", "crl"):
            if not re.fullmatch(HASH_PATTERN, getattr(self, role + "_hash")):
                raise Refused("public CA and revocation pins are mandatory boot inputs")
            path = Path(getattr(self, role + "_path"))
            if not path.is_absolute() or path != path.resolve():
                raise Refused("canonical public trust input required")


@dataclass(frozen=True)
class OwnerCertificateBinding:
    """Reviewed boot mapping between a machine actor and its certified key.

    This is not a caller alias, owner grant, identity rename or certificate
    replacement. The original machine party and existing provider must still
    match; only the independently verified certificate subject is made explicit.
    """
    machine_owner_id: str
    certificate_agent_id: str
    public_key_sha256: str

    def __post_init__(self):
        for value in (self.machine_owner_id, self.certificate_agent_id):
            if (not isinstance(value, str) or not 3 <= len(value) <= 256
                    or value != value.strip() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                raise Refused("exact named boot owner and certificate subjects required")
        if not isinstance(self.public_key_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", self.public_key_sha256):
            raise Refused("exact existing owner public-key pin required")


class ReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    spec_id: str = Field(pattern=SPEC_PATTERN)
    requirement_id: str = Field(pattern=REQUIREMENT_PATTERN)
    requester_actor_id: str = Field(min_length=3, max_length=128)
    reason: str = Field(min_length=16, max_length=4096)
    existing_signer_agent_id: str = Field(min_length=3, max_length=256)
    existing_signer_public_key_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    added_tools: list[str] | None = Field(default=None, min_length=1, max_length=1)


class ApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    review: dict
    expected_snapshot: str = Field(pattern=HASH_PATTERN)
    confirmed: bool


class EnvelopeToolAdministration:
    def __init__(self, workspace, *, identity_root, source_workspace,
                 source_admission: SourceAdmission, trust_bundle: TrustBundle,
                 owner_trust_bundle: TrustBundle | None = None,
                 owner_certificate_binding: OwnerCertificateBinding | None = None):
        if not isinstance(source_admission, SourceAdmission) or not isinstance(trust_bundle, TrustBundle):
            raise Refused("typed server-owned authority boot configuration required")
        self.root = _canonical_root(workspace)
        self.identity_root = _canonical_root(identity_root)
        self.source_root = _canonical_root(source_workspace)
        if self.source_root == self.root:
            raise Refused("administration implementation and target workspaces must be separate")
        self.source_admission, self.trust_bundle = source_admission, trust_bundle
        self.owner_trust_bundle = owner_trust_bundle or trust_bundle
        if not isinstance(self.owner_trust_bundle, TrustBundle):
            raise Refused("typed boot-pinned owner certificate trust bundle required")
        if owner_certificate_binding is not None and not isinstance(owner_certificate_binding, OwnerCertificateBinding):
            raise Refused("typed server-owned machine/certificate binding required")
        self.owner_certificate_binding = owner_certificate_binding
        self._boot_directories = {
            str(path): (path.lstat().st_dev, path.lstat().st_ino, stat.S_IFMT(path.lstat().st_mode))
            for root in (self.root, self.identity_root, self.source_root)
            for path in (root, *root.parents)
        }

    def _boot_pinned(self):
        for relative, expected in self._boot_directories.items():
            current = Path(relative).lstat()
            if (current.st_dev, current.st_ino, stat.S_IFMT(current.st_mode)) != expected:
                raise Refused("trusted boot workspace or identity ancestry was replaced")

    @staticmethod
    def _paths(request):
        return (f".apatch/sdd/prepared/{request.spec_id}.json",
                f".apatch/sdd/envelopes/{request.spec_id}/{request.requirement_id}.json")

    def _binding(self, request):
        binding = ExistingSignerBinding(request.existing_signer_agent_id, request.existing_signer_public_key_sha256)
        binding.resolve(str(self.root))
        return binding

    @staticmethod
    def _qualified_identity(agent_id, certificate_path, public, *, key_path, backend, bundle):
        """Actual PKIX + native key binding for one typed owner/signer identity."""
        from cryptography import x509
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from cryptography.x509.oid import NameOID
        from apatch.trust_identity import verify_anchor
        pins, pem = {}, {}
        for role in ("root_ca", "intermediate", "crl"):
            path = Path(getattr(bundle, role + "_path"))
            raw, pin = capture(path.parent, path.name)
            if digest(raw) != getattr(bundle, role + "_hash"):
                raise Refused("boot-pinned public trust bundle changed")
            pins[role], pem[role] = pin, raw.decode()
        leaf_path = Path(certificate_path)
        if not leaf_path.is_absolute() or leaf_path != leaf_path.resolve():
            raise Refused("canonical native owner certificate required")
        leaf_raw, pins["leaf"] = capture(leaf_path.parent, leaf_path.name)
        # Native PEM backend resolves its own key path. Command providers must
        # never silently use an ambient PEM signer for chain qualification.
        if backend == "command" and os.environ.get("APATCH_AGENT_KEY"):
            raise Refused("ambient PEM signer is not the bound command provider")
        result = verify_anchor(root_ca=pem["root_ca"], intermediate=pem["intermediate"],
                               leaf_cert=leaf_raw.decode(), signer_key=key_path,
                               agent_id=agent_id, crl=pem["crl"])
        if (result.get("ok") is not True or result.get("chain_ok") is not True
                or result.get("validity_ok") is not True or result.get("revoked") is not False
                or backend == "pem" and result.get("key_match") is not True):
            raise Refused("native owner PKIX validity or revocation qualification failed")
        root, intermediate, leaf = [x509.load_pem_x509_certificate(raw.encode())
                                    for raw in (pem["root_ca"], pem["intermediate"], leaf_raw.decode())]
        crl = x509.load_pem_x509_crl(pem["crl"].encode())
        names = leaf.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        if (len(names) != 1 or names[0].value != agent_id
                or not isinstance(leaf.public_key(), Ed25519PublicKey)
                or leaf.public_key().public_bytes_raw() != public
                or root.subject != root.issuer or intermediate.issuer != root.subject
                or leaf.issuer != intermediate.subject or crl.issuer != intermediate.subject):
            raise Refused("native owner certificate purpose or key binding differs")
        for certificate in (root, intermediate):
            if certificate.extensions.get_extension_for_class(x509.BasicConstraints).value.ca is not True:
                raise Refused("actual CA certificates required")
            usage = certificate.extensions.get_extension_for_class(x509.KeyUsage).value
            if not usage.key_cert_sign or not usage.crl_sign:
                raise Refused("CA key usage does not authorize this chain")
        if leaf.extensions.get_extension_for_class(x509.BasicConstraints).value.ca:
            raise Refused("owner certificate must not itself be a CA")
        leaf_usage = leaf.extensions.get_extension_for_class(x509.KeyUsage).value
        if not leaf_usage.digital_signature or leaf_usage.key_cert_sign or leaf_usage.crl_sign:
            raise Refused("native identity certificate cannot authorize CA operations")
        root_public, intermediate_public = root.public_key(), intermediate.public_key()
        if not isinstance(root_public, Ed25519PublicKey) or not isinstance(intermediate_public, Ed25519PublicKey):
            raise Refused("registered native Ed25519 CA algorithm required")
        try:
            root_public.verify(root.signature, root.tbs_certificate_bytes)
            intermediate_public.verify(crl.signature, crl.tbs_certlist_bytes)
        except (InvalidSignature, ValueError):
            raise Refused("native CA self-signature or revocation signature is invalid") from None
        moment = datetime.now(timezone.utc)
        if crl.next_update_utc is None or not crl.last_update_utc <= moment < crl.next_update_utc:
            raise Refused("fresh signed native revocation data required")
        return {"agent_id": agent_id, "public_key_sha256": hashlib.sha256(public).hexdigest(),
                "public_trust_pins": pins}

    def _trusted_owner(self, binding):
        """Owner actor and operational signer are distinct, independently qualified roles."""
        self._boot_pinned()
        from apatch.trust_identity import _PemKeyProvider
        record = _read(self.identity_root, IDENTITY_FILE)
        party = approver_for(self.identity_root)
        if (party.get("certified") is not True or record.get("machine_name") != party.get("id")
                or not record.get("key_path") or not record.get("certificate_path")):
            raise Refused("native OS owner identity is incomplete")
        owner_key = Path(record["key_path"])
        if not owner_key.is_absolute() or owner_key != owner_key.resolve():
            raise Refused("canonical existing owner key route required")
        _canonical_root(owner_key.parent)
        value = owner_key.lstat()
        if not stat.S_ISREG(value.st_mode) or value.st_nlink != 1 or value.st_uid != os.getuid() or value.st_mode & 0o077:
            raise Refused("existing owner key route is not private")
        # This existing native PEM provider is selected by the trusted OS owner
        # record, not a request or ambient operational signer. No new key is
        # created and no signing action is taken during qualification.
        owner_provider = _PemKeyProvider(str(owner_key), key_id=party["id"])
        owner_public = owner_provider.get_public_key()
        if _identity(owner_key.lstat()) != _identity(value):
            raise Refused("native owner key route changed during qualification")
        certificate_agent_id = party["id"]
        selected_binding = self.owner_certificate_binding
        if selected_binding is not None:
            if (selected_binding.machine_owner_id != party["id"]
                    or selected_binding.machine_owner_id != record["machine_name"]
                    or selected_binding.public_key_sha256 != hashlib.sha256(owner_public).hexdigest()):
                raise Refused("reviewed boot owner/certificate binding differs from the native owner")
            certificate_agent_id = selected_binding.certificate_agent_id
        owner_certificate = self._qualified_identity(certificate_agent_id, record["certificate_path"], owner_public,
            key_path=str(owner_key), backend="pem", bundle=self.owner_trust_bundle)
        native = binding.resolve(str(self.root))
        agent, verifier = _workspace_verifier(self.root)
        public = base64.b64decode(verifier._public_key_b64, validate=True)
        if agent != binding.agent_id or hashlib.sha256(public).hexdigest() != binding.public_key_sha256 or not native.cert_path:
            raise Refused("registered operational existing signer public identity differs")
        signer_certificate = self._qualified_identity(binding.agent_id, native.cert_path, public,
            key_path=native.key_path, backend=native.backend, bundle=self.trust_bundle)
        result = {"party": party, "owner_certificate": owner_certificate,
                  "operational_signer_certificate": signer_certificate,
                  "owner_key_inode_pin": _identity(value),
                  "identity_pin": capture(self.identity_root, IDENTITY_FILE)[1]}
        if selected_binding is not None:
            result["owner_certificate_binding"] = {
                "machine_owner_id": selected_binding.machine_owner_id,
                "certificate_agent_id": selected_binding.certificate_agent_id,
                "public_key_sha256": selected_binding.public_key_sha256,
            }
        return result

    def _source_admission(self, binding, owner):
        """No real authority use until this exact source has genuine finalized SDD proof."""
        from apatch.runtime.finalization import load_finalization
        from apatch.spec_ownership import _strict_ownership_declarations, _declared_owners_for_path
        root, descriptor = self.source_root, self.source_admission
        if load_active_leases(str(root)):
            raise Refused("active administration source writer prevents authority use")
        if digest(Path(__file__).read_bytes()) != _LOADED_HASH or descriptor.module_hash != _LOADED_HASH:
            raise Refused("import-time administration source changed")
        source, module_pin = capture(root, MODULE)
        if digest(source) != descriptor.module_hash:
            raise Refused("running administration module is not the admitted source")
        agent, verifier = _workspace_verifier(root)
        if agent != binding.agent_id or hashlib.sha256(base64.b64decode(verifier._public_key_b64, validate=True)).hexdigest() != binding.public_key_sha256:
            raise Refused("administration source and operational owner signing keys differ")
        reference = descriptor.spec_id + "#" + descriptor.requirement_id
        envelope_path = f".apatch/sdd/envelopes/{descriptor.spec_id}/{descriptor.requirement_id}.json"
        active_bytes, active_pin = capture(root, PROFILE)
        active = json.loads(active_bytes)
        if not isinstance(active, dict):
            raise Refused("current administration source profile must be one object")
        _verify_seal(active, "current administration source profile")
        active_frozen = ".apatch/sdd/frozen/" + active["document_hash"][7:] + ".json"
        active_frozen_bytes, active_frozen_pin = capture(root, active_frozen)
        if (active.get("schema") != "apatch.sdd.verification-contract.v1"
                or active.get("status") != "frozen" or active.get("implementation_allowed") is not True
                or json.loads(active_frozen_bytes) != active):
            raise Refused("current administration source profile has no exact frozen archive")
        envelope = validate_task_envelope(_read(root, envelope_path))
        contract = _read(root, ".apatch/sdd/frozen/" + envelope["contract_hash"][7:] + ".json")
        _verify_seal(contract, "frozen administration source contract")
        if (contract.get("status") != "frozen" or contract.get("implementation_allowed") is not True
                or contract.get("authority") != {"actor_id": owner["party"]["id"], "role": "authority"}
                or envelope["contract_hash"] != contract["document_hash"]
                or envelope["requirement"] != reference or envelope["allowed_writes"] != [MODULE]):
            raise Refused("exact separately frozen administration implementation scope required")
        declarations, errors = _strict_ownership_declarations(str(root))
        owners = _declared_owners_for_path(MODULE, declarations)
        if errors or len(owners) != 1 or owners[0].get("requirement") != reference:
            raise Refused("unique strict administration source owner required")
        pins = {MODULE: module_pin, PROFILE: active_pin, active_frozen: active_frozen_pin,
                envelope_path: capture(root, envelope_path)[1],
                ".apatch/agent-identity.json": capture(root, ".apatch/agent-identity.json")[1]}
        source_spec, source_rfp = f"docs/specs/{descriptor.spec_id}.md", f"docs/RFP-{descriptor.spec_id[5:]}.md"
        pins[source_spec], pins[source_rfp] = capture(root, source_spec)[1], capture(root, source_rfp)[1]
        if pins[source_spec]["hash"] != contract.get("spec_hash") or pins[source_rfp]["hash"] != contract.get("rfp_hash"):
            raise Refused("frozen administration source requirements changed")
        frozen_source = ".apatch/sdd/frozen/" + contract["document_hash"][7:] + ".json"
        if _read(root, frozen_source) != contract:
            raise Refused("immutable native administration source provenance differs")
        pins[frozen_source] = capture(root, frozen_source)[1]
        for obligation in contract["obligations"]:
            for asset in obligation["judge_assets"]:
                pins[asset["path"]] = capture(root, asset["path"])[1]
                if pins[asset["path"]]["hash"] != asset["sha256"]:
                    raise Refused("administration source judge drift")
        rows, mutations = _signed_rows(str(root)), {}
        source_head = capture(root, ".trustchain/HEAD")[0].decode().strip()
        if source_head not in {row["signature"] for row in rows}:
            raise Refused("administration source native writer HEAD is not authenticated")
        pins[".trustchain/HEAD"] = capture(root, ".trustchain/HEAD")[1]
        for row in rows:
            payload, files = row["payload"], row["payload"].get("files") or {}
            item = files.get(MODULE) if isinstance(files, dict) else None
            value = item.get("sha256") if isinstance(item, dict) else item
            if (row["tool_id"] in {"apatch", "apatch_expert"} and value in (descriptor.module_hash, descriptor.module_hash[7:])
                    and payload.get("governed_session_id") and any(isinstance(x, dict) and x.get("kind") == "spec" and x.get("id") == reference for x in payload.get("artifacts", []))):
                mutations.setdefault(payload["governed_session_id"], set()).add(row["id"])
        for row in rows:
            payload = row["payload"]
            proof, sid = payload.get("sdd_evidence") or {}, payload.get("governed_session_id")
            if row["tool_id"] != "apatch_attest" or sid not in mutations:
                continue
            _verify_seal(proof, "signed administration SDD evidence")
            decision = (proof.get("verification") or {}).get("decision") or {}
            falsification = proof.get("falsification") or {}
            if (proof.get("contract_hash") == contract["document_hash"] and proof.get("envelope_hash") == envelope["document_hash"]
                    and decision.get("accepted") is True and decision.get("executed", 0) > 0
                    and decision.get("failed") == 0 and decision.get("skipped") == 0
                    and falsification.get("observed_red") is True and falsification.get("restored_green") is True
                    and set(proof.get("mutation_ids", [])) & mutations[sid]
                    and (load_finalization(str(root), sid) or {}).get("status") == "complete"):
                from apatch.runtime.finalization import FINALIZATIONS_REL
                pins[Path(FINALIZATIONS_REL).as_posix()] = capture(root, Path(FINALIZATIONS_REL).as_posix())[1]
                return {"module_hash": descriptor.module_hash, "contract_hash": contract["document_hash"],
                        "envelope_hash": envelope["document_hash"], "session_id": sid,
                        "attestation_signature": row["signature"], "pins": pins}
        raise Refused("genuine finalized native administration implementation proof is absent")

    def _snapshot(self, request):
        binding = self._binding(request)
        owner = self._trusted_owner(binding)
        source_admission = self._source_admission(binding, owner)
        if request.requester_actor_id == owner["party"]["id"] or any(ord(c) < 32 or ord(c) == 127 for c in request.requester_actor_id + request.reason):
            raise Refused("separate plain-text requester and native owner required")
        prepared_path, envelope_path = self._paths(request)
        contract = _read(self.root, PROFILE)
        _verify_seal(contract, "original active frozen contract")
        envelope = validate_task_envelope(_read(self.root, envelope_path))
        prepared = _read(self.root, prepared_path)
        if (contract.get("status") != "frozen" or contract.get("implementation_allowed") is not True
                or contract.get("authority") != {"actor_id": owner["party"]["id"], "role": "authority"}
                or contract.get("candidate_path") or contract.get("judge_amendment")
                or envelope["contract_hash"] != contract["document_hash"]
                or envelope["requirement"] != request.spec_id + "#" + request.requirement_id
                or envelope.get("containment") != "mediated_only"):
            raise Refused("ordinary original-owner frozen mediated-only task required")
        if (set(prepared) != {"schema", "spec_id", "objective", "prepared_at", "source_mutation_count", "contract_request", "task_envelopes"}
                or prepared.get("schema") != "apatch.studio.sdd-preparation.v1"
                or prepared.get("spec_id") != request.spec_id or prepared.get("source_mutation_count") != 0):
            raise Refused("canonical unchanged zero-source-mutation preparation required")
        draft = prepared["task_envelopes"][request.requirement_id]
        if "document_hash" in draft or "contract_hash" in draft or validate_task_envelope({**draft, "contract_hash": contract["document_hash"]}) != envelope:
            raise Refused("native preparation and current task envelope differ")
        native_request = prepared["contract_request"]
        if {"authority", "status", "document_hash", "frozen_at", "implementation_allowed", "source_mutation_count"} & set(native_request):
            raise Refused("preparation cannot carry owner authority")
        reconstructed = freeze_contract({**native_request, "authority": contract["authority"],
            "frozen_at": contract["frozen_at"], "source_mutation_count": 0,
            "obligations": [{**item, "approver": owner["party"]["id"]} for item in native_request["obligations"]]})
        if reconstructed != contract:
            raise Refused("frozen contract no longer matches its original preparation")
        pins = {PROFILE: capture(self.root, PROFILE)[1], prepared_path: capture(self.root, prepared_path)[1],
                envelope_path: capture(self.root, envelope_path)[1], ".apatch/agent-identity.json": capture(self.root, ".apatch/agent-identity.json")[1]}
        frozen_path = ".apatch/sdd/frozen/" + contract["document_hash"][7:] + ".json"
        if _read(self.root, frozen_path) != contract:
            raise Refused("immutable frozen contract provenance missing")
        pins[frozen_path] = capture(self.root, frozen_path)[1]
        for relative in {f"docs/specs/{request.spec_id}.md", f"docs/RFP-{request.spec_id[5:]}.md", *envelope["allowed_writes"]}:
            pins[relative] = capture(self.root, relative)[1]
        if (pins[f"docs/specs/{request.spec_id}.md"]["hash"] != contract.get("spec_hash")
                or pins[f"docs/RFP-{request.spec_id[5:]}.md"]["hash"] != contract.get("rfp_hash")):
            raise Refused("original frozen requirements changed before review")
        from apatch.spec_ownership import _strict_ownership_declarations, _declared_owners_for_path
        declarations, errors = _strict_ownership_declarations(str(self.root))
        if errors:
            raise Refused("target strict ownership declarations are invalid")
        for relative in envelope["allowed_writes"]:
            owners = _declared_owners_for_path(relative, declarations)
            if len(owners) != 1 or owners[0].get("requirement") != envelope["requirement"]:
                raise Refused("selected target must retain its unique exact strict owner")
            aliases = _declared_owners_for_path(".apatch/" + relative, declarations)
            if any(item.get("requirement") == envelope["requirement"] for item in aliases):
                raise Refused("hidden source alias ownership is not a singleton tool repair")
        for obligation in contract["obligations"]:
            for asset in obligation["judge_assets"]:
                pins[asset["path"]] = capture(self.root, asset["path"])[1]
                if pins[asset["path"]]["hash"] != asset["sha256"]:
                    raise Refused("original frozen judge changed")
        rows = _signed_rows(str(self.root))
        head = capture(self.root, ".trustchain/HEAD")[0].decode().strip()
        if not head or head not in {row["signature"] for row in rows}:
            raise Refused("native writer HEAD is not authenticated")
        authenticated = {row["object_path"] for row in rows}
        for relative in _ledger_paths(self.root):
            raw = _read(self.root, relative)
            record = raw.get("value", raw)
            payload, purpose = record.get("data") or {}, str(record.get("tool") or "")
            proof = payload.get("sdd_evidence") or {}
            selected = proof.get("envelope_hash") == envelope["document_hash"] or any(isinstance(x, dict) and x.get("kind") == "spec" and x.get("id") == envelope["requirement"] for x in payload.get("artifacts", []))
            if selected and (payload.get("files") or purpose == "apatch_attest" or payload.get("action") == "attest"):
                if relative.removeprefix(".trustchain/") not in authenticated:
                    raise Refused("unauthenticated selected evidence cannot establish zero applied history")
                raise Refused("selected task already applied or accepted; tool repair is too late")
        return {"owner": owner, "source_admission": source_admission, "contract": contract,
                "envelope": envelope, "prepared": prepared, "pins": pins, "head": head}

    def _idle(self, review=None, lease=None):
        self._boot_pinned()
        assert_can_freeze(self.root, own_review=review["document_hash"] if review else None)
        for path in (".apatch/sdd/contract-intake-pending.json", ".apatch/sdd/successor-pending.json"):
            if _exists(self.root, path):
                raise Refused("another native transaction remains incomplete")
        leases = load_active_leases(str(self.root))
        if lease is None and leases:
            raise Refused("active writer lease prevents owner amendment")
        if lease is not None and (len(leases) != 1 or any(leases[0].get(k) != lease.get(k) for k in ("lease_id", "governed_session_id", "pid", "canonical_paths")) or leases[0].get("pid") != os.getpid()):
            raise Refused("exclusive native owner lease changed or expired")

    def review(self, request: ReviewRequest):
        self._idle()
        baseline = self._snapshot(request)
        new_envelope = _extend_tools(baseline["envelope"], request.added_tools)
        new_prepared = json.loads(json.dumps(baseline["prepared"]))
        new_prepared["task_envelopes"][request.requirement_id]["tools"] = new_envelope["tools"]
        prepared_path, envelope_path = self._paths(request)
        return _seal({"schema": "apatch.studio.envelope-tool-review.v1", "workspace": str(self.root),
                      "request": request.model_dump(exclude_none=True), "authority_id": baseline["owner"]["party"]["id"],
                      "baseline": baseline, "new_envelope": new_envelope, "new_prepared": new_prepared,
                      "metadata_paths": [prepared_path, envelope_path], "added_tools": request.added_tools or [ADDED_TOOL],
                      "scope_expansion": True, "functional_acceptance": False, "profile_changed": False})

    @staticmethod
    def _folder(review):
        return ".apatch/sdd/envelope-tool-amendments/" + review["document_hash"][7:]

    def _validate(self, request):
        review = request.review
        _verify_seal(review, "confirmed native singleton tool review")
        if request.confirmed is not True or request.expected_snapshot != review["document_hash"] or review.get("workspace") != str(self.root) or review.get("schema") != "apatch.studio.envelope-tool-review.v1":
            raise Refused("exact freshly confirmed original-owner review required")
        prepared = ReviewRequest.model_validate(review["request"])
        binding = self._binding(prepared)
        owner = self._trusted_owner(binding)
        if owner != review["baseline"]["owner"] or review["authority_id"] != owner["party"]["id"]:
            raise Refused("original native owner identity changed")
        return review, prepared, binding

    def _body(self, review, stage, binding):
        return enrich_payload_with_actor({"schema": "apatch.studio.envelope-tool-decision.v1", "stage": stage,
            "review_hash": review["document_hash"], "authority_id": review["authority_id"],
            "requester_actor_id": review["request"]["requester_actor_id"], "added_tools": review["added_tools"],
            "scope_expansion": True, "functional_acceptance": False, "profile_changed": False,
            "contract_hash": review["baseline"]["contract"]["document_hash"],
            "old_envelope_hash": review["baseline"]["envelope"]["document_hash"],
            "new_envelope_hash": review["new_envelope"]["document_hash"],
            "old_prepared_hash": review["baseline"]["pins"][review["metadata_paths"][0]]["hash"],
            "new_prepared_hash": digest(_json_bytes(review["new_prepared"])),
            "native_signer": {"agent_id": binding.agent_id, "public_key_sha256": binding.public_key_sha256}}, agent_id=binding.agent_id)

    def _receipt(self, review, stage, binding, *, required=False):
        relative = self._folder(review) + "/" + stage + ".json"
        if not _exists(self.root, relative):
            if required:
                raise Refused("required real native signed receipt missing")
            return None
        locator = _read(self.root, relative)
        _verify_seal(locator, "immutable native SDK receipt selector")
        path = locator.get("object_path")
        if not isinstance(path, str) or not re.fullmatch(r"objects/op_[0-9]+\.json", path):
            raise Refused("canonical native SDK object required")
        raw = _read(self.root, ".trustchain/" + path)
        record = raw.get("value", raw)
        public = binding.resolve(str(self.root)).key_provider.get_public_key()
        if verify_record_signature(record, TrustChainVerifier(base64.b64encode(public).decode(), binding.agent_id, max_age_seconds=None)) is not True:
            raise Refused("actual native receipt signature is invalid")
        if (record.get("tool") != TOOL or record.get("key_id") != binding.agent_id
                or record.get("data") != self._body(review, stage, binding)
                or canonical_hash(record["data"]) != locator.get("payload_hash")
                or record.get("signature") != locator.get("signature")
                or record.get("parent_signature") != locator.get("parent_signature")):
            raise Refused("signed native receipt is outside the exact owner review")
        return record

    def _pending(self, review, *, stage=None, written=None):
        raw, fingerprint = capture(self.root, PENDING)
        current = json.loads(raw)
        _verify_seal(current, "native singleton tool fence")
        if current.get("schema") != "apatch.studio.envelope-tool-pending.v1" or current.get("review_hash") != review["document_hash"]:
            raise Refused("foreign native pending transaction")
        if stage is not None or written is not None:
            value = {key: item for key, item in current.items() if key != "document_hash"}
            if stage is not None:
                value["stage"] = stage
            if written is not None:
                value["written"] = written
            _write(self.root, PENDING, _json_bytes(_seal(value)), expected=fingerprint)
            return self._pending(review)
        return current

    def _pins(self, review, lease, *, expected_head=None, state="before"):
        self._idle(review, lease)
        request = ReviewRequest.model_validate(review["request"])
        observed = self._snapshot(request)
        baseline = review["baseline"]
        for key in ("owner", "source_admission", "contract"):
            if observed[key] != baseline[key]:
                raise Refused("owner, source admission or contract changed; retain fence")
        pending = self._pending(review) if _exists(self.root, PENDING) else None
        expected = {"envelope": baseline["envelope"], "prepared": baseline["prepared"]}
        if state == "after":
            expected = {"envelope": review["new_envelope"], "prepared": review["new_prepared"]}
        if any(observed[key] != value for key, value in expected.items()):
            raise Refused("paired task metadata state differs from owner transaction")
        for relative, original in baseline["pins"].items():
            if relative in review["metadata_paths"]:
                wanted = ((pending or {}).get("written") or {}).get(relative, original)
                if state == "before":
                    restored = ((pending or {}).get("restored") or {}).get(relative, original)
                    if observed["pins"][relative] != restored:
                        raise Refused("original or own-restored metadata inode changed")
                elif observed["pins"][relative] != wanted:
                    raise Refused("own-written metadata inode was replaced")
            elif observed["pins"].get(relative) != original:
                raise Refused("unchanged source, identity or judge inode drifted")
        if expected_head is not None and observed["head"] != expected_head:
            raise Refused("native writer HEAD changed; retain fence")

    def _commit(self, review, stage, binding, lease, previous_head, state):
        prior = self._receipt(review, stage, binding)
        if prior is not None:
            return prior
        pending = self._pending(review)
        if str(pending.get("stage", "")).startswith("signing_"):
            raise ExistingSignerRefused("EXISTING_SIGNER_RECONCILIATION_REQUIRED", reconciliation_required=True)
        self._pins(review, lease, expected_head=previous_head, state=state)
        self._pending(review, stage="signing_" + stage)
        helper = TrustChainHelper(str(self.root), auto_init=False, existing_signer=binding)
        if not helper.commit_action(TOOL, self._body(review, stage, binding)):
            raise ExistingSignerRefused("EXISTING_SIGNER_RECEIPT_INVALID", reconciliation_required=True)
        evidence = helper.last_commit_evidence
        raw = _read(self.root, ".trustchain/" + evidence["object_path"])
        record = raw.get("value", raw)
        if (record.get("parent_signature") != previous_head or evidence.get("merkle_root")
                or capture(self.root, ".trustchain/HEAD")[0].decode().strip() != record.get("signature")):
            raise ExistingSignerRefused("EXISTING_SIGNER_HEAD_MISMATCH", reconciliation_required=True)
        _save(self.root, self._folder(review) + "/" + stage + ".json", _seal({
            "object_path": evidence["object_path"], "payload_hash": canonical_hash(record["data"]),
            "signature": record["signature"], "parent_signature": record["parent_signature"]}))
        result = self._receipt(review, stage, binding, required=True)
        self._pins(review, lease, expected_head=result["signature"], state=state)
        self._pending(review, stage=stage)
        return result

    def _lease(self, review):
        paths = sorted(set(review["baseline"]["pins"]) | {PENDING, self._folder(review), ".trustchain/HEAD"})
        return acquire_path_lease(str(self.root), paths, tool=TOOL,
                                  governed_session_id="envelope-tool-amendment:" + review["document_hash"], max_seconds=300)

    def _restore(self, review, lease, approved_head):
        """Restore our own paired postimages only; never overwrite foreign metadata."""
        self._idle(review, lease)
        pending = self._pending(review)
        if capture(self.root, ".trustchain/HEAD")[0].decode().strip() != approved_head:
            raise Refused("signing outcome or foreign writer is unresolved; retain fence")
        before = _read(self.root, self._folder(review) + "/before.json")
        _verify_seal(before, "immutable paired metadata preimage")
        conflicts = []
        restored = dict(pending.get("restored") or {})
        for relative in review["metadata_paths"]:
            raw, fingerprint = capture(self.root, relative)
            original = before["files"][relative]
            saved = base64.b64decode(original["bytes"], validate=True)
            if digest(saved) != review["baseline"]["pins"][relative]["hash"]:
                raise Refused("immutable paired preimage corrupted")
            if raw == saved:
                if fingerprint != restored.get(relative, review["baseline"]["pins"][relative]):
                    conflicts.append(relative)
                continue
            if fingerprint != pending.get("written", {}).get(relative):
                conflicts.append(relative)
                continue
            restored[relative] = _write(self.root, relative, saved, expected=fingerprint, mode=original["mode"])
            current_raw, current_pin = capture(self.root, PENDING)
            current = json.loads(current_raw)
            _verify_seal(current, "own pending rollback journal")
            if current.get("review_hash") != review["document_hash"]:
                raise Refused("foreign rollback journal; retain fence")
            body = {key: value for key, value in current.items() if key != "document_hash"}
            body["restored"] = restored
            _write(self.root, PENDING, _json_bytes(_seal(body)), expected=current_pin)
        if conflicts:
            raise Refused("foreign metadata preserved; retain fence for owner reconciliation")
        self._pins(review, lease, expected_head=approved_head, state="before")

    def approve(self, request: ApprovalRequest):
        review, prepared, binding = self._validate(request)
        folder = self._folder(review)
        if _exists(self.root, folder + "/completed.json"):
            with freeze_lock(self.root):
                self._idle()
                approved = self._receipt(review, "approved", binding, required=True)
                completed = self._receipt(review, "completed", binding, required=True)
                if approved["parent_signature"] != review["baseline"]["head"] or completed["parent_signature"] != approved["signature"]:
                    raise Refused("native receipt lineage mismatch")
                observed = self._snapshot(prepared)  # Authentic current inputs, not merely sealed history.
                for key in ("owner", "source_admission", "contract"):
                    if observed[key] != review["baseline"][key]:
                        raise Refused("completed original-owner provenance changed")
                for relative, original in review["baseline"]["pins"].items():
                    if relative not in review["metadata_paths"] and observed["pins"].get(relative) != original:
                        raise Refused("completed unchanged input drifted")
                if _read(self.root, review["metadata_paths"][0]) != review["new_prepared"] or validate_task_envelope(_read(self.root, review["metadata_paths"][1])) != review["new_envelope"]:
                    raise Refused("completed metadata changed after owner decision")
                return self._result(review, replayed=True)
        with freeze_lock(self.root):
            # Compare the exact reviewed pair while serialized with the winner.
            # Re-reviewing an already widened envelope would misclassify a CAS
            # loser as a malformed fresh amendment request.
            prepared_path, envelope_path = self._paths(prepared)
            if (_read(self.root, prepared_path) != review["baseline"]["prepared"]
                    or validate_task_envelope(_read(self.root, envelope_path)) != review["baseline"]["envelope"]):
                raise Refused("owner amendment snapshot conflict; refresh the reviewed task metadata",
                              error_type="ENVELOPE_TOOL_AMENDMENT_CONFLICT")
            if self.review(prepared) != review:
                raise Refused("fresh native owner snapshot drifted under lock")
            lease = self._lease(review)
            try:
                _save(self.root, folder + "/review.json", review)
                before = {relative: {"bytes": base64.b64encode(capture(self.root, relative)[0]).decode(),
                                     "mode": stat.S_IMODE(capture(self.root, relative)[1]["identity"][5])}
                          for relative in review["metadata_paths"]}
                _save(self.root, folder + "/before.json", _seal({"files": before}))
                _save(self.root, PENDING, _seal({"schema": "apatch.studio.envelope-tool-pending.v1",
                      "review_hash": review["document_hash"], "stage": "prepared", "written": {}}))
                approved = self._commit(review, "approved", binding, lease, review["baseline"]["head"], "before")
                try:
                    _save(self.root, folder + "/old-envelope.json", review["baseline"]["envelope"])
                    written = {}
                    for relative, value in zip(review["metadata_paths"], (review["new_prepared"], review["new_envelope"])):
                        written[relative] = _write(self.root, relative, _json_bytes(value),
                            expected=review["baseline"]["pins"][relative], mode=before[relative]["mode"])
                        self._pending(review, written=written)
                    self._pins(review, lease, expected_head=approved["signature"], state="after")
                except Exception:
                    self._restore(review, lease, approved["signature"])
                    terminal = self._commit(review, "rolled_back", binding, lease, approved["signature"], "before")
                    self._clear(review, lease, terminal["signature"], "before")
                    raise
                try:
                    completed = self._commit(review, "completed", binding, lease, approved["signature"], "after")
                except Exception:
                    # Unknown signing is never retried or presented as success.
                    # If HEAD is still approved, restore only our own images;
                    # otherwise the fence remains and no foreign state is touched.
                    self._restore(review, lease, approved["signature"])
                    raise
                self._clear(review, lease, completed["signature"], "after")
                return self._result(review, replayed=False)
            finally:
                release_path_leases(str(self.root), governed_session_id=lease["governed_session_id"])

    def _clear(self, review, lease, head, state):
        self._pins(review, lease, expected_head=head, state=state)
        pending, pin = capture(self.root, PENDING)
        if json.loads(pending).get("review_hash") != review["document_hash"]:
            raise Refused("foreign fence cannot be cleared")
        _unlink(self.root, PENDING, pin)

    @staticmethod
    def _result(review, *, replayed):
        return {"ok": True, "replayed": replayed, "review_hash": review["document_hash"],
                "contract_hash": review["baseline"]["contract"]["document_hash"],
                "old_envelope_hash": review["baseline"]["envelope"]["document_hash"],
                "envelope_hash": review["new_envelope"]["document_hash"],
                "added_tools": review["added_tools"], "functional_acceptance": False, "profile_changed": False}

    def _recover_signed_receipt(self, review, stage, binding, lease):
        if stage not in {"approved", "completed", "rolled_back"}:
            raise Refused("unknown native signing stage; retain fence")
        expected = self._body(review, stage, binding)
        rows = [row for row in _signed_rows(str(self.root), tool_ids={TOOL})
                if row["key_id"] == binding.agent_id and row["payload"] == expected]
        if len(rows) != 1:
            raise ExistingSignerRefused("EXISTING_SIGNER_RECONCILIATION_REQUIRED", reconciliation_required=True)
        row = rows[0]
        relative = row["object_path"]
        if not re.fullmatch(r"objects/op_[0-9]+\.json", relative):
            raise Refused("canonical signed recovery object required")
        raw = _read(self.root, ".trustchain/" + relative)
        record = raw.get("value", raw)
        public = binding.resolve(str(self.root)).key_provider.get_public_key()
        if verify_record_signature(record, TrustChainVerifier(base64.b64encode(public).decode(), binding.agent_id, max_age_seconds=None)) is not True:
            raise Refused("recovery receipt signature is invalid")
        previous = (review["baseline"]["head"] if stage == "approved"
                    else self._receipt(review, "approved", binding, required=True)["signature"])
        if (record.get("tool") != TOOL or record.get("key_id") != binding.agent_id
                or record.get("data") != expected or record.get("signature") != row["signature"]
                or record.get("parent_signature") != previous
                or capture(self.root, ".trustchain/HEAD")[0].decode().strip() != row["signature"]):
            raise Refused("signed recovery lineage or current head differs; retain fence")
        self._pins(review, lease, expected_head=row["signature"],
                   state="after" if stage == "completed" else "before")
        _save(self.root, self._folder(review) + "/" + stage + ".json", _seal({
            "object_path": relative, "payload_hash": canonical_hash(expected),
            "signature": row["signature"], "parent_signature": previous}))
        self._receipt(review, stage, binding, required=True)
        return self._pending(review, stage=stage)

    def reconcile(self, request: ApprovalRequest):
        review, _, binding = self._validate(request)
        if not _exists(self.root, PENDING) and _exists(self.root, self._folder(review) + "/completed.json"):
            result = self.approve(request)
            return {**result, "stage": "completed"}
        with freeze_lock(self.root):
            pending = self._pending(review)
            if _read(self.root, self._folder(review) + "/review.json") != review:
                raise Refused("immutable original owner review differs")
            self._idle(review)
            if str(pending.get("stage", "")).startswith("signing_"):
                lease = self._lease(review)
                try:
                    pending = self._recover_signed_receipt(review, pending["stage"][8:], binding, lease)
                finally:
                    release_path_leases(str(self.root), governed_session_id=lease["governed_session_id"])
            approved = self._receipt(review, "approved", binding, required=True)
            if approved["parent_signature"] != review["baseline"]["head"]:
                raise Refused("approved native lineage differs")
            lease = self._lease(review)
            try:
                stage = pending["stage"]
                if stage == "approved":
                    self._restore(review, lease, approved["signature"])
                    terminal = self._commit(review, "rolled_back", binding, lease, approved["signature"], "before")
                    stage = "rolled_back"
                elif stage in {"completed", "rolled_back"}:
                    terminal = self._receipt(review, stage, binding, required=True)
                else:
                    raise Refused("pending owner signing requires native SDK reconciliation, never a blind retry")
                if terminal["parent_signature"] != approved["signature"]:
                    raise Refused("terminal native lineage differs")
                self._clear(review, lease, terminal["signature"], "after" if stage == "completed" else "before")
                return {"ok": True, "stage": stage, "functional_acceptance": False, "profile_changed": False}
            finally:
                release_path_leases(str(self.root), governed_session_id=lease["governed_session_id"])


def create_envelope_tool_amendment_app(workspace, **boot):
    """Two-step native Owner UI, separate from implementation tools and sessions.

    Factory alone is not source admission. Every review/approve requalifies its
    genuine frozen source proof; unadmitted candidate stays fail-closed.
    """
    admin = EnvelopeToolAdministration(workspace, **boot)
    guard, app = StudioRequestGuard(), FastAPI()

    @app.middleware("http")
    async def secure(request: Request, call_next):
        denied = guard.authenticate(request)
        response = denied if denied is not None else await call_next(request)
        security_headers(response)
        return response

    @app.exception_handler(ExistingSignerRefused)
    async def signer_refused(request, exception):
        return JSONResponse(exception.to_dict(), status_code=409)

    @app.exception_handler(PathLeaseConflict)
    async def lease_refused(request, exception):
        return JSONResponse({"ok": False, "error_type": "ENVELOPE_TOOL_LEASE_CONFLICT", "error": str(exception)}, status_code=409)

    @app.exception_handler(ValueError)
    async def refused(request, exception):
        return JSONResponse({"ok": False, "error_type": getattr(exception, "error_type", "ENVELOPE_TOOL_AMENDMENT_REFUSED"), "error": str(exception)}, status_code=409)

    @app.exception_handler(OSError)
    async def io_refused(request, exception):
        return JSONResponse({"ok": False, "error_type": "ENVELOPE_TOOL_IO_REFUSED",
                             "error": "native input or canonical filesystem path unavailable; retained fence"}, status_code=409)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return ('<!doctype html><html lang="en"><meta name="apatch-studio-session" content="' + guard.token + '">'
            '<title>Owner: exact tool amendment</title><h1>Review one exact native tool</h1>'
            '<p>Scope widening; not functional acceptance. Contract, judges and implementation source remain unchanged.</p>'
            '<form id="form"><label>SPEC <input name="spec_id" required></label><label>Rk <input name="requirement_id" required></label>'
            '<label>Requester <input name="requester_actor_id" required></label><label>Reason <input name="reason" required></label>'
            '<label>Native tool <input name="added_tool" value="apatch_apply_session" required pattern="apatch_[a-z][a-z0-9_]+"></label>'
            '<label>Existing signer ID <input name="existing_signer_agent_id" required></label>'
            '<label>Public key SHA256 <input name="existing_signer_public_key_sha256" required></label><button>Review exact snapshot</button></form>'
            '<pre id="review"></pre><button id="approve" disabled>Approve exact singleton tool scope</button><pre id="result"></pre>'
            '<script src="/assets/envelope-tool-owner.js" defer></script></html>')

    @app.get("/assets/envelope-tool-owner.js")
    def owner_script():
        # Same-origin script works under the unchanged native script-src self
        # CSP. No unsafe-inline, nonce shortcut or broadening of browser policy.
        return Response('let snapshot;const form=document.querySelector("#form"),button=document.querySelector("#approve");'
            'async function call(path,body){const response=await fetch(path,{method:"POST",headers:{"content-type":"application/json",'
            '"x-apatch-studio-session":document.querySelector("meta[name=apatch-studio-session]").content},body:JSON.stringify(body)});'
            'const value=await response.json();if(!response.ok)throw Error(JSON.stringify(value));return value;}'
            'form.onsubmit=async event=>{event.preventDefault();snapshot=undefined;button.disabled=true;try{const body=Object.fromEntries(new FormData(form));'
            'body.added_tools=[body.added_tool];delete body.added_tool;const value=await call("/api/v1/envelope-tool-amendment/review",body);snapshot=value;document.querySelector("#review").textContent=JSON.stringify(value,null,2);button.disabled=false;}'
            'catch(error){document.querySelector("#review").textContent=error.message;}};button.onclick=async()=>{if(!snapshot)return;button.disabled=true;'
            'try{const value=await call("/api/v1/envelope-tool-amendment/approve",{review:snapshot,expected_snapshot:snapshot.document_hash,confirmed:true});'
            'document.querySelector("#result").textContent=JSON.stringify(value,null,2);}catch(error){document.querySelector("#result").textContent=error.message;}'
            'snapshot=undefined;};', media_type="application/javascript")

    @app.post("/api/v1/envelope-tool-amendment/review")
    def review(body: ReviewRequest):
        return admin.review(body)

    @app.post("/api/v1/envelope-tool-amendment/approve")
    def approve(body: ApprovalRequest):
        return admin.approve(body)

    @app.post("/api/v1/envelope-tool-amendment/reconcile")
    def reconcile(body: ApprovalRequest):
        return admin.reconcile(body)

    return app
