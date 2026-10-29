"""One admitted Linux gVisor run, using the existing Studio stop ACK protocol.

This module never creates a container, key, admission or execution binding.
Production entry is qa_handoff_cli.py with a root-owned fixed installation.
The injected engine/kernel parameters exist for local tests, not CLI input.
"""
from __future__ import annotations

import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import threading
import time

from apatch_studio.state_io import StateDirectory
from apatch_studio.work_handoff_stop import StopObserver, StopUnavailable, canonical, digest, scope_key

SCHEMA = 'trustchain.cowork.qa-handoff-host-admission.v1'
STATE_SCHEMA = 'trustchain.cowork.qa-contained-run.v1'
HEX = r'[a-f0-9]{64}'


def require(value, reason):
    if not value:
        raise StopUnavailable(reason)


def trusted(path, *, uid=0, directory=False, private=False):
    """No symlinks/hardlinks or writable ancestry; only a fixed installed tree."""
    path = Path(path)
    require(path.is_absolute() and '..' not in path.parts, 'Noncanonical protected path')
    for parent in reversed(path.parents):
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and info.st_uid in {0, uid}, 'Untrusted path ancestry')
        # Sticky /tmp is useful for local tests. Production uses fixed /var/lib.
        require(not info.st_mode & 0o022 or bool(info.st_mode & stat.S_ISVTX), 'Writable path ancestry')
    info = path.lstat()
    require(info.st_uid == uid and not info.st_mode & 0o022, 'Protected path is not owner controlled')
    require(stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
            'Linked or nonregular protected path')
    if private:
        require(not info.st_mode & 0o077, 'Private state or key permissions')
    return path


def load_json(path, *, uid=0):
    path = trusted(path, uid=uid)
    with StateDirectory(path.parent) as directory:
        return directory.read_json(path.name, limit=256 * 1024)


def validate_admission(value):
    if isinstance(value,dict) and value.get('schema')=='trustchain.cowork.systemd-handoff-host-admission.v1':
        from qa_systemd_handoff import validate
        return validate(value)
    a = copy.deepcopy(value)
    keys = {'schema', 'scope', 'observer', 'container_id', 'container_created', 'image', 'argv',
            'workspace', 'container_env_sha256', 'cgroup_root', 'cgroup_parent', 'host_boot_id',
            'memory_bytes', 'pids_limit'}
    require(isinstance(a, dict) and set(a) in (keys, keys | {'container_workspace'})
            and a['schema'] == SCHEMA, 'Closed host admission required')
    scope_key(a['scope'])
    o = a['observer']
    require(isinstance(o, dict) and set(o) == {'schema','observer_id','program_sha256','host_id','workspace_id',
        'request_key_id','public_key','binding_ids','expected_run_ids','qualified_until'}
        and o['schema'] == 'trustchain.cowork.stop-observer-admission.v1', 'Existing observer admission required')
    for k in ('program_sha256', 'request_key_id'):
        require(bool(re.fullmatch('sha256:'+HEX, str(o[k]))), 'Invalid observer digest')
    import base64
    try:
        public = base64.urlsafe_b64decode(o['public_key'] + '=' * (-len(o['public_key']) % 4))
        require(len(public) == 32 and base64.urlsafe_b64encode(public).rstrip(b'=').decode() == o['public_key']
            and 'sha256:'+hashlib.sha256(public).hexdigest() != o['request_key_id'], 'Observer and performer keys must differ')
        expiry = datetime.fromisoformat(o['qualified_until'].replace('Z','+00:00'))
        require(expiry.tzinfo is not None and datetime.now(timezone.utc) < expiry, 'Observer admission expired')
    except (ValueError, TypeError, KeyError) as exc:
        raise StopUnavailable('Invalid observer public admission') from exc
    for key, pattern in [('binding_ids',r'tcawieb_[a-f0-9]{32}'),('expected_run_ids',r'apr_[a-f0-9]{32}')]:
        require(type(o[key]) is list and len(o[key]) == 1 and re.fullmatch(pattern, str(o[key][0])), 'Exactly one qualified binding and run required')
    require(all(type(o[k]) is str and 1 <= len(o[k]) <= 128 for k in ('observer_id','host_id','workspace_id')), 'Invalid host identity')
    require(re.fullmatch(HEX, str(a['container_id'])) and re.fullmatch('sha256:'+HEX, str(a['image'])), 'Exact container and image required')
    require(type(a['argv']) is list and a['argv'] and len(a['argv']) <= 128
        and all(type(x) is str and x and '\0' not in x for x in a['argv']), 'Exact process arguments required')
    for key in ('workspace','cgroup_root'):
        p = Path(a[key]); require(p.is_absolute() and '..' not in p.parts, 'Noncanonical admitted path')
    require(a.get('container_workspace', '/workspace') in ('/workspace', a['workspace']),
            'Only the exact admitted workspace or fixed mount is allowed')
    # The root is a dedicated persistent parent, not Docker's removable leaf.
    require(re.fullmatch(r'tc-cowork-handoff-qa-[a-f0-9]{32}(?:\.slice)?', Path(a['cgroup_root']).name), 'Dedicated QA cgroup parent required')
    require(type(a['cgroup_parent']) is str and a['cgroup_parent'] and '\0' not in a['cgroup_parent'], 'Exact Docker cgroup parent required')
    require(re.fullmatch(r'[a-f0-9-]{36}', str(a['host_boot_id'])), 'Host boot identity required')
    require(type(a['container_created']) is str and a['container_created'], 'Precreated container identity required')
    require(re.fullmatch('sha256:'+HEX, str(a['container_env_sha256'])), 'Pinned container environment required')
    require(type(a['memory_bytes']) is int and 16*1024**2 <= a['memory_bytes'] <= 2*1024**3, 'Bounded memory required')
    require(type(a['pids_limit']) is int and 8 <= a['pids_limit'] <= 256, 'Bounded process count required')
    return a


