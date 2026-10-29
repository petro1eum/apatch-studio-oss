"""Real Core documents/Ed25519; current ledger/contribution queries are doubles."""
import copy
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from apatch import governed_work as G
from apatch.trustchain_helper import TrustChainHelper
from apatch_studio.exact_contract_handoffs import ExactContractManager
from apatch_studio.execution_intents import ExecutionIntentError


@pytest.fixture
def retained(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    provider = SimpleNamespace(sign=key.sign, get_public_key=lambda: key.public_key().public_bytes_raw())
    spec = tmp_path / 'SPEC-REUSE.md'
    spec.write_text('# SPEC-REUSE\n\n## R1 Preserve native evidence\n\n(verify: true)\n')
    change = G.prepare_change(str(tmp_path), tenant_id='11111111-1111-4111-8111-111111111111', project_group_id='tcpg_'+'1'*32,
        work_program_id='tcwp_'+'2'*32, work_program_hash='sha256:'+'3'*64,
        spec_id='SPEC-REUSE', spec_path=str(spec), purpose='TEST ONLY', key_provider=provider)['change']
    binding = {name: change[name] for name in ('tenant_id','project_group_id','source_kind',
        'work_program_id','work_program_hash','context_release_id','context_release_manifest_hash',
        'execution_system','spec_id','spec_hash','requirement_refs')}
    binding.update(schema=G.SOURCE_BINDING_SCHEMA, binding_id='tcpsb_'+'4'*32,
        change_id=change['change_id'], change_hash=G.document_hash(change), actor_ref='test-actor',
        authority_version=1, issued_at='2026-10-22T09:00:00Z')
    binding = G.sign_document(binding, provider)
    G._atomic_json(G.governed_work_root(str(tmp_path))/'bindings'/(binding['binding_id']+'.json'),binding)
    session = 'test-current-session'
    refs = [G.source_binding_artifact(binding),
        'spec:SPEC-REUSE#R1@'+binding['requirement_refs'][0]['requirement_hash']]
    rows = [{'tool_id':'apatch_attest','id':'op_0001','signature':'test-ledger-double',
        'payload':{'governed_session_id':session,'artifacts':refs}}]
    events = [G.sign_document({'event_id':'event-current', 'created_at':'2026-10-22T09:02:00Z',
        'session':{'session_id':session,'started_at':'2026-10-22T09:01:00Z',
                   'ended_at':'2026-10-22T09:02:00Z','active_sec':60}},provider)]
    monkeypatch.setattr(TrustChainHelper,'iter_ledger_entries',lambda self:copy.deepcopy(rows))
    monkeypatch.setattr(G,'_load_source_bound_contributions',lambda *args,**kw:copy.deepcopy(events))
    # Reproduce the actual native producer: the two documents have distinct issue times.
    stamps=iter(['2026-10-22T09:02:01.000001Z','2026-10-22T09:02:01.000002Z'])
    monkeypatch.setattr(G,'_utc_now',lambda:next(stamps))
    built=G.build_workspace_evidence(str(tmp_path),binding_id=binding['binding_id'],key_provider=provider)
    root=G.governed_work_root(str(tmp_path))
    paths={'timesheet':root/'timesheets'/(built['timesheet']['timesheet_id']+'.json'),
           'evidence_bundle':root/'evidence'/(built['evidence_bundle']['bundle_id']+'.json')}
    manager=ExactContractManager.__new__(ExactContractManager);manager.workspace=tmp_path
    row={'status':'consumed','requirement':'SPEC-REUSE#R1'}
    manager._find=lambda rows,identity:row;manager._update=lambda fn:fn([row])
    manager._delivery_attempt=lambda row:{'run_id':'apr_'+'5'*32,'status':'succeeded','runner':'codex'}
    manager.delivery=SimpleNamespace(selected=lambda identity:{'context':{}},evidence_time=lambda identity:'2026-10-22T09:03:00Z')
    manager._read_bundle=lambda *args,**kw:{'legacy_intent':dict(intent_id='tcapsei_'+'8'*32,tenant_id='11111111-1111-4111-8111-111111111111',
        project_group_id='tcpg_'+'1'*32,work_item_id='tcpwi_'+'6'*32,work_item_hash='sha256:'+'7'*64,
        authority_version=1,work_program_id='tcwp_'+'2'*32,work_program_hash='sha256:'+'3'*64)}
    manager._preflight=lambda *args:SimpleNamespace(spec_id='SPEC-REUSE',requirement_id='R1')
    current=SimpleNamespace(source_binding_id=binding['binding_id'],source_binding_hash=G.document_hash(binding),
        change_id=change['change_id'],change_hash=G.document_hash(change))
    manager.guard_execution=lambda *args,**kw:current
    manager.gateway=SimpleNamespace(_workspace_key_provider=lambda:provider)
    return SimpleNamespace(manager=manager,built=built,paths=paths,rows=rows,events=events,
        current=current,provider=provider)


def test_prebuilt_separate_times_are_reused_without_rewriting(retained):
    before={name:path.read_bytes() for name,path in retained.paths.items()}
    with pytest.raises(G.GovernedWorkError, match='already bound'):
        G.build_workspace_evidence(str(retained.manager.workspace),binding_id=retained.current.source_binding_id,
            key_provider=retained.provider,issued_at='2026-10-22T09:03:00Z')
    for _ in range(2):
        result=retained.manager.build_for_delivery('handoff','apr_'+'5'*32)
        assert result['evidence_bundle_hash']==retained.built['evidence_bundle_hash']
        assert result['timesheet_hash']==retained.built['timesheet_hash']
        assert result['attestation_count']==1 and result['contribution_event_count']==1
    assert {name:path.read_bytes() for name,path in retained.paths.items()}==before


def test_admitted_runner_model_is_preserved_when_building_evidence(retained):
    from typing import Literal
    from apatch_studio.operations import AgentRunRequest
    class AdmittedRequest(AgentRunRequest):
        runner: Literal['fixture_runner'] = 'fixture_runner'
    retained.manager.run_request_model = AdmittedRequest
    retained.manager._delivery_attempt = lambda row: {
        'run_id': 'apr_'+'5'*32, 'status': 'succeeded', 'runner': 'fixture_runner'}
    observed = []
    def guard(request, *args, **kwargs):
        observed.append((type(request), request.runner, kwargs['stage']))
        return retained.current
    retained.manager.guard_execution = guard
    result = retained.manager.build_for_delivery('handoff', 'apr_'+'5'*32)
    assert observed == [(AdmittedRequest, 'fixture_runner', 'build_evidence')]
    assert result['attestation_count'] == 1 and result['contribution_event_count'] == 1
    assert not result['customer_accepted']


@pytest.mark.parametrize('document,field,value',[
    ('timesheet','claimed_active_seconds',999),('timesheet','subject_key_id','foreign'),
    ('evidence_bundle','change_hash','sha256:'+'f'*64),
    ('evidence_bundle','project_source_binding_hash','sha256:'+'e'*64),
])
def test_validly_resigned_wrong_pair_is_rejected_without_repair(retained,document,field,value):
    changed={**retained.built[document],field:value}
    changed=G.sign_document(changed,retained.provider)
    G._atomic_json(retained.paths[document],changed)
    before={name:path.read_bytes() for name,path in retained.paths.items()}
    with pytest.raises(ExecutionIntentError) as exc:
        retained.manager.build_for_delivery('handoff','apr_'+'5'*32)
    assert exc.value.status_code==409
    assert {name:path.read_bytes() for name,path in retained.paths.items()}==before


@pytest.mark.parametrize('failure',['no_attestation','rollback','no_contribution','wrong_binding'])
def test_old_pair_cannot_replace_current_native_facts(retained,failure):
    if failure=='no_attestation':retained.rows.clear()
    if failure=='rollback':retained.rows.append({'payload':{'action':'rollback','governed_session_id':'test-current-session'}})
    if failure=='no_contribution':retained.events.clear()
    if failure=='wrong_binding':retained.current.source_binding_hash='sha256:'+'f'*64
    before={name:path.read_bytes() for name,path in retained.paths.items()}
    with pytest.raises(ExecutionIntentError) as exc:
        retained.manager.build_for_delivery('handoff','apr_'+'5'*32)
    assert exc.value.status_code==409
    assert {name:path.read_bytes() for name,path in retained.paths.items()}==before


def test_invalid_signature_is_not_repaired_or_overwritten(retained):
    changed=copy.deepcopy(retained.built['evidence_bundle'])
    value=changed['signature']['value'];changed['signature']['value']=('A' if value[0]!='A' else 'B')+value[1:]
    G._atomic_json(retained.paths['evidence_bundle'],changed)
    before=retained.paths['evidence_bundle'].read_bytes()
    with pytest.raises(ExecutionIntentError) as exc:
        retained.manager.build_for_delivery('handoff','apr_'+'5'*32)
    assert exc.value.status_code==409
    assert retained.paths['evidence_bundle'].read_bytes()==before


def test_linked_evidence_is_not_followed(retained):
    path=retained.paths['evidence_bundle'];other=path.parent/'test-only-retained.json'
    path.rename(other);path.symlink_to(other)
    before=other.read_bytes()
    with pytest.raises(ExecutionIntentError) as exc:
        retained.manager.build_for_delivery('handoff','apr_'+'5'*32)
    assert exc.value.status_code==409 and other.read_bytes()==before


def test_no_prebuilt_pair_uses_normal_native_builder(retained):
    for path in retained.paths.values():path.unlink()
    result=retained.manager.build_for_delivery('handoff','apr_'+'5'*32)
    assert result['ready_for_publication'] and not result['customer_accepted']
    assert len(list(retained.paths['timesheet'].parent.glob('*.json')))==1
    assert len(list(retained.paths['evidence_bundle'].parent.glob('*.json')))==1


def test_actual_http_missing_native_facts_is_409_not_500(retained):
    import subprocess
    from fastapi.testclient import TestClient
    from apatch_studio.app import create_app
    subprocess.run(['git','init','-q',str(retained.manager.workspace)],check=True)
    retained.rows.clear()
    retained.manager.trust=SimpleNamespace(trusted_origins=frozenset())
    app=create_app(str(retained.manager.workspace),exact_contract_manager=retained.manager,
        run_manager=SimpleNamespace(close=lambda:None))
    with TestClient(app,base_url='http://127.0.0.1:8765') as client:
        response=client.post('/api/v1/exact-contract-handoffs/tceh_'+'a'*32+'/build-evidence',
            json={'confirmed':True,'run_id':'apr_'+'5'*32},headers={
                'origin':'http://127.0.0.1:8765','x-apatch-studio-session':app.state.studio_guard.token})
    assert response.status_code==409
    assert response.json()['error_code']=='exact_evidence_unconfirmed'
