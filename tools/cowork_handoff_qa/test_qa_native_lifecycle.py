"""Real native RunStore + local child; Linux/root/authority transports are doubles.

These tests exercise adapter wiring, not production admission or gVisor proof.
The separate existing observer suite covers real durable fence/ACK semantics.
"""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import qa_native_lifecycle as q
from qa_handoff import digest, StopUnavailable
from test_qa_handoff import admission, TEST_KEY, PUBLIC
from apatch_studio.operations import AgentRunRequest, ExecutionContext, SddExecutionContext
from apatch_studio.exact_contract_handoffs import ExactContractConfirmation
from apatch_studio.run_store import RunStore
from apatch_studio.exact_contract_delivery import SourceBoundExecutionContext
from apatch import governed_work as G, governed_work_mcp as M


def contexts():
    h = 'sha256:' + '1' * 64
    external = ExecutionContext(intent_id='tcapsei_'+'2'*32,
        tenant_id='11111111-1111-4111-8111-111111111111', project_group_id='tcpg_'+'1'*32,
        work_item_id='tcpwi_'+'2'*32, work_item_hash=h, authority_version=1,
        work_program_id='tcwp_'+'3'*32, work_program_hash=h, document_hash=h, envelope_hash=h)
    sdd = SddExecutionContext(spec_id='SPEC-STOP-QA',requirement_id='R1',actor_id='test-actor',
        contract_hash=h,envelope_hash=h,contract={'document_hash':h},task_envelope={
            'document_hash':h,'contract_hash':h,'requirement':'SPEC-STOP-QA#R1','artifacts':[]})
    return external,sdd


