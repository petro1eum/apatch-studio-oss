"""Release wiring: real app starts; explicit public pins reach the CLI."""
import base64
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from apatch_studio.cli import _parser
from apatch_studio.exact_contract_handoffs import ExactContractTrust
from apatch_studio.execution_intents import ExecutionIntentError


def test_exact_public_pins_load_from_cli_path(tmp_path):
    public = bytes(range(32))
    key_id = 'sha256:' + hashlib.sha256(public).hexdigest()
    keys = {key_id: base64.urlsafe_b64encode(public).decode().rstrip('=')}
    path = tmp_path / 'public-pins.json'
    path.write_text(json.dumps({
        'schema': 'apatch.studio.exact-contract-trust.v1',
        'trusted_origins': ['https://trust-chain.ai'],
        'handoff_keys': keys, 'association_keys': keys, 'legacy_keys': keys,
    }))
    args = _parser().parse_args(['serve', '--workspace', str(tmp_path),
                               '--exact-contract-trust-file', str(path)])
    trust = ExactContractTrust.from_path(args.exact_contract_trust_file)
    assert trust.trusted_origins == frozenset({'https://trust-chain.ai'})
    assert trust.handoff_keys == {key_id: public}


@pytest.mark.parametrize('content', [None, '{}', 'not json'])
def test_missing_or_invalid_pins_never_enable_import(tmp_path, content):
    path = tmp_path / 'pins.json'
    if content is not None:
        path.write_text(content)
    with pytest.raises(ExecutionIntentError) as error:
        ExactContractTrust.from_path(path)
    assert error.value.code == 'exact_authority_unconfigured'
    assert error.value.status_code == 503


def test_optional_amendment_missing_does_not_break_studio(monkeypatch, tmp_path):
    # No fake Core module is supplied: the missing optional capability must
    # remain a refusal while unrelated app routes continue working.
    monkeypatch.setitem(sys.modules, 'apatch.sdd_successor', None)
    from apatch_studio.app import create_app
    from fastapi.testclient import TestClient
    subprocess.run(['git', 'init', '-q', str(tmp_path)], check=True)
    frontend = tmp_path / 'web'
    (frontend / 'assets').mkdir(parents=True)
    (frontend / 'assets/app.js').write_text('/* transport test */')
    (frontend / 'theme-init.js').write_text('/* transport test */')
    (frontend / 'index.html').write_text(
        '<meta content="__APATCH_STUDIO_SESSION__"><script src="/theme-init.js"></script>'
        '<script src="/assets/app.js"></script>')
    app = create_app(str(tmp_path), frontend_root=frontend)
    with TestClient(app, base_url='http://127.0.0.1:8765') as client:
        assert client.get('/api/v1/health').status_code == 200
        headers = {'x-apatch-studio-session': app.state.studio_guard.token}
        denied = client.get('/api/v1/exact-contract-handoffs', headers=headers)
        assert denied.status_code == 503
    assert not (tmp_path / 'not-created.json').exists()


