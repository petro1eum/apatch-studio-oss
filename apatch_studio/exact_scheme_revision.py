"""Install only the exact scheme revision in an explicitly confirmed handoff.

The signed Platform handoff supplies both current consents. This adapter never
approves work, changes a test, renews an old run's budget or edits its evidence.
"""
from __future__ import annotations

import copy
import hashlib

from apatch import sdd_integrity as S
from apatch_studio.state_io import StateDirectory

PLAN_PATH = 'acceptance/work-plan.json'


def _seal(value):
    body = {k: v for k, v in value.items() if k != 'document_hash'}
    return {**body, 'document_hash': S.canonical_hash(body)}


def validate_revision(previous, previous_envelopes, candidate, envelopes, source_plan):
    """Independent exact delta check over the existing native v1 format."""
    S.validate_native_snapshot(previous, previous_envelopes)
    S.validate_native_snapshot(candidate, envelopes)
    plan = candidate.get('acceptance_scheme')
    if not isinstance(plan, dict) or candidate.get('supersedes_hash') != previous['document_hash']:
        raise ValueError('The revision must name its current frozen predecessor')
    expected = copy.deepcopy(previous)
    expected.update(supersedes_hash=previous['document_hash'], plan_hash=S.canonical_hash(plan), acceptance_scheme=plan)
    for check in expected['obligations']:
        if sum(a['path'] == PLAN_PATH for a in check['judge_assets']) != 1:
            raise ValueError('The previous checks must all pin the plan')
        for asset in check['judge_assets']:
            if asset['path'] == PLAN_PATH:
                asset['sha256'] = S.canonical_hash(plan)
        check['asset_hashes'] = [a['sha256'] for a in check['judge_assets']]
    expected = _seal(expected)
    exact_envelopes = {rk: _seal({**env, 'contract_hash': expected['document_hash']})
                       for rk, env in previous_envelopes.items()}
    if candidate != expected or envelopes != exact_envelopes:
        raise ValueError('A scheme revision cannot change tests, scope, budgets or the baseline')
    # Use the runtime's actual graph validator, not executable conditions.
    from apatch_studio.exact_scheme_validation import validate_plan_delta
    validate_plan_delta(source_plan, plan, previous_envelopes)
    return plan


def _review_inputs(manager, bundle, requirement):
    snapshot = bundle['snapshot']
    candidate, envelopes = snapshot['frozen_contract'], snapshot['task_envelopes']
    spec, rk = requirement.split('#')
    if any(r['status'] in {'queued', 'running', 'cancelling', 'starting'} for r in manager.run_manager.list()):
        raise ValueError('A running task must finish before changing the current execution profile')
    current = manager.sdd.execution_binding(spec, rk, actor_id=manager.actor_id)
    previous = current['contract']
    previous_envelopes = {name: manager.sdd.execution_binding(spec, name, actor_id=manager.actor_id)['task_envelope']
                          for name in envelopes}
    import json
    with StateDirectory(manager.workspace / 'acceptance') as directory:
        source_bytes = directory.read_bytes('work-plan.json', limit=1_048_576)
    plan = validate_revision(previous, previous_envelopes, candidate, envelopes, json.loads(source_bytes))
    for check in previous['obligations']:
        for asset in check['judge_assets']:
            parent, _, filename = asset['path'].rpartition('/')
            with StateDirectory(manager.workspace / parent) as directory:
                data = directory.read_bytes(filename, limit=1_048_576)
            if 'sha256:' + hashlib.sha256(data).hexdigest() != asset['sha256']:
                raise ValueError('An existing immutable asset changed')
    with StateDirectory(manager.workspace / 'docs/specs') as directory:
        spec_bytes = directory.read_bytes(spec + '.md', limit=1_048_576)
    if 'sha256:' + hashlib.sha256(spec_bytes).hexdigest() != previous['spec_hash']:
        raise ValueError('The existing SPEC changed')
    return current, previous_envelopes, plan, source_bytes


def review_revision(manager, bundle, requirement):
    """Review the incoming profile without installing it or asserting identity."""
    spec, rk = requirement.split('#')
    with manager.run_manager._lock, manager.sdd._freeze_lock:
        current, _, _, _ = _review_inputs(manager, bundle, requirement)
        candidate = bundle['snapshot']['frozen_contract']
        envelope = bundle['snapshot']['task_envelopes'][rk]
        S.issue_capability(candidate, envelope, actor_id=manager.actor_id, role='implementation')
        return {**current, 'contract': candidate, 'task_envelope': envelope,
                'contract_hash': candidate['document_hash'], 'envelope_hash': envelope['document_hash']}


