"""Actual Core/native files. The incoming handoff is a prevalidated test double.

These tests do not claim real bilateral consent, a run or website acceptance.
"""
import copy
import hashlib
import json
import threading
import base64
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from apatch import sdd_integrity as S
from apatch import governed_work as G
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from apatch_studio.exact_scheme_revision import validate_revision, install_revision
from apatch_studio.exact_contract_handoffs import ExactContractManager, BIND_PURPOSE
from apatch_studio.sdd_workflow import SddWorkflowFacade
from apatch_studio.execution_intents import ExecutionIntentError


def seal(value):
    body={k:v for k,v in value.items() if k!='document_hash'}
    return {**body,'document_hash':S.canonical_hash(body)}


@pytest.fixture
def world(tmp_path):
    plan={'schema':'trustchain.cowork.acceptance-plan.v1','tenant_id':'company','project_group_id':'tcpg_'+'1'*32,
        'work_item_id':'tcpwi_'+'2'*32,'candidate_paths':['src/result.py'],'fixture_assets':[],
        'environment':{'executor':'platform_sandbox','profile':'managed-sandbox.v1','network_mode':'none','image_digest':'sha256:'+'a'*64},
        'checks':[{'check_id':'C','requirement':'SPEC-CONTROL#R1','phase':'component','requires':None,'max_attempts':4,'timeout_seconds':30},
                  {'check_id':'I','requirement':'SPEC-CONTROL#R1','phase':'integration','requires':{'kind':'check','check_id':'C'},'max_attempts':4,'timeout_seconds':30}]}
    spec=b'# SPEC-CONTROL\n\n## R1 Control\n\n(verify: python3 -m pytest)\n'
    files={'acceptance/work-plan.json':S.canonical_json(plan).encode(),'docs/specs/SPEC-CONTROL.md':spec,
           'tests/test_C.py':b'assert True\n','tests/test_I.py':b'assert True\n'}
    h=lambda raw:'sha256:'+hashlib.sha256(raw).hexdigest()
    obligations=[]
    for cid in ('C','I'):
        argv=['/usr/bin/env','-i','/usr/bin/python3','-m','pytest','tests/test_'+cid+'.py']
        assets=[{'path':p,'sha256':h(files[p])} for p in ('acceptance/work-plan.json','tests/test_'+cid+'.py')]
        obligations.append({'acceptance_id':cid,'test_id':'tests/test_'+cid+'.py','oracle':'Keep every original case','approver':'owner',
            'perspectives':['positive','negative','boundary','regression'],'material':False,'command':argv,'command_hash':S.canonical_hash(argv),
            'asset_hashes':[a['sha256'] for a in assets],'judge_assets':assets,'baseline':{'kind':'observed_red','result_hash':h(b'observed-red-fixture')},'expected_case_ids':[h(cid.encode())]})
    native=S.freeze_contract({**{k:h(spec) for k in ('brief_hash','rfp_hash','spec_hash','plan_hash','baseline_hash')},
        'coverage':{'complete':True,'missing':[],'ambiguous':[],'waivers':[]},'authority':{'role':'authority','actor_id':'owner'},
        'judge_environment':{'cwd':'.','env':{}},'obligations':obligations})
    envelope=S.validate_task_envelope({'schema':'apatch.sdd.task-envelope.v1','requirement':'SPEC-CONTROL#R1',
        'contract_hash':native['document_hash'],'baseline_hash':native['baseline_hash'],'allowed_reads':list(files)+['src/result.py'],
        'allowed_writes':['src/result.py'],'allowed_symbols':[],'forbidden_paths':['tests/**','acceptance/work-plan.json'],
        'tools':['apatch_verify_run','apatch_attest'],'network':[],'remote':[],'services':[],'checks':['C','I'],
        'commands':[o['command'] for o in obligations],'budgets':{'files':1,'insertions':12,'deletions':12,'seconds':1800},'rollback_owner':'owner','containment':'mediated_only'})
    facade=SddWorkflowFacade(tmp_path)
    paths={**files,'.apatch/sdd_verification_contract.json':json.dumps(native).encode(),
        str(facade._envelope_path('SPEC-CONTROL','R1').relative_to(tmp_path)):json.dumps(envelope).encode()}
    for name,raw in paths.items():
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
    draft=copy.deepcopy(plan);draft['checks'][1]['requires']={'kind':'all_of','terms':[{'kind':'check','check_id':'C'}]}
    candidate=copy.deepcopy(native);candidate.update(supersedes_hash=native['document_hash'],plan_hash=S.canonical_hash(draft),acceptance_scheme=draft)
    for check in candidate['obligations']:
        for asset in check['judge_assets']:
            if asset['path']=='acceptance/work-plan.json':asset['sha256']=S.canonical_hash(draft)
        check['asset_hashes']=[a['sha256'] for a in check['judge_assets']]
    candidate=seal(candidate)
    envelopes={'R1':seal({**envelope,'contract_hash':candidate['document_hash']})}
    manager=ExactContractManager.__new__(ExactContractManager)
    manager.workspace=tmp_path;manager.actor_id='performer';manager.sdd=facade
    manager.run_manager=SimpleNamespace(_lock=threading.RLock(),list=lambda:[])
    bundle={'snapshot':{'frozen_contract':candidate,'task_envelopes':envelopes},
            'handoff':{**{name: 'test-only-'+name for name in ('handoff_id','contract_id','snapshot_hash','tenant_id',
                'project_group_id','work_item_id','work_program_id','work_program_hash','commissioner_principal_ref','consents_hash')},
                       'native_contract_hash':candidate['document_hash'],
                       'requirements':[{'requirement':'SPEC-CONTROL#R1'}],
                       'performer_principal_ref':'member:'+hashlib.sha256(b'performer').hexdigest()[:32]}}
    key=Ed25519PrivateKey.generate();public=key.public_key().public_bytes_raw()
    key_id='ed25519:sha256:'+hashlib.sha256(public).hexdigest()
    manager.trust=SimpleNamespace(association_keys={key_id:public})
    association={k:v for k,v in bundle['handoff'].items() if k!='requirements'}
    association.update(handoff_document_hash=G.document_hash(bundle['handoff']),handoff_envelope_hash=G.envelope_hash(bundle['handoff']),
        requirement='SPEC-CONTROL#R1',task_envelope_hash=envelopes['R1']['document_hash'])
    def signed(document,purpose=BIND_PURPOSE):
        body={k:v for k,v in document.items() if k!='signature'}
        return {**body,'signature':{'algorithm':'Ed25519','key_id':key_id,
            'value':base64.urlsafe_b64encode(key.sign(G._platform_signature_payload(body,purpose=purpose))).rstrip(b'=').decode()}}
    return SimpleNamespace(manager=manager,native=native,envelope=envelope,plan=plan,draft=draft,bundle=bundle,
        files=paths,association=signed(association),signed=signed)