def test_signed_bundle_crosses_real_http_import_once_without_starting_run(tmp_path):
    """Independent TEST-ONLY issuers; actual signature checks, journal and ASGI."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from fastapi.testclient import TestClient
    from apatch import execution_proposal as P, governed_work as G
    from apatch_studio.app import create_app
    from apatch_studio.exact_contract_handoffs import (
        ExactContractManager, raw_canonical, raw_hash, ISSUE_PURPOSE,
    )
    from apatch_studio.security import StudioRequestGuard

    corpus = json.loads((Path(__file__).parent / 'fixtures/sdd_wire_v1.json').read_text())
    native = deepcopy(next(case for case in corpus['cases'] if case['valid']))
    contract, envelopes = native['contract'], native['envelopes']
    now = datetime.now(timezone.utc)
    stamp = lambda value: value.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    handoff_key, association_key, legacy_key = [Ed25519PrivateKey.generate() for _ in range(3)]
    def public_map(key):
        public = key.public_key().public_bytes_raw()
        return {'ed25519:sha256:' + hashlib.sha256(public).hexdigest(): public}
    def sign(body, key, purpose):
        return {**body, 'signature': {'algorithm': 'Ed25519', 'key_id': next(iter(public_map(key))),
            'value': base64.urlsafe_b64encode(key.sign(G._platform_signature_payload(body, purpose=purpose))).decode().rstrip('=')}}
    scope = {'tenant_id': '11111111-1111-4111-8111-111111111111',
        'project_group_id': 'tcpg_' + '1'*32, 'work_item_id': 'tcpwi_' + '2'*32,
        'work_item_hash': 'sha256:' + '3'*64, 'authority_version': 1,
        'work_program_id': 'tcwp_' + '4'*32, 'work_program_hash': 'sha256:' + '5'*64}
    legacy = sign({'schema': P.SCHEMA, 'intent_id': 'tcapsei_'+'6'*32, **scope,
        'mode': 'new_change', 'objective': 'TEST-ONLY transport verification',
        'acceptance_criteria': ['TEST-ONLY existing native wire fixture'], 'audience': 'apatch-studio',
        'nonce': base64.urlsafe_b64encode(b'n'*32).decode().rstrip('='),
        'issued_at': stamp(now), 'expires_at': stamp(now+timedelta(minutes=5))}, legacy_key, P.PURPOSE)
    snapshot = {'schema': 'trustchain.cowork.initial-contract-snapshot.v1',
        **{key: scope[key] for key in ('tenant_id','project_group_id','work_item_id','work_item_hash','authority_version')},
        'assignee_ref': 'member:'+'7'*32, 'terms': {'scope': 'TEST-ONLY'},
        'frozen_contract': contract, 'task_envelopes': envelopes}
    handoff = {'schema': 'trustchain.apatch-studio.exact-contract-handoff.v1',
        'handoff_id': 'tceh_'+'8'*32, 'contract_id': 'tciwc_'+'9'*32, **scope,
        'snapshot_hash': raw_hash(snapshot), 'contract_state_version': 1,
        'assignee_ref': snapshot['assignee_ref'], 'commissioner_principal_ref': 'member:'+'a'*32,
        'performer_principal_ref': snapshot['assignee_ref'], 'consents_hash': raw_hash(['TEST-ONLY party A','TEST-ONLY party B']),
        'native_contract_hash': contract['document_hash'], 'native_baseline_hash': contract['baseline_hash'],
        'native_judge_environment_hash': raw_hash(contract['judge_environment']),
        'requirements': [{'requirement': value['requirement'], 'task_envelope_hash': value['document_hash']}
                         for _, value in sorted(envelopes.items())],
        'legacy_intent_document_hash': G.document_hash(legacy), 'legacy_intent_envelope_hash': G.envelope_hash(legacy),
        'audience': 'apatch-studio', 'operation': 'exact_requirement_run', 'nonce': 'b'*48,
        'issued_at': stamp(now), 'expires_at': stamp(now+timedelta(minutes=5))}
    bundle = {'schema': 'trustchain.apatch-studio.exact-contract-bundle.v1',
              'handoff': sign(handoff, handoff_key, ISSUE_PURPOSE), 'snapshot': snapshot, 'legacy_intent': legacy}
    trust = ExactContractTrust(handoff_keys=public_map(handoff_key), association_keys=public_map(association_key),
                              legacy_keys=public_map(legacy_key), trusted_origins={'https://trust-chain.ai'})
    workspace = tmp_path / 'workspace'
    workspace.mkdir()
    from apatch_studio.agent_runs import AgentRunManager
    def unexpected_process(*args, **kwargs):
        pytest.fail('Contract import must not start a process')
    runs = AgentRunManager(workspace, state_root=tmp_path/'runs', popen=unexpected_process)
    manager = ExactContractManager(workspace, run_manager=runs, trust=trust, state_root=tmp_path/'private', gateway=object())
    guard = StudioRequestGuard(trusted_execution_origins=trust.trusted_origins)
    app = create_app(str(workspace), run_manager=runs, adapter=SimpleNamespace(),
        delivery_pack_workflow=SimpleNamespace(), exact_contract_manager=manager, guard=guard)
    headers = {'origin': 'https://trust-chain.ai', 'content-type': 'application/json'}
    path = '/api/v1/exact-contract-handoffs/import'
    with TestClient(app, base_url='http://127.0.0.1:8765', raise_server_exceptions=False) as client:
        first = client.post(path, content=raw_canonical(bundle), headers=headers)
        assert first.status_code == 200, first.text
        assert first.headers['access-control-allow-origin'] == headers['origin']
        assert first.json()['status'] == 'pending' and first.json()['run_id'] is None
        assert client.post(path, content=raw_canonical(bundle), headers=headers).json() == first.json()
        assert len(manager.list()) == 1
        assert runs.list() == []
        altered = deepcopy(bundle)
        altered['handoff']['consents_hash'] = 'sha256:'+'c'*64
        refused = client.post(path, content=raw_canonical(altered), headers=headers)
        assert refused.status_code == 409
        assert len(manager.list()) == 1
        # The remote site cannot confirm, even when presenting a process token.
        headers['x-apatch-studio-session'] = guard.token
        assert client.post(path.replace('/import', '/'+handoff['handoff_id']+'/confirm'),
                           json={}, headers=headers).status_code == 403
