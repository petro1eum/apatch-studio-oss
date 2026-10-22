"""Fail-closed native stop observer candidate; NOT a performer-key attestation.

No observer signer is installed by this module. Production admission must bind a
restricted observer identity to this program, host, workspace and process registry.
Every controlled spawn and fence shares the same durable lock. Existing/untracked
runs are never inferred stopped from a UI state or from a runner's exit code.
"""
from __future__ import annotations

import copy
try:
    import fcntl
except ImportError:  # importing the disabled candidate remains safe on Windows
    fcntl = None
import hashlib
import json
import os
import re
import signal
import subprocess
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from apatch_studio.state_io import StateDirectory

SCHEMA = 'apatch.studio.handoff-process-control.v1'
ACK_SCHEMA = 'trustchain.cowork.handoff-stop-ack.v1'
SCOPE_KEYS = {'tenant_id', 'project_group_id', 'work_item_id'}


class StopUnavailable(RuntimeError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return 'sha256:' + hashlib.sha256(canonical(value)).hexdigest()


def scope_key(scope):
    if (not isinstance(scope, dict) or set(scope) != SCOPE_KEYS
            or not isinstance(scope['tenant_id'], str) or not 1 <= len(scope['tenant_id']) <= 128
            or not re.fullmatch(r'tcpg_[a-f0-9]{32}', str(scope['project_group_id']))
            or not re.fullmatch(r'tcpwi_[a-f0-9]{32}', str(scope['work_item_id']))):
        raise StopUnavailable('Invalid stop scope')
    return digest(scope)


def _identity(pid):
    """Kernel process identity used only to avoid signalling a reused PID."""
    result = subprocess.run(['/bin/ps', '-p', str(pid), '-o', 'lstart=', '-o', 'pgid='],
                            capture_output=True, text=True, timeout=2, check=False)
    value = result.stdout.strip()
    if result.returncode != 0 or not value:
        return None
    return value


def _group_exists(pgid):
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # inability to inspect never means stopped


class ControlledProcesses:
    """POSIX-only candidate. Instantiate only for a qualified host/workspace."""
    def __init__(self, state_directory):
        if os.name != 'posix' or fcntl is None:
            raise StopUnavailable('This stop observer requires qualified POSIX process control')
        self.directory = Path(state_directory).absolute()

    @contextmanager
    def _transaction(self):
        with StateDirectory(self.directory, create=True) as directory:
            fd = os.open('work-handoff-stop.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW,
                         0o600, dir_fd=directory.fd)
            try:
                directory._regular(os.fstat(fd))
                fcntl.flock(fd, fcntl.LOCK_EX)
                try:
                    state = directory.read_json('work-handoff-stop.json', limit=4 * 1024 * 1024)
                except FileNotFoundError:
                    state = {'schema': SCHEMA, 'fences': {}, 'runs': {}}
                if (not isinstance(state, dict) or set(state) != {'schema', 'fences', 'runs'}
                        or state['schema'] != SCHEMA or not isinstance(state['fences'], dict)
                        or not isinstance(state['runs'], dict) or len(state['runs']) > 4096):
                    raise StopUnavailable('Native process registry is unavailable')
                yield state
                directory.write_json('work-handoff-stop.json', state)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

    def spawn(self, scope, run_id, start):
        """The actual Popen factory executes under the same lock as the fence."""
        key = scope_key(scope)
        if not re.fullmatch(r'apr_[a-f0-9]{32}', str(run_id)):
            raise StopUnavailable('Invalid native run identity')
        with self._transaction() as state:
            if key in state['fences']:
                raise StopUnavailable('This work is permanently fenced for handoff')
            if run_id in state['runs'] or len(state['runs']) >= 4096:
                raise StopUnavailable('Run identity is reused or process registry is full')
            # A crash in the Popen/registration window leaves an uncertain record
            # that blocks every stop ACK. It cannot disappear on restart.
            state['runs'][run_id] = {'scope': scope, 'pid': None, 'pgid': None, 'identity': None}
            with StateDirectory(self.directory) as directory:
                directory.write_json('work-handoff-stop.json', state)
            process = start()
            try:
                pgid = os.getpgid(process.pid)
                identity = _identity(process.pid)
                if pgid != process.pid or identity is None:
                    raise StopUnavailable('Runner has no independently tracked process group')
                state['runs'][run_id] = {'scope': copy.deepcopy(scope), 'pid': process.pid,
                                         'pgid': pgid, 'identity': identity}
                with StateDirectory(self.directory) as directory:
                    directory.write_json('work-handoff-stop.json', state)
            except BaseException:
                try:
                    process.terminate()
                except OSError:
                    pass
                raise
            return process

    def fence_and_drain(self, scope, request_id, request_hash, *, timeout=5.0):
        if not 0 <= timeout <= 30:
            raise StopUnavailable('Stop deadline is outside the bounded profile')
        key = scope_key(scope)
        if (not re.fullmatch(r'tcwh_[a-f0-9]{32}', str(request_id))
                or not re.fullmatch(r'sha256:[a-f0-9]{64}', str(request_hash))):
            raise StopUnavailable('Invalid handoff request pin')
        fence = {'request_id': request_id, 'request_hash': request_hash, 'scope': scope}
        with self._transaction() as state:
            previous = state['fences'].get(key)
            if previous is not None and previous != fence:
                raise StopUnavailable('An existing handoff fence cannot be replaced')
            state['fences'][key] = copy.deepcopy(fence)
            runs = {rid: copy.deepcopy(row) for rid, row in state['runs'].items() if row['scope'] == scope}
        # The fence is on disk before any signal. New/queued/restarted launches
        # using this control are denied even when cancellation or ACK delivery fails.
        for row in runs.values():
            if row['pid'] is None or row['pgid'] is None or row['identity'] is None:
                raise StopUnavailable('A native spawn was interrupted before it could be observed')
            if _group_exists(row['pgid']):
                if _identity(row['pid']) != row['identity']:
                    raise StopUnavailable('Process identity changed; manual scoped recovery required')
                os.killpg(row['pgid'], signal.SIGTERM)
        deadline = time.monotonic() + timeout
        while any(_group_exists(row['pgid']) for row in runs.values()):
            if time.monotonic() >= deadline:
                raise StopUnavailable('Process descendants are still draining')
            time.sleep(min(0.025, max(0, deadline - time.monotonic())))
        with self._transaction() as state:
            actual = {rid: row for rid, row in state['runs'].items() if row['scope'] == scope}
            if actual != runs or state['fences'].get(key) != fence:
                raise StopUnavailable('Native fence or process inventory changed')
        return {'fence_hash': digest(fence), 'run_ids': sorted(runs),
                'process_groups': sorted(row['pgid'] for row in runs.values()),
                'active_process_group_count': 0, 'queue_fenced': True,
                'observed_at': datetime.now(timezone.utc).isoformat()}


class StopObserver:
    """Closed observer interface. No generic signer or client-supplied observation.

    ``qualification`` and ``signer`` come from the restricted host service, never
    a browser request, performer workspace or APatch client key. This candidate
    deliberately has no default production qualification/signing implementation.
    """
    def __init__(self, control, *, qualification=None, signer=None, containment=None):
        self.control, self.qualification, self.signer = control, qualification, signer
        self.containment = containment

    def stop(self, authenticated_request, *, timeout=5.0, accepted_ack_hash=None):
        # The independently installed service is the only owner of this state.
        # Serialize ACK observation/signing so retries reuse exact persisted bytes.
        if self.qualification is None or self.signer is None or self.containment is None:
            raise StopUnavailable("Qualified native stop observer is not installed")
        with StateDirectory(self.control.directory, create=True) as directory:
            fd=os.open("handoff-observer.lock",os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600,dir_fd=directory.fd)
            try:
                directory._regular(os.fstat(fd))
                fcntl.flock(fd,fcntl.LOCK_EX)
                return self._stop(authenticated_request,timeout=timeout,accepted_ack_hash=accepted_ack_hash)
            finally:
                fcntl.flock(fd,fcntl.LOCK_UN)
                os.close(fd)

    def _stop(self, authenticated_request, *, timeout=5.0, accepted_ack_hash=None):
        q = self.qualification
        if q is None or self.signer is None or self.containment is None:
            raise StopUnavailable('Qualified native stop observer is not installed')
        expected = {'schema', 'observer_id', 'program_sha256', 'host_id', 'workspace_id', 'request_key_id'}
        if set(q) != expected or q['schema'] != 'trustchain.cowork.stop-observer-qualification.v1':
            raise StopUnavailable('Native observer qualification is invalid')
        request = copy.deepcopy(authenticated_request)
        if set(request) != {'request_id', 'request_hash', 'scope', 'binding_ids', 'expected_run_ids'}:
            raise StopUnavailable('Stop request must come from the exact authenticated authority')
        if accepted_ack_hash is not None and not re.fullmatch(r'sha256:[a-f0-9]{64}',str(accepted_ack_hash)):
            raise StopUnavailable('Invalid server acknowledgement pin')
        ack_name = 'handoff-ack-' + hashlib.sha256(canonical(request)).hexdigest() + '.json'
        with StateDirectory(self.control.directory, create=True) as directory:
            try:
                read_name=('handoff-ack-history-'+accepted_ack_hash[7:]+'.json') if accepted_ack_hash else ack_name
                prior = directory.read_json(read_name, limit=256*1024)
            except FileNotFoundError:
                prior = None
        if accepted_ack_hash and (prior is None or digest(prior)!=accepted_ack_hash):
            raise StopUnavailable('The server acknowledgement is absent from immutable local history')
        if prior is not None:
            if any(prior.get(k) != v for k,v in request.items()) or any(prior.get(k) != v for k,v in q.items() if k != 'schema'):
                raise StopUnavailable('Stored stop acknowledgement changed')
            self.containment.assert_closed_and_quiescent(request, prior)
            observed=datetime.fromisoformat(prior['observed_at'].replace('Z','+00:00'))
            if accepted_ack_hash or datetime.now(timezone.utc)-observed < timedelta(minutes=4):
                return prior
            # A first delivery can be lost or delayed. Re-observe the still-closed
            # containment only when the authenticated server has no ACK. Each
            # signed observation remains addressable by its immutable hash.
        proof = self.control.fence_and_drain(request['scope'], request['request_id'], request['request_hash'], timeout=timeout)
        if proof['run_ids'] != request['expected_run_ids']:
            raise StopUnavailable('Native run inventory is incomplete or mismatched')
        # A process-group drain alone cannot observe descendants that called setsid.
        # Only a separately qualified host containment service can close this gate.
        # No implementation is enabled by this candidate or by browser parameters.
        self.containment.assert_closed_and_quiescent(request, proof)
        body = {'schema': ACK_SCHEMA, **q, **request,
                **{k:v for k,v in proof.items() if k != 'active_process_group_count'},
                'active_operation_count':0}
        body['schema'] = ACK_SCHEMA
        signature = self.signer(canonical(body))
        if not isinstance(signature, dict) or set(signature) != {'algorithm', 'key_id', 'value'}:
            raise StopUnavailable('Qualified observer signing failed')
        ack = {**body, 'signature': signature}
        with StateDirectory(self.control.directory) as directory:
            directory.write_json('handoff-ack-history-'+digest(ack)[7:]+'.json',ack)
            directory.write_json(ack_name, ack)
        return ack
