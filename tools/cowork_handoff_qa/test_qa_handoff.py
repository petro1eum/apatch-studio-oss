"""Real durable files, locks and existing ACK crypto; simulated engine/kernel.

No Docker daemon or server is contacted. Cgroup escape cases are adversarial
observations, not a claim that this Mac provides Linux/gVisor containment.
"""
import base64
import copy
from datetime import datetime,timedelta,timezone
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat

import qa_handoff as q

# Public RFC8032 test-vector material, never a newly generated or production key.
TEST_SEED=bytes.fromhex('9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60')
TEST_KEY=Ed25519PrivateKey.from_private_bytes(TEST_SEED)
PUBLIC=TEST_KEY.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
SCOPE={'tenant_id':'qa','project_group_id':'tcpg_'+'1'*32,'work_item_id':'tcpwi_'+'2'*32}
RUN='apr_'+'3'*32
BINDING='tcawieb_'+'4'*32
BOOT='12345678-1234-1234-1234-123456789abc'
REQUEST={'request_id':'tcwh_'+'5'*32,'tenant_id':'qa','project_group_id':SCOPE['project_group_id'],
         'source_work_item_id':SCOPE['work_item_id'],'requested_at':datetime.now(timezone.utc).isoformat()}
QUERY={'request_id':REQUEST['request_id'],'request_hash':q.digest(REQUEST),'scope':SCOPE,
       'binding_ids':[BINDING],'expected_run_ids':[RUN]}


def admission(root):
    return {'schema':q.SCHEMA,'scope':copy.deepcopy(SCOPE),'container_id':'a'*64,'container_created':'2026-10-22T00:00:00Z',
        'image':'sha256:'+'b'*64,'argv':['python3','/workspace/fixed_qa.py'],'workspace':str(root/'workspace'),
        'container_env_sha256':q.digest(['PATH=/usr/bin']),
        'cgroup_root':str(root/('tc-cowork-handoff-qa-'+'c'*32)), 'cgroup_parent':'qa-parent', 'host_boot_id':BOOT,
        'memory_bytes':128*1024**2,'pids_limit':32,
        'observer':{'schema':'trustchain.cowork.stop-observer-admission.v1','observer_id':'qa-one',
            'program_sha256':'sha256:'+'d'*64,'host_id':'host-one','workspace_id':'workspace-one',
            'request_key_id':'sha256:'+'e'*64,'public_key':base64.urlsafe_b64encode(PUBLIC).rstrip(b'=').decode(),
            'binding_ids':[BINDING],'expected_run_ids':[RUN],
            'qualified_until':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}}


class Kernel:
    def __init__(self,a):
        self.a=a;self.inode=123;self.processes={};self.populated=False;self.nested_populated=False;self.boot=BOOT
    def boot_id(self):return self.boot
    def process(self,pid):return copy.deepcopy(self.processes.get(str(pid)))
    def tree(self):
        own={p:copy.deepcopy(v) for p,v in self.processes.items() if Path(v['cgroup']).is_relative_to(Path(self.a['cgroup_root']))}
        return {'inode':self.inode,'groups':{
            self.a['cgroup_root']:{'inode':self.inode,'populated':'1' if own or self.populated or self.nested_populated else '0','pids':[int(x) for x in own]},
            self.a['cgroup_root']+'/nested':{'inode':124,'populated':'1' if self.nested_populated else '0','pids':[]}},'processes':own}
    def group_alive(self,pgid):return any(x['pgid']==pgid for x in self.processes.values())


class Engine:
    def __init__(self,a,k):
        self.a=a;self.k=k;self.calls=[];self.stubborn=False;self.leave_attach=False
        self.row={'Id':a['container_id'],'Image':a['image'],'Created':a['container_created'],'RestartCount':0,
            'State':{'Status':'created','Running':False,'Pid':0,'StartedAt':'0001-01-01T00:00:00Z'},
            'HostConfig':{'Runtime':'runsc','CgroupParent':a['cgroup_parent'],'NetworkMode':'none','RestartPolicy':{'Name':'no'},
                'AutoRemove':False,'Privileged':False,'ReadonlyRootfs':True,'CapDrop':['ALL'],'CapAdd':None,
                'SecurityOpt':['no-new-privileges'],'Devices':[],'DeviceRequests':None,'DeviceCgroupRules':None,
                'PidMode':'','IpcMode':'private','CgroupnsMode':'private','Memory':a['memory_bytes'],'PidsLimit':a['pids_limit']},
            'Config':{'User':'1000:1000','WorkingDir':'/workspace','Entrypoint':None,'Cmd':a['argv'],
                'Env':['PATH=/usr/bin'],'Labels':{'tc.handoff.run_id':RUN,'tc.handoff.scope_hash':q.digest(SCOPE)}},
            'Mounts':[{'Type':'bind','Source':a['workspace'],'Destination':'/workspace','RW':True,'Propagation':'rprivate'}]}
    def inspect(self,cid):assert cid==self.a['container_id'];return copy.deepcopy(self.row)
    def attach_start(self,cid):
        assert cid==self.a['container_id'];self.calls.append('start')
        self.row['State'].update(Status='running',Running=True,Pid=601,StartedAt='2026-10-22T01:02:03Z')
        self.k.processes={'601':{'start_ticks':100,'pgid':601,'cgroup':self.a['cgroup_root']+'/container'},
                          '701':{'start_ticks':200,'pgid':701,'cgroup':'/host/attach'}}
        return SimpleNamespace(pid=701,wait=lambda timeout:0)
    def stop(self,cid,timeout):
        assert cid==self.a['container_id'];self.calls.append('stop')
        self.row['State'].update(Status='exited',Running=False,Pid=0)
        if not self.stubborn:
            self.k.processes={p:v for p,v in self.k.processes.items() if p=='701' and self.leave_attach}
        else:
            self.k.processes.pop('701',None);self.k.nested_populated=True


