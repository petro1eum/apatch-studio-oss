"""Exact Cowork dispatch adapter; Core owns the frozen contract and execution.

The two new signatures are issued by Platform, not by this module. A local
content seal, persisted association or successful HTTP status is not authority.
Every external dispatch obtains a new purpose-verified Platform acknowledgement.
The first supported judge environment is cwd='.' with an exact /usr/bin/env -i
argv. Other native environments fail closed instead of silently inheriting env.
"""
from __future__ import annotations

import copy
import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from apatch import execution_proposal as P
from apatch import governed_work as G
from apatch import governed_work_delivery as D
from apatch import governed_work_mcp as M
from apatch import governed_work_transport as T
from apatch import sdd_integrity as S
from apatch import work_item_acceptance as W
from apatch_studio.execution_intents import ExecutionIntentError
from apatch_studio.governed_work_gateway import APatchGovernedWorkGateway
from apatch_studio.intent_store import IntentStore
from apatch_studio.operations import AgentRunRequest, ExecutionContext, SddExecutionContext
from apatch_studio.sdd_workflow import SddWorkflowFacade
from apatch_studio.state_io import StateDirectory, read_json
from apatch_studio.exact_contract_delivery import ExactContractDelivery

ISSUE_PURPOSE = 'apatch_studio.exact_contract_handoff.issue'
BIND_PURPOSE = 'apatch_studio.exact_contract.bind'
BUNDLE_SCHEMA = 'trustchain.apatch-studio.exact-contract-bundle.v1'
HANDOFF_SCHEMA = 'trustchain.apatch-studio.exact-contract-handoff.v1'
FACTS_SCHEMA = 'trustchain.apatch-studio.exact-contract-request-facts.v1'
ACK_SCHEMA = 'trustchain.apatch-studio.exact-contract-ack.v1'
ASSOCIATION_SCHEMA = 'trustchain.apatch-studio.exact-contract-association.v1'
HANDOFF_KEYS = frozenset(('schema','handoff_id','contract_id','snapshot_hash','contract_state_version',
    'tenant_id','project_group_id','work_item_id','work_item_hash','authority_version','work_program_id',
    'work_program_hash','assignee_ref','commissioner_principal_ref','performer_principal_ref','consents_hash',
    'native_contract_hash','native_baseline_hash','native_judge_environment_hash','requirements',
    'legacy_intent_document_hash','legacy_intent_envelope_hash','audience','operation','nonce','issued_at','expires_at','signature'))
ASSOCIATION_KEYS = frozenset(('schema','association_id','handoff_id','handoff_document_hash','handoff_envelope_hash',
    'contract_id','snapshot_hash','tenant_id','project_group_id','work_item_id','accepted_work_item_hash',
    'accepted_authority_version','current_work_item_hash','current_authority_version','work_program_id','work_program_hash',
    'commissioner_principal_ref','performer_principal_ref','consents_hash','native_contract_hash','requirement',
    'task_envelope_hash','change_id','change_hash','native_binding_id','native_binding_hash','exact_request_facts_hash',
    'raw_spec_hash','native_spec_hash','accepted_at','signature'))
SNAPSHOT_KEYS = frozenset(('schema','tenant_id','project_group_id','work_item_id','work_item_hash','authority_version',
    'assignee_ref','terms','frozen_contract','task_envelopes'))
HASH = re.compile(r'^sha256:[0-9a-f]{64}$')
REQUIREMENT = re.compile(r'^(SPEC-[A-Z0-9][A-Z0-9-]*)#(R[0-9]+)$')
MAX_DOCUMENT = 2 * 1024 * 1024
MAX_SPEC_BYTES = 256 * 1024


def denied(message, code='exact_contract_invalid', status_code=409):
    raise ExecutionIntentError(message, code=code, status_code=status_code)


def raw_canonical(value):
    """Preserve every customer Unicode codepoint; do not normalize a snapshot."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def raw_hash(value):
    return 'sha256:' + hashlib.sha256(raw_canonical(value)).hexdigest()


def validate_native_snapshot(contract, envelopes):
    """Use the native owner's cowork-exact-v1 reader; never re-freeze input."""
    try:
        S.validate_native_snapshot(contract, envelopes)
    except (S.SddContractError, TypeError) as exc:
        denied('Exact native format is invalid: ' + str(exc))


def native_requirement_refs(spec_bytes, requirement):
    """Use the actual unchanged public native parser on the SAME raw SPEC."""
    from apatch.spec import parse_spec
    match = REQUIREMENT.fullmatch(requirement)
    if match is None:
        denied('An exact selected requirement is required', 'exact_native_requirement_mismatch')
    parsed = parse_spec(spec_bytes.decode('utf-8'),spec_id=match[1])
    selected = [item for item in parsed.requirements if item.id == match[2]]
    if parsed.warnings or len(selected) != 1:
        denied('The native selected requirement is ambiguous or unsupported', 'exact_native_requirement_mismatch')
    return [{'requirement_id':selected[0].id,'requirement_hash':selected[0].content_hash}]


def native_acceptance_purpose(requirement, handoff_id):
    # A renewed handoff carries a new native proposal. Its immutable acceptance
    # must not collide with the previous handoff for the same requirement.
    return 'Execute the exact agreed requirement ' + requirement + ' via handoff ' + handoff_id