def test_read_or_import_cannot_install_a_different_current_profile(world):
    with pytest.raises(ExecutionIntentError):
        world.manager._preflight(world.bundle,'SPEC-CONTROL#R1')
    assert all((world.manager.workspace/p).read_bytes()==raw for p,raw in world.files.items())


def test_explicit_revision_install_uses_real_core_and_keeps_old_version(world):
    current=world.manager._preflight(world.bundle,'SPEC-CONTROL#R1',review_revision=True)
    assert all((world.manager.workspace/p).read_bytes()==raw for p,raw in world.files.items())
    install_revision(world.manager,world.bundle,'SPEC-CONTROL#R1',association=world.association)
    assert current.contract==world.bundle['snapshot']['frozen_contract']
    assert current.task_envelope['budgets']==world.envelope['budgets']
    assert json.loads((world.manager.workspace/'acceptance/work-plan.json').read_bytes())==world.draft
    archived=world.manager.workspace/'.apatch/sdd/frozen'/ (world.native['document_hash'].split(':')[1]+'.json')
    assert json.loads(archived.read_bytes())==world.native
    # Re-reading needs no second install and changes no bytes.
    assert world.manager._preflight(world.bundle,'SPEC-CONTROL#R1').contract_hash==current.contract_hash


@pytest.mark.parametrize('change',['budget','command','inventory','scope','predecessor','network','actor','busy'])
def test_invalid_or_foreign_revision_never_writes_native_inputs(world,change):
    s=world.bundle['snapshot'];n=s['frozen_contract'];e=s['task_envelopes']['R1']
    if change=='budget':e['budgets']['seconds']+=1
    if change=='command':n['obligations'][0]['command']=['true']
    if change=='inventory':n['obligations'][0]['expected_case_ids']=[]
    if change=='scope':e['allowed_writes'].append('private/key')
    if change=='predecessor':n['supersedes_hash']='sha256:'+'f'*64
    if change=='network':n['acceptance_scheme']['environment']['network_mode']='host'
    if change=='actor':world.bundle['handoff']['performer_principal_ref']='member:'+hashlib.sha256(b'other-person').hexdigest()[:32]
    if change=='busy':world.manager.run_manager.list=lambda:[{'status':'running'}]
    s['frozen_contract']=seal(n);s['task_envelopes']['R1']=seal({**e,'contract_hash':s['frozen_contract']['document_hash']})
    with pytest.raises(ValueError):install_revision(world.manager,world.bundle,'SPEC-CONTROL#R1',association=world.association)
    assert all((world.manager.workspace/p).read_bytes()==raw for p,raw in world.files.items())


