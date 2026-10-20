"""Explicit full-delivery bridge, preserving Core's closed v1 documents.

Canonical assignment and separately signed program-source receipt are two
different authorities. They join only through the same exact signed Change.
No identifier conversion or synthetic source receipt is accepted here.
"""
from __future__ import annotations

import copy
from datetime import timezone
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from apatch import governed_work as G
from apatch import governed_work_delivery as D
from apatch import work_item_acceptance as W
from apatch_studio.state_io import StateDirectory
from apatch_studio.selected_governed_work_delivery import dispatch_selected, SelectedDeliveryError

HASH = r'^sha256:[0-9a-f]{64}$'
JOURNAL = 'exact-contract-delivery.json'
SCHEMA = 'apatch.studio.exact-contract-delivery-journal.v1'


def denied(message, code='exact_delivery_invalid'):
    from apatch_studio.execution_intents import ExecutionIntentError
    raise ExecutionIntentError(message, code=code, status_code=409)


class SourceBoundExecutionContext(BaseModel):
    """Private verified lineage returned only by the authority dispatch guard."""

    model_config = ConfigDict(extra='forbid', frozen=True)
    schema: Literal['apatch.studio.source-bound-execution.v1'] = 'apatch.studio.source-bound-execution.v1'
    handoff_id: str = Field(pattern=r'^tceh_[0-9a-f]{32}$')
    tenant_id: str
    project_group_id: str = Field(pattern=r'^tcpg_[0-9a-f]{32}$')
    work_item_id: str = Field(pattern=r'^tcpwi_[0-9a-f]{32}$')
    change_id: str = Field(pattern=r'^apchg_[0-9a-f]{32}$')
    change_hash: str = Field(pattern=HASH)
    canonical_binding_id: str = Field(pattern=r'^tcawieb_[0-9a-f]{32}$')
    canonical_binding_hash: str = Field(pattern=HASH)
    canonical_binding_envelope_hash: str = Field(pattern=HASH)
    association_id: str = Field(pattern=r'^tcea_[0-9a-f]{32}$')
    association_hash: str = Field(pattern=HASH)
    association_envelope_hash: str = Field(pattern=HASH)
    source_binding_id: str = Field(pattern=r'^tcpsb_[0-9a-f]{32}$')
    source_binding_hash: str = Field(pattern=HASH)
    source_binding_envelope_hash: str = Field(pattern=HASH)
    requirement: str = Field(pattern=r'^SPEC-[A-Z0-9][A-Z0-9-]*#R[0-9]+$')
    contract_hash: str = Field(pattern=HASH)
    task_envelope_hash: str = Field(pattern=HASH)
    artifacts: tuple[str, ...]


class EvidenceBuildRequest(BaseModel):
    model_config = ConfigDict(extra='forbid', frozen=True)
    confirmed: Literal[True]
    run_id: str = Field(pattern=r'^apr_[0-9a-f]{32}$')