def exact(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        denied('Exact document has an invalid closed shape')
    return copy.deepcopy(value)


def stamp(value):
    if not isinstance(value, str) or not value.endswith('Z'):
        denied('Exact document timestamp is invalid')
    try:
        result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        denied('Exact document timestamp is invalid')
    if result.utcoffset().total_seconds() != 0:
        denied('Exact document timestamp is invalid')
    return result


def parse_raw(raw):
    if not isinstance(raw, bytes) or not raw or len(raw) > MAX_DOCUMENT:
        denied('Exact document is outside its size limit')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                denied('Exact document contains duplicate members')
            result[key] = value
        return result
    try:
        value = json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: denied('Nonfinite JSON is forbidden'))
        if raw_canonical(value) != raw:
            denied('Exact document must use raw canonical JSON')
    except (ValueError, UnicodeError, TypeError):
        denied('Exact document is invalid JSON')
    return value


class ExactContractConfirmation(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    confirmed: Literal[True]
    workspace_id: str = Field(pattern=r'^[0-9a-f]{32}$')
    runner_id: Literal['codex','claude']
    requirement: str = Field(pattern=r'^SPEC-[A-Z0-9][A-Z0-9-]*#R[0-9]+$')


class ExactContractTrust:
    """Separately provisioned public pins for the two exact Platform purposes."""
    def __init__(self, *, handoff_keys, association_keys, legacy_keys, trusted_origins=()):
        if not handoff_keys or not association_keys or not legacy_keys:
            denied('Exact purpose-specific authority pins are unavailable', 'exact_authority_unconfigured', 503)
        self.handoff_keys = dict(handoff_keys)
        self.association_keys = dict(association_keys)
        self.legacy_keys = dict(legacy_keys)
        self.trusted_origins = frozenset(trusted_origins)

    @classmethod
    def from_path(cls, path):
        try:
            return cls.from_document(read_json(Path(path).expanduser().absolute(), limit=1048576))
        except (OSError, ValueError, TypeError, ExecutionIntentError):
            denied('Exact authority pins could not be loaded', 'exact_authority_unconfigured', 503)

    @classmethod
    def from_document(cls, document):
        import base64
        value = exact(document, {'schema','trusted_origins','handoff_keys','association_keys','legacy_keys'})
        if value['schema'] != 'apatch.studio.exact-contract-trust.v1':
            denied('Exact authority pins have an invalid schema', 'exact_authority_unconfigured', 503)
        maps = {}
        for field in ('handoff_keys','association_keys','legacy_keys'):
            keys = value[field]
            if not isinstance(keys, dict) or not keys:
                denied('Exact authority pins are unavailable', 'exact_authority_unconfigured', 503)
            checked = {}
            for key_id, encoded in keys.items():
                try:
                    public = base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))
                except (ValueError, TypeError):
                    denied('Exact public authority pin is invalid', 'exact_authority_unconfigured', 503)
                digest = hashlib.sha256(public).hexdigest()
                if len(public) != 32 or key_id not in ('ed25519:sha256:' + digest, 'sha256:' + digest):
                    denied('Exact public authority pin is invalid', 'exact_authority_unconfigured', 503)
                checked[key_id] = public
            maps[field] = checked
        from apatch_studio.security import _normalized_origin
        if not isinstance(value['trusted_origins'], list) or not all(isinstance(x,str) and _normalized_origin(x) is not None for x in value['trusted_origins']):
            denied('Exact trusted origins are invalid', 'exact_authority_unconfigured', 503)
        return cls(**maps, trusted_origins=value['trusted_origins'])

    def validate_bundle(self, document, *, now, historical=False):
        try:
            return self._validate_bundle(document, now=now, historical=historical)
        except ExecutionIntentError:
            raise
        except (G.GovernedWorkError, S.SddContractError, ValueError, TypeError, KeyError) as exc:
            denied('Exact contract verification failed: ' + str(exc))

    def _validate_bundle(self, document, *, now, historical=False):
        b = exact(document, {'schema','handoff','snapshot','legacy_intent'})
        h = exact(b['handoff'], HANDOFF_KEYS)
        snapshot = exact(b['snapshot'], SNAPSHOT_KEYS)
        if (b['schema'] != BUNDLE_SCHEMA or h['schema'] != HANDOFF_SCHEMA or h['audience'] != 'apatch-studio'
                or h['operation'] != 'exact_requirement_run' or snapshot['schema'] != 'trustchain.cowork.initial-contract-snapshot.v1'):
            denied('Wrong exact contract operation')
        for name, prefix in (('handoff_id','tceh_'),('contract_id','tciwc_'),('project_group_id','tcpg_'),
                             ('work_item_id','tcpwi_'),('work_program_id','tcwp_')):
            if not isinstance(h[name], str) or not re.fullmatch(prefix + r'[0-9a-f]{32}', h[name]):
                denied('Invalid exact contract identity')
        for name in HANDOFF_KEYS:
            if name.endswith('_hash') and (not isinstance(h[name], str) or not HASH.fullmatch(h[name])):
                denied('Invalid exact contract digest')
        for name in ('authority_version','contract_state_version'):
            if type(h[name]) is not int or h[name] < 1:
                denied('Invalid exact contract version')
        for name in ('assignee_ref','commissioner_principal_ref','performer_principal_ref'):
            if not isinstance(h[name], str) or not re.fullmatch(r'member:[0-9a-f]{32}', h[name]):
                denied('Invalid exact party reference')
        if h['commissioner_principal_ref'] == h['performer_principal_ref']:
            denied('Two distinct consenting parties are required')
        if not isinstance(h['nonce'], str) or not re.fullmatch(r'[0-9a-f]{48}', h['nonce']):
            denied('Invalid exact handoff nonce')
        issued, expires = stamp(h['issued_at']), stamp(h['expires_at'])
        if (not 0 < (expires-issued).total_seconds() <= 300 or now < issued
                or (not historical and now >= expires)):
            denied('Exact handoff is no longer current', 'exact_contract_expired', 410)
        G.verify_platform_document_signature(h, self.handoff_keys, purpose=ISSUE_PURPOSE)
        # Historical proof checks the original signature/lifetime at issuance;
        # dispatch always uses the current clock. No new admission is created.
        legacy = P.validate_execution_proposal(b['legacy_intent'], trusted_keys=self.legacy_keys,
            now=issued if historical else now)
        if (G.document_hash(legacy) != h['legacy_intent_document_hash'] or G.envelope_hash(legacy) != h['legacy_intent_envelope_hash']
                or expires > stamp(legacy['expires_at'])):
            denied('Embedded native proposal commitment changed')
        for name in ('tenant_id','project_group_id','work_item_id','work_item_hash','authority_version','assignee_ref'):
            if snapshot[name] != h[name]:
                denied('Exact snapshot scope changed')
        for name in ('tenant_id','project_group_id','work_item_id','work_item_hash','authority_version','work_program_id','work_program_hash'):
            if legacy[name] != h[name]:
                denied('Embedded native proposal scope changed')
        native = snapshot['frozen_contract']
        if (not isinstance(native, dict) or raw_hash({k:v for k,v in native.items() if k != 'document_hash'}) != native.get('document_hash')
                or native.get('document_hash') != h['native_contract_hash'] or native.get('baseline_hash') != h['native_baseline_hash']
                or raw_hash(native.get('judge_environment')) != h['native_judge_environment_hash'] or raw_hash(snapshot) != h['snapshot_hash']):
            denied('Exact frozen snapshot commitment changed')
        envelopes = snapshot['task_envelopes']
        if not isinstance(envelopes, dict) or not envelopes:
            denied('Exact selected envelopes are unavailable')
        validate_native_snapshot(native, envelopes)
        expected = []
        for rk, envelope in sorted(envelopes.items()):
            checked = S.validate_task_envelope(envelope)
            if (raw_canonical(checked) != raw_canonical(envelope) or not REQUIREMENT.fullmatch(checked['requirement'])
                    or checked['requirement'].split('#')[1] != rk or checked['contract_hash'] != native['document_hash']):
                denied('Exact selected envelope changed')
            expected.append({'requirement': checked['requirement'], 'task_envelope_hash': checked['document_hash']})
        if h['requirements'] != expected:
            denied('Exact selected requirements changed')
        return b


