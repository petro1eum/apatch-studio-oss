"""Draft native owner transaction for traceability header labels only.

This module is a qualification candidate, not an admission or activation.
All publication uses public native I/O, compilers, leases and SDK methods.
"""
from __future__ import annotations

import base64
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import tempfile

from apatch.sdd_integrity import canonical_hash, freeze_contract, validate_task_envelope
from apatch.strict_existing_signer import ExistingSignerBinding
from apatch.runtime.atomic_io import exclusive_file_lock
from apatch_studio.state_io import StateDirectory


TOOL = 'apatch_sdd_own_document_header_amendment'
SCHEMA = 'apatch.sdd.own-document-header-amendment.v1'
PROFILE = '.apatch/sdd_verification_contract.json'
PENDING = '.apatch/sdd/draft-amendment-pending.json'
SOURCE = 'apatch_studio/own_document_header_amendment.py'
BAD = b'| RFP acceptance | Requirement | Disposition |'
GOOD = b'| RFP id | SPEC Rk | Disposition |'
MAX_BYTES = 2 * 1024 * 1024
STAGES = ('preparation_approved', 'preparation_completed', 'freeze_approved', 'freeze_completed')


class Refused(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, code):
    if not condition:
        raise Refused(code)


def digest(raw):
    return 'sha256:' + hashlib.sha256(raw).hexdigest()


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True,
                       separators=(',', ':'), allow_nan=False) + '\n').encode()


def seal(value):
    value = copy.deepcopy(value)
    value.pop('document_hash', None)
    value['document_hash'] = canonical_hash(value)
    return value


def checked(value):
    require(isinstance(value, dict), 'INVALID_REVIEW')
    body = dict(value)
    expected = body.pop('document_hash', None)
    require(expected == canonical_hash(body), 'INVALID_REVIEW_SEAL')
    return value


def identifier(value):
    require(isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,127}', value),
            'INVALID_IDENTIFIER')
    return value


