"""Real SDK signatures/content hashes; verifier decision is a labelled double.

The live unchanged-judge execution is a separate browser acceptance check.
"""
import copy
import hashlib
import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from trustchain import TrustChain
from apatch import governed_work as G, sdd_integrity as S
from apatch.trustchain_helper import TrustChainHelper
from apatch_studio.exact_contract_artifacts import verify_run_outputs
from apatch_studio.execution_intents import ExecutionIntentError


def seal(body):
    body={k:v for k,v in body.items() if k!='document_hash'}
    return {**body,'document_hash':S.canonical_hash(body)}


@pytest.fixture
def verified(tmp_path,monkeypatch):
    import base64
    tc=TrustChain();public=base64.b64decode(tc.export_public_key())
    def verify(raw,sig):
        try:Ed25519PublicKey.from_public_bytes(public).verify(sig,raw);return True
        except Exception:return False
    provider=SimpleNamespace(get_public_key=lambda:public,verify=verify)
    (tmp_path/'.git').mkdir();objects=tmp_path/'.trustchain/objects';objects.mkdir(parents=True)
    path='src/result.py';data=b'answer = 42\n';sid='test-only-reverification-session'
    source={'binding_id':'tcpsb_'+'1'*32,'spec_id':'SPEC-CONTROL','requirement_refs':[{'requirement_id':'R1','requirement_hash':'sha256:'+'2'*16}]}
    contract=seal({'supersedes_hash':'sha256:'+'3'*64,'obligations':[{'acceptance_id':'C','expected_case_ids':['TEST-ONLY'],'material':True}]})
    envelope=seal({'checks':['C'],'contract_hash':contract['document_hash']})
    snapshot=seal({'schema':'apatch.sdd.verification-content.v1','contract_hash':contract['document_hash'],
        'envelope_hash':envelope['document_hash'],'environment_hash':'sha256:'+'4'*64,
        'files':{path:{'sha256':'sha256:'+hashlib.sha256(data).hexdigest(),'mode':420}}})
    verification=seal({'schema':'apatch.sdd.session-verification.v1','session_id':sid,'content_snapshot_hash':snapshot['document_hash'],
        'decision':{'accepted':True,'executed':1,'collected':1,'failed':0,'skipped':0}})
    proof=seal({'schema':'apatch.sdd.attestation-evidence.v1','actor':{'actor_id':'studio:implementation','role':'implementation'},
        'contract_hash':contract['document_hash'],'envelope_hash':envelope['document_hash'],
        'task_envelope':envelope,'mutation_ids':[],'verification':verification,'environment_hash':snapshot['environment_hash'],
        'adherence':{'status':'compliant'},'falsification':seal({k:True for k in ('observed_red','restored_green','bytes_restored','mode_restored')})})
    def record(evidence):
        payload={'session_id':sid,'artifacts':[f"project-source-binding:{source['binding_id']}@{G.document_hash(source)}",'spec:SPEC-CONTROL#R1@sha256:'+'2'*16],
            'sdd_evidence':seal(evidence)}
        value=asdict(tc.sign('apatch_attest',data=payload));value['tool']=value.pop('tool_id');value['response_timestamp']=value['timestamp']
        value.update(algorithm='ed25519',key_id='TEST-ONLY provider')
        (objects/'op_0001.json').write_text(json.dumps({'id':'op_0001','value':value}))
        rows=TrustChainHelper(str(tmp_path),auto_init=False,read_only=True).iter_ledger_entries()
        facts=G.derive_source_bound_attestation_facts(rows,binding=source)
        return {'evidence_bundle':{'attestation_refs':[{k:f[k] for k in ('attestation_id','attestation_hash')} for f in facts]}}
    built=record(proof)
    cache=tmp_path/'private-state/exact-verified-outputs';cache.mkdir(parents=True)
    witness=cache/(snapshot['document_hash'][7:]+'.json');witness.write_text(json.dumps(snapshot))
    manager=SimpleNamespace(workspace=tmp_path,actor_id='studio:implementation',store=SimpleNamespace(directory=cache.parent),gateway=SimpleNamespace(_workspace_key_provider=lambda:provider))
    monkeypatch.setattr(G,'load_project_source_binding',lambda *args:source)
    return SimpleNamespace(manager=manager,source=source,path=path,data=data,contract=contract,envelope=envelope,
        snapshot=snapshot,proof=proof,built=built,record=record,witness=witness)


def test_fresh_signed_verifier_content_qualifies_without_a_fabricated_mutation(verified):
    v=verified
    verify_run_outputs(v.manager,v.source['binding_id'],v.built,[v.path],{v.path:v.data},(v.contract,v.envelope))


def test_first_delivery_recovers_only_the_exact_finalized_signed_snapshot(verified):
    from apatch.lane import lane_state_path_for
    from pathlib import Path
    v=verified;v.witness.unlink()
    sid=v.proof['verification']['session_id']
    state=Path(lane_state_path_for(str(v.manager.workspace),'test-only-reverification','session_state.json'))
    state.parent.mkdir(parents=True)
    state.write_text(json.dumps({'session_id':sid,'ended_at':'2026-10-21T00:00:00Z','sdd':{'verification_content_snapshot':v.snapshot}}))
    finals=v.manager.workspace/'.apatch/state';finals.mkdir()
    (finals/'finalizations.json').write_text(json.dumps({'records':{sid:{'session_id':sid,'lane_id':'test-only-reverification'}}}))
    verify_run_outputs(v.manager,v.source['binding_id'],v.built,[v.path],{v.path:v.data},(v.contract,v.envelope))
    assert json.loads(v.witness.read_bytes())==v.snapshot


@pytest.mark.parametrize('change',['bytes','snapshot','foreign_contract','foreign_envelope','foreign_session','failed',
    'skipped','missing_case','no_red','not_restored','scope','invented_mutation','no_revision','no_expected_profile'])
def test_old_partial_or_substituted_proof_cannot_qualify_an_unchanged_output(verified,change):
    v=verified;profile=(v.contract,v.envelope);data=v.data;proof=copy.deepcopy(v.proof)
    if change=='bytes':data=b'forged output'
    if change=='snapshot':
        forged=copy.deepcopy(v.snapshot);forged['files'][v.path]['sha256']='sha256:'+'f'*64
        v.witness.write_text(json.dumps(seal(forged)))
    if change=='foreign_contract':proof['contract_hash']='sha256:'+'f'*64
    if change=='foreign_envelope':proof['envelope_hash']='sha256:'+'f'*64
    if change=='foreign_session':proof['verification']['session_id']='other'
    if change=='failed':proof['verification']['decision']['failed']=1
    if change=='skipped':proof['verification']['decision']['skipped']=1
    if change=='missing_case':proof['verification']['decision']['executed']=0
    if change=='no_red':proof['falsification']['observed_red']=False
    if change=='not_restored':proof['falsification']['bytes_restored']=False
    if change=='scope':proof['adherence']['status']='violated'
    if change=='invented_mutation':proof['mutation_ids']=['invented']
    if change=='no_revision':profile=({**v.contract,'supersedes_hash':None},v.envelope)
    if change=='no_expected_profile':profile=None
    proof['verification']=seal(proof['verification'])
    built=v.record(proof)
    with pytest.raises(ExecutionIntentError,match='not recorded'):
        verify_run_outputs(v.manager,v.source['binding_id'],built,[v.path],{v.path:data},profile)