def test_process_role_is_not_mistaken_for_the_authenticated_sso_performer(world):
    world.manager.actor_id='studio:implementation'
    current=world.manager._preflight(world.bundle,'SPEC-CONTROL#R1',review_revision=True)
    assert current.actor_id=='studio:implementation'
    assert all((world.manager.workspace/p).read_bytes()==raw for p,raw in world.files.items())
    installed=install_revision(world.manager,world.bundle,'SPEC-CONTROL#R1',association=world.association)
    assert installed['contract']==world.bundle['snapshot']['frozen_contract']


@pytest.mark.parametrize('change',['unsigned','tamper','wrong_purpose','foreign_performer','foreign_handoff','foreign_envelope'])
def test_no_revision_install_before_authentic_same_performer_ack(world,change):
    ack=copy.deepcopy(world.association)
    if change=='unsigned':ack.pop('signature')
    if change=='tamper':ack['performer_principal_ref']='member:other'
    if change=='wrong_purpose':ack=world.signed(ack,'other.operation')
    if change=='foreign_performer':ack=world.signed({**ack,'performer_principal_ref':'member:other'})
    if change=='foreign_handoff':ack=world.signed({**ack,'handoff_id':'different-handoff'})
    if change=='foreign_envelope':ack=world.signed({**ack,'task_envelope_hash':'sha256:'+'a'*64})
    with pytest.raises((G.GovernedWorkError,ValueError)):
        install_revision(world.manager,world.bundle,'SPEC-CONTROL#R1',association=ack)
    assert all((world.manager.workspace/p).read_bytes()==raw for p,raw in world.files.items())


@pytest.mark.parametrize('ack_allowed',[True,False])
def test_confirmation_authenticates_performer_before_install_or_dispatch(world,monkeypatch,ack_allowed):
    """Actual confirmation orchestration and native files; HTTP/signing double."""
    from apatch_studio import exact_contract_handoffs as H
    manager=world.manager
    manager.actor_id='studio:implementation';manager.workspace_id='1'*32
    manager.clock=lambda:datetime.now(timezone.utc)
    proposal={'intent_id':'tcapsei_'+'2'*32,'tenant_id':'11111111-1111-4111-8111-111111111111','project_group_id':'tcpg_'+'1'*32,
        'work_item_id':'tcpwi_'+'2'*32,'work_item_hash':'sha256:'+'3'*64,'authority_version':3,
        'work_program_id':'tcwp_'+'4'*32,'work_program_hash':'sha256:'+'5'*64,'objective':'TEST-ONLY revised scheme'}
    world.bundle['legacy_intent']=proposal
    row={'status':'pending','requirement':None,'run_id':None,'ack':None,'facts':None}
    manager._update=lambda fn:fn([row]);manager._find=lambda rows,identity:rows[0]
    manager._read_bundle=lambda row:world.bundle
    manager._project=lambda row:row.copy()
    manager._reconcile=lambda **kwargs:None
    manager.gateway=SimpleNamespace(_workspace_key_provider=lambda:object())
    monkeypatch.setattr(H.M,'accept_execution_proposal',lambda *args,**kwargs:{'ok':True,'work_started':False,
        'change':{'change_id':'apchg_'+'6'*32,'spec_hash':world.native['spec_hash']},
        'proposal_acceptance':{'accepted_at':'2026-10-21T00:00:00Z'}})
    calls=[]
    def exchange(*args):
        assert all((manager.workspace/p).read_bytes()==raw for p,raw in world.files.items())
        calls.append('authenticated_ack')
        if not ack_allowed:raise ValueError('Foreign or revoked performer enrollment')
        return {'association':world.association}
    manager._exchange=exchange
    def prepare(*args):
        assert manager.sdd.execution_binding('SPEC-CONTROL','R1',actor_id=manager.actor_id)['contract']==world.bundle['snapshot']['frozen_contract']
        calls.append('prepare_source')
    manager.delivery=SimpleNamespace(prepare=prepare)
    def start(*args,**kwargs):
        calls.append('dispatch');return {'run_id':'apr_'+'7'*32}
    manager.run_manager.start=start
    confirmation=SimpleNamespace(workspace_id=manager.workspace_id,requirement='SPEC-CONTROL#R1',runner_id='codex')
    if ack_allowed:
        result=manager._confirm(world.bundle['handoff']['handoff_id'],confirmation,for_delivery=True)
        assert result['status']=='consumed'
        assert calls==['authenticated_ack','prepare_source','dispatch']
    else:
        with pytest.raises(ValueError,match='Foreign or revoked'):manager._confirm(world.bundle['handoff']['handoff_id'],confirmation,for_delivery=True)
        assert calls==['authenticated_ack']
        assert all((manager.workspace/p).read_bytes()==raw for p,raw in world.files.items())


