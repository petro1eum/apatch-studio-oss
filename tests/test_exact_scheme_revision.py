"""Actual Core/native files. The incoming handoff is a prevalidated test double.

These tests do not claim real bilateral consent, a run or website acceptance.
"""
import copy
import hashlib
import json
import threading
from types import SimpleNamespace

import pytest
from apatch import sdd_integrity as S
from apatch_studio.exact_scheme_revision import validate_revision
from apatch_studio.exact_contract_handoffs import ExactContractManager
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
            'handoff':{'requirements':[{'requirement':'SPEC-CONTROL#R1'}],
                       'performer_principal_ref':'member:'+hashlib.sha256(b'performer').hexdigest()[:32]}}
    return SimpleNamespace(manager=manager,native=native,envelope=envelope,plan=plan,draft=draft,bundle=bundle,files=paths)


def test_read_or_import_cannot_install_a_different_current_profile(world):
    with pytest.raises(ExecutionIntentError):
        world.manager._preflight(world.bundle,'SPEC-CONTROL#R1')
    assert all((world.manager.workspace/p).read_bytes()==raw for p,raw in world.files.items())


def test_explicit_revision_install_uses_real_core_and_keeps_old_version(world):
    current=world.manager._preflight(world.bundle,'SPEC-CONTROL#R1',install_revision=True)
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
    if change=='actor':world.manager.actor_id='other-person'
    if change=='busy':world.manager.run_manager.list=lambda:[{'status':'running'}]
    s['frozen_contract']=seal(n);s['task_envelopes']['R1']=seal({**e,'contract_hash':s['frozen_contract']['document_hash']})
    with pytest.raises(ExecutionIntentError):world.manager._preflight(world.bundle,'SPEC-CONTROL#R1',install_revision=True)
    assert all((world.manager.workspace/p).read_bytes()==raw for p,raw in world.files.items())
