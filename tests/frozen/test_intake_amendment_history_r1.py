"""Real native amendment activation, independent fixture keys, actual HTTP guard."""
import importlib.util, json
from pathlib import Path
import pytest
from apatch.sdd_judge_amendment import prepare_judge_amendment,activate_judge_amendment
from apatch.sdd_integrity import _seal,freeze_contract

ORIGINAL=Path('/Users/edcher/Documents/GitHub/apatch-studio-oss/tests/frozen/test_intake_historical_parent_r1.py')
loader=importlib.util.spec_from_file_location('amendment_history_original_fixture',ORIGINAL)
probe=importlib.util.module_from_spec(loader);loader.loader.exec_module(probe)
c=probe.c
def amended(c):
    # Use the actual canonical writer for the envelope that native amendment updates.
    from apatch_studio.state_io import write_json
    envelope=c.root/'.apatch/sdd/envelopes/SPEC-FIXTURE-BASE-1/R1.json'
    write_json(envelope,json.loads(envelope.read_bytes()))
    probe.completed(c)
    review=prepare_judge_amendment(c.root,spec_id='SPEC-FIXTURE-BASE-1',requirement_id='R1',acceptance_id='FIXTURE-BASE-1',judge_path='tests/frozen/test_base_fixture.py',replacement_text='def test_base():\n    from feature import public_result\n    assert public_result()==42\n# Owner-approved native successor\n',reason='Exact fixture-native judge successor; preparation only')
    result=activate_judge_amendment(c.root,review,authority_id=probe.OWNER['id'],expected_snapshot=review['document_hash'])
    assert result['functional_acceptance'] is False
    assert result['contract_hash']==review['new_contract']['document_hash']
    return review
def appended(c,previous):
    contract=previous['new_contract'];value=dict(contract);value.pop('document_hash');value.pop('judge_amendment');value.pop('amended_at');value.pop('amendment_requires_fresh_verification')
    value['supersedes_hash']=contract['document_hash'];value['plan_hash']=probe.digest(b'additional independent fixture wave')
    value['obligations']=[*contract['obligations'],dict(contract['obligations'][0],acceptance_id='FIXTURE-LATER-1')]
    head=freeze_contract(value);probe.write(c.root,probe.core.PROFILE,head);probe.write(c.root,'.apatch/sdd/frozen/'+head['document_hash'][7:]+'.json',head)
    return head
@pytest.mark.parametrize('growth',[False,True])
def test_actual_signed_amendment_allows_only_fresh_owner_preparation(c,growth):
    review=amended(c);head=appended(c,review) if growth else review['new_contract']
    before=probe.snapshot(c.root)
    response=probe.propose(c,'apsreq_fixture_amended_fresh',1)
    assert response.status_code==200,response.text
    value=response.json();assert value['status']=='awaiting_approval'
    assert value['functional_acceptance'] is value['implementation_allowed'] is False
    assert value['review']['active_contract_hash']==head['document_hash']
    for path,raw in before.items():
        if path.startswith('.trustchain/') or path==probe.core.PROFILE or path.startswith('.apatch/sdd/judge-amendments/'):
            assert (c.root/path).read_bytes()==raw
@pytest.mark.parametrize('target',['receipt','review','archive','judge','profile','envelope','signature','purpose','owner'])
def test_amended_history_tamper_stays_denied_without_effects(c,target):
    review=amended(c);folder=c.root/'.apatch/sdd/judge-amendments'/review['document_hash'][7:]
    if target in {'receipt','review'}:(folder/(target+'.json')).unlink()
    elif target=='archive':
        p=folder/'old-judge.json';value=json.loads(p.read_text());value['base64']='Zm9yZWlnbg==';probe.write(c.root,p.relative_to(c.root).as_posix(),value)
    elif target=='judge':(c.root/review['judge_path']).write_bytes(b'foreign')
    elif target=='profile':
        value=dict(review['new_contract']);value.pop('document_hash');value['plan_hash']=probe.digest(b'resealed foreign plan');probe.write(c.root,probe.core.PROFILE,_seal(value))
    elif target=='envelope':
        p=c.root/'.apatch/sdd/envelopes/SPEC-FIXTURE-BASE-1/R1.json';value=json.loads(p.read_bytes());value.pop('document_hash');value['allowed_writes'].append('foreign.py');probe.write(c.root,p.relative_to(c.root).as_posix(),_seal(value))
    else:
        records=[]
        for p in (c.root/'.trustchain/objects').glob('op_*.json'):
            value=json.loads(p.read_bytes());record=value.get('value',value)
            if record.get('tool')=='apatch_sdd_judge_amendment' and record.get('data',{}).get('stage')=='activated':records.append((p,value,record))
        assert len(records)==1
        p,value,record=records[0]
        if target=='signature':record['signature']='00'*64
        elif target=='purpose':record['tool']='fixture_foreign_purpose'
        else:record['data']['authority_id']='foreign-owner'
        probe.write(c.root,p.relative_to(c.root).as_posix(),value)
    probe.refusal_unchanged(c)
