"""Actual local process observations: never equate cancellation with quiescence."""
import json
import os
import signal
import subprocess
import sys
import threading
import time
import pytest
from apatch_studio.work_handoff_stop import ControlledProcesses, StopObserver, StopUnavailable, digest

SCOPE={'tenant_id':'qa','project_group_id':'tcpg_'+'1'*32,'work_item_id':'tcpwi_'+'2'*32}
RUN='apr_'+'3'*32
REQ='tcwh_'+'4'*32
HASH='sha256:'+'5'*64

def spawn(control,code):
    return control.spawn(SCOPE,RUN,lambda:subprocess.Popen([sys.executable,'-u','-c',code],
                         start_new_session=True,stdout=subprocess.PIPE,text=True))

def reaper(process):
    thread=threading.Thread(target=process.wait,daemon=True);thread.start();return thread

def clean(process):
    try: os.killpg(process.pid,signal.SIGKILL)
    except ProcessLookupError: pass
    process.wait(timeout=3)
    if process.stdout: process.stdout.close()


def test_durable_fence_blocks_queued_and_restarted_spawn_after_real_stop(tmp_path):
    control=ControlledProcesses(tmp_path/'state')
    p=spawn(control,"import time; print('ready',flush=True); time.sleep(30)")
    assert p.stdout.readline().strip()=='ready';thread=reaper(p)
    try:
        proof=control.fence_and_drain(SCOPE,REQ,HASH,timeout=2)
        assert proof['run_ids']==[RUN] and proof['process_groups']==[p.pid]
        assert proof['active_process_group_count']==0 and proof['queue_fenced'] is True
        called=[]
        for c in [control,ControlledProcesses(tmp_path/'state')]:
            with pytest.raises(StopUnavailable,match='fenced'):
                c.spawn(SCOPE,'apr_'+'6'*32,lambda:called.append(True))
        assert not called
        with pytest.raises(StopUnavailable,match='cannot be replaced'):
            control.fence_and_drain(SCOPE,REQ,'sha256:'+'6'*64,timeout=0)
    finally: clean(p);thread.join(timeout=3)


def test_parent_and_child_are_both_drained(tmp_path):
    control=ControlledProcesses(tmp_path/'state')
    code="""import subprocess,sys,time,signal
child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'])
def stop(*args):
    child.wait(timeout=2)
    raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
print(child.pid,flush=True)
time.sleep(30)
"""
    p=spawn(control,code);child=int(p.stdout.readline());thread=reaper(p)
    try:
        result=control.fence_and_drain(SCOPE,REQ,HASH,timeout=3)
        assert result['active_process_group_count']==0
        with pytest.raises(ProcessLookupError): os.kill(child,0)
    finally: clean(p);thread.join(timeout=3)


def test_stubborn_descendant_prevents_ack_and_restart_cannot_clear_fence(tmp_path):
    control=ControlledProcesses(tmp_path/'state')
    code="""import subprocess,sys,time,signal
signal.signal(signal.SIGTERM,lambda *args:None)
child=subprocess.Popen([sys.executable,'-c',"import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); print('child ready',flush=True); time.sleep(30)"])
time.sleep(30)
"""
    p=spawn(control,code);assert p.stdout.readline().strip()=='child ready'
    try:
        with pytest.raises(StopUnavailable,match='still draining'): control.fence_and_drain(SCOPE,REQ,HASH,timeout=.1)
        with pytest.raises(StopUnavailable,match='still draining'): ControlledProcesses(tmp_path/'state').fence_and_drain(SCOPE,REQ,HASH,timeout=.1)
    finally: clean(p)


def test_interrupted_spawn_never_turns_into_stopped_on_restart(tmp_path):
    control=ControlledProcesses(tmp_path/'state')
    def interrupted(): raise RuntimeError('simulated pre-Popen interruption')
    with pytest.raises(RuntimeError): control.spawn(SCOPE,RUN,interrupted)
    with pytest.raises(StopUnavailable,match='interrupted'):
        ControlledProcesses(tmp_path/'state').fence_and_drain(SCOPE,REQ,HASH,timeout=0)


def test_no_containment_no_signer_and_caller_assertion_cannot_ack(tmp_path):
    control=ControlledProcesses(tmp_path/'state')
    request={'request_id':REQ,'request_hash':HASH,'scope':SCOPE,'binding_ids':['tcawieb_'+'7'*32],'expected_run_ids':[RUN]}
    called=[]
    q={'schema':'trustchain.cowork.stop-observer-qualification.v1','observer_id':'test','program_sha256':HASH,
       'host_id':'test','workspace_id':'test','request_key_id':'sha256:'+'8'*64}
    for observer in [StopObserver(control),StopObserver(control,qualification=q,signer=lambda body:called.append(body))]:
        with pytest.raises(StopUnavailable,match='not installed'): observer.stop(request)
    assert called==[] and not (tmp_path/'state'/'work-handoff-stop.json').exists()


def test_linked_registry_is_not_read_or_overwritten(tmp_path):
    outside=tmp_path/'outside.json';outside.write_text('{"unrelated":true}')
    state=tmp_path/'state';state.mkdir();(state/'work-handoff-stop.json').symlink_to(outside)
    with pytest.raises(OSError): ControlledProcesses(state).fence_and_drain(SCOPE,REQ,HASH,timeout=0)
    assert outside.read_text()=='{"unrelated":true}'