class ExactContractDelivery:
    def __init__(self, manager):
        self.manager = manager

    @staticmethod
    def _validate(document):
        if (not isinstance(document, dict) or set(document) != {'schema', 'records'}
                or document['schema'] != SCHEMA or not isinstance(document['records'], list)
                or len(document['records']) > 256):
            denied('Full-delivery journal is invalid')
        seen = set()
        for row in document['records']:
            if (not isinstance(row,dict) or set(row) != {'handoff_id','requirement','context','evidence_issued_at'}
                    or row['handoff_id'] in seen):
                denied('Full-delivery journal is invalid')
            seen.add(row['handoff_id'])
            if row['context'] is not None:
                context = SourceBoundExecutionContext.model_validate(row['context'])
                if context.handoff_id != row['handoff_id'] or context.requirement != row['requirement']:
                    denied('Full-delivery journal has changed its lineage')
            if row['evidence_issued_at'] is not None:
                G._timestamp(row['evidence_issued_at'],'evidence_issued_at')
        return document

    def _read(self):
        with self.manager.store._transaction():
            with StateDirectory(self.manager.store.directory, create=True) as directory:
                try:
                    document = directory.read_json(JOURNAL, limit=2 * 1024 * 1024)
                except FileNotFoundError:
                    return {'schema': SCHEMA, 'records': []}
        return self._validate(document)

    def _write(self, record):
        with self.manager.store._transaction():
            with StateDirectory(self.manager.store.directory, create=True) as directory:
                try:
                    document = directory.read_json(JOURNAL, limit=2 * 1024 * 1024)
                except FileNotFoundError:
                    document = {'schema': SCHEMA, 'records': []}
                self._validate(document)
                matches = [i for i, row in enumerate(document['records']) if row['handoff_id'] == record['handoff_id']]
                if len(matches) > 1:
                    denied('Full-delivery journal has ambiguous lineage')
                if matches:
                    old = document['records'][matches[0]]
                    if old['requirement'] != record['requirement']:
                        denied('Full-delivery replay changed its requirement')
                    if old.get('context') is not None and old != record:
                        denied('Full-delivery replay changed its exact receipts')
                    document['records'][matches[0]] = copy.deepcopy(record)
                else:
                    document['records'].append(copy.deepcopy(record))
                self._validate(document)
                directory.write_json(JOURNAL, document)

    def selected(self, handoff_id):
        matches = [row for row in self._read()['records'] if row['handoff_id'] == handoff_id]
        if len(matches) > 1:
            denied('Full-delivery journal has ambiguous lineage')
        return copy.deepcopy(matches[0]) if matches else None

    def prepare(self, row, change, ack):
        manager = self.manager
        requirement = row['requirement']
        record = {'handoff_id': row['handoff_id'], 'requirement': requirement, 'context': None, 'evidence_issued_at': None}
        prior = self.selected(row['handoff_id'])
        if prior is None:
            self._write(record)
        elif prior['requirement'] != requirement:
            denied('Full-delivery replay changed its requirement')
        else:
            record['evidence_issued_at'] = prior.get('evidence_issued_at')
        config = D.load_config(str(manager.workspace))
        # Existing native immutable queue and ACK validator, not private HTTP
        # or a rewritten canonical receipt. Queuing alone never admits work.
        provider = manager.gateway._workspace_key_provider()
        queued = D.queue_source_binding_request(str(manager.workspace), change=change, client_id=config['client_id'])
        def guard_current():
            manager._preflight(manager._read_bundle(row), requirement)
            if D.load_config(str(manager.workspace)) != config:
                denied('The full-delivery connection changed', 'exact_source_ack_invalid')
        def guard_response(reply):
            guard_current()
            source = G.validate_project_source_binding(reply, change=change,
                trusted_authority_keys=config['binding_authority_keys'])
            if source['actor_ref'] != ack['native_binding']['actor_ref']:
                denied('Source acknowledgement belongs to another performer', 'exact_source_ack_invalid')
        try:
            result = dispatch_selected(str(manager.workspace),entry_id=queued['entry_id'],request_hash=queued['request_hash'],
                key_provider=provider,expected_scope={'command':'source_binding','tenant_id':change['tenant_id'],
                    'project_group_id':change['project_group_id'],'client_id':config['client_id']},
                context_guard=guard_current,response_guard=guard_response,http_client_factory=manager.http_client_factory)
        except SelectedDeliveryError:
            denied('The selected native source delivery changed or is unsupported', 'exact_source_ack_invalid')
        if result.get('ok') is not True:
            denied('The separate source acknowledgement is unavailable or rejected', 'exact_source_ack_required')
        source = self._find_source(change, ack, config)
        if source is None:
            denied('The separate source acknowledgement is still pending', 'exact_source_ack_required')
        context = self._context(row, change, ack, source)
        record['context'] = context.model_dump(mode='json')
        self._write(record)
        return context

    def _find_source(self, change, ack, config):
        root = G.governed_work_root(str(self.manager.workspace)) / 'bindings'
        matches = []
        if root.is_dir():
            for path in sorted(root.glob('tcpsb_*.json')):
                source = G.load_project_source_binding(str(self.manager.workspace), path.stem)
                if source.get('change_id') != change['change_id']:
                    continue
                source = G.validate_project_source_binding(source, change=change,
                    trusted_authority_keys=config['binding_authority_keys'])
                if source['actor_ref'] != ack['native_binding']['actor_ref']:
                    denied('Source acknowledgement belongs to another performer', 'exact_source_ack_invalid')
                matches.append(source)
        if len(matches) > 1:
            denied('Source acknowledgement is ambiguous', 'exact_source_ack_invalid')
        return matches[0] if matches else None

    def _context(self, row, change, ack, source):
        binding, association = ack['native_binding'], ack['association']
        if (association['native_binding_id'] != binding['binding_id']
                or association['native_binding_hash'] != G.document_hash(binding)
                or association['change_id'] != change['change_id']
                or association['change_hash'] != G.document_hash(change)
                or source['change_id'] != change['change_id']
                or source['change_hash'] != G.document_hash(change)):
            denied('The exact association and source acknowledgement do not join the same Change')
        ref = next((ref for ref in change['requirement_refs'] if ref['requirement_id'] == row['requirement'].split('#')[1]), None)
        if ref is None:
            denied('The exact selected requirement is absent from the Change')
        artifacts = (
            G.source_binding_artifact(source),
            f"spec:{change['spec_id']}#{ref['requirement_id']}@{ref['requirement_hash']}",
            f"cowork-exact-association:{association['association_id']}@{G.document_hash(association)}",
            f"work-item-execution-binding:{binding['binding_id']}@{G.document_hash(binding)}",
        )
        return SourceBoundExecutionContext(handoff_id=row['handoff_id'], tenant_id=change['tenant_id'],
            project_group_id=change['project_group_id'], work_item_id=binding['work_item_id'],
            change_id=change['change_id'], change_hash=G.document_hash(change),
            canonical_binding_id=binding['binding_id'], canonical_binding_hash=G.document_hash(binding),
            canonical_binding_envelope_hash=G.envelope_hash(binding), association_id=association['association_id'],
            association_hash=G.document_hash(association), association_envelope_hash=G.envelope_hash(association),
            source_binding_id=source['binding_id'], source_binding_hash=G.document_hash(source),
            source_binding_envelope_hash=G.envelope_hash(source), requirement=row['requirement'],
            contract_hash=association['native_contract_hash'], task_envelope_hash=association['task_envelope_hash'],
            artifacts=artifacts)

    def guard_context(self, row, change, ack):
        selected = self.selected(row['handoff_id'])
        if selected is None:
            return None  # existing private verification flow, no delivery claim
        if selected['context'] is None:
            denied('Full delivery has no separately acknowledged source', 'exact_source_ack_required')
        retained = SourceBoundExecutionContext.model_validate(selected['context'])
        config = D.load_config(str(self.manager.workspace))
        W.validate_binding(ack['native_binding'], trusted_keys=config['binding_authority_keys'])
        source = self._find_source(change, ack, config)
        if source is None:
            denied('The retained source acknowledgement is missing', 'exact_source_ack_required')
        current = self._context(row, change, ack, source)
        if current != retained:
            denied('Full-delivery signed receipt or native lineage changed', 'exact_source_ack_invalid')
        return current

    def evidence_time(self, handoff_id):
        # Keep the first actual evidence-build time stable across retries. Never
        # backdate evidence to the earlier handoff or rewrite signed v1 files.
        with self.manager.store._transaction():
            with StateDirectory(self.manager.store.directory, create=True) as directory:
                journal = directory.read_json(JOURNAL, limit=2 * 1024 * 1024)
                self._validate(journal)
                matches = [row for row in journal['records'] if row['handoff_id'] == handoff_id]
                if len(matches) != 1 or matches[0]['context'] is None:
                    denied('No source-bound delivery exists')
                row = matches[0]
                if row.get('evidence_issued_at') is None:
                    row['evidence_issued_at'] = self.manager.clock().astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00','Z')
                    directory.write_json(JOURNAL,journal)
                return row['evidence_issued_at']