class Transport:
    def __init__(self):
        self.a = None; self.started = []; self.release = threading.Event(); self.entered = threading.Event()
    def call(self, operation, **pins):
        assert operation == 'admission'
        self.entered.set()
        if self.a is None:
            raise StopUnavailable('Not admitted yet')
        return copy.deepcopy(self.a)
    def start(self, run_id, pin):
        assert run_id == self.a['observer']['expected_run_ids'][0] and pin == digest(self.a)
        self.started.append((run_id,pin))
        return subprocess.Popen([sys.executable,'-u','-c',
            "import sys,time,json; sys.stdin.read(); print(json.dumps({'type':'qa.heartbeat'}),flush=True); time.sleep(60)"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True,start_new_session=True)


@pytest.fixture
def native(tmp_path,monkeypatch):
    workspace=tmp_path/'workspace';workspace.mkdir()
    transport=Transport();control=q.RemoteControl(transport=transport,wait_seconds=3)
    manager=q.OperatorQaRunManager(workspace,control=control,state_root=tmp_path/'native-state')
    context,sdd=contexts();binding='tcawieb_'+'4'*32; calls=[];revoked=[False]
    row={'intent_id':context.intent_id,'status':'consuming','run_id':None,
         'ack':{'native_binding':{'binding_id':binding}}}
    exact=SimpleNamespace(run_manager=manager,workspace_id='a'*32,_update=lambda fn:fn([row]))
    control.bind(manager,exact)
    # Real Core Change, purpose-signed source receipt and on-disk config. Only
    # current Platform admission is a boundary double; source resolution is real.
    provider=SimpleNamespace(sign=TEST_KEY.sign,get_public_key=lambda:PUBLIC)
    import base64
    keys={G.signer_key_id(provider):base64.urlsafe_b64encode(PUBLIC).rstrip(b'=').decode()}
    configured=M.configure_governed_work(str(workspace),platform_url='https://qa.example',
        client_id='apatch:test-qa',binding_authority_keys=keys,request_key_provider=provider)
    assert configured['ok']
    from apatch import governed_work_delivery as D
    request_key=D.load_config(str(workspace))['service_request_key_id']
    spec=workspace/'docs/specs/SPEC-STOP-QA.md';spec.parent.mkdir(parents=True)
    spec.write_text('# SPEC-STOP-QA -- Stop QA\n\n## R1 Exact stop\n\n(verify: true)\n')
    change=G.prepare_change(str(workspace),tenant_id=context.tenant_id,
        project_group_id=context.project_group_id,work_program_id=context.work_program_id,
        work_program_hash=context.work_program_hash,spec_id=sdd.spec_id,spec_path=str(spec),
        requirement_ids=['R1'],purpose='TEST ONLY fixed QA native adapter',key_provider=provider)['change']
    source={key:change[key] for key in ('tenant_id','project_group_id','source_kind','work_program_id',
        'work_program_hash','context_release_id','context_release_manifest_hash','execution_system',
        'spec_id','spec_hash','requirement_refs')}
    source.update(schema=G.SOURCE_BINDING_SCHEMA,binding_id='tcpsb_'+'6'*32,
        change_id=change['change_id'],change_hash=G.document_hash(change),actor_ref='test-actor',
        authority_version=1,issued_at='2026-10-22T09:00:00Z')
    source['signature']={'algorithm':'Ed25519','key_id':G.signer_key_id(provider),
        'value':base64.urlsafe_b64encode(TEST_KEY.sign(G._platform_signature_payload(source,
            purpose=G.PLATFORM_SOURCE_BINDING_PURPOSE))).rstrip(b'=').decode()}
    G.store_project_source_binding(str(workspace),source,change=change,trusted_authority_keys=keys)
    h='sha256:'+'1'*64
    bound=SourceBoundExecutionContext(handoff_id='tceh_'+'7'*32,tenant_id=context.tenant_id,
        project_group_id=context.project_group_id,work_item_id=context.work_item_id,
        change_id=change['change_id'],change_hash=G.document_hash(change),canonical_binding_id=binding,
        canonical_binding_hash=h,canonical_binding_envelope_hash=h,association_id='tcea_'+'8'*32,
        association_hash=h,association_envelope_hash=h,source_binding_id=source['binding_id'],
        source_binding_hash=G.document_hash(source),source_binding_envelope_hash=G.envelope_hash(source),
        requirement='SPEC-STOP-QA#R1',contract_hash=sdd.contract_hash,task_envelope_hash=sdd.envelope_hash,
        artifacts=(G.source_binding_artifact(source),))
    def guard(request,ctx,contract,*,stage):
        calls.append(stage)
        assert ctx==context and contract==sdd
        if revoked[0]:raise StopUnavailable('Current native authority was revoked')
        return bound
    manager.configure_external_dispatch_guard(guard)
    request=q.QaRunRequest(objective='Exercise one real stoppable QA process',spec_id=sdd.spec_id,requirement_id='R1')
    def admit(run):
        a=admission(tmp_path);a['scope']={k:getattr(context,k) for k in ('tenant_id','project_group_id','work_item_id')}
        a['argv']=list(q.ARGV);a['observer']['public_key']=base64.urlsafe_b64encode(bytes(range(32))).rstrip(b'=').decode();a['observer'].update(workspace_id=exact.workspace_id,expected_run_ids=[run['run_id']],request_key_id=request_key)
        transport.a=a;row.update(status='consumed',run_id=run['run_id'])
        return a
    result=SimpleNamespace(manager=manager,control=control,transport=transport,context=context,sdd=sdd,
        request=request,admit=admit,calls=calls,revoked=revoked,row=row,root=tmp_path,source=source,bound=bound,spec=spec)
    yield result
    manager.close()


def start(n):return n.manager.start(n.request,execution_context=n.context,sdd_execution=n.sdd)


def running(n,run):
    deadline=time.monotonic()+3
    while time.monotonic()<deadline:
        with n.manager._lock:
            process=n.manager._record(run['run_id']).process
        if process is not None:return process
        time.sleep(.01)
    pytest.fail(str(n.manager.get(run['run_id'])))


def test_real_native_allocator_journal_and_current_guard_before_fixed_process(native):
    n=native;run=start(n)
    assert n.transport.entered.wait(2)
    assert not n.transport.started
    saved=n.manager._store.load().records
    assert len(saved)==1 and saved[0]['run_id']==run['run_id']
    assert saved[0]['request']['runner']==q.RUNNER and saved[0]['execution_context']==n.context.model_dump()
    n.admit(run);process=running(n,run)
    assert process.poll() is None and n.transport.started[0][0]==run['run_id']
    assert n.calls==['start','pre_popen','pre_popen']
    n.manager.cancel(run['run_id']);ended=n.manager.wait(run['run_id'],3)
    assert ended['status']=='cancelled' and ended['runner']==q.RUNNER
    assert process.poll() is not None
    # Cancellation is a native local outcome, never a root stop ACK.
    assert not list(n.root.rglob('handoff-ack-*.json'))


@pytest.mark.parametrize('field', ['run','binding','workspace','request_key','scope','argv'])
def test_root_admission_must_name_the_actual_native_tuple(native,field):
    n=native;run=start(n);assert n.transport.entered.wait(2)
    a=n.admit(run)
    if field=='run':a['observer']['expected_run_ids']=['apr_'+'f'*32]
    elif field=='binding':a['observer']['binding_ids']=['tcawieb_'+'f'*32]
    elif field=='workspace':a['observer']['workspace_id']='another'
    elif field=='request_key':a['observer']['request_key_id']='sha256:'+'f'*64
    elif field=='scope':a['scope']['tenant_id']='foreign'
    else:a['argv']=['/bin/sh','-c','echo forbidden']
    assert n.manager.wait(run['run_id'],3)['status']=='failed'
    assert not n.transport.started


def test_revoked_authority_during_operator_wait_never_starts(native):
    n=native;run=start(n);assert n.transport.entered.wait(2)
    n.revoked[0]=True;n.admit(run)
    assert n.manager.wait(run['run_id'],3)['status']=='failed'
    assert not n.transport.started


def test_cancel_waiting_native_run_does_not_start_after_admission(native):
    n=native;run=start(n);assert n.transport.entered.wait(2)
    n.manager.cancel(run['run_id']);n.admit(run)
    assert n.manager.wait(run['run_id'],3)['status'] in {'failed','cancelled'}
    assert not n.transport.started


def test_ordinary_models_stay_closed_and_qa_needs_external_contract(native):
    n=native
    with pytest.raises(ValidationError):AgentRunRequest.model_validate(n.request.model_dump())
    with pytest.raises(ValidationError):ExactContractConfirmation(confirmed=True,workspace_id='a'*32,
        requirement='SPEC-STOP-QA#R1',runner_id=q.RUNNER)
    with pytest.raises(Exception,match='current exact native contract'):n.manager.start(n.request)
    assert n.manager.list()==[]


def test_restart_restores_qa_records_in_existing_store_without_relaunch(native):
    n=native;run=start(n);assert n.transport.entered.wait(2);n.admit(run);running(n,run)
    n.manager.cancel(run['run_id']);n.manager.wait(run['run_id'],3);n.manager.close()
    other=q.OperatorQaRunManager(n.manager._workspace,control=q.RemoteControl(transport=n.transport),
        state_root=n.manager._store.state_root)
    try:
        restored=other.get(run['run_id'])
        assert restored['runner']==q.RUNNER and restored['status']=='cancelled'
        assert restored['execution_context']==run['execution_context']
        assert len(n.transport.started)==1
    finally:other.close()


def test_direct_popen_cannot_bypass_native_spawn(native):
    n=native
    with pytest.raises(StopUnavailable):n.control.popen(q.ARGV,cwd=n.manager._workspace,shell=False,start_new_session=True)
    assert not n.transport.started


def test_fixed_ssh_command_rejects_shell_and_foreign_scope_inputs():
    command=q.FixedSshTransport.command('start',run_id='apr_'+'1'*32,admission_sha256='sha256:'+'2'*64)
    assert command[:8]==['/usr/bin/ssh','-T','-o','BatchMode=yes','-o','ConnectTimeout=10','hc-server','/usr/bin/sudo']
    assert command[-4:]==['--run-id','apr_'+'1'*32,'--admission-sha256','sha256:'+'2'*64]
    for op,pins in [('exec',{}),('start',{'run_id':'$(bad)','admission_sha256':'sha256:'+'2'*64}),
                    ('admission',{'host':'foreign'}),('start',{'run_id':'apr_'+'1'*32})]:
        with pytest.raises(StopUnavailable):q.FixedSshTransport.command(op,**pins)


def test_real_nonempty_source_binding_is_verified_without_legacy_fallback(native,monkeypatch):
    n=native
    from apatch_studio.intent_store import IntentStore
    monkeypatch.setattr(IntentStore,'load',lambda self:pytest.fail('No unrelated legacy admission'))
    refs=q.execution_source_artifacts(n.manager._workspace,n.request,n.context,
        state_root=n.manager._store.state_root,source_binding_context=n.bound)
    assert len(refs)==1 and refs[0]['kind']=='project-source-binding'
    assert refs[0]['id']==n.source['binding_id'] and refs[0]['content_hash']==G.document_hash(n.source)
    run=start(n);assert n.transport.entered.wait(2);n.admit(run);running(n,run)
    assert len(n.transport.started)==1
    n.manager.cancel(run['run_id']);n.manager.wait(run['run_id'],3)


def test_changed_spec_after_operator_wait_fails_real_source_recheck(native):
    n=native;run=start(n);assert n.transport.entered.wait(2)
    n.spec.write_text(n.spec.read_text()+'\nChanged while waiting\n');n.admit(run)
    assert n.manager.wait(run['run_id'],3)['status']=='failed'
    assert not n.transport.started


def test_forged_stored_source_envelope_never_starts(native):
    n=native
    path=G.governed_work_root(str(n.manager._workspace))/'bindings'/(n.source['binding_id']+'.json')
    altered=copy.deepcopy(n.source);altered['signature']['value']='A'*86
    path.write_text(json.dumps(altered))
    run=start(n)
    assert n.manager.wait(run['run_id'],3)['status']=='failed'
    assert not n.transport.started


def test_stop_proxy_forwards_only_exact_current_query_and_preserves_root_ack(native):
    n=native;run=start(n);assert n.transport.entered.wait(2);a=n.admit(run);running(n,run)
    observer=q.RemoteObserver(n.control)
    request={'request_id':'tcwh_'+'5'*32,'request_hash':'sha256:'+'6'*64,
        'scope':a['scope'],'binding_ids':a['observer']['binding_ids'],'expected_run_ids':[run['run_id']]}
    ack={**request,'schema':'trustchain.cowork.handoff-stop-ack.v1','signature':{'root':'opaque-test-transport'}}
    calls=[]
    def call(operation,**pins):calls.append((operation,pins));return copy.deepcopy(ack)
    n.transport.call=call
    assert observer.stop(request)==ack
    assert calls==[('stop',{'request_id':request['request_id'],'request_sha256':digest(request),
                          'acknowledgement_sha256':digest(None)})]
    assert observer.last_query=={'schema':'trustchain.cowork.qa-handoff-authority-query.v1',
                                'request':request,'acknowledgement_hash':None}
    changed=copy.deepcopy(request);changed['scope']['work_item_id']='tcpwi_'+'f'*32
    with pytest.raises(StopUnavailable):observer.stop(changed)
    assert len(calls)==1
    n.manager.cancel(run['run_id']);n.manager.wait(run['run_id'],3)


def test_restarted_controller_can_only_recover_existing_exact_observer(native):
    n=native;run=start(n);assert n.transport.entered.wait(2);n.admit(run);running(n,run)
    n.manager.cancel(run['run_id']);n.manager.wait(run['run_id'],3)
    n.control.admission=None
    n.control.exact._find=lambda rows,identity:rows[0]
    n.control.exact._read_bundle=lambda row,**kwargs: {'test':'historical validation boundary'}
    restored=n.control.restore_observer('tceh_'+'7'*32)
    assert restored['run_id']==run['run_id'] and restored['status']=='cancelled'
    assert n.control.admission['observer']['expected_run_ids']==[run['run_id']]
    assert len(n.transport.started)==1
    n.row['run_id']='apr_'+'f'*32
    with pytest.raises(Exception):n.control.restore_observer('tceh_'+'7'*32)
    assert len(n.transport.started)==1


def test_headless_session_sets_the_existing_local_implementation_actor(tmp_path):
    workspace=tmp_path/'workspace';workspace.mkdir()
    runs,exact,observer=q.create_session(workspace,trust=object(),state_root=tmp_path/'state')
    try:
        assert exact.actor_id=='studio:implementation'
        assert exact.run_manager is runs and observer.control is runs._handoff_process_control
        assert exact.run_request_model is q.QaRunRequest
        assert runs._external_dispatch_guard==exact.guard_execution
        assert runs.list()==[]
    finally:runs.close()


def test_real_manager_retry_keeps_original_exact_row_and_requires_new_run_admission(native):
    n=native;first=start(n);assert n.transport.entered.wait(2)
    n.admit(first);running(n,first)
    n.manager.cancel(first['run_id']);n.manager.wait(first['run_id'],3)
    original=dict(n.row)
    n.transport.a=None;n.transport.entered.clear()
    retry=n.manager.retry(first['run_id'])
    assert retry['retry_of']==first['run_id'] and retry['run_id']!=first['run_id']
    assert n.transport.entered.wait(2)
    # Original association points at the first run forever. Only the actual
    # native retry edge selects the new leaf; operator admission must be fresh.
    assert n.row==original and len(n.transport.started)==1
    a=n.admit(retry);n.row.update(original)
    process=running(n,retry)
    assert process.poll() is None and n.transport.started[-1][0]==retry['run_id']
    assert n.row==original and a['observer']['expected_run_ids']==[retry['run_id']]
    n.manager.cancel(retry['run_id']);n.manager.wait(retry['run_id'],3)
    n.control.exact._find=lambda rows,identity:rows[0]
    n.control.exact._read_bundle=lambda row,**kwargs: {'test':'historical validation boundary'}
    n.control.admission=None
    restored=n.control.restore_observer('tceh_'+'7'*32)
    assert restored['run_id']==retry['run_id'] and restored['retry_of']==first['run_id']
    assert n.control.admission['observer']['expected_run_ids']==[retry['run_id']]
    assert len(n.transport.started)==2 and n.row==original


def test_diagnostic_ssh_does_not_consume_interactive_native_commands(monkeypatch):
    captured={}
    def call(argv,**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(returncode=0,stdout='{}')
    monkeypatch.setattr(q.subprocess,'run',call)
    assert q.FixedSshTransport().call('admission')=={}
    assert captured['stdin'] is subprocess.DEVNULL