@pytest.fixture
def world(tmp_path):
    root=tmp_path.resolve();state=root/'state';state.mkdir(mode=0o700)
    a=admission(root);k=Kernel(a);e=Engine(a,k)
    c=q.ContainerControl(a,state,e,k,uid=os.getuid());signed=[]
    def sign(raw):
        signed.append(json.loads(raw))
        return {'algorithm':'Ed25519','key_id':'sha256:'+hashlib.sha256(PUBLIC).hexdigest(),
                'value':base64.urlsafe_b64encode(TEST_KEY.sign(raw)).rstrip(b'=').decode()}
    return SimpleNamespace(a=a,k=k,e=e,c=c,state=state,sign=sign,signed=signed,
        restart=lambda:q.ContainerControl(a,state,e,k,uid=os.getuid()))


def launch(w,control=None):
    c=control or w.c
    return c.spawn(SCOPE,RUN,lambda:c.popen(w.a['argv'],cwd=w.a['workspace'],shell=False,start_new_session=True))


def stop(w,control=None,**kwargs):
    return q.observer(control or w.c,w.sign).stop(copy.deepcopy(QUERY),timeout=0,**kwargs)


def test_actual_candidate_observer_and_platform_verifier_accept_only_measured_stop(world):
    from apatch_studio.work_handoff_stop import StopObserver
    from backend.app.services.cowork_work_handoff import verify_stop_ack
    w=world;launch(w)
    assert isinstance(q.observer(w.c,w.sign),StopObserver)
    ack=stop(w)
    assert verify_stop_ack(ack,REQUEST,w.a['observer'],now=datetime.now(timezone.utc))==ack
    assert w.e.calls==['start','stop'] and len(w.signed)==1
    assert ack['run_ids']==[RUN] and ack['process_groups']==[701]
    assert ack['queue_fenced'] is True and ack['active_operation_count']==0


def test_retry_and_process_restart_keep_exact_ack_and_cannot_relaunch(world):
    w=world;launch(w);ack=stop(w)
    assert stop(w,w.restart())==ack
    assert stop(w,w.restart(),accepted_ack_hash=q.digest(ack))==ack
    assert len(w.signed)==1 and w.e.calls==['start','stop']
    with pytest.raises(q.StopUnavailable,match='permanently fenced'):launch(w,w.restart())
    assert w.e.calls==['start','stop']
    with pytest.raises(q.StopUnavailable,match='absent from immutable local history'):
        stop(w,w.restart(),accepted_ack_hash='sha256:'+'f'*64)
    assert len(w.signed)==1


@pytest.mark.parametrize('field,value',[('binding_ids',['tcawieb_'+'f'*32]),('expected_run_ids',['apr_'+'f'*32]),
    ('scope',{**SCOPE,'tenant_id':'foreign'}),('claimed_stopped',True),('request_hash','invalid')])
def test_foreign_or_caller_claimed_request_cannot_even_set_fence(world,field,value):
    w=world;launch(w);query=copy.deepcopy(QUERY);query[field]=value
    with pytest.raises(q.StopUnavailable):q.observer(w.c,w.sign).stop(query,timeout=0)
    state=json.loads((w.state/'contained-run.json').read_bytes())
    assert state['fence'] is None and not w.signed and w.e.calls==['start']


