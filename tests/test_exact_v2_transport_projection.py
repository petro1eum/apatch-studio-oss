"""v2 private projection and bounded artifact transport. No live admission claim."""
import hashlib
import json

import pytest
from apatch import sdd_integrity as S
from apatch_studio import exact_contract_artifacts as artifacts
from apatch_studio.projection import private_sdd_projection, assert_projection_safe, UnsafeProjectionError
from apatch_studio.exact_scheme_revision import install_revision
from apatch_studio.execution_intents import ExecutionIntentError
from test_exact_scheme_revision import world
from test_exact_scheme_v2 import prepare, pins
from test_exact_contract_artifacts import scenario


def test_private_v2_binding_remains_only_a_hash_and_public_guard_is_not_relaxed(world):
    plan,_,_,ack=prepare(world,pins()[1])
    value=install_revision(world.manager,world.bundle,'SPEC-CONTROL#R1',association=ack)
    view=private_sdd_projection(value)
    assert view['contract']['acceptance_scheme_hash']==S.canonical_hash(plan)
    assert 'acceptance_scheme' not in view['contract']
    text=json.dumps(view)
    for forbidden in ('secret_refs','response_sha256','https://example.org/readiness','upstream'):
        assert forbidden not in text
    assert_projection_safe(view)
    with pytest.raises(UnsafeProjectionError):assert_projection_safe({'contract':{'environment':plan['environment']}})


def upgrade_transport(s):
    plan={'schema':'trustchain.cowork.acceptance-plan.v2',**{k:s.bundle['handoff'][k] for k in ('tenant_id','project_group_id','work_item_id')},
        'candidate_paths':['src/result.py'],'fixture_assets':[],'inputs':[pins()[1]],
        'environment':{'executor':'platform_sandbox','profile':'managed-sandbox.v2','network_mode':'none','image_digest':'sha256:'+'a'*64,
            'resources':{'cpu_millis':1000,'memory_bytes':1610612736,'pids':256,'scratch_bytes':33554432},'services':[],'secret_refs':[]},
        'checks':[{'check_id':'C','requirement':'SPEC-TEST#R1','phase':'component','requires':{'kind':'input','input_id':'upstream'},'max_attempts':4,'timeout_seconds':30}]}
    raw=S.canonical_json(plan).encode();(s.manager.workspace/artifacts.PLAN).write_bytes(raw);s.files[artifacts.PLAN]=raw
    native=s.bundle['snapshot']['frozen_contract'];native['obligations'][0]['acceptance_id']='C'
    for asset in native['obligations'][0]['judge_assets']:
        if asset['path']==artifacts.PLAN:asset['sha256']='sha256:'+hashlib.sha256(raw).hexdigest()
    s.bundle['snapshot']['task_envelopes']['R1'].update(checks=['C'],budgets={'seconds':1800})
    return plan


def test_v2_package_contains_only_exact_original_files_and_metadata_stays_in_pinned_plan(scenario):
    s=scenario;plan=upgrade_transport(s)
    package,_=artifacts.build_package(s.manager,'tceh_'+'1'*32,'apr_'+'2'*32)
    assert [f['path'] for f in package['files']]==sorted(s.files)
    assert next(f for f in package['manifest']['files'] if f['path']==artifacts.PLAN)['sha256']==S.canonical_hash(plan)
    assert 'secret' not in json.dumps(package['manifest'])


@pytest.mark.parametrize('mutate',[
    lambda p:p['inputs'][0].update(work_item_id=p['work_item_id']),
    lambda p:p['environment'].update(host_mounts=['/']),
    lambda p:p.update(customer_accepted=True),
    lambda p:p['checks'][0].update(check_id='unknown'),
])
def test_even_content_pinned_v2_invalid_schema_or_native_inventory_is_never_exported(scenario,mutate):
    s=scenario;plan=upgrade_transport(s);mutate(plan)
    raw=S.canonical_json(plan).encode();(s.manager.workspace/artifacts.PLAN).write_bytes(raw)
    for asset in s.bundle['snapshot']['frozen_contract']['obligations'][0]['judge_assets']:
        if asset['path']==artifacts.PLAN:asset['sha256']='sha256:'+hashlib.sha256(raw).hexdigest()
    with pytest.raises(ExecutionIntentError):artifacts.build_package(s.manager,'tceh_'+'1'*32,'apr_'+'2'*32)