def install_revision(manager, bundle, requirement, *, association):
    """Install only after Platform verifies the enrolled key's actual performer.

    The Studio process actor is a local execution role, not an SSO principal.
    A purpose-verified fresh ACK bridges those identities; a local name cannot.
    """
    from apatch import governed_work as G
    from apatch_studio.exact_contract_handoffs import BIND_PURPOSE
    G.verify_platform_document_signature(association, manager.trust.association_keys, purpose=BIND_PURPOSE)
    h = bundle['handoff']
    expected = {name: h[name] for name in ('handoff_id', 'contract_id', 'snapshot_hash',
        'tenant_id', 'project_group_id', 'work_item_id', 'work_program_id', 'work_program_hash',
        'commissioner_principal_ref', 'performer_principal_ref', 'consents_hash', 'native_contract_hash')}
    expected.update(handoff_document_hash=G.document_hash(h), handoff_envelope_hash=G.envelope_hash(h),
        requirement=requirement,
        task_envelope_hash=bundle['snapshot']['task_envelopes'][requirement.split('#')[1]]['document_hash'])
    if any(association.get(name) != value for name, value in expected.items()):
        raise ValueError('The acknowledged performer or agreed revision changed')
    snapshot = bundle['snapshot']
    candidate, envelopes = snapshot['frozen_contract'], snapshot['task_envelopes']
    spec, rk = requirement.split('#')
    with manager.run_manager._lock, manager.sdd._freeze_lock:
        current, previous_envelopes, plan, source_bytes = _review_inputs(manager, bundle, requirement)
        previous = current['contract']
        import json
        # StateDirectory rejects symlinks/unsafe ancestry and writes atomically.
        writes = [(PLAN_PATH, S.canonical_json(plan).encode('utf-8'))]
        encoded = lambda d: (json.dumps(d, sort_keys=True, ensure_ascii=False, separators=(',', ':')) + '\n').encode()
        writes += [(str(manager.sdd._envelope_path(spec, name).relative_to(manager.workspace)), encoded(env))
                   for name, env in envelopes.items()]
        writes += [('.apatch/sdd_verification_contract.json', encoded(candidate))]
        before = []
        expected_documents = {PLAN_PATH: json.loads(source_bytes), '.apatch/sdd_verification_contract.json': previous,
            **{str(manager.sdd._envelope_path(spec, name).relative_to(manager.workspace)):env for name,env in previous_envelopes.items()}}
        for path, _ in writes:
            parent, _, filename = path.rpartition('/')
            with StateDirectory(manager.workspace / parent) as directory:
                raw = directory.read_bytes(filename, limit=1_048_576)
                if json.loads(raw) != expected_documents[path]:
                    raise ValueError('The reviewed local inputs changed')
                before.append((path, raw))
        with StateDirectory(manager.workspace / '.apatch/sdd/frozen', create=True) as directory:
            for doc in (previous, candidate):
                filename = doc['document_hash'].split(':', 1)[1] + '.json'
                try:
                    existing = directory.read_json(filename)
                except FileNotFoundError:
                    directory.write_json(filename, doc)
                else:
                    if existing != doc:
                        raise ValueError('An archived frozen version changed')
        written = []
        try:
            for path, data in writes:
                parent, _, filename = path.rpartition('/')
                with StateDirectory(manager.workspace / parent) as directory:
                    if directory.read_bytes(filename, limit=1_048_576) != dict(before)[path]:
                        raise ValueError('The reviewed local inputs changed before installation')
                    directory.write_bytes(filename, data)
                written.append(path)
            return manager.sdd.execution_binding(spec, rk, actor_id=manager.actor_id)
        except Exception:
            for path, data in reversed(before):
                if path in written:
                    parent, _, filename = path.rpartition('/')
                    with StateDirectory(manager.workspace / parent) as directory:
                        if directory.read_bytes(filename, limit=1_048_576) == dict(writes)[path]:
                            directory.write_bytes(filename, data)
            raise