@pytest.mark.parametrize('mutation', ['escaped','nested','restarted','inode','attach','boot'])
def test_unclosed_or_changed_containment_never_signs(world,mutation):
    w=world;launch(w)
    if mutation=='escaped':w.k.processes['601']['cgroup']='/foreign/cgroup'
    elif mutation=='nested':w.e.stubborn=True
    elif mutation=='restarted':w.e.row['State']['StartedAt']='another-start'
    elif mutation=='inode':w.k.inode+=1
    elif mutation=='attach':w.e.leave_attach=True
    else:w.k.boot='abcdefab-abcd-abcd-abcd-abcdefabcdef'
    with pytest.raises(q.StopUnavailable):stop(w)
    assert not w.signed
    assert not list(w.state.glob('handoff-ack-*.json'))


def test_a_setsid_child_in_another_nested_cgroup_is_part_of_the_drain(world):
    w=world;launch(w)
    w.k.processes['602']={'start_ticks':101,'pgid':999,'cgroup':w.a['cgroup_root']+'/container/setsid-child'}
    ack=stop(w)
    assert ack['active_operation_count']==0 and not w.k.processes
    persisted=json.loads((w.state/'contained-run.json').read_bytes())
    assert '602' in persisted['run']['processes']


def test_unobserved_launch_is_not_registered_retroactively(world):
    w=world
    def interrupted():
        w.c.popen(w.a['argv'],cwd=w.a['workspace'],start_new_session=True)
        raise RuntimeError('interrupted registration')
    with pytest.raises(RuntimeError):w.c.spawn(SCOPE,RUN,interrupted)
    with pytest.raises(q.StopUnavailable,match='Interrupted or unobserved'):stop(w,w.restart())
    assert not w.signed
    with pytest.raises(q.StopUnavailable,match='fenced'):launch(w,w.restart())


def test_stop_before_any_launch_cannot_claim_a_preexisting_run(world):
    w=world
    with pytest.raises(q.StopUnavailable,match='Interrupted or unobserved'):stop(w)
    assert not w.e.calls and not w.signed
    with pytest.raises(q.StopUnavailable,match='fenced'):launch(w)


@pytest.mark.parametrize('path,value',[
    (('HostConfig','Runtime'),'runc'),(('HostConfig','RestartPolicy'),{'Name':'always'}),
    (('HostConfig','Privileged'),True),(('HostConfig','CgroupnsMode'),'host'),
    (('HostConfig','DeviceCgroupRules'),['a *:* rwm']), (('HostConfig','Memory'),0),
    (('Config','Env'),['PATH=/changed']), (('Config','Cmd'),['other-command']),
    (('Image',),'sha256:'+'0'*64),(('Created',),'new-container'),
    (('Mounts',),[{'Type':'bind','Source':'/','Destination':'/workspace','RW':True,'Propagation':'rprivate'}])])
def test_changed_precreated_container_posture_rejects_before_start(world,path,value):
    w=world;cursor=w.e.row
    for part in path[:-1]:cursor=cursor[part]
    cursor[path[-1]]=value
    with pytest.raises(q.StopUnavailable):launch(w)
    assert not w.e.calls and not w.signed


def test_direct_popen_and_changed_runner_arguments_cannot_launch(world):
    w=world
    with pytest.raises(q.StopUnavailable,match='durable spawn fence'):
        w.c.popen(w.a['argv'],cwd=w.a['workspace'],start_new_session=True)
    with pytest.raises(q.StopUnavailable,match='differs from admission'):
        w.c.spawn(SCOPE,RUN,lambda:w.c.popen(['forged'],cwd=w.a['workspace'],start_new_session=True))
    assert not w.e.calls


def test_concurrent_stop_waits_for_registration_and_the_fence_survives_restart(world):
    w=world;entered=threading.Event();release=threading.Event();finished=threading.Event();failures=[]
    def start():
        entered.set();assert release.wait(2)
        return w.c.popen(w.a['argv'],cwd=w.a['workspace'],start_new_session=True)
    def launch_thread():
        try:w.c.spawn(SCOPE,RUN,start)
        except BaseException as exc:failures.append(exc)
    def stop_thread():
        try:stop(w,w.restart())
        except BaseException as exc:failures.append(exc)
        finally:finished.set()
    t=threading.Thread(target=launch_thread);t.start();assert entered.wait(2)
    s=threading.Thread(target=stop_thread);s.start()
    assert not finished.wait(.05)
    release.set();t.join(2);s.join(2)
    assert not failures and finished.is_set() and len(w.signed)==1
    with pytest.raises(q.StopUnavailable,match='fenced'):launch(w,w.restart())