class OwnDocumentHeaderAmendment:
    def __init__(self, workspace, trusted_identity_root, trusted_public_binding, *, trusted_registry,
                 trusted_source_binding=None):
        self.root = self._directory(workspace)
        self.identity_root = self._directory(trusted_identity_root)
        require(isinstance(trusted_public_binding, ExistingSignerBinding), 'INVALID_TRUSTED_BINDING')
        from apatch.mcp.call_admission import PublicRegistry
        require(isinstance(trusted_registry, PublicRegistry), 'INVALID_TRUSTED_REGISTRY')
        self.binding = trusted_public_binding
        self.source_binding = trusted_public_binding if trusted_source_binding is None else trusted_source_binding
        require(isinstance(self.source_binding, ExistingSignerBinding), 'INVALID_TRUSTED_SOURCE_BINDING')
        self.registry = trusted_registry
        self.module_path = Path(__file__).absolute()
        require(self.module_path == self.module_path.resolve(), 'LINKED_SOURCE_ORIGIN')
        self.source_root = self.module_path.parent.parent

    @staticmethod
    def _directory(value):
        path = Path(value).absolute()
        require(path == path.resolve() and path.is_dir(), 'INVALID_TRUSTED_DIRECTORY')
        for parent in (path, *path.parents):
            info = parent.lstat()
            require(not stat.S_ISLNK(info.st_mode), 'LINKED_DIRECTORY')
            require(not info.st_mode & 0o022 or (parent != path and info.st_mode & stat.S_ISVTX),
                    'UNTRUSTED_DIRECTORY_CUSTODY')
        require(path.stat().st_uid == os.getuid(), 'FOREIGN_DIRECTORY_OWNER')
        return path

    @staticmethod
    def _relative(value):
        path = Path(value)
        require(isinstance(value, str) and not path.is_absolute() and '..' not in path.parts
                and value == path.as_posix() and value not in ('', '.'), 'UNSAFE_RELATIVE_PATH')
        return value

    def _read(self, relative, *, root=None, optional=False):
        root = self.root if root is None else root
        path = root / self._relative(relative)
        try:
            before = path.lstat()
            with StateDirectory(path.parent) as directory:
                raw = directory.read_bytes(path.name, limit=MAX_BYTES)
            info = path.lstat()
            fields = ('st_dev', 'st_ino', 'st_mode', 'st_size', 'st_mtime_ns', 'st_ctime_ns',
                      'st_uid', 'st_gid', 'st_nlink')
            require(all(getattr(before, f) == getattr(info, f) for f in fields), 'INPUT_CAPTURE_RACE')
            require(info.st_uid == os.getuid() and not info.st_mode & 0o022,
                    'UNTRUSTED_FILE_CUSTODY')
            return raw
        except FileNotFoundError:
            if optional:
                return None
            raise Refused('REQUIRED_INPUT_ABSENT') from None

    def _json(self, relative, *, root=None, optional=False):
        raw = self._read(relative, root=root, optional=optional)
        if raw is None:
            return None
        def pairs(items):
            result = {}
            for name, value in items:
                require(name not in result, 'DUPLICATE_JSON_FIELD')
                result[name] = value
            return result
        value = json.loads(raw, object_pairs_hook=pairs,
                           parse_constant=lambda _: (_ for _ in ()).throw(Refused('NONFINITE_JSON')))
        require(isinstance(value, dict), 'INVALID_NATIVE_DOCUMENT')
        return value

    def _write(self, relative, raw, *, immutable=False):
        path = self.root / self._relative(relative)
        with StateDirectory(path.parent, create=True) as directory:
            if immutable:
                try:
                    existing = directory.read_bytes(path.name, limit=MAX_BYTES)
                except FileNotFoundError:
                    existing = None
                if existing is not None:
                    require(existing == raw, 'IMMUTABLE_ARCHIVE_DRIFT')
                    return
            directory.write_bytes(path.name, raw)

    def _put(self, relative, value, *, immutable=False):
        self._write(relative, encoded(value), immutable=immutable)

    def _unlink(self, relative):
        path = self.root / self._relative(relative)
        with StateDirectory(path.parent) as directory:
            directory.unlink(path.name)

    def _records(self, *, root=None):
        root = self.root if root is None else root
        folder = root / '.trustchain/objects'
        rows = []
        if not folder.exists():
            return rows
        with StateDirectory(folder) as directory:
            names = directory.names()
        for name in names:
            if re.fullmatch(r'op_[0-9]+\.json', name):
                value = self._json('.trustchain/objects/' + name, root=root)
                record = value.get('value', value)
                require(isinstance(record, dict), 'INVALID_NATIVE_RECORD')
                rows.append((name[:-5], record))
        rows.sort(key=lambda row: int(row[0][3:]))
        return rows

    def _verify_record(self, record, *, expected_key=None):
        from trustchain.v2.chain_store import verify_record_signature
        from trustchain.v2.verifier import TrustChainVerifier
        key = record.get('key_id')
        require(isinstance(key, str) and (expected_key is None or key == expected_key),
                'FOREIGN_RECORD_SIGNER')
        identity = self.registry.identity(key)
        public = identity['public_key']
        if key == self.binding.agent_id:
            require(hashlib.sha256(public).hexdigest() == self.binding.public_key_sha256,
                    'FOREIGN_SIGNER_PUBLIC_KEY')
        if key == self.source_binding.agent_id:
            require(hashlib.sha256(public).hexdigest() == self.source_binding.public_key_sha256,
                    'FOREIGN_SOURCE_EXECUTOR_PUBLIC_KEY')
        timestamp = record.get('response_timestamp')
        require(record.get('algorithm') == 'ed25519' and type(timestamp) in (int, float)
                and math.isfinite(timestamp) and 0 < timestamp <= datetime.now(timezone.utc).timestamp(),
                'INVALID_RECORD_CHRONOLOGY')
        verifier = TrustChainVerifier(base64.b64encode(public).decode(), key_id=key,
                                      max_age_seconds=None)
        require(verify_record_signature(record, verifier) is True, 'INVALID_NATIVE_SIGNATURE')
        return record

    def _source_admission(self):
        from apatch.runtime.finalization import load_finalization
        from apatch.spec import parse_spec
        require(self.module_path == self.source_root / SOURCE, 'UNACCEPTED_IMPORTED_SOURCE')
        source_hash = digest(self._read(SOURCE, root=self.source_root))
        rows = dict(self._records(root=self.source_root))
        for op, record in reversed(list(rows.items())):
            data = record.get('data', {})
            proof = data.get('sdd_evidence', {})
            if record.get('tool') != 'apatch_attest' or not isinstance(proof, dict):
                continue
            mutations = proof.get('mutation_ids', [])
            matches = []
            for mutation_id in mutations:
                mutation = rows.get(mutation_id)
                if mutation is None:
                    continue
                entry = mutation.get('data', {}).get('files', {}).get(SOURCE, {})
                if entry.get('sha256') in (source_hash, source_hash[7:]):
                    matches.append(mutation)
            if not matches:
                continue
            self._verify_record(record, expected_key=self.source_binding.agent_id)
            for mutation in matches:
                self._verify_record(mutation, expected_key=record['key_id'])
            verification = proof.get('verification', {})
            result = verification.get('result', {})
            decision = verification.get('decision', {})
            falsification = proof.get('falsification', {})
            envelope = validate_task_envelope(proof.get('task_envelope', {}))
            sid = data.get('governed_session_id') or data.get('session_id')
            finalized = load_finalization(str(self.source_root), sid)
            source_spec, source_rk = envelope['requirement'].split('#')
            source_doc = self._read('docs/specs/' + source_spec + '.md', root=self.source_root)
            parsed = parse_spec(source_doc.decode())
            owned = next((r for r in parsed.requirements if r.id == source_rk), None)
            require(parsed.id == source_spec and parsed.strict_ownership and owned is not None
                    and SOURCE in owned.owns, 'SOURCE_STRICT_OWNER_DIFFERS')
            artifact = lambda d: any(a.get('kind') == 'spec'
                and a.get('id') == envelope['requirement'] and a.get('content_hash') == owned.content_hash
                for a in d.get('artifacts', []) if isinstance(a, dict))
            require(artifact(data) and proof.get('actor', {}).get('role') == 'implementation'
                    and isinstance(proof.get('actor', {}).get('actor_id'), str), 'SOURCE_ACTOR_BINDING_DIFFERS')
            for mutation in matches:
                md = mutation.get('data', {})
                require(mutation.get('tool') in ('apatch', 'apatch_expert')
                        and (md.get('governed_session_id') or md.get('session_id')) == sid
                        and artifact(md), 'SOURCE_MUTATION_CONTEXT_DIFFERS')
            source_contract = checked(self._json('.apatch/sdd/frozen/' + proof['contract_hash'][7:] + '.json',
                                                 root=self.source_root))
            require(source_contract['document_hash'] == proof['contract_hash']
                    and freeze_contract({k: v for k, v in source_contract.items() if k != 'document_hash'})
                        == source_contract, 'SOURCE_TYPED_CONTRACT_DIFFERS')
            source_checks = [o for o in source_contract['obligations']
                             if o['acceptance_id'] in envelope['checks']]
            require({o['acceptance_id'] for o in source_checks} == set(envelope['checks']),
                    'SOURCE_CHECK_BINDING_DIFFERS')
            for obligation in source_checks:
                for asset in obligation['judge_assets']:
                    require(digest(self._read(asset['path'], root=self.source_root)) == asset['sha256'],
                            'SOURCE_JUDGE_PIN_DIFFERS')
            require(decision.get('accepted') is True and result.get('executed', 0) > 0
                    and result.get('failed') == 0 and result.get('skipped') == 0
                    and falsification.get('observed_red') is True
                    and falsification.get('restored_green') is True
                    and finalized is not None and finalized.get('status') == 'complete'
                    and envelope['allowed_writes'] == [SOURCE]
                    and envelope['contract_hash'] == proof.get('contract_hash')
                    and envelope['document_hash'] == proof.get('envelope_hash'),
                    'SOURCE_ADMISSION_INCOMPLETE')
            require(proof.get('adherence', {}).get('status') == 'compliant'
                    and not proof.get('adherence', {}).get('violations'), 'SOURCE_SCOPE_VIOLATION')
            return {'source_hash': source_hash, 'attestation_op': op,
                    'attestation_hash': canonical_hash(record), 'signature': record['signature'],
                    'session_id': sid, 'contract_hash': proof['contract_hash'],
                    'expected_source_executor': {'agent_id': self.source_binding.agent_id,
                        'public_key_sha256': self.source_binding.public_key_sha256}}
        raise Refused('UNACCEPTED_IMPORTED_SOURCE')

    def _owner(self):
        from apatch_studio.lock_authority import approver_for
        raw = self._read('machine-identity.json', root=self.identity_root)
        owner = approver_for(self.identity_root)
        require(owner.get('certified') is True, 'UNCERTIFIED_OWNER')
        identity = self.registry.identity(self.binding.agent_id)
        require(hashlib.sha256(identity['public_key']).hexdigest() == self.binding.public_key_sha256,
                'FOREIGN_SIGNER_PUBLIC_KEY')
        record = json.loads(raw)
        certificate_path = record.get('certificate_path')
        require(isinstance(certificate_path, str), 'OWNER_CERTIFICATE_ABSENT')
        certificate_path = Path(certificate_path).absolute()
        require(certificate_path == certificate_path.resolve(), 'LINKED_OWNER_CERTIFICATE')
        from cryptography import x509
        from cryptography.hazmat.primitives.serialization import Encoding
        certificate = x509.load_pem_x509_certificate(certificate_path.read_bytes())
        require(certificate.public_bytes(Encoding.DER) == identity['leaf'].public_bytes(Encoding.DER),
                'OWNER_CREDENTIAL_REPLACED')
        return {'owner': owner, 'identity_hash': digest(raw),
                'certificate_digest': identity['certificate_digest']}

    def _idle(self, *, own_review=None, lease_id=None):
        from apatch.sdd_draft_amendment import assert_can_freeze
        from apatch.path_leases import load_active_leases
        assert_can_freeze(self.root, own_review=own_review)
        for name in ('.apatch/sdd/contract-intake-pending.json',):
            require(self._read(name, optional=True) is None, 'FOREIGN_PENDING_TRANSACTION')
        for lease in load_active_leases(str(self.root)):
            require(lease_id is not None and lease.get('lease_id') == lease_id,
                    'FOREIGN_WRITER_LEASE')

    def _head(self):
        raw = self._read('.trustchain/HEAD')
        return raw.decode().strip()

    def _profile(self):
        profile = checked(self._json(PROFILE))
        require(profile.get('status') == 'frozen' and profile.get('implementation_allowed') is True,
                'PROFILE_NOT_FROZEN')
        body = {k: v for k, v in profile.items() if k != 'document_hash'}
        require(freeze_contract(body) == profile, 'INVALID_TYPED_PROFILE')
        return profile

    def _lint(self, spec_id, rfp_id, spec_raw, rfp_raw):
        from apatch.spec import spec_lint_workspace
        from apatch.rfp_coverage import rfp_lint, rfp_spec_coverage
        with tempfile.TemporaryDirectory(prefix='apatch-own-header-review-') as temporary:
            root = Path(temporary)
            (root / 'docs/specs').mkdir(parents=True)
            (root / 'docs/specs' / (spec_id + '.md')).write_bytes(spec_raw)
            (root / 'docs' / (rfp_id + '.md')).write_bytes(rfp_raw)
            result = spec_lint_workspace(str(root), spec=spec_id)
        rfp = rfp_lint(rfp_raw.decode(), rfp_id=rfp_id)
        coverage = rfp_spec_coverage(rfp_raw.decode(), spec_raw.decode(),
                                     rfp_id=rfp_id, spec_id=spec_id)
        require(result.get('passed') is True and rfp.get('passed') is True
                and coverage.get('passed') is True, 'CORRECTED_FULL_LINT_REFUSED')
        return {'format': True, 'rfp_lint': True, 'rfp_coverage': True}

    def _provenance(self, spec_id, spec_path, original_hash, owner):
        rows = self._records()
        for op, completed in reversed(rows):
            body = completed.get('data', {})
            if (completed.get('tool') != 'apatch_sdd_contract_intake'
                    or body.get('schema') != 'apatch.sdd.contract-intake-review.v1'
                    or body.get('stage') != 'completed' or body.get('spec_id') != spec_id
                    or body.get('workspace') != str(self.root) or body.get('authority_id') != owner):
                continue
            approved = next((r for _, r in rows if r.get('signature') == completed.get('parent_signature')), None)
            if approved is None:
                continue
            a = approved.get('data', {})
            expected = {'agent_id': self.binding.agent_id,
                        'public_key_sha256': self.binding.public_key_sha256}
            require(approved.get('tool') == completed['tool'] and a.get('stage') == 'approved'
                    and a.get('review_hash') == body.get('review_hash')
                    and a.get('authority_id') == owner and a.get('owner', {}).get('id') == owner
                    and a.get('owner', {}).get('certified') is True
                    and a.get('native_signer') == expected and body.get('native_signer') == expected,
                    'INVALID_OWNER_PROVENANCE')
            self._verify_record(approved, expected_key=self.binding.agent_id)
            self._verify_record(completed, expected_key=self.binding.agent_id)
            require(approved['response_timestamp'] <= completed['response_timestamp'],
                    'INVALID_OWNER_PROVENANCE_CHRONOLOGY')
            review_hash = body['review_hash']
            review = checked(self._json('.apatch/sdd/contract-intakes/' + review_hash[7:] + '/review.json'))
            require(review['document_hash'] == review_hash and review.get('authority_id') == owner
                    and review.get('workspace') == str(self.root), 'INVALID_OWNER_REVIEW')
            files = {f['path']: f['after_hash'] for f in review['files']}
            require(files.get(spec_path) == original_hash
                    and body.get('result', {}).get('files') == files, 'OWNER_DOCUMENT_PIN_DIFFERS')
            candidate_path = '.apatch/sdd/prepared/' + spec_id + '.json'
            candidate_row = next((f for f in review['files'] if f['path'] == candidate_path), None)
            require(candidate_row is not None
                    and digest(candidate_row['content'].encode()) == candidate_row['after_hash'],
                    'APPROVED_CANDIDATE_PROVENANCE_ABSENT')
            return {'review_hash': review_hash, 'approved_hash': canonical_hash(approved),
                    'completed_hash': canonical_hash(completed), 'completed_op': op,
                    'approved_candidate': json.loads(candidate_row['content']),
                    'approved_files': files}
        raise Refused('OWNER_PROVENANCE_ABSENT')

    def _context(self, spec_id, rfp_id, requirement_id, requester, reason):
        from apatch.spec import parse_spec
        spec_id, rfp_id, requirement_id = map(identifier, (spec_id, rfp_id, requirement_id))
        require(isinstance(requester, str) and 3 <= len(requester) <= 128,
                'INVALID_REQUESTER')
        require(isinstance(reason, str) and 8 <= len(reason) <= 500, 'INVALID_REASON')
        self._idle()
        source = self._source_admission()
        owner = self._owner()
        require(requester != owner['owner']['id'], 'SELF_APPROVAL_FORBIDDEN')
        profile = self._profile()
        require(profile.get('authority') == {'role': 'authority', 'actor_id': owner['owner']['id']},
                'FOREIGN_FROZEN_OWNER')
        spec_path, rfp_path = 'docs/specs/' + spec_id + '.md', 'docs/' + rfp_id + '.md'
        raw = self._read(spec_path)
        lines = raw.splitlines(keepends=True)
        matched = [i for i, line in enumerate(lines) if line.rstrip(b'\r\n') == BAD]
        require(len(matched) == 1 and b'\r' not in raw, 'NOT_THE_PERMITTED_HEADER_DEFECT')
        corrected = b''.join(line.replace(BAD, GOOD, 1) if i == matched[0] else line
                             for i, line in enumerate(lines))
        parsed = parse_spec(raw.decode(), source_path=str(self.root / spec_path))
        require(parsed.id == spec_id and parsed.strict_ownership and not parsed.warnings,
                'STRICT_OWNER_REQUIRED')
        requirement = next((r for r in parsed.requirements if r.id == requirement_id), None)
        require(requirement is not None and requirement.owns and requirement.verify,
                'REQUIREMENT_OWNER_REQUIRED')
        import fnmatch
        ownership_inputs = {}
        for path in sorted((self.root / 'docs/specs').glob('SPEC-*.md')):
            relative = path.relative_to(self.root).as_posix()
            other_raw = self._read(relative)
            other = parse_spec(other_raw.decode(), source_path=str(path))
            if not other.strict_ownership:
                continue
            ownership_inputs[relative] = digest(other_raw)
            for declared in other.requirements:
                if other.id == spec_id and declared.id == requirement_id:
                    continue
                for target in requirement.owns:
                    require(not any(fnmatch.fnmatchcase(target, claim) or fnmatch.fnmatchcase(claim, target) or
                                    (claim.endswith('/**') and target.startswith(claim[:-2])) or
                                    (target.endswith('/**') and claim.startswith(target[:-2]))
                                    for claim in declared.owns), 'AMBIGUOUS_STRICT_OWNERSHIP')
        rfp_raw = self._read(rfp_path)
        lint = self._lint(spec_id, rfp_id, corrected, rfp_raw)
        envelope_path = '.apatch/sdd/envelopes/' + spec_id + '/' + requirement_id + '.json'
        envelope = validate_task_envelope(self._json(envelope_path))
        require(envelope.get('requirement') == spec_id + '#' + requirement_id,
                'FOREIGN_ENVELOPE')
        own_ids = set(envelope['checks'])
        own = [o for o in profile['obligations'] if o['acceptance_id'] in own_ids]
        require(own and {o['acceptance_id'] for o in own} == own_ids, 'AMBIGUOUS_OWN_OBLIGATION')
        old_hash = digest(raw)
        inputs = {PROFILE: digest(self._read(PROFILE)), spec_path: old_hash,
                  rfp_path: digest(rfp_raw), envelope_path: digest(self._read(envelope_path))}
        inputs.update(ownership_inputs)
        identity_raw = self._read('.apatch/agent-identity.json')
        inputs['.apatch/agent-identity.json'] = digest(identity_raw)
        for obligation in profile['obligations']:
            for asset in obligation['judge_assets']:
                expected = asset['sha256']
                require(digest(self._read(asset['path'])) == expected, 'CURRENT_JUDGE_ASSET_DRIFT')
                inputs[asset['path']] = expected
                if asset['path'] == spec_path:
                    require(obligation['acceptance_id'] in own_ids and expected == old_hash,
                            'FOREIGN_DOCUMENT_PIN')
        require(all(any(a['path'] == spec_path and a['sha256'] == old_hash
                        for a in o['judge_assets']) for o in own), 'OWN_SPEC_PIN_ABSENT')
        candidate_path = '.apatch/sdd/prepared/' + spec_id + '.json'
        candidate = self._json(candidate_path)
        require(candidate.get('schema') == 'apatch.studio.sdd-preparation.v1'
                and candidate.get('spec_id') == spec_id and candidate.get('source_mutation_count') == 0,
                'INVALID_OWN_CANDIDATE')
        inputs[candidate_path] = digest(self._read(candidate_path))
        provenance = self._provenance(spec_id, spec_path, old_hash, owner['owner']['id'])
        approved_candidate = provenance['approved_candidate']
        metadata = lambda c: {k: v for k, v in c.items() if k not in {'contract_request', 'task_envelopes'}}
        request_metadata = lambda c: {k: v for k, v in c['contract_request'].items()
                                     if k not in {'obligations', 'supersedes_hash'}}
        require(metadata(candidate) == metadata(approved_candidate)
                and request_metadata(candidate) == request_metadata(approved_candidate),
                'CANDIDATE_METADATA_DIFFERS_FROM_OWNER_APPROVAL')
        require(candidate['contract_request']['rfp_hash'] == digest(rfp_raw)
                and candidate['contract_request']['spec_hash'] == old_hash,
                'APPROVED_COMPILER_INPUT_DIFFERS')
        approved_envelope = approved_candidate['task_envelopes'].get(requirement_id)
        require(isinstance(approved_envelope, dict), 'APPROVED_OWN_SCOPE_ABSENT')
        scope = lambda e: {k: v for k, v in e.items() if k not in {'document_hash', 'contract_hash'}}
        require(scope(envelope) == scope(approved_envelope)
                and scope(candidate['task_envelopes'][requirement_id]) == scope(approved_envelope),
                'CURRENT_SCOPE_DIFFERS_FROM_OWNER_APPROVAL')
        for old in approved_candidate['contract_request']['obligations']:
            old = {**old, 'approver': owner['owner']['id']}
            if old['acceptance_id'] in own_ids:
                current = next((o for o in own if o['acceptance_id'] == old['acceptance_id']), None)
                require(current == old, 'OWN_CHECK_DIFFERS_FROM_OWNER_APPROVAL')
        if envelope['contract_hash'] != profile['document_hash']:
            self._accepted_historical_envelope(spec_id, requirement_id, envelope, profile)
        else:
            from apatch_studio.sdd_workflow import SddWorkflowFacade
            compiler_review = SddWorkflowFacade(self.root).contract_review(spec_id, requirement_id)
            require(compiler_review.get('status') == 'frozen'
                    and compiler_review.get('contract_hash') == profile['document_hash']
                    and compiler_review.get('envelope_hash') == envelope['document_hash'],
                    'CURRENT_COMPILER_EQUIVALENCE_REFUSED')
        metadata = {p: {'mode': stat.S_IMODE((self.root / p).stat().st_mode),
                        'uid': (self.root / p).stat().st_uid, 'gid': (self.root / p).stat().st_gid}
                    for p in inputs}
        return {'profile': profile, 'envelope': envelope, 'candidate': candidate,
                'paths': {'spec': spec_path, 'rfp': rfp_path, 'candidate': candidate_path,
                          'profile': PROFILE, 'envelope': envelope_path},
                'inputs': inputs, 'input_metadata': metadata,
                'request': {'spec_id': spec_id, 'rfp_id': rfp_id, 'requirement_id': requirement_id,
                            'requester_actor_id': requester, 'reason': reason},
                'spec_raw_b64': base64.b64encode(raw).decode(),
                'corrected_raw_b64': base64.b64encode(corrected).decode(),
                'requirement_body_hash': requirement.content_hash,
                'owner': owner, 'source': source, 'provenance': provenance,
                'provider_environment': self._provider_environment(),
                'head': self._head(), 'lint': lint}

    @staticmethod
    def _provider_environment():
        names = ('APATCH_AGENT_ID', 'APATCH_AGENT_KEY', 'APATCH_AGENT_CERT',
                 'APATCH_AGENT_PUBKEY', 'APATCH_AGENT_SIGN_CMD', 'APATCH_KEY_BACKEND')
        return {n: digest(os.environ[n].encode()) if n in os.environ else None for n in names}

    def _accepted_historical_envelope(self, spec_id, requirement_id, envelope, current):
        from apatch.runtime.finalization import load_finalization
        old = checked(self._json('.apatch/sdd/frozen/' + envelope['contract_hash'][7:] + '.json'))
        require(old['authority'] == current['authority']
                and freeze_contract({k: v for k, v in old.items() if k != 'document_hash'}) == old,
                'HISTORICAL_SCOPE_OWNER_DIFFERS')
        ancestor = current
        seen = set()
        for _ in range(256):
            if ancestor['document_hash'] == old['document_hash']:
                break
            require(ancestor['document_hash'] not in seen, 'HISTORICAL_PARENT_CYCLE')
            seen.add(ancestor['document_hash'])
            parent = ancestor.get('supersedes_hash')
            require(isinstance(parent, str) and re.fullmatch(r'sha256:[0-9a-f]{64}', parent),
                    'HISTORICAL_PARENT_LINEAGE_ABSENT')
            ancestor = checked(self._json('.apatch/sdd/frozen/' + parent[7:] + '.json'))
            require(ancestor['document_hash'] == parent and ancestor['authority'] == current['authority']
                    and freeze_contract({k: v for k, v in ancestor.items() if k != 'document_hash'}) == ancestor,
                    'HISTORICAL_PARENT_LINEAGE_INVALID')
        else:
            raise Refused('HISTORICAL_PARENT_LINEAGE_TOO_LONG')
        for check in envelope['checks']:
            previous = next((o for o in old['obligations'] if o['acceptance_id'] == check), None)
            now = next((o for o in current['obligations'] if o['acceptance_id'] == check), None)
            require(previous is not None and previous == now, 'HISTORICAL_CHECK_NOT_CURRENT')
        rows = dict(self._records())
        for _, record in reversed(list(rows.items())):
            data = record.get('data', {})
            proof = data.get('sdd_evidence', {})
            if record.get('tool') != 'apatch_attest' or proof.get('task_envelope') != envelope:
                continue
            self._verify_record(record, expected_key=self.source_binding.agent_id)
            sid = data.get('governed_session_id') or data.get('session_id')
            final = load_finalization(str(self.root), sid)
            decision = proof.get('verification', {}).get('decision', {})
            result = proof.get('verification', {}).get('result', {})
            require(final is not None and final.get('status') == 'complete'
                    and decision.get('accepted') is True and result.get('executed', 0) > 0
                    and result.get('failed') == 0 and result.get('skipped') == 0
                    and proof.get('falsification', {}).get('observed_red') is True
                    and proof.get('falsification', {}).get('restored_green') is True
                    and proof.get('adherence', {}).get('status') == 'compliant'
                    and not proof.get('adherence', {}).get('violations')
                    and proof.get('contract_hash') == old['document_hash']
                    and proof.get('envelope_hash') == envelope['document_hash']
                    and proof.get('actor', {}).get('role') == 'implementation',
                    'HISTORICAL_SOURCE_ACCEPTANCE_INCOMPLETE')
            joined = False
            for mutation_id in proof.get('mutation_ids', []):
                mutation = rows.get(mutation_id)
                if mutation is None:
                    continue
                md = mutation.get('data', {})
                require(mutation.get('tool') in ('apatch', 'apatch_expert')
                        and (md.get('governed_session_id') or md.get('session_id')) == sid,
                        'HISTORICAL_MUTATION_CONTEXT_DIFFERS')
                self._verify_record(mutation, expected_key=record['key_id'])
                for path, entry in md.get('files', {}).items():
                    if path in envelope['allowed_writes']:
                        require(digest(self._read(path)) in (entry['sha256'], 'sha256:' + entry['sha256']),
                                'HISTORICAL_ACCEPTED_SOURCE_DRIFT')
                        joined = True
            require(joined and envelope['requirement'] == spec_id + '#' + requirement_id,
                    'HISTORICAL_SOURCE_JOIN_ABSENT')
            return
        raise Refused('STALE_ENVELOPE_NOT_EXPLICITLY_RENEWABLE')

    def prepare_header_correction(self, spec_id, rfp_id, requirement_id, requester_actor_id, reason):
        try:
            context = self._context(spec_id, rfp_id, requirement_id, requester_actor_id, reason)
            body = {'schema': 'apatch.sdd.own-header-review.v1', 'status': 'review_ready',
                    'workspace': str(self.root), 'spec_id': spec_id, 'rfp_id': rfp_id,
                    'requirement_id': requirement_id, 'requester_actor_id': requester_actor_id,
                    'owner_actor_id': context['owner']['owner']['id'], 'reason': reason,
                    'created_at': datetime.now(timezone.utc).isoformat(), 'context': context,
                    'functional_acceptance': False}
            body['inputs_hash'] = canonical_hash(context)
            body['outputs_hash'] = canonical_hash({context['paths']['spec']:
                digest(base64.b64decode(context['corrected_raw_b64']))})
            body['snapshot'] = canonical_hash({'inputs_hash': body['inputs_hash'],
                                               'outputs_hash': body['outputs_hash']})
            return seal(body)
        except Refused:
            raise
        except Exception:
            raise Refused('HEADER_REVIEW_REFUSED') from None

    @staticmethod
    def _folder(review):
        return '.apatch/sdd/own-header-amendments/' + review['document_hash'][7:]

    def _check_review(self, review, snapshot, confirmed, *, phase):
        checked(review)
        require(confirmed is True and snapshot == review.get('snapshot'), 'EXACT_CONFIRMATION_REQUIRED')
        require(review.get('workspace') == str(self.root) and review.get('functional_acceptance') is False,
                'FOREIGN_REVIEW')
        require(review.get('schema') == ('apatch.sdd.own-header-review.v1' if phase == 'prepare'
                                        else 'apatch.sdd.own-header-freeze-review.v1'),
                'DISTINCT_OWNER_FREEZE_REVIEW_REQUIRED')
        if phase == 'prepare':
            context = review['context']
            require(all(review.get(k) == v for k, v in context['request'].items())
                    and review.get('owner_actor_id') == context['owner']['owner']['id'],
                    'REVIEW_AUTHORITY_FIELD_DIFFERS')
            inputs_hash = canonical_hash(context)
            outputs_hash = canonical_hash({context['paths']['spec']:
                digest(base64.b64decode(context['corrected_raw_b64']))})
            require(review.get('inputs_hash') == inputs_hash and review.get('outputs_hash') == outputs_hash
                    and review.get('snapshot') == canonical_hash({'inputs_hash': inputs_hash,
                                                                  'outputs_hash': outputs_hash}),
                    'REVIEW_IO_BINDING_DIFFERS')

    def _original(self, review):
        if review.get('schema') == 'apatch.sdd.own-header-review.v1':
            return review
        original = checked(self._json(review['original_review_path']))
        require(original['document_hash'] == review['original_review_hash'], 'ORIGINAL_REVIEW_DRIFT')
        return original

    def _assert_state(self, original, *, phase, lease_id=None):
        self._idle(own_review=original['document_hash'], lease_id=lease_id)
        owner = self._owner()
        require(owner == original['context']['owner'], 'CURRENT_OWNER_DRIFT')
        require(self._source_admission() == original['context']['source'], 'SOURCE_ADMISSION_DRIFT')
        require(self._provider_environment() == original['context']['provider_environment'],
                'PROVIDER_ROUTE_ENVIRONMENT_DRIFT')
        context = original['context']
        expected = dict(context['inputs'])
        if phase in ('prepared', 'frozen'):
            expected[context['paths']['spec']] = digest(base64.b64decode(context['corrected_raw_b64']))
        if phase == 'frozen':
            frozen = checked(self._json(self._folder(original) + '/freeze-review.json'))
            expected.update({p: digest(base64.b64decode(b)) for p, b in frozen['outputs'].items()})
        for path, value in expected.items():
            require(digest(self._read(path)) == value, 'CURRENT_CAS_DRIFT')
        self._assert_metadata(original)
        return expected

    def _assert_metadata(self, original):
        for path, expected in original['context']['input_metadata'].items():
            info = (self.root / path).lstat()
            actual = {'mode': stat.S_IMODE(info.st_mode), 'uid': info.st_uid, 'gid': info.st_gid}
            require(actual == expected, 'FILE_RIGHTS_CAS_DRIFT')

    def _payload(self, phase_review, original, stage):
        return {'schema': SCHEMA, 'stage': stage, 'review_hash': phase_review['document_hash'],
                'original_review_hash': original['document_hash'], 'workspace': str(self.root),
                'spec_id': original['spec_id'], 'rfp_id': original['rfp_id'],
                'requirement_id': original['requirement_id'],
                'owner_actor_id': original['owner_actor_id'],
                'requester_actor_id': original['requester_actor_id'],
                'native_signer_id': self.binding.agent_id,
                'public_key_sha256': self.binding.public_key_sha256,
                'inputs_hash': phase_review['inputs_hash'], 'outputs_hash': phase_review['outputs_hash'],
                'functional_acceptance': False, 'signed_by': self.binding.agent_id,
                'agent_id': self.binding.agent_id, 'key_id': self.binding.agent_id}

    def _receipt(self, phase_review, original, stage):
        expected = self._payload(phase_review, original, stage)
        matches = [(op, r) for op, r in self._records()
                   if r.get('tool') == TOOL and r.get('data', {}).get('review_hash') == expected['review_hash']
                   and r.get('data', {}).get('stage') == stage]
        require(len(matches) <= 1, 'AMBIGUOUS_NATIVE_COMMIT')
        if not matches:
            return None
        op, record = matches[0]
        self._verify_record(record, expected_key=self.binding.agent_id)
        require(record.get('data') == expected, 'NATIVE_RECEIPT_PAYLOAD_DIFFERS')
        return {'object_path': 'objects/' + op + '.json', 'signature': record['signature'],
                'parent_signature': record.get('parent_signature'), 'payload_hash': canonical_hash(expected)}

    def _pending(self, original, stage):
        self._put(PENDING, seal({'schema': 'apatch.sdd.own-header-pending.v1',
                                'review_hash': original['document_hash'], 'stage': stage,
                                'original_review': original,
                                'functional_acceptance': False}))

    def _sign(self, phase_review, original, stage, parent, *, lease_id=None):
        prior = self._receipt(phase_review, original, stage)
        if prior is not None:
            require(prior['parent_signature'] == parent, 'NATIVE_PARENT_DIFFERS')
            return prior
        pending = self._json(PENDING, optional=True)
        require(pending is not None and pending.get('review_hash') == original['document_hash'],
                'OWN_PENDING_REQUIRED')
        require(pending.get('stage') != 'signing_' + stage, 'AMBIGUOUS_NATIVE_COMMIT')
        state = ('original' if stage == 'preparation_approved' else
                 'frozen' if stage == 'freeze_completed' else 'prepared')
        self._assert_state(original, phase=state, lease_id=lease_id)
        self._owner()
        identity = self.binding.resolve(str(self.root))
        payload = self._payload(phase_review, original, stage)
        from trustchain import TrustChain, TrustChainConfig
        from trustchain.v2.policy_hooks import get_policy_registry
        from trustchain.v2.signer import SignedResponse
        from apatch.enforcement import ensure_enforcement_hooks
        ensure_enforcement_hooks(str(self.root))
        require(TOOL not in {v.strip() for v in os.environ.get('APATCH_POLICY_DENY', '').split(',')},
                'POLICY_DENIED')
        allowed, _ = get_policy_registry().evaluate(SignedResponse(tool_id=TOOL, data=payload,
                                                  signature='pending'),
                                                   {'source': 'apatch', 'workspace': str(self.root)})
        require(allowed, 'POLICY_DENIED')
        self._pending(original, 'signing_' + stage)
        try:
            with exclusive_file_lock(str(self.root / '.apatch/trustchain_ledger')):
                self._assert_state(original, phase=state, lease_id=lease_id)
                require(self._head() == parent, 'NATIVE_HEAD_CAS_DRIFT')
                tc = TrustChain(TrustChainConfig(key_provider=identity.key_provider,
                    enable_pki=False, enable_chain=True, chain_storage='file',
                    chain_dir=str(self.root / '.trustchain')))
                self.binding.require_native_key(tc)
                length = tc.chain.length
                require(tc.chain.parent_signature() == parent, 'NATIVE_CHAIN_CAS_DRIFT')
                signed = tc.sign(TOOL, payload, parent_signature=parent)
                require(tc.chain.length == length + 1 and self._head() == signed.signature,
                        'AMBIGUOUS_NATIVE_COMMIT')
                receipt = self._receipt(phase_review, original, stage)
                require(receipt is not None and receipt['signature'] == signed.signature
                        and receipt['parent_signature'] == parent, 'NATIVE_COMMIT_NOT_PERSISTED')
            self._put(self._folder(original) + '/' + stage + '.json', seal(receipt), immutable=True)
            self._pending(original, stage)
            return receipt
        except Refused:
            raise
        except Exception:
            raise Refused('AMBIGUOUS_NATIVE_COMMIT') from None

    def _lease(self, original):
        from apatch.path_leases import acquire_path_lease
        paths = [str(self.root / p) for p in original['context']['inputs']]
        paths += [str(self.root / PENDING), str(self.root / self._folder(original)),
                  str(self.root / '.apatch/sdd/frozen')]
        return acquire_path_lease(str(self.root), paths, tool=TOOL,
                governed_session_id='own-header:' + original['document_hash'], max_seconds=300)

    def _release(self, original):
        from apatch.path_leases import release_path_leases
        release_path_leases(str(self.root), governed_session_id='own-header:' + original['document_hash'])

    def _archive(self, original):
        folder = self._folder(original)
        self._pending(original, 'archiving')
        self._put(folder + '/review.json', original, immutable=True)
        for role, path in original['context']['paths'].items():
            if role == 'rfp':
                continue
            raw = self._read(path)
            require(digest(raw) == original['context']['inputs'][path], 'ARCHIVE_INPUT_DRIFT')
            self._write(folder + '/original-' + role + '.bin', raw, immutable=True)
        self._pending(original, 'archived')

    def approve_preparation(self, review, expected_snapshot, confirmed):
        try:
            self._check_review(review, expected_snapshot, confirmed, phase='prepare')
            pending = self._json(PENDING, optional=True)
            if pending is None:
                context = self._context(review['spec_id'], review['rfp_id'], review['requirement_id'],
                                         review['requester_actor_id'], review['reason'])
                require(context == review['context'], 'REVIEW_INPUT_DRIFT')
            else:
                require(pending.get('review_hash') == review['document_hash'], 'FOREIGN_PENDING_TRANSACTION')
                self._assert_recoverable(review, phase='prepare')
            from apatch.sdd_draft_amendment import freeze_lock
            with freeze_lock(self.root):
                lease = self._lease(review)
                try:
                    lease_id = lease.get('lease_id')
                    if pending is None:
                        self._assert_state(review, phase='original', lease_id=lease_id)
                        require(self._head() == review['context']['head'], 'NATIVE_HEAD_CAS_DRIFT')
                        self._archive(review)
                    else:
                        self._finish_archives(review)
                    approved = self._sign(review, review, 'preparation_approved', review['context']['head'],
                                          lease_id=lease_id)
                    self._assert_recoverable(review, phase='prepare', lease_id=lease_id)
                    self._apply_one(review['context']['paths']['spec'],
                        base64.b64decode(review['context']['corrected_raw_b64']),
                        review['context']['inputs'][review['context']['paths']['spec']])
                    self._assert_state(review, phase='prepared', lease_id=lease_id)
                    completed = self._sign(review, review, 'preparation_completed', approved['signature'],
                                           lease_id=lease_id)
                    self._pending(review, 'prepared')
                    return {'status': 'prepared', 'review_hash': review['document_hash'],
                            'receipts': [approved, completed], 'functional_acceptance': False}
                finally:
                    self._release(review)
        except Refused:
            raise
        except Exception:
            raise Refused('PREPARATION_REFUSED') from None

    def _finish_archives(self, original):
        folder = self._folder(original)
        self._put(folder + '/review.json', original, immutable=True)
        for role, path in original['context']['paths'].items():
            if role == 'rfp':
                continue
            archive_path = folder + '/original-' + role + '.bin'
            saved = self._read(archive_path, optional=True)
            if saved is None:
                current = self._read(path)
                require(digest(current) == original['context']['inputs'][path], 'MISSING_ARCHIVE_AFTER_MUTATION')
                self._write(archive_path, current, immutable=True)
            else:
                require(digest(saved) == original['context']['inputs'][path], 'ORIGINAL_ARCHIVE_DRIFT')

    def _apply_one(self, path, raw, original_hash):
        current = self._read(path)
        if current == raw:
            return
        require(digest(current) == original_hash, 'PUBLICATION_CAS_DRIFT')
        info = (self.root / path).lstat()
        mode = stat.S_IMODE(info.st_mode)
        require(os.name == 'posix', 'MODE_PRESERVING_WRITER_UNAVAILABLE')
        import secrets
        target = self.root / self._relative(path)
        with StateDirectory(target.parent) as directory:
            temporary = '.' + target.name + '.' + secrets.token_hex(16) + '.tmp'
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         0o600, dir_fd=directory.fd)
            try:
                with os.fdopen(fd, 'wb') as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fchown(stream.fileno(), info.st_uid, info.st_gid)
                    os.fchmod(stream.fileno(), mode)
                    os.fsync(stream.fileno())
                now = target.lstat()
                require((now.st_dev, now.st_ino, now.st_mode, now.st_mtime_ns, now.st_ctime_ns)
                        == (info.st_dev, info.st_ino, info.st_mode, info.st_mtime_ns, info.st_ctime_ns),
                        'PUBLICATION_FILE_RACE')
                os.replace(temporary, target.name, src_dir_fd=directory.fd, dst_dir_fd=directory.fd)
                os.fsync(directory.fd)
            finally:
                try:
                    os.unlink(temporary, dir_fd=directory.fd)
                except FileNotFoundError:
                    pass

    def _freeze_outputs(self, original):
        context = original['context']
        corrected = base64.b64decode(context['corrected_raw_b64'])
        spec_path = context['paths']['spec']
        old_hash, new_hash = context['inputs'][spec_path], digest(corrected)
        profile = copy.deepcopy(context['profile'])
        profile.pop('document_hash')
        if profile['spec_hash'] == old_hash:
            profile['spec_hash'] = new_hash
        for obligation in profile['obligations']:
            if obligation['acceptance_id'] not in context['envelope']['checks']:
                continue
            for asset in obligation['judge_assets']:
                if asset['path'] == spec_path:
                    asset['sha256'] = new_hash
            obligation['asset_hashes'] = [new_hash if value == old_hash else value
                                         for value in obligation['asset_hashes']]
        profile['supersedes_hash'] = context['profile']['document_hash']
        profile = freeze_contract(profile)
        envelope = copy.deepcopy(context['envelope'])
        envelope.pop('document_hash')
        envelope['contract_hash'] = profile['document_hash']
        envelope = validate_task_envelope(envelope)
        candidate = copy.deepcopy(context['candidate'])
        candidate['contract_request']['spec_hash'] = new_hash
        candidate['contract_request']['obligations'] = copy.deepcopy(profile['obligations'])
        candidate['contract_request']['supersedes_hash'] = context['profile']['document_hash']
        return {context['paths']['candidate']: encoded(candidate), PROFILE: encoded(profile),
                context['paths']['envelope']: encoded(envelope)}, profile

    def review_owner_freeze(self, review):
        try:
            checked(review)
            require(review.get('schema') == 'apatch.sdd.own-header-review.v1'
                    and review.get('workspace') == str(self.root), 'FOREIGN_REVIEW')
            self._assert_state(review, phase='prepared')
            a = self._receipt(review, review, 'preparation_approved')
            c = self._receipt(review, review, 'preparation_completed')
            require(a is not None and c is not None and a['parent_signature'] == review['context']['head']
                    and c['parent_signature'] == a['signature'] and self._head() == c['signature'],
                    'PREPARATION_NOT_COMPLETE')
            return self._expected_freeze_review(review, c['signature'])
        except Refused:
            raise
        except Exception:
            raise Refused('OWNER_FREEZE_REVIEW_REFUSED') from None

    def _expected_freeze_review(self, review, preparation_head):
            outputs, profile = self._freeze_outputs(review)
            inputs = dict(review['context']['inputs'])
            inputs[review['context']['paths']['spec']] = digest(base64.b64decode(review['context']['corrected_raw_b64']))
            body = {'schema': 'apatch.sdd.own-header-freeze-review.v1', 'status': 'freeze_ready',
                    'workspace': str(self.root), 'original_review_hash': review['document_hash'],
                    'original_review_path': self._folder(review) + '/review.json',
                    'owner_actor_id': review['owner_actor_id'],
                    'requester_actor_id': review['requester_actor_id'],
                    'inputs': inputs, 'head': preparation_head,
                    'outputs': {p: base64.b64encode(raw).decode() for p, raw in outputs.items()},
                    'frozen_contract': profile, 'functional_acceptance': False}
            body['inputs_hash'] = canonical_hash({'inputs': inputs, 'head': body['head']})
            body['outputs_hash'] = canonical_hash({p: digest(raw) for p, raw in outputs.items()})
            body['snapshot'] = canonical_hash({'inputs_hash': body['inputs_hash'],
                                               'outputs_hash': body['outputs_hash']})
            return seal(body)

    def freeze_corrected_requirement(self, freeze_review, expected_snapshot, confirmed):
        try:
            self._check_review(freeze_review, expected_snapshot, confirmed, phase='freeze')
            original = self._original(freeze_review)
            preparation = self._receipt(original, original, 'preparation_completed')
            require(preparation is not None
                    and self._expected_freeze_review(original, preparation['signature']) == freeze_review,
                    'FREEZE_PLAN_NOT_DERIVED_FROM_APPROVED_INPUTS')
            prior = self._json(self._folder(original) + '/freeze-review.json', optional=True)
            if prior is None:
                require(self.review_owner_freeze(original) == freeze_review, 'FREEZE_REVIEW_DRIFT')
            else:
                require(prior == freeze_review, 'IMMUTABLE_FREEZE_REVIEW_DRIFT')
                self._assert_recoverable(original, phase='freeze', freeze_review=freeze_review)
            from apatch.sdd_draft_amendment import freeze_lock
            with freeze_lock(self.root):
                lease = self._lease(original)
                try:
                    lease_id = lease.get('lease_id')
                    if prior is None:
                        self._assert_state(original, phase='prepared', lease_id=lease_id)
                        self._put(self._folder(original) + '/freeze-review.json', freeze_review, immutable=True)
                    approved = self._sign(freeze_review, original, 'freeze_approved', freeze_review['head'],
                                          lease_id=lease_id)
                    profile = freeze_review['frozen_contract']
                    self._assert_recoverable(original, phase='freeze', freeze_review=freeze_review,
                                             lease_id=lease_id)
                    self._put('.apatch/sdd/frozen/' + profile['document_hash'][7:] + '.json', profile, immutable=True)
                    for role in ('candidate', 'profile', 'envelope'):
                        path = original['context']['paths'][role]
                        b64 = freeze_review['outputs'][path]
                        self._assert_recoverable(original, phase='freeze', freeze_review=freeze_review,
                                                 lease_id=lease_id)
                        self._apply_one(path, base64.b64decode(b64), original['context']['inputs'][path])
                    self._assert_state(original, phase='frozen', lease_id=lease_id)
                    completed = self._sign(freeze_review, original, 'freeze_completed', approved['signature'],
                                           lease_id=lease_id)
                    self._assert_state(original, phase='frozen', lease_id=lease_id)
                    require(self._head() == completed['signature'], 'NATIVE_HEAD_CAS_DRIFT')
                    self._lint(original['spec_id'], original['rfp_id'],
                               self._read(original['context']['paths']['spec']),
                               self._read(original['context']['paths']['rfp']))
                    from apatch_studio.sdd_workflow import SddWorkflowFacade
                    bound = SddWorkflowFacade(self.root).execution_binding(original['spec_id'],
                        original['requirement_id'], actor_id=original['requester_actor_id'])
                    require(bound['contract_hash'] == profile['document_hash'], 'NORMAL_BINDING_REFUSED')
                    compiler_review = SddWorkflowFacade(self.root).contract_review(
                        original['spec_id'], original['requirement_id'])
                    require(compiler_review.get('status') == 'frozen'
                            and compiler_review.get('contract_hash') == profile['document_hash']
                            and compiler_review.get('envelope_hash') == bound['envelope_hash'],
                            'NORMAL_COMPILER_EQUIVALENCE_REFUSED')
                    self._unlink(PENDING)
                    return {'status': 'frozen', 'review_hash': freeze_review['document_hash'],
                            'receipts': [approved, completed], 'functional_acceptance': False}
                finally:
                    self._release(original)
        except Refused:
            raise
        except Exception:
            raise Refused('OWNER_FREEZE_REFUSED') from None

    def _assert_recoverable(self, original, *, phase, freeze_review=None, lease_id=None):
        checked(original)
        persisted = self._json(self._folder(original) + '/review.json', optional=True)
        if persisted is None:
            pending = checked(self._json(PENDING))
            require(pending.get('original_review') == original, 'PENDING_REVIEW_DRIFT')
        else:
            require(persisted == original, 'IMMUTABLE_REVIEW_DRIFT')
        self._idle(own_review=original['document_hash'], lease_id=lease_id)
        require(self._owner() == original['context']['owner'], 'CURRENT_OWNER_DRIFT')
        require(self._source_admission() == original['context']['source'], 'SOURCE_ADMISSION_DRIFT')
        require(self._provider_environment() == original['context']['provider_environment'],
                'PROVIDER_ROUTE_ENVIRONMENT_DRIFT')
        expected = original['context']['inputs']
        alternates = {original['context']['paths']['spec']:
                      digest(base64.b64decode(original['context']['corrected_raw_b64']))}
        if freeze_review is not None:
            alternates.update({p: digest(base64.b64decode(b)) for p, b in freeze_review['outputs'].items()})
        preparation = [self._receipt(original, original, s) for s in STAGES[:2]]
        freezing = [self._receipt(freeze_review, original, s) for s in STAGES[2:]] if freeze_review else []
        seen_gap = False
        for receipt in preparation + freezing:
            if receipt is None:
                seen_gap = True
            else:
                require(not seen_gap, 'NATIVE_RECEIPT_STAGE_GAP')
        if freeze_review is not None:
            require(preparation[1] is not None and freeze_review == self._expected_freeze_review(
                original, preparation[1]['signature']), 'FREEZE_PLAN_NOT_DERIVED_FROM_APPROVED_INPUTS')
        for path, before in expected.items():
            allowed = {before}
            if path == original['context']['paths']['spec'] and preparation[0] is not None:
                allowed.add(alternates[path])
                if preparation[1] is not None:
                    allowed = {alternates[path]}
            if freeze_review is not None and freezing[0] is not None and path in freeze_review['outputs']:
                allowed.add(alternates[path])
                if freezing[1] is not None:
                    allowed = {alternates[path]}
            require(digest(self._read(path)) in allowed, 'UNRECOGNIZED_PARTIAL_STATE')
        if freeze_review is not None:
            after_seen_gap = False
            for role in ('candidate', 'profile', 'envelope'):
                path = original['context']['paths'][role]
                after = digest(base64.b64decode(freeze_review['outputs'][path]))
                current = digest(self._read(path))
                if current != after:
                    after_seen_gap = True
                else:
                    require(not after_seen_gap, 'UNRECOGNIZED_PUBLICATION_PREFIX')
        self._assert_metadata(original)
        parent = original['context']['head']
        for receipt in preparation + freezing:
            if receipt is not None:
                require(receipt['parent_signature'] == parent, 'NATIVE_PARENT_DIFFERS')
                parent = receipt['signature']
        require(self._head() == parent, 'AMBIGUOUS_NATIVE_COMMIT')
        pending = self._json(PENDING, optional=True)
        if pending is not None and str(pending.get('stage', '')).startswith('signing_'):
            stage = pending['stage'][8:]
            phase_review = freeze_review if stage.startswith('freeze_') else original
            require(phase_review is not None and self._receipt(phase_review, original, stage) is not None,
                    'AMBIGUOUS_NATIVE_COMMIT')

    def review_reconciliation(self, original_review):
        try:
            checked(original_review)
            require(original_review.get('schema') == 'apatch.sdd.own-header-review.v1'
                    and original_review.get('workspace') == str(self.root), 'FOREIGN_REVIEW')
            folder = self._folder(original_review)
            freeze_review = self._json(folder + '/freeze-review.json', optional=True)
            self._assert_recoverable(original_review, phase='freeze' if freeze_review else 'prepare',
                                     freeze_review=freeze_review)
            completed = (self._receipt(freeze_review, original_review, 'freeze_completed')
                         if freeze_review else None)
            if completed is not None and self._read(PENDING, optional=True) is None:
                self._assert_state(original_review, phase='frozen')
                status, stage = 'complete', 'freeze_completed'
            else:
                status, stage = 'reconciled', self._json(PENDING)['stage']
            return {'status': status, 'stage': stage, 'review_hash': original_review['document_hash'],
                    'functional_acceptance': False}
        except Refused as exc:
            return {'status': 'hold', 'reason': exc.code, 'functional_acceptance': False}
        except Exception:
            return {'status': 'hold', 'reason': 'RECONCILIATION_REFUSED', 'functional_acceptance': False}