class DockerEngine:
    """Only inspect/start/stop of a full pinned ID; never arbitrary docker argv."""
    def __init__(self, binary='/usr/bin/docker'):
        self.binary = str(trusted(binary))
        self.command = [self.binary, '--host=unix:///var/run/docker.sock']
        self.environment = {'PATH':'/usr/sbin:/usr/bin:/sbin:/bin'}

    def inspect(self, container):
        out = subprocess.run([*self.command,'inspect',container], check=True, capture_output=True, timeout=10, env=self.environment, cwd='/')
        rows = json.loads(out.stdout)
        require(len(rows) == 1 and rows[0]['Id'] == container, 'Exact container disappeared')
        return rows[0]

    def attach_start(self, container):
        return subprocess.Popen([*self.command,'start','--attach','--interactive',container], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',
            bufsize=1,start_new_session=True,env=self.environment,cwd='/')

    def stop(self, container, timeout):
        subprocess.run([*self.command,'stop','--time',str(max(1,int(timeout))),container],check=True,
            capture_output=True,timeout=timeout+10,env=self.environment,cwd='/')


class LinuxKernel:
    """Read actual cgroup-v2 descendants and PID start-time identity, not ps text."""
    def __init__(self, cgroup_root, *, proc_root='/proc', cgroup_mount='/sys/fs/cgroup'):
        self.root = Path(cgroup_root); self.proc = Path(proc_root); self.mount = Path(cgroup_mount)
        require(self.root.is_relative_to(self.mount) and self.root != self.mount, 'Cgroup is outside cgroup v2')

    def boot_id(self):
        return (self.proc/'sys/kernel/random/boot_id').read_text().strip()

    def process(self, pid):
        try:
            raw = (self.proc/str(pid)/'stat').read_text()
            tail = raw[raw.rfind(')')+2:].split()
            rows = (self.proc/str(pid)/'cgroup').read_text().splitlines()
        except FileNotFoundError:
            return None
        require(len(tail) >= 20 and len(rows) == 1 and rows[0].startswith('0::/'), 'Unsupported process cgroup identity')
        return {'start_ticks':int(tail[19]),'pgid':int(tail[2]),'cgroup':str(self.mount/rows[0][4:])}

    def tree(self):
        require(self.root.is_dir() and not self.root.is_symlink(), 'Dedicated cgroup parent disappeared')
        result = {}; processes = {}
        for directory, children, files in os.walk(self.root, followlinks=False):
            path = Path(directory)
            require(not path.is_symlink() and all(not (path/x).is_symlink() for x in children), 'Linked cgroup subtree')
            require('cgroup.procs' in files and 'cgroup.events' in files
                and not (path/'cgroup.procs').is_symlink() and not (path/'cgroup.events').is_symlink(), 'Incomplete cgroup v2 observation')
            values = dict(line.split() for line in (path/'cgroup.events').read_text().splitlines())
            require(values.get('populated') in {'0','1'}, 'Missing cgroup populated state')
            pids = [int(s) for s in (path/'cgroup.procs').read_text().split()]
            require(all(x > 1 for x in pids), 'Invalid cgroup process inventory')
            for pid in pids:
                process = self.process(pid)
                require(process is not None and Path(process['cgroup']).is_relative_to(self.root), 'Process escaped its qualified cgroup')
                processes[str(pid)] = process
            result[str(path)] = {'inode':path.stat().st_ino,'populated':values['populated'],'pids':pids}
        return {'inode':self.root.stat().st_ino,'groups':result,'processes':processes}

    def group_alive(self, pgid):
        # Host attach client is outside the container's cgroup; it must also exit.
        for p in self.proc.iterdir():
            if p.name.isdigit():
                info = self.process(int(p.name))
                if info is not None and info['pgid'] == pgid:
                    return True
        return False


