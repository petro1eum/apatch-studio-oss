#!/usr/bin/env python3
"""Root-only, fixed installation. No server calls, create, delete or sign command.

The unprivileged performer delivers the returned ACK through the existing signed
native query/ack transport. Do not run the general Studio UI as root.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import stat
import sys

INSTALL = Path('/opt/trustchain-cowork-handoff-qa')
STATE = Path('/var/lib/trustchain-cowork-handoff-qa')
FILES = ('qa_handoff.py','qa_handoff_cli.py','studio/apatch_studio/__init__.py',
         'studio/apatch_studio/work_handoff_stop.py','studio/apatch_studio/state_io.py')


def protected(path, *, private=False, directory=False):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts: raise RuntimeError('Invalid installed path')
    for current in [*reversed(path.parents),path]:
        info = current.lstat()
        if info.st_uid != 0 or info.st_mode & 0o022 or stat.S_ISLNK(info.st_mode):
            raise RuntimeError('Installation must be root-owned and unlinked')
        if current != path or directory:
            if not stat.S_ISDIR(info.st_mode): raise RuntimeError('Non-directory installed ancestor')
        elif not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise RuntimeError('Nonregular installed file')
    if private and info.st_mode & 0o077: raise RuntimeError('Private file permissions required')
    return path


def public_admission():
    if os.geteuid() != 0: raise RuntimeError('Root-only installation; no caller-supplied authority')
    if not sys.flags.isolated or not sys.flags.dont_write_bytecode:
        raise RuntimeError('Run this fixed CLI with python -I -B')
    protected(Path(sys.executable).resolve())
    protected(STATE,directory=True,private=True)
    manifest=json.loads(protected(STATE/'installation.json').read_bytes())
    if set(manifest) != {'schema','files','program_sha256'} or manifest['schema'] != 'trustchain.cowork.qa-handoff-installation.v1' or set(manifest['files']) != set(FILES):
        raise RuntimeError('Exact installed program inventory required')
    for name,pin in manifest['files'].items():
        raw=protected(INSTALL/name).read_bytes()
        if 'sha256:'+hashlib.sha256(raw).hexdigest()!=pin: raise RuntimeError('Installed observer code changed')
    canonical=lambda v:json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    if 'sha256:'+hashlib.sha256(canonical(manifest['files'])).hexdigest()!=manifest['program_sha256']:
        raise RuntimeError('Observer package digest mismatch')
    sys.path[:0]=[str(INSTALL),str(INSTALL/'studio')]
    core=importlib.import_module('qa_handoff')
    admission=core.load_json(STATE/'admission.json')
    if admission['observer']['program_sha256']!=manifest['program_sha256']:
        raise RuntimeError('Observer admission names another program')
    return core,core.validate_admission(admission)


def signer(admission):
    """Only StopObserver calls this after measuring closure; never a generic API."""
    def sign(raw):
        body=json.loads(raw)
        if (body.get('schema')!='trustchain.cowork.handoff-stop-ack.v1'
                or body.get('scope')!=admission['scope'] or body.get('active_operation_count')!=0
                or body.get('queue_fenced') is not True
                or body.get('run_ids')!=admission['observer']['expected_run_ids']):
            raise RuntimeError('Signing is restricted to the measured admitted stop')
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding,PublicFormat
        # Existing 32-byte raw key provisioned separately by the operator.
        # There is deliberately no generation, import or arbitrary key-path option.
        seed=protected(STATE/'observer.ed25519',private=True).read_bytes()
        if len(seed)!=32: raise RuntimeError('Expected externally provisioned Ed25519 seed')
        key=Ed25519PrivateKey.from_private_bytes(seed)
        public=key.public_key().public_bytes(Encoding.Raw,PublicFormat.Raw)
        encoded=base64.urlsafe_b64encode(public).rstrip(b'=').decode()
        if encoded!=admission['observer']['public_key']: raise RuntimeError('Provisioned observer public pin differs')
        return {'algorithm':'Ed25519','key_id':'sha256:'+hashlib.sha256(public).hexdigest(),
                'value':base64.urlsafe_b64encode(key.sign(raw)).rstrip(b'=').decode()}
    return sign


def main():
    parser=argparse.ArgumentParser(description=__doc__,allow_abbrev=False)
    parser.add_argument('operation',choices=['start','stop','status','admission'])
    parser.add_argument('--request-id')
    parser.add_argument('--run-id')
    parser.add_argument('--admission-sha256')
    parser.add_argument('--request-sha256')
    parser.add_argument('--acknowledgement-sha256')
    args=parser.parse_args()
    core,admission=public_admission()
    if args.operation in {'admission','status'} and any((args.request_id,args.run_id,args.admission_sha256,args.request_sha256,args.acknowledgement_sha256)):
        raise RuntimeError('No pins accepted on public diagnostic operations')
    if args.operation=='admission':
        print(json.dumps(admission,sort_keys=True))
        return
    core.trusted(admission['cgroup_root'],directory=True)
    kernel=core.LinuxKernel(admission['cgroup_root'])
    control=core.ContainerControl(admission,STATE,core.DockerEngine(),kernel)
    if args.operation=='start':
        if any((args.request_id,args.request_sha256,args.acknowledgement_sha256)):
            raise RuntimeError('No stop request fields on start')
        if args.run_id!=admission['observer']['expected_run_ids'][0] or args.admission_sha256!=core.digest(admission):
            raise RuntimeError('Start must match the actual native run and root admission')
        prompt=sys.stdin.read(65537)
        if len(prompt.encode('utf-8'))>65536: raise RuntimeError('Native prompt exceeds QA limit')
        process=control.spawn(admission['scope'],admission['observer']['expected_run_ids'][0],
            lambda:control.popen(admission['argv'],cwd=admission['workspace'],shell=False,start_new_session=True))
        if process.stdin is not None:
            process.stdin.write(prompt);process.stdin.close()
        # Drain attach stdout so the immutable admitted process cannot block on it.
        for line in process.stdout:
            sys.stdout.write(line);sys.stdout.flush()
        raise SystemExit(process.wait())
    if args.operation=='status':
        if args.request_id is not None: raise RuntimeError('No request fields on status')
        with control._transaction() as (state,directory):
            # This is diagnostic only: it does not infer stopped or create an ACK.
            print(json.dumps({'schema':'trustchain.cowork.qa-handoff-status.v1',
                'run_registered':state['run'] is not None,'fenced':state['fence'] is not None,
                'container_state':control._inspect()['State']['Status']}))
        return
    if args.run_id is not None or args.admission_sha256 is not None:
        raise RuntimeError('No launch fields on stop')
    if not re.fullmatch(r'tcwh_[a-f0-9]{32}',args.request_id or ''):
        raise RuntimeError('Exact provisioned request ID required')
    envelope=core.load_json(STATE/(args.request_id+'.authority.json'))
    if set(envelope)!={'schema','request','acknowledgement_hash'} or envelope['schema']!='trustchain.cowork.qa-handoff-authority-query.v1':
        raise RuntimeError('Root-retained current native query required')
    request=envelope['request']
    if request['request_id']!=args.request_id: raise RuntimeError('Authority request ID changed')
    if args.request_sha256!=core.digest(request) or args.acknowledgement_sha256!=core.digest(envelope['acknowledgement_hash']):
        raise RuntimeError('Native query differs from the root-retained current authority')
    result=core.observer(control,signer(admission)).stop(request,accepted_ack_hash=envelope['acknowledgement_hash'])
    print(json.dumps(result,sort_keys=True))


if __name__=='__main__':
    main()