def test_explicit_observer_cannot_attach_to_uncontrolled_manager():
    from apatch_studio.work_handoff_delivery import WorkHandoffDelivery
    from types import SimpleNamespace
    manager=SimpleNamespace(run_manager=SimpleNamespace(),workspace_id='qa')
    observer=SimpleNamespace(qualification={'workspace_id':'qa'},containment=object(),control=object())
    with pytest.raises(StopUnavailable,match='not configured'):
        WorkHandoffDelivery(manager,observer).stop('irrelevant',{'workspace_id':'qa'})


def test_http_stop_cannot_configure_its_own_observer_or_claim_stopped(tmp_path):
    from fastapi.testclient import TestClient
    from apatch_studio.app import create_app
    from types import SimpleNamespace
    app=create_app(str(tmp_path),adapter=SimpleNamespace(overview=lambda **kwargs:{}),frontend_root=tmp_path)
    with TestClient(app,base_url='http://127.0.0.1:8765') as client:
        url='/api/v1/exact-contract-handoffs/tceh_'+'1'*32+'/stop-for-reassignment'
        assert client.post(url,json={'stopped':True}).status_code==401
        response=client.post(url,json={'workspace_id':'qa','qualification':{'observer_id':'forged'},'stopped':True},
                            headers={'x-apatch-studio-session':app.state.studio_guard.token,'origin':'http://127.0.0.1:8765'})
        assert response.status_code==503
        assert response.json()['error_code']=='handoff_stop_unconfigured'


def test_actual_typescript_stop_transport_sends_no_claim_and_rejects_cancelling(tmp_path):
    from pathlib import Path
    module=(Path(__file__).resolve().parents[1]/'frontend/src/exactContractDeliveryApi.ts').as_uri()
    script=f'''import {{stopExactWorkForReassignment as stop}} from {json.dumps(module)};
globalThis.document={{querySelector:()=>({{content:'test-session'}})}};
const seen=[];
let state='stop_requested';
globalThis.fetch=async(path,options)=>{{seen.push([path,options]);return {{ok:true,json:async()=>({{
schema:'trustchain.cowork.work-handoff.v1',state,request:{{request_id:'tcwh_'+'1'.repeat(32)}},acknowledged_observers:['test-observer']}})}}}};
const result=await stop('tceh_'+'2'.repeat(32),'3'.repeat(32));
state='cancelling';let rejected=false;try{{await stop('tceh_'+'2'.repeat(32),'3'.repeat(32));}}catch{{rejected=true;}}
console.log(JSON.stringify({{result,rejected,body:JSON.parse(seen[0][1].body),path:seen[0][0],session:seen[0][1].headers['X-APatch-Studio-Session']}}));'''
    result=subprocess.run(['node','--experimental-transform-types','--input-type=module','-e',script],
                          capture_output=True,text=True,check=True)
    value=json.loads(result.stdout)
    assert value=={'result':'stop_requested','rejected':True,'body':{'workspace_id':'3'*32},
                  'path':'/api/v1/exact-contract-handoffs/tceh_'+'2'*32+'/stop-for-reassignment','session':'test-session'}


def test_lost_ack_reobserves_when_unrecorded_but_recorded_ack_retries_exact_history(tmp_path,monkeypatch):
    """Protocol retry fixture, not a production containment qualification."""
    from datetime import datetime,timedelta,timezone
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import base64,hashlib
    import apatch_studio.work_handoff_stop as mod
    clock=[datetime(2026,10,22,tzinfo=timezone.utc)]
    class TestClock(datetime):
        @classmethod
        def now(cls,tz=None): return clock[0]
    monkeypatch.setattr(mod,'datetime',TestClock)
    control=ControlledProcesses(tmp_path/'state')
    p=spawn(control,"import time; print('ready',flush=True); time.sleep(30)")
    assert p.stdout.readline().strip()=='ready';thread=reaper(p)
    key=Ed25519PrivateKey.generate()
    q={'schema':'trustchain.cowork.stop-observer-qualification.v1','observer_id':'test-only','program_sha256':HASH,
       'host_id':'test','workspace_id':'test','request_key_id':'sha256:'+'8'*64}
    def signer(body):
        return {'algorithm':'Ed25519','key_id':'sha256:'+hashlib.sha256(key.public_key().public_bytes_raw()).hexdigest(),
                'value':base64.urlsafe_b64encode(key.sign(body)).rstrip(b'=').decode()}
    class TestContainment:
        def assert_closed_and_quiescent(self,request,proof):
            # This fixture exercises only our known sleeping child; it does not
            # stand in for the missing restricted OS containment service.
            with pytest.raises(ProcessLookupError): os.killpg(p.pid,0)
    observer=StopObserver(control,qualification=q,signer=signer,containment=TestContainment())
    request={'request_id':REQ,'request_hash':HASH,'scope':SCOPE,'binding_ids':['tcawieb_'+'7'*32],'expected_run_ids':[RUN]}
    try:
        first=observer.stop(request,timeout=2)
        assert observer.stop(request)==first
        clock[0]+=timedelta(minutes=6)
        refreshed=observer.stop(request)
        assert refreshed['observed_at']!=first['observed_at'] and digest(refreshed)!=digest(first)
        assert observer.stop(request,accepted_ack_hash=digest(first))==first
        with pytest.raises(StopUnavailable,match='absent from immutable'):
            observer.stop(request,accepted_ack_hash='sha256:'+'0'*64)
        assert len(list((tmp_path/'state').glob('handoff-ack-history-*.json')))==2
    finally: clean(p);thread.join(timeout=3)
