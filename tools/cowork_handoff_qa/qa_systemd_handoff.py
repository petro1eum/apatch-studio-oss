"""Native SDK in a private Linux root, with its own measured cgroup observer.

This is explicitly a systemd/namespace provider, not gVisor. The original
gVisor provider is unchanged. Frozen SDK judges additionally use Landlock.
"""
import json
import os
from pathlib import Path
import re
import shlex
import subprocess

import qa_handoff as q

SCHEMA='trustchain.cowork.systemd-handoff-host-admission.v1'


def validate(a):
    extra={'unit','root_directory','environment','rootfs_image'}
    base={k:v for k,v in a.items() if k not in extra}
    # Reuse exact observer, cgroup and scope validation without pretending this
    # is a Docker admission. Container-only placeholders never leave this call.
    base.update(schema=q.SCHEMA,container_id='0'*64,container_created='not-a-container',
                image=a['rootfs_image'],container_env_sha256=q.digest(a['environment']))
    q.validate_admission(base)
    q.require(a['schema']==SCHEMA and re.fullmatch(r'tc-cowork-native-[a-f0-9]{32}\.service',a['unit']),
              'Exact native systemd unit required')
    root=Path(a['root_directory'])
    q.require(root.is_absolute() and root.is_relative_to('/var/lib/trustchain-cowork-native-rootfs')
              and '..' not in root.parts,'Dedicated native root required')
    q.require(type(a['environment']) is dict and all(isinstance(k,str) and re.fullmatch(r'[A-Z_][A-Z0-9_]*',k)
              and isinstance(v,str) and '\0' not in v for k,v in a['environment'].items()),'Pinned environment required')
    return a


class Engine:
    def __init__(self,a):self.a=a
    def attach_start(self,unit):
        q.require(unit==self.a['unit'],'Different native unit')
        a=self.a
        properties={'RootDirectory':a['root_directory'],'WorkingDirectory':a['workspace'],
            'BindPaths':a['workspace']+':'+a['workspace'],'User':'1000','Group':'1000',
            'PrivateNetwork':'yes','PrivateDevices':'yes','NoNewPrivileges':'yes',
            'ProtectSystem':'strict','ProtectControlGroups':'yes','ProtectKernelTunables':'yes',
            'ProtectKernelModules':'yes','ProtectKernelLogs':'yes','ProtectClock':'yes',
            'CapabilityBoundingSet':'','AmbientCapabilities':'','RestrictSUIDSGID':'yes',
            'RestrictNamespaces':'yes','LockPersonality':'yes','MountAPIVFS':'yes',
            'KillMode':'control-group','Restart':'no','Slice':a['cgroup_parent'],
            'MemoryMax':str(a['memory_bytes']),'TasksMax':str(a['pids_limit'])}
        argv=['/usr/bin/systemd-run','--quiet','--pipe','--wait','--unit='+unit]
        for k,v in properties.items():argv+=['--property='+k+'='+v]
        for k,v in a['environment'].items():argv+=['--setenv='+k+'='+v]
        return subprocess.Popen([*argv,*a['argv']],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,text=True,bufsize=1,start_new_session=True,
            env={'PATH':'/usr/sbin:/usr/bin:/sbin:/bin'},cwd='/')
    def stop(self,unit,timeout):
        q.require(unit==self.a['unit'],'Different native unit')
        subprocess.run(['/usr/bin/systemctl','stop',unit],check=True,timeout=timeout+10,
            stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)


class Control(q.ContainerControl):
    @property
    def execution_id(self):return self.admission['unit']

    def _inspect(self):
        a=self.admission
        q.trusted(a['root_directory'],directory=True)
        q.require(q.load_json(Path(a['root_directory']).parent/'image.json')['image']==a['rootfs_image'],
                  'Native root image changed')
        names=['LoadState','ActiveState','SubState','MainPID','InvocationID','NRestarts','User','Group',
            'RootDirectory','WorkingDirectory','PrivateNetwork','PrivateDevices','NoNewPrivileges',
            'ProtectSystem','ProtectControlGroups','CapabilityBoundingSet','AmbientCapabilities',
            'RestrictNamespaces','KillMode','Restart','MemoryMax','TasksMax','ControlGroup','Transient',
            'Environment','ExecStart','BindPaths']
        r=subprocess.run(['/usr/bin/systemctl','show',a['unit'],*['--property='+n for n in names]],
            capture_output=True,text=True,timeout=10)
        props=dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
        if props.get('LoadState')=='not-found':
            done=Path(self.directory)/'native-terminal.json'
            if done.exists():
                result=q.load_json(done)
                q.require(result['admission_hash']==q.digest(a),'Native completion changed')
                return {'State':{'Status':'exited','Running':False,'Pid':0,'StartedAt':result['started_at']},'RestartCount':0}
            return {'State':{'Status':'created','Running':False,'Pid':0,'StartedAt':''},'RestartCount':0}
        expected={'LoadState':'loaded','User':'1000','Group':'1000','RootDirectory':a['root_directory'],
            'WorkingDirectory':a['workspace'],'PrivateNetwork':'yes','PrivateDevices':'yes','NoNewPrivileges':'yes',
            'ProtectSystem':'strict','ProtectControlGroups':'yes','CapabilityBoundingSet':'','AmbientCapabilities':'',
            'KillMode':'control-group','Restart':'no','MemoryMax':str(a['memory_bytes']),
            'TasksMax':str(a['pids_limit']),'Transient':'yes','NRestarts':'0'}
        q.require(all(props.get(k)==v for k,v in expected.items()),'Native unit isolation changed')
        observed=dict(part.split('=',1) for part in shlex.split(props.get('Environment','')))
        q.require(observed==a['environment'],'Native unit environment changed')
        q.require(('argv[]='+' '.join(a['argv'])+' ;') in props.get('ExecStart',''),
                  'Native unit command changed')
        q.require(props.get('BindPaths') in (a['workspace']+':'+a['workspace'],
                  a['workspace']+':'+a['workspace']+':rbind'), 'Native workspace mount changed')
        q.require(props.get('RestrictNamespaces') in ('yes','~cgroup ipc net mnt pid user uts time','~cgroup ipc net mnt pid user uts'),
                  'Native unit namespaces changed')
        pid=int(props.get('MainPID','0'));running=pid>0
        if running:
            q.require(('/sys/fs/cgroup'+props['ControlGroup']).startswith(a['cgroup_root']+'/'),
                      'Native unit left the admitted cgroup')
        return {'State':{'Status':'running' if running else 'exited','Running':running,'Pid':pid,
                         'StartedAt':props['InvocationID']},'RestartCount':int(props['NRestarts'])}

    def record_exit(self,code):
        # Called only by the pinned root CLI after waiting on its actual child.
        with self._transaction() as (state,directory):
            q.require(state['run'] and state['run']['phase']=='running','Unobserved native launch')
            tree=self.kernel.tree()
            q.require(not tree['processes'] and all(x['populated']=='0' for x in tree['groups'].values()),
                      'Native descendants remain after completion')
            value={'admission_hash':q.digest(self.admission),'started_at':state['run']['started_at'],
                   'exit_code':int(code),'backend':'linux-systemd-namespace-landlock'}
            directory.write_json('native-terminal.json',value)