class ExactContractManager:
    def __init__(self, workspace, *, run_manager, trust, state_root=None, gateway=None, clock=None,
                 actor_id=None, sdd_facade=None, http_client_factory=None):
        self.workspace = Path(workspace).expanduser().resolve()
        self.workspace_id = hashlib.sha256(str(self.workspace).encode()).hexdigest()[:32]
        self.run_manager, self.trust = run_manager, trust
        self.store = IntentStore(self.workspace, state_root=state_root)
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.gateway = gateway or APatchGovernedWorkGateway(self.workspace)
        self.sdd = sdd_facade or SddWorkflowFacade(self.workspace)
        self.actor_id = actor_id
        self.http_client_factory = http_client_factory or (lambda: httpx.Client(timeout=10, follow_redirects=False, trust_env=False))
        self._journal_name = 'exact-contract-handoffs.json'
        self.delivery = ExactContractDelivery(self)
        self.run_manager.configure_external_dispatch_guard(self.guard_execution)
        self._reconcile()

    def _update(self, mutate):
        # Same cross-process private workspace lock as the legacy journal; never
        # rewrite its closed v1 records or envelopes.
        with self.store._transaction():
            with StateDirectory(self.store.directory, create=True) as directory:
                try:
                    journal = directory.read_json(self._journal_name, limit=MAX_DOCUMENT)
                except FileNotFoundError:
                    journal = {'schema':'apatch.studio.exact-contract-journal.v1','records':[]}
                exact(journal, {'schema','records'})
                if journal['schema'] != 'apatch.studio.exact-contract-journal.v1' or not isinstance(journal['records'], list):
                    denied('Exact journal is unavailable', 'exact_journal_invalid', 503)
                result = mutate(journal['records'])
                directory.write_json(self._journal_name, journal)
                return copy.deepcopy(result)

    def _find(self, records, handoff_id):
        for row in records:
            if row['handoff_id'] == handoff_id:
                return row
        denied('Exact handoff was not found', 'exact_contract_not_found', 404)

    def _read_bundle(self, row, *, historical=False):
        path = self.store.directory / 'exact-contract-bundles' / (row['handoff_id'] + '.json')
        bundle = read_json(path, limit=MAX_DOCUMENT)
        if raw_hash(bundle) != row['bundle_hash']:
            denied('Private exact handoff changed', 'exact_journal_tampered')
        if historical and (row['status'] != 'consumed' or row['ack'] is None or row['facts'] is None):
            denied('Historical proof requires a retained admission', 'exact_ack_required')
        return self.trust.validate_bundle(bundle, now=self.clock(), historical=historical)

    def import_raw(self, raw):
        bundle = self.trust.validate_bundle(parse_raw(raw), now=self.clock())
        h = bundle['handoff']
        def admit(records):
            for row in records:
                if row['handoff_id'] == h['handoff_id']:
                    if row['bundle_hash'] == raw_hash(bundle) and row['status'] == 'pending':
                        return self._project(row)
                    denied('Exact handoff replay or equivocation', 'exact_contract_replay')
                if row['nonce'] == h['nonce'] or row['intent_id'] == bundle['legacy_intent']['intent_id']:
                    denied('Exact handoff nonce or native proposal was already used', 'exact_contract_replay')
            if len(records) >= 256:
                denied('Exact private journal is full', 'exact_journal_full', 503)
            with StateDirectory(self.store.directory / 'exact-contract-bundles', create=True) as directory:
                filename = h['handoff_id'] + '.json'
                try:
                    prior = directory.read_bytes(filename, limit=MAX_DOCUMENT)
                except FileNotFoundError:
                    directory.write_bytes(filename, raw)
                else:
                    if prior != raw:
                        denied('Private exact handoff conflicts', 'exact_journal_tampered')
            row = {'handoff_id':h['handoff_id'],'intent_id':bundle['legacy_intent']['intent_id'],'bundle_hash':raw_hash(bundle),
                   'nonce':h['nonce'],'status':'pending','requirement':None,'ack':None,'facts':None,'run_id':None}
            records.append(row)
            return self._project(row)
        return self._update(admit)

    def list(self):
        return self._update(lambda rows: [self._project(row) for row in rows])

    def get(self, handoff_id):
        return self._update(lambda rows: self._project(self._find(rows, handoff_id)))

    @staticmethod
    def _project(row):
        return {key:row[key] for key in ('handoff_id','intent_id','status','requirement','run_id','bundle_hash')}

    def _preflight(self, bundle, requirement, *, review_revision=False):
        match = REQUIREMENT.fullmatch(requirement)
        if match is None or requirement not in {x['requirement'] for x in bundle['handoff']['requirements']}:
            denied('This requirement was not agreed', 'exact_requirement_mismatch')
        if not self.actor_id:
            denied('Existing local execution actor is not configured', 'exact_actor_unavailable', 503)
        current = SddExecutionContext.model_validate(self.sdd.execution_binding(match[1], match[2], actor_id=self.actor_id))
        expected = bundle['snapshot']
        revision_plan = None
        if (review_revision and current.contract.get('document_hash') != expected['frozen_contract'].get('document_hash')
                and expected['frozen_contract'].get('acceptance_scheme') is not None):
            from apatch_studio.exact_scheme_revision import review_revision as review_scheme
            try:
                current = SddExecutionContext.model_validate(review_scheme(self, bundle, requirement))
                revision_plan = current.contract['acceptance_scheme']
            except (ValueError, OSError):
                denied('The new agreed scheme could not be installed safely', 'exact_revision_unconfirmed')
        if (raw_canonical(current.contract) != raw_canonical(expected['frozen_contract'])
                or raw_canonical(current.task_envelope) != raw_canonical(expected['task_envelopes'][match[2]])):
            denied('The already frozen local contract is different', 'exact_local_contract_mismatch')
        with StateDirectory(self.workspace / 'docs' / 'specs') as directory:
            spec_bytes = directory.read_bytes(match[1] + '.md', limit=MAX_SPEC_BYTES)
        if 'sha256:' + hashlib.sha256(spec_bytes).hexdigest() != current.contract['spec_hash']:
            denied('The local SPEC changed', 'exact_judge_drift')
        native_requirement_refs(spec_bytes,requirement)
        by_id = {x['acceptance_id']:x for x in current.contract['obligations']}
        selected = [by_id[x] for x in current.task_envelope['checks']]
        environment = current.contract.get('judge_environment')
        if not isinstance(environment, dict) or set(environment) != {'cwd','env'} or environment['cwd'] != '.' or not isinstance(environment['env'], dict):
            denied('This native judge working directory is not supported', 'exact_judge_environment_unsupported')
        for obligation in selected:
            argv = obligation['command']
            if raw_hash(argv) != obligation['command_hash'] or argv not in current.task_envelope['commands']:
                denied('The agreed argv changed', 'exact_judge_drift')
            if len(argv) < 3 or argv[:2] != ['/usr/bin/env','-i']:
                denied('A clean exact native judge environment is required', 'exact_judge_environment_unsupported')
            variables, cursor = {}, 2
            while cursor < len(argv) and '=' in argv[cursor]:
                key, value = argv[cursor].split('=',1)
                if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key) or key in variables:
                    denied('The native judge environment is ambiguous', 'exact_judge_environment_unsupported')
                variables[key] = value
                cursor += 1
            if variables != environment['env'] or cursor == len(argv) or not Path(argv[cursor]).is_absolute():
                denied('The native argv does not implement its declared environment', 'exact_judge_environment_unsupported')
            if sorted(x['sha256'] for x in obligation['judge_assets']) != sorted(obligation['asset_hashes']):
                denied('The agreed judge asset map is incomplete', 'exact_judge_drift')
            for asset in obligation['judge_assets']:
                relative = Path(asset['path'])
                if relative.is_absolute() or '..' in relative.parts:
                    denied('The agreed judge asset path is invalid', 'exact_judge_drift')
                with StateDirectory(self.workspace / relative.parent) as directory:
                    data = directory.read_bytes(relative.name, limit=MAX_DOCUMENT)
                if revision_plan is not None and asset['path'] == 'acceptance/work-plan.json':
                    # The predecessor file was already verified. Review the
                    # incoming immutable plan in memory, before any write.
                    data = S.canonical_json(revision_plan).encode('utf-8')
                if 'sha256:' + hashlib.sha256(data).hexdigest() != asset['sha256']:
                    denied('An immutable local judge asset changed', 'exact_judge_drift')
        return current

    def _exchange(self, bundle, facts, change, acceptance, *, historical=False, original_ack=None, source_context=None):
        provider = self.gateway._workspace_key_provider()
        config = D.load_config(str(self.workspace))
        actor_keys = {G.signer_key_id(provider):provider.get_public_key()}
        change = G.validate_change(change, trusted_actor_keys=actor_keys)
        acceptance = W.validate_acceptance(acceptance)
        G.verify_document_signature(acceptance, actor_keys)
        if (acceptance['signature']['key_id'] != change['actor_key_id'] or acceptance['change_id'] != change['change_id']
                or acceptance['change_hash'] != G.document_hash(change)):
            denied('Native acceptance and request keys differ', 'exact_native_acceptance_failed')
        with StateDirectory(self.workspace / 'docs' / 'specs') as directory:
            spec_bytes = directory.read_bytes(change['spec_id'] + '.md',limit=MAX_SPEC_BYTES)
        raw_spec_hash = 'sha256:' + hashlib.sha256(spec_bytes).hexdigest()
        try:
            native_spec_hash = G.full_spec_hash(spec_bytes.decode('utf-8'))
        except UnicodeError:
            denied('The agreed SPEC is not exact UTF-8', 'exact_judge_drift')
        if (raw_spec_hash != bundle['snapshot']['frozen_contract']['spec_hash'] or facts['raw_spec_hash'] != raw_spec_hash
                or facts['native_spec_hash'] != native_spec_hash or change['spec_hash'] != native_spec_hash):
            denied('The same SPEC bytes do not match both owner and native pins', 'exact_judge_drift')
        if change['requirement_refs'] != native_requirement_refs(spec_bytes,facts['requirement']):
            denied('The native short requirement reference does not match the agreed SPEC', 'exact_native_requirement_mismatch')
        h = bundle['handoff']
        if not stamp(h['issued_at']) <= stamp(acceptance['accepted_at']) < stamp(h['expires_at']):
            denied('The native acceptance was outside the agreed admission lifetime', 'exact_native_acceptance_failed')
        revalidate = historical and self.clock() >= stamp(h['expires_at'])
        operation = 'exact-revalidations' if revalidate else 'exact-acceptances'
        path = f"/api/internal/client/project-groups/{h['project_group_id']}/work-items/{h['work_item_id']}/apatch-studio/{operation}"
        body = {'subject':config['client_id'],'tenant_id':h['tenant_id'],'handoff_id':h['handoff_id'],
            'exact_request_facts':facts,'proposal_acceptance':acceptance,'change':change,
            'spec_document_utf8_b64':base64.b64encode(spec_bytes).decode('ascii'),
            'idempotency_key':'exact-acceptance:' + raw_hash({'handoff_id':h['handoff_id'],'requirement':facts['requirement']})}
        if revalidate:
            if original_ack is None or source_context is None:
                denied('Historical evidence requires its original source acknowledgement', 'exact_source_ack_required')
            body.update(original_ack_hash=raw_hash(original_ack),source_binding_id=source_context.source_binding_id,
                        source_binding_hash=source_context.source_binding_hash)
        raw = raw_canonical(body)
        headers = {'Content-Type':'application/json','X-Apatch-Client-Id':config['client_id'],
            **T.signed_service_headers(str(self.workspace), method='POST', path=path, raw_body=raw,
                tenant_id=h['tenant_id'], subject=config['client_id'], expected_key_id=config['service_request_key_id'], key_provider=provider)}
        with self.http_client_factory() as client:
            response = client.post(config['platform_url'] + path, content=raw, headers=headers)
        if response.status_code not in (200,201):
            denied('Current agreed-contract acknowledgement was rejected', 'exact_current_authority_rejected', 502)
        ack = exact(response.json(), {'schema','native_binding','association'})
        if ack['schema'] != ACK_SCHEMA:
            denied('Exact acknowledgement shape is invalid', 'exact_ack_invalid')
        binding = W.validate_binding(ack['native_binding'], trusted_keys=config['binding_authority_keys'])
        association = exact(ack['association'], ASSOCIATION_KEYS)
        if association['schema'] != ASSOCIATION_SCHEMA:
            denied('Exact association shape is invalid', 'exact_ack_invalid')
        G.verify_platform_document_signature(association, self.trust.association_keys, purpose=BIND_PURPOSE)
        expected = {name:h[name] for name in ('handoff_id','contract_id','snapshot_hash','tenant_id','project_group_id','work_item_id',
            'work_program_id','work_program_hash','commissioner_principal_ref','performer_principal_ref','consents_hash','native_contract_hash')}
        expected.update(handoff_document_hash=G.document_hash(h),handoff_envelope_hash=G.envelope_hash(h),
            requirement=facts['requirement'],task_envelope_hash=facts['task_envelope_hash'],change_id=change['change_id'],
            change_hash=G.document_hash(change),native_binding_id=binding['binding_id'],native_binding_hash=G.document_hash(binding),
            exact_request_facts_hash=raw_hash(facts),accepted_at=acceptance['accepted_at'])
        expected.update(raw_spec_hash=raw_spec_hash,native_spec_hash=native_spec_hash)
        expected.update({name:binding[name] for name in ('accepted_work_item_hash','accepted_authority_version','current_work_item_hash','current_authority_version')})
        if any(association[name] != value for name,value in expected.items()) or not re.fullmatch(r'tcea_[0-9a-f]{32}',str(association['association_id'])):
            denied('Exact association changed an agreed or native pin', 'exact_ack_invalid')
        self.trust.validate_bundle(bundle, now=self.clock(), historical=historical)
        # All purpose/scope checks precede the native local write.
        if not revalidate:
            W.store_binding(str(self.workspace), binding=binding, acceptance=acceptance, change=change, trusted_keys=config['binding_authority_keys'])
        return ack

    def confirm(self, handoff_id, confirmation):
        # This original action is bounded private verification, not submission.
        if self.delivery.selected(handoff_id) is not None:
            denied('Use the explicit full-delivery action for this handoff', 'exact_delivery_action_required')
        return self._confirm(handoff_id, confirmation, for_delivery=False)

    def confirm_for_delivery(self, handoff_id, confirmation):
        selected = self.delivery.selected(handoff_id)
        existing = self._update(lambda rows: copy.deepcopy(self._find(rows, handoff_id)))
        if existing['status'] == 'consumed' and selected is None:
            denied('An earlier private verification cannot be retroactively turned into delivery', 'exact_delivery_action_required')
        result = self._confirm(handoff_id, confirmation, for_delivery=True)
        return self.delivery_projection(handoff_id)

    def delivery_projection(self, handoff_id):
        row = self._update(lambda rows: copy.deepcopy(self._find(rows, handoff_id)))
        attempt = self._delivery_attempt(row)
        selected = self.delivery.selected(handoff_id)
        context = None if selected is None else selected['context']
        return {'schema':'apatch.studio.exact-contract-delivery-view.v1','handoff_id':handoff_id,
            'run_id':None if attempt is None else attempt['run_id'],'requirement':row['requirement'],
            'status':'not_selected' if selected is None else ('pending_source_ack' if context is None else 'source_acknowledged'),
            'source_binding_id':None if context is None else context['source_binding_id'],
            'source_binding_hash':None if context is None else context['source_binding_hash'],
            'ready_for_publication':False,'customer_accepted':False}

    def delivery_choices(self, handoff_id):
        row = self._update(lambda rows: copy.deepcopy(self._find(rows, handoff_id)))
        bundle = self._read_bundle(row, historical=row['status'] == 'consumed')
        return {'schema':'apatch.studio.exact-contract-delivery-choices.v1','handoff_id':handoff_id,
            'workspace_id':self.workspace_id,'action':'confirm_for_delivery',
            'requirements':copy.deepcopy(bundle['handoff']['requirements'])}

    def _delivery_attempt(self, row):
        """Follow persisted genuine retry edges; keep the original admission fixed.

        Matching intent alone is insufficient. Every retry must preserve the
        entire external/native context and descend from a retryable attempt.
        Branches are ambiguous and require review rather than arbitrary choice.
        """
        if row['run_id'] is None:
            return None
        first = self.run_manager.get(row['run_id'])
        lineage = {first['run_id']: first}
        remaining = {run['run_id']: run for run in self.run_manager.list()
            if run['run_id'] != first['run_id']}
        while True:
            children = [run for run in remaining.values() if run.get('retry_of') in lineage]
            if not children:
                break
            for run in children:
                parent = lineage[run['retry_of']]
                retryable = (parent['status'] in ('failed', 'cancelled', 'interrupted')
                    or (parent['status'] == 'succeeded' and parent.get('can_retry') is True
                        and parent.get('contribution') is None))
                if (not retryable
                        or any(run.get(key) != first.get(key) for key in
                            ('mode', 'runner', 'execution_context', 'execution_contract'))):
                    denied('Delivery retry changed its admitted context', 'exact_delivery_run_incomplete')
                lineage[run['run_id']] = run
                remaining.pop(run['run_id'])
        parents = {run.get('retry_of') for run in lineage.values()}
        leaves = [run for identity, run in lineage.items() if identity not in parents]
        if len(leaves) != 1:
            denied('Delivery retry lineage is ambiguous', 'exact_delivery_run_incomplete')
        return leaves[0]

    def build_for_delivery(self, handoff_id, run_id):
        row = self._update(lambda rows: copy.deepcopy(self._find(rows, handoff_id)))
        run = self._delivery_attempt(row)
        if row['status'] != 'consumed' or run is None or run['run_id'] != run_id:
            denied('The selected full-delivery run does not match this handoff', 'exact_delivery_run_incomplete')
        if run['status'] != 'succeeded':
            denied('The exact full-delivery run has not succeeded', 'exact_delivery_run_incomplete')
        context = self.delivery.selected(handoff_id)
        if context is None or context['context'] is None:
            denied('This run has no full-delivery acknowledgement', 'exact_source_ack_required')
        bundle = self._read_bundle(row, historical=True)
        sdd = self._preflight(bundle,row['requirement'])
        proposal = bundle['legacy_intent']
        external = ExecutionContext(**{name:proposal[name] for name in ('intent_id','tenant_id','project_group_id','work_item_id',
            'work_item_hash','authority_version','work_program_id','work_program_hash')},
            document_hash=G.document_hash(proposal),envelope_hash=G.envelope_hash(proposal))
        current = self.guard_execution(AgentRunRequest(mode='requirement',runner=run['runner'],objective='Build selected evidence',
            spec_id=sdd.spec_id,requirement_id=sdd.requirement_id),external,sdd,stage='build_evidence')
        if current is None:
            denied('The exact source lineage is unavailable', 'exact_source_ack_required')
        built = G.build_workspace_evidence(str(self.workspace),binding_id=current.source_binding_id,
            key_provider=self.gateway._workspace_key_provider(),issued_at=self.delivery.evidence_time(handoff_id))
        if built['change_id'] != current.change_id or built['change_hash'] != current.change_hash:
            denied('Native evidence belongs to another Change', 'exact_source_ack_invalid')
        return {'schema':'apatch.studio.exact-contract-evidence-ready.v1','handoff_id':handoff_id,'run_id':run_id,
            'source_binding_id':current.source_binding_id,'source_binding_hash':current.source_binding_hash,
            'change_id':current.change_id,'change_hash':current.change_hash,
            'evidence_bundle_hash':built['evidence_bundle_hash'],'timesheet_hash':built['timesheet_hash'],
            'attestation_count':built['attestation_count'],'contribution_event_count':built['contribution_event_count'],
            'ready_for_publication':True,'customer_accepted':False}

    def _confirm(self, handoff_id, confirmation, *, for_delivery):
        if confirmation.workspace_id != self.workspace_id:
            denied('A different workspace was selected', 'workspace_identity_mismatch')
        def begin(rows):
            row = self._find(rows, handoff_id)
            if row['status'] == 'consumed':
                if row['requirement'] != confirmation.requirement or self.run_manager.get(row['run_id'])['runner'] != confirmation.runner_id:
                    denied('Exact confirmation replay changed its choice', 'exact_contract_replay')
                return copy.deepcopy(row)
            if row['status'] != 'pending':
                denied('Exact dispatch is already inflight or requires review', 'exact_contract_replay')
            row['status'], row['requirement'] = 'consuming', confirmation.requirement
            return copy.deepcopy(row)
        row = self._update(begin)
        if row['status'] == 'consumed':
            return self._project(row)
        try:
            # No local acceptance or profile read follows an existing native
            # disconnect fence; the provider is the already enrolled identity.
            provider = self.gateway._workspace_key_provider()
            bundle = self._read_bundle(row)
            sdd = self._preflight(bundle, confirmation.requirement, review_revision=True)
            if for_delivery and 'apatch_attest' not in sdd.task_envelope['tools']:
                denied('The agreed envelope does not authorize an attested delivery cycle', 'exact_delivery_contract_required')
            h, proposal = bundle['handoff'], bundle['legacy_intent']
            accepted = M.accept_execution_proposal(str(self.workspace), proposal=proposal,
                confirmation=f"{proposal['work_item_id']}:{proposal['authority_version']}", spec_id=sdd.spec_id,
                requirement_ids=[sdd.requirement_id], purpose=native_acceptance_purpose(confirmation.requirement, h['handoff_id']),
                queue_source_binding=False, request_key_provider=provider, now=self.clock())
            if accepted.get('ok') is not True or accepted.get('work_started') is not False:
                denied('Native acceptance is unavailable', 'exact_native_acceptance_failed')
            change, acceptance = accepted['change'], accepted['proposal_acceptance']
            facts = {'schema':FACTS_SCHEMA, **{name:h[name] for name in ('handoff_id','contract_id','snapshot_hash','tenant_id',
                'project_group_id','work_item_id','work_program_id','work_program_hash','native_contract_hash')},
                'handoff_document_hash':G.document_hash(h),'handoff_envelope_hash':G.envelope_hash(h),
                'requirement':confirmation.requirement,'task_envelope_hash':sdd.envelope_hash,
                'change_id':change['change_id'],'change_hash':G.document_hash(change),
                'raw_spec_hash':sdd.contract['spec_hash'],'native_spec_hash':change['spec_hash'],
                'proposal_acceptance_hash':G.envelope_hash(acceptance),'accepted_at':acceptance['accepted_at']}
            ack = self._exchange(bundle, facts, change, acceptance)
            local = self.sdd.execution_binding(sdd.spec_id, sdd.requirement_id, actor_id=self.actor_id)
            if local['contract_hash'] != sdd.contract_hash:
                from apatch_studio.exact_scheme_revision import install_revision
                install_revision(self, bundle, confirmation.requirement, association=ack['association'])
                self._preflight(bundle, confirmation.requirement)
            def record_ack(rows):
                current = self._find(rows,handoff_id)
                if current['status'] != 'consuming' or current['requirement'] != confirmation.requirement:
                    denied('Exact dispatch state changed', 'exact_journal_conflict')
                if current['ack'] is not None and raw_canonical(current['ack']) != raw_canonical(ack):
                    denied('Exact association equivocation', 'exact_ack_invalid')
                current['ack'], current['facts'] = ack, facts
            self._update(record_ack)
            if for_delivery:
                row['ack'],row['facts'] = ack,facts
                self.delivery.prepare(row,change,ack)
            context = ExecutionContext(**{name:proposal[name] for name in ('intent_id','tenant_id','project_group_id','work_item_id',
                'work_item_hash','authority_version','work_program_id','work_program_hash')},
                document_hash=G.document_hash(proposal),envelope_hash=G.envelope_hash(proposal))
            run = self.run_manager.start(AgentRunRequest(mode='requirement', runner=confirmation.runner_id,
                objective=proposal['objective'],spec_id=sdd.spec_id,requirement_id=sdd.requirement_id),
                execution_context=context,sdd_execution=sdd)
            if not isinstance(run.get('run_id'), str):
                denied('Native dispatch has no retained run identity', 'exact_dispatch_uncertain')
        except Exception:
            self._reconcile(handoff_id=handoff_id, restore_if_absent=True)
            raise
        def consume(rows):
            current = self._find(rows,handoff_id)
            current['status'], current['run_id'] = 'consumed', run['run_id']
            return self._project(current)
        return self._update(consume)

    def guard_execution(self, request, execution_context, sdd_execution, *, stage):
        if execution_context is None:
            return
        self.gateway._workspace_key_provider()
        rows = self._update(lambda rows: copy.deepcopy(rows))
        matches = [row for row in rows if row['intent_id'] == execution_context.intent_id]
        if not matches:
            return self.gateway.guard_execution(request, execution_context, sdd_execution, stage=stage)
        if len(matches) != 1:
            denied('Exact private association is ambiguous', 'exact_ack_invalid')
        row = matches[0]
        if row['status'] not in ('consuming','consumed') or row['ack'] is None or row['facts'] is None:
            denied('Exact association was not acknowledged', 'exact_ack_required')
        if request.mode != 'requirement' or sdd_execution is None:
            denied('Exact work requires the genuine native requirement context', 'exact_requirement_context_required')
        historical = stage == 'build_evidence'
        if historical:
            attempt = self._delivery_attempt(row)
            if attempt is None or attempt['status'] != 'succeeded':
                denied('Historical evidence requires a successful admitted attempt', 'exact_delivery_run_incomplete')
        bundle = self._read_bundle(row, historical=historical)
        current = self._preflight(bundle,row['requirement'])
        if (raw_canonical(current.model_dump()) != raw_canonical(sdd_execution.model_dump())
                or request.spec_id != current.spec_id or request.requirement_id != current.requirement_id):
            denied('Native dispatch context changed', 'exact_local_contract_mismatch')
        proposal = bundle['legacy_intent']
        if any(getattr(execution_context,name) != proposal[name] for name in ('intent_id','tenant_id','project_group_id','work_item_id',
            'work_item_hash','authority_version','work_program_id','work_program_hash')) or execution_context.document_hash != G.document_hash(proposal) or execution_context.envelope_hash != G.envelope_hash(proposal):
            denied('External dispatch context changed', 'exact_ack_invalid')
        change = G.load_change(str(self.workspace),row['facts']['change_id'])
        acceptance = W.validate_acceptance(read_json(P.acceptance_path(str(self.workspace),change['change_id']),limit=MAX_DOCUMENT))
        source_context = (self.delivery.guard_context(row,change,row['ack'])
                          if historical and self.clock() >= stamp(bundle['handoff']['expires_at']) else None)
        ack = self._exchange(bundle,row['facts'],change,acceptance,historical=historical,
                             original_ack=row['ack'],source_context=source_context)
        if raw_canonical(ack) != raw_canonical(row['ack']):
            denied('Exact association changed after admission', 'exact_ack_invalid')
        # Network latency must not open a local file-drift window before Popen.
        after_ack = self._preflight(bundle,row['requirement'])
        if raw_canonical(after_ack.model_dump()) != raw_canonical(current.model_dump()):
            denied('The native context changed during authority refresh', 'exact_local_contract_mismatch')
        self.trust.validate_bundle(bundle, now=self.clock(), historical=historical)
        return self.delivery.guard_context(row,change,ack)

    def _reconcile(self, *, handoff_id=None, restore_if_absent=False):
        runs = self.run_manager.list()
        def reconcile(rows):
            for row in rows:
                if row['status'] != 'consuming' or (handoff_id and row['handoff_id'] != handoff_id):
                    continue
                matching_intents = [run for run in runs if (run.get('execution_context') or {}).get('intent_id') == row['intent_id']]
                found = []
                if row['ack'] is not None and row['facts'] is not None:
                    for run in matching_intents:
                        native = run.get('execution_contract') or {}
                        if (run.get('mode') == 'requirement' and native.get('contract_hash') == row['facts']['native_contract_hash']
                                and native.get('envelope_hash') == row['facts']['task_envelope_hash']
                                and native.get('spec_id','') + '#' + native.get('requirement_id','') == row['requirement']):
                            found.append(run)
                if len(found) == 1:
                    row['status'],row['run_id'] = 'consumed',found[0]['run_id']
                elif not matching_intents and restore_if_absent:
                    row['status'] = 'pending'
                else:
                    row['status'] = 'manual_review'
        self._update(reconcile)