@pytest.mark.parametrize('stage',['start','pre_popen'])
@pytest.mark.parametrize('failure',[None,'revoked','budget'])
def test_admitted_retry_refreshes_authority_and_preserves_the_native_budget(world,monkeypatch,stage,failure):
    """Real native budget; authority/transport doubles, not a live grant."""
    from apatch_studio import exact_contract_handoffs as H
    from apatch.task_budget import TaskBudget
    import time
    m=world.manager
    current=m._preflight(world.bundle,'SPEC-CONTROL#R1',review_revision=True)
    proposal={k:'TEST-ONLY-'+k for k in ('intent_id','tenant_id','project_group_id','work_item_id','work_item_hash','authority_version','work_program_id','work_program_hash')}
    world.bundle['legacy_intent']=proposal
    world.bundle['handoff']['expires_at']='2026-10-20T00:00:00Z'
    ctx=SimpleNamespace(**proposal,document_hash=G.document_hash(proposal),envelope_hash=G.envelope_hash(proposal))
    row={'intent_id':proposal['intent_id'],'handoff_id':'TEST-ONLY','status':'consumed',
        'requirement':'SPEC-CONTROL#R1','ack':{'ORIGINAL':'TEST-ONLY'},'facts':{'change_id':'TEST-ONLY'}}
    m._update=lambda fn:fn([row]);m._preflight=lambda *args,**kw:current
    m._delivery_attempt=lambda row:{'status':'succeeded' if stage=='start' else 'running',
        'can_retry':True,'retry_of':None if stage=='start' else 'prior-run'}
    calls=[]
    def bundle(row,*,historical):assert historical is True;return world.bundle
    m._read_bundle=bundle;m.clock=lambda:datetime(2026,10,21,tzinfo=timezone.utc)
    m.gateway=SimpleNamespace(_workspace_key_provider=lambda:object())
    source=SimpleNamespace(source_binding_id='TEST-ONLY',source_binding_hash='TEST-ONLY')
    m.delivery=SimpleNamespace(selected=lambda identity:{'context':source},guard_context=lambda *args:source)
    m.trust.validate_bundle=lambda *args,**kw:calls.append(('current_bundle',kw['historical']))
    monkeypatch.setattr(H.G,'load_change',lambda *args:{'change_id':'TEST-ONLY'})
    monkeypatch.setattr(H.P,'acceptance_path',lambda *args:'TEST-ONLY')
    monkeypatch.setattr(H,'read_json',lambda *args,**kw:{'TEST_ONLY':True})
    monkeypatch.setattr(H.W,'validate_acceptance',lambda doc:doc)
    def exchange(*args,**kw):
        assert kw['historical'] is True and kw['original_ack']==row['ack'] and kw['source_context']==source
        calls.append(('fresh_server_revalidation',True))
        if failure=='revoked':raise ValueError('Current authority revoked')
        return row['ack']
    m._exchange=exchange
    budget=TaskBudget(str(m.workspace),current.task_envelope)
    before=budget.check()
    if failure=='budget':
        actual=time.time();monkeypatch.setattr('apatch.task_budget.time.time',lambda:actual+3601)
    request=SimpleNamespace(mode='requirement',spec_id=current.spec_id,requirement_id=current.requirement_id)
    if failure is None:
        assert m.guard_execution(request,ctx,current,stage=stage)==source
        after=budget.check()
        assert after['started_at']==before['started_at'] and after['deadline']==before['deadline']
        assert calls==[('fresh_server_revalidation',True),('current_bundle',True)]
    else:
        with pytest.raises((ValueError,ExecutionIntentError)):
            m.guard_execution(request,ctx,current,stage=stage)
        assert not any(c[0]=='current_bundle' for c in calls)
        if failure=='budget':assert calls==[]