def test_state_symlink_and_mutated_admission_are_refused(world,tmp_path):
    w=world;other=tmp_path/'other';other.write_text('{}')
    (w.state/'contained-run.json').symlink_to(other)
    with pytest.raises(OSError):launch(w)
    assert other.read_text()=='{}' and not w.e.calls
    (w.state/'contained-run.json').unlink();launch(w)
    altered=copy.deepcopy(w.a);altered['observer']['qualified_until']=(datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()
    c=q.ContainerControl(altered,w.state,w.e,w.k,uid=os.getuid())
    with pytest.raises(q.StopUnavailable,match='Admission or durable'):stop(w,c)
    assert not w.signed


def test_changed_fence_never_reopens_stopped_generation(world):
    w=world;launch(w);stop(w)
    with pytest.raises(q.StopUnavailable,match='cannot be replaced'):
        w.c.fence_and_drain(SCOPE,'tcwh_'+'f'*32,'sha256:'+'f'*64,timeout=0)
    assert w.e.calls==['start','stop']


def proc_file(proc,pid,*,pgid,cgroup,start=100):
    p=proc/str(pid);p.mkdir(exist_ok=True)
    fields=['S','1',str(pgid)]+['0']*16+[str(start)]+['0']*2
    (p/'stat').write_text(f'{pid} (name with ) space) '+' '.join(fields))
    (p/'cgroup').write_text('0::'+cgroup+'\n')


def cgroup_file(path,*,pids='',populated='0'):
    path.mkdir(parents=True,exist_ok=True)
    (path/'cgroup.procs').write_text(pids)
    (path/'cgroup.events').write_text('populated '+populated+'\nfrozen 0\n')


def test_linux_reader_observes_nested_processes_and_pid_identity(tmp_path):
    mount=tmp_path/'cgroup';root=mount/'qa';proc=tmp_path/'proc';proc.mkdir()
    cgroup_file(root,populated='1');cgroup_file(root/'child',pids='22\n',populated='1')
    proc_file(proc,22,pgid=99,cgroup='/qa/child',start=456)
    k=q.LinuxKernel(root,proc_root=proc,cgroup_mount=mount)
    tree=k.tree()
    assert tree['processes']['22']=={'start_ticks':456,'pgid':99,'cgroup':str(root/'child')}
    assert k.group_alive(99) is True
    (proc/'22/cgroup').write_text('0::/outside\n')
    with pytest.raises(q.StopUnavailable,match='escaped'):k.tree()


def test_linux_reader_refuses_linked_or_removed_cgroup_sources(tmp_path):
    mount=tmp_path/'cgroup';root=mount/'qa';proc=tmp_path/'proc';proc.mkdir();cgroup_file(root)
    k=q.LinuxKernel(root,proc_root=proc,cgroup_mount=mount)
    source=root/'cgroup.events';source.unlink();source.symlink_to(root/'cgroup.procs')
    with pytest.raises(q.StopUnavailable,match='Incomplete'):k.tree()
    source.unlink();(root/'cgroup.procs').unlink();root.rmdir()
    with pytest.raises(q.StopUnavailable,match='disappeared'):k.tree()


def test_cli_has_no_arbitrary_authority_key_or_sign_entry(monkeypatch):
    import qa_handoff_cli as cli
    for argv in [('sign',),('stop','--admission','/tmp/forged'),('stop','--key','/tmp/key')]:
        monkeypatch.setattr('sys.argv',['qa_handoff_cli.py',*argv])
        monkeypatch.setattr(cli,'public_admission',lambda:pytest.fail('invalid command reached privileged configuration'))
        with pytest.raises(SystemExit) as exc:cli.main()
        assert exc.value.code==2


def test_cli_refuses_nonroot_before_reading_any_private_input(monkeypatch):
    import qa_handoff_cli as cli
    monkeypatch.setattr(cli.os,'geteuid',lambda:1234)
    with pytest.raises(RuntimeError,match='Root-only'):cli.public_admission()


def test_docker_stages_use_same_fixed_daemon_and_clean_environment(monkeypatch):
    monkeypatch.setenv('DOCKER_HOST','ssh://foreign')
    monkeypatch.setenv('DOCKER_CONTEXT','foreign-context')
    monkeypatch.setenv('DOCKER_CONFIG','/untrusted/config')
    monkeypatch.setattr(q,'trusted',lambda path:Path(path))
    calls=[]
    def invoke(argv,**kwargs):
        calls.append((argv,kwargs))
        return SimpleNamespace(stdout=json.dumps([{'Id':'a'*64}]))
    monkeypatch.setattr(q.subprocess,'run',invoke)
    monkeypatch.setattr(q.subprocess,'Popen',invoke)
    engine=q.DockerEngine()
    assert engine.inspect('a'*64)=={'Id':'a'*64}
    engine.attach_start('a'*64)
    engine.stop('a'*64,5)
    assert [argv[2] for argv,_ in calls]==['inspect','start','stop']
    for argv,kwargs in calls:
        assert argv[:2]==['/usr/bin/docker','--host=unix:///var/run/docker.sock']
        assert argv[-1]=='a'*64
        assert kwargs['env']=={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin'}
        assert kwargs['cwd']=='/'