class ContainerControl:
    """Studio's spawn/fence API, with a separately injected closed Popen adapter."""
    def __init__(self, admission, directory, engine, kernel, *, uid=0):
        self.admission = validate_admission(admission)
        self.directory = trusted(directory, uid=uid, directory=True, private=True)
        self.engine, self.kernel, self.uid = engine, kernel, uid
        self._ticket = threading.local()
        self._process = None

    @property
    def execution_id(self):return self.admission['container_id']

    def _current(self):
        validate_admission(self.admission)
        require(self.kernel.boot_id() == self.admission['host_boot_id'], 'Host restarted; qualification is unavailable')

    @contextmanager
    def _transaction(self):
        self._current()
        with StateDirectory(self.directory) as directory:
            fd = os.open('contained-run.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600,dir_fd=directory.fd)
            try:
                directory._regular(os.fstat(fd)); fcntl.flock(fd,fcntl.LOCK_EX)
                try: state = directory.read_json('contained-run.json',limit=512*1024)
                except FileNotFoundError: state = {'schema':STATE_SCHEMA,'admission_hash':digest(self.admission),'run':None,'fence':None}
                require(set(state) == {'schema','admission_hash','run','fence'} and state['schema'] == STATE_SCHEMA
                    and state['admission_hash'] == digest(self.admission), 'Admission or durable run state changed')
                yield state, directory
            finally:
                fcntl.flock(fd,fcntl.LOCK_UN); os.close(fd)

    def _inspect(self):
        a = self.admission; row = self.engine.inspect(a['container_id']); h = row['HostConfig']; c = row['Config']
        require(row['Id'] == a['container_id'] and row['Image'] == a['image'] and row['Created'] == a['container_created'], 'Container identity changed')
        require(h['Runtime'] == 'runsc' and h['CgroupParent'] == a['cgroup_parent'] and h['NetworkMode'] == 'none'
            and h['RestartPolicy']['Name'] == 'no' and h['AutoRemove'] is False and h['Privileged'] is False
            and h['ReadonlyRootfs'] is True and h['CapDrop'] == ['ALL'] and not h.get('CapAdd')
            and set(h['SecurityOpt']) == {'no-new-privileges'} and not h.get('Devices') and not h.get('DeviceRequests')
            and h.get('PidMode','') in {'','private'} and h.get('IpcMode') == 'private'
            and h.get('CgroupnsMode') == 'private' and not h.get('DeviceCgroupRules')
            and h['Memory'] == a['memory_bytes'] and h['PidsLimit'] == a['pids_limit'], 'Containment posture changed')
        target = a.get('container_workspace', '/workspace')
        require(c['User'] == '1000:1000' and c['WorkingDir'] == target
            and (c.get('Entrypoint') or [])+(c.get('Cmd') or []) == a['argv']
            and digest(c.get('Env') or []) == a['container_env_sha256'], 'Pinned runner configuration changed')
        mounts = row['Mounts']
        require(len(mounts) == 1 and mounts[0]['Type'] == 'bind' and mounts[0]['Source'] == a['workspace']
            and mounts[0]['Destination'] == target and mounts[0]['RW'] is True
            and mounts[0].get('Propagation') == 'rprivate', 'Only the exact QA workspace may be mounted')
        require((c.get('Labels') or {}).get('tc.handoff.run_id') == a['observer']['expected_run_ids'][0]
            and (c.get('Labels') or {}).get('tc.handoff.scope_hash') == digest(a['scope']), 'Container run labels changed')
        return row

    def popen(self, argv, **kw):
        # Configure AgentRunManager(popen=control.popen,handoff_process_control=control).
        # No untrusted host command is executed; the precreated container's own
        # argv/environment have just been checked against operator admission.
        require(getattr(self._ticket,'active',False) and not getattr(self._ticket,'used',False), 'Popen must run once inside the durable spawn fence')
        require(list(argv) == self.admission['argv'] and kw.get('cwd') == self.admission['workspace']
            and kw.get('shell',False) is False and kw.get('start_new_session') is True, 'Runner launch differs from admission')
        self._ticket.used = True
        self._process = self.engine.attach_start(self.execution_id)
        return self._process

    def spawn(self, scope, run_id, start):
        a = self.admission
        require(scope == a['scope'] and run_id == a['observer']['expected_run_ids'][0], 'Unqualified execution scope or run')
        with self._transaction() as (state,directory):
            require(state['fence'] is None, 'This source is permanently fenced')
            require(state['run'] is None, 'Run identity cannot be reused or retroactively registered')
            row = self._inspect()
            require(row['State']['Status'] == 'created' and row['State']['Running'] is False
                and row['RestartCount'] == 0, 'Only a never-started admitted container can launch')
            tree = self.kernel.tree()
            require(not tree['processes'] and all(x['populated']=='0' for x in tree['groups'].values()), 'Qualified parent is not initially empty')
            state['run'] = {'phase':'launching','run_id':run_id,'cgroup_inode':tree['inode']}
            directory.write_json('contained-run.json',state)
            try:
                self._ticket.active = True
                self._ticket.used = False
                process = start()
                require(process is self._process and process is not None, 'The closed Popen adapter was bypassed')
                end = time.monotonic()+5
                while True:
                    row = self._inspect()
                    if row['State']['Running'] is True: break
                    require(time.monotonic()<end,'Runner was not observed running')
                    time.sleep(.02)
                tree = self.kernel.tree(); pid = row['State']['Pid']; host = self.kernel.process(pid)
                require(tree['inode'] == state['run']['cgroup_inode'] and str(pid) in tree['processes']
                    and host == tree['processes'][str(pid)], 'Runtime is outside the qualified cgroup')
                attach = self.kernel.process(process.pid)
                require(attach is not None and attach['pgid'] == process.pid, 'Attach process is not independently tracked')
                state['run'].update(phase='running',started_at=row['State']['StartedAt'],restart_count=row['RestartCount'],
                    processes=tree['processes'],attach_pid=process.pid,attach=attach)
                directory.write_json('contained-run.json',state)
                return process
            finally:
                self._ticket.active = False
                # A failure leaves the durable 'launching' record. It cannot ACK.

    def _closed(self, state, *, record_more=False):
        run = state['run']; require(run and run['phase'] == 'running','Interrupted or unobserved launch cannot qualify a stop')
        row = self._inspect()
        require(row['State']['StartedAt'] == run['started_at'] and row['RestartCount'] == run['restart_count'], 'Container was restarted outside its fence')
        tree = self.kernel.tree()
        require(tree['inode'] == run['cgroup_inode'], 'Qualified cgroup parent was replaced')
        for pid, old in run['processes'].items():
            current = self.kernel.process(int(pid))
            if current is not None and current['start_ticks'] == old['start_ticks']:
                require(Path(current['cgroup']).is_relative_to(Path(self.admission['cgroup_root'])), 'Tracked process escaped its cgroup')
        if record_more:
            run['processes'].update(tree['processes'])
        return row, tree

    def fence_and_drain(self, scope, request_id, request_hash, *, timeout=5.0):
        require(scope == self.admission['scope'] and re.fullmatch(r'tcwh_[a-f0-9]{32}',str(request_id))
            and re.fullmatch('sha256:'+HEX,str(request_hash)) and 0 <= timeout <= 30,'Unqualified stop request')
        fence = {'request_id':request_id,'request_hash':request_hash,'scope':scope}
        with self._transaction() as (state,directory):
            require(state['fence'] is None or state['fence'] == fence, 'Permanent fence cannot be replaced')
            state['fence'] = copy.deepcopy(fence); directory.write_json('contained-run.json',state)
            row, tree = self._closed(state,record_more=True); directory.write_json('contained-run.json',state)
            if row['State']['Running']:
                self.engine.stop(self.execution_id,timeout)
            if self._process is not None:
                self._process.wait(timeout=max(1,timeout))
            end = time.monotonic()+timeout
            while True:
                try:
                    self._assert_empty(state)
                    break
                except StopUnavailable as exc:
                    if str(exc) not in {'Container is not terminal','Contained descendants remain',
                                        'Attach process remains','Attach descendants remain'} or time.monotonic() >= end:
                        raise
                    time.sleep(.02)
            return {'fence_hash':digest(fence),'run_ids':[state['run']['run_id']],
                'process_groups':[state['run']['attach']['pgid']], 'active_process_group_count':0,
                'queue_fenced':True,'observed_at':datetime.now(timezone.utc).isoformat()}

    def _assert_empty(self, state):
        row, tree = self._closed(state)
        require(row['State']['Status'] == 'exited' and row['State']['Running'] is False and row['State']['Pid'] == 0,
            'Container is not terminal')
        require(not tree['processes'] and all(x['populated']=='0' and not x['pids'] for x in tree['groups'].values()), 'Contained descendants remain')
        run = state['run']
        current = self.kernel.process(run['attach_pid'])
        require(current is None or current['start_ticks'] != run['attach']['start_ticks'], 'Attach process remains')
        require(not self.kernel.group_alive(run['attach']['pgid']), 'Attach descendants remain')

    def validate_request(self, request):
        a = self.admission
        require(set(request) == {'request_id','request_hash','scope','binding_ids','expected_run_ids'}
            and request['scope'] == a['scope'] and request['binding_ids'] == a['observer']['binding_ids']
            and request['expected_run_ids'] == a['observer']['expected_run_ids'], 'Observer request differs from admission')
        require(re.fullmatch(r'tcwh_[a-f0-9]{32}',str(request['request_id']))
            and re.fullmatch('sha256:'+HEX,str(request['request_hash'])), 'Invalid authority request pin')

    def assert_closed_and_quiescent(self, request, proof):
        self.validate_request(request)
        a = self.admission
        with self._transaction() as (state,directory):
            fence = {k:request[k] for k in ('request_id','request_hash','scope')}
            require(state['fence'] == fence and proof['fence_hash'] == digest(fence)
                and proof['run_ids'] == a['observer']['expected_run_ids']
                and proof['process_groups'] == [state['run']['attach']['pgid']] and proof['queue_fenced'] is True,
                'Stored proof and durable fence differ')
            self._assert_empty(state)


class QualifiedStopObserver(StopObserver):
    def stop(self, authenticated_request, **kwargs):
        # Reject a foreign inventory BEFORE persisting a fence or stopping work.
        self.control.validate_request(authenticated_request)
        return super().stop(authenticated_request, **kwargs)


def observer(control, signer):
    """The actual candidate class; no alternative stop-ACK schema or verifier."""
    o = control.admission['observer']
    qualification = {k:o[k] for k in ('observer_id','program_sha256','host_id','workspace_id','request_key_id')}
    qualification['schema'] = 'trustchain.cowork.stop-observer-qualification.v1'
    return QualifiedStopObserver(control,qualification=qualification,signer=signer,containment=control)
