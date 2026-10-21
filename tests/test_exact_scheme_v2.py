"""Real Core sealing/files/ACK crypto; no live Platform or worker claim.

Historical v1 tests remain unchanged. These cases add closed v2 parity and
prove that only the consented plan asset changes during installation.
"""
import copy
import json

import pytest
from apatch import governed_work as G
from apatch import sdd_integrity as S
from apatch_studio.exact_scheme_revision import validate_revision, install_revision
from apatch_studio.exact_scheme_validation import validate_plan_delta
from apatch_studio.acceptance_profiles import EXTENDED_SCHEMA, RESOURCES
from test_exact_scheme_revision import world, seal


def pins():
    h='sha256:'+'b'*64;item='tcpwi_'+'3'*32
    return [
        {'kind':'result','input_id':'upstream','release_id':'tcwr_'+'4'*32,'release_hash':h,'required_state':'accepted'},
        {'kind':'work_result','input_id':'upstream','release_id':'tcwr_'+'4'*32,'release_hash':h,'required_state':'accepted','work_item_id':item,'work_item_hash':h,'authority_version':7},
        {'kind':'folder','input_id':'upstream','folder_id':'tcpfr_'+'5'*32,'authority_version':2,'grant_id':'tcpfg_'+'6'*32,'grant_authority_version':2},
        {'kind':'resource','input_id':'upstream','binding_id':'tcnrb_'+'7'*32,'binding_hash':h,'authority_version':1,'actions':['read']},
        {'kind':'human','input_id':'upstream','work_item_id':item,'authority_version':4,'decision':'close','decision_hash':h},
        {'kind':'human_wait','input_id':'upstream','work_item_id':item,'authority_version':3,'work_item_hash':h,'decision':'close','actor_role':'owner'},
    ]


def prepare(world,pin):
    plan=copy.deepcopy(world.draft)
    plan.update(schema=EXTENDED_SCHEMA,inputs=[pin])
    plan['environment'].update(profile='managed-public-network.v1',network_mode='public_http',resources=dict(RESOURCES),secret_refs=[],services=[
        {'service_id':'readiness','url':'https://example.org/readiness','response_sha256':'sha256:'+'c'*64,'timeout_seconds':3}])
    plan['checks'][1]['requires']={'kind':'if','condition':'input:upstream',
        'then':{'kind':'all_of','terms':[{'kind':'check','check_id':'C'},{'kind':'input','input_id':'upstream'}]},
        'otherwise':{'kind':'any_of','terms':[{'kind':'check','check_id':'C'},{'kind':'input','input_id':'upstream'}]}}
    native=copy.deepcopy(world.native)
    native.update(supersedes_hash=world.native['document_hash'],plan_hash=S.canonical_hash(plan),acceptance_scheme=plan)
    for c in native['obligations']:
        for a in c['judge_assets']:
            if a['path']=='acceptance/work-plan.json':a['sha256']=S.canonical_hash(plan)
        c['asset_hashes']=[a['sha256'] for a in c['judge_assets']]
    native=seal(native);env=seal({**world.envelope,'contract_hash':native['document_hash']})
    world.bundle['snapshot'].update(frozen_contract=native,task_envelopes={'R1':env})
    world.bundle['handoff']['native_contract_hash']=native['document_hash']
    ack={k:v for k,v in world.association.items() if k!='signature'}
    ack.update(native_contract_hash=native['document_hash'],task_envelope_hash=env['document_hash'],
        handoff_document_hash=G.document_hash(world.bundle['handoff']),handoff_envelope_hash=G.envelope_hash(world.bundle['handoff']))
    return plan,native,env,world.signed(ack)


@pytest.mark.parametrize('pin',pins(),ids=lambda p:p['kind'])
def test_all_six_closed_input_shapes_install_only_with_exact_ack_and_predecessor(world,pin):
    plan,native,env,ack=prepare(world,pin)
    assert validate_revision(world.native,{'R1':world.envelope},native,{'R1':env},world.plan)==plan
    before={name:(world.manager.workspace/name).read_bytes() for name in world.files}
    installed=install_revision(world.manager,world.bundle,'SPEC-CONTROL#R1',association=ack)
    assert installed['contract']==native
    assert json.loads((world.manager.workspace/'acceptance/work-plan.json').read_bytes())==plan
    for name in ('docs/specs/SPEC-CONTROL.md','tests/test_C.py','tests/test_I.py'):
        assert (world.manager.workspace/name).read_bytes()==before[name]
    assert installed['task_envelope']['budgets']==world.envelope['budgets']
    assert installed['task_envelope']['network']==world.envelope['network']==[]


@pytest.mark.parametrize('change',[
    lambda p:p['environment'].update(network_mode='host'),
    lambda p:p['environment'].update(image_digest='sha256:'+'f'*64),
    lambda p:p['environment']['resources'].update(pids=999),
    lambda p:p['environment'].update(host_mounts=['/']),
    lambda p:p['environment']['services'][0].update(url='http://169.254.169.254/'),
    lambda p:p['environment']['services'][0].update(url='https://user:password@example.org/'),
    lambda p:p['inputs'][0].update(tenant_id='foreign'),
    lambda p:p['inputs'][0].update(work_item_id=p['work_item_id']),
    lambda p:p['inputs'][0].update(authority_version=True),
    lambda p:p['checks'].pop(),
    lambda p:p['checks'][1].update(requirement='SPEC-OTHER#R1'),
    lambda p:p['checks'][1].update(requires={'kind':'input','input_id':'unknown'}),
    lambda p:p['checks'][0].update(requires={'kind':'check','check_id':'I'}),
    lambda p:p['checks'][0].update(requires={'kind':'all_of','terms':[]}),
    lambda p:p['checks'][0].update(requires={'kind':'check','check_id':'missing'}),
    lambda p:p['checks'][1].update(timeout_seconds=1801),
    lambda p:p.update(candidate_paths=['private/key']),
])
def test_v2_does_not_weaken_judges_scope_limits_or_graph_validation(world,change):
    plan,_,_,_=prepare(world,pins()[1]);change(plan)
    with pytest.raises((ValueError,KeyError)):
        validate_plan_delta(world.plan,plan,{'R1':world.envelope})
    assert all((world.manager.workspace/path).read_bytes()==raw for path,raw in world.files.items())


def test_legacy_plan_cannot_silently_acquire_new_fields_and_v2_supports_next_revision(world):
    plan,_,_,_=prepare(world,pins()[2])
    next_plan=copy.deepcopy(plan);next_plan['checks'][1]['phase']='usage'
    validate_plan_delta(plan,next_plan,{'R1':world.envelope})
    hidden=copy.deepcopy(world.plan);hidden['inputs']=[]
    with pytest.raises(ValueError):validate_plan_delta(world.plan,hidden,{'R1':world.envelope})
