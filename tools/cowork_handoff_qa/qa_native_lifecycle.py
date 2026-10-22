"""Operator-only adapter for ONE new exact native run on the fixed Linux host.

Run allocation, journals, native acceptance and signed association remain in
Studio. This module cannot create admissions, keys, containers, bindings or ACKs.
It is not imported by the browser API and adds no ordinary runner choice.
"""
from __future__ import annotations
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import time
from typing import Literal

from apatch_studio.agent_runs import AgentRunManager, RunStateError, execution_source_artifacts
from apatch_studio.exact_contract_handoffs import ExactContractConfirmation, ExactContractManager
from apatch_studio.operations import AgentRunRequest
from apatch_studio.work_handoff_stop import StopUnavailable, digest
from qa_handoff import validate_admission

RUNNER = 'cowork_stop_qa'
ARGV = ['/usr/local/bin/python', '-I', '-B', '-u', '/opt/cowork-qa/work.py']
ROOT_COMMAND = ['/usr/bin/sudo', '-n', '/usr/bin/python3', '-I', '-B',
                '/opt/trustchain-cowork-handoff-qa/qa_handoff_cli.py']


class QaRunRequest(AgentRunRequest):
    mode: Literal['requirement'] = 'requirement'
    runner: Literal['cowork_stop_qa'] = RUNNER


class QaConfirmation(ExactContractConfirmation):
    runner_id: Literal['cowork_stop_qa'] = RUNNER


class FixedSshTransport:
    """No host, executable, environment, container or arbitrary command input."""
    @staticmethod
    def command(operation, **pins):
        shapes = {'admission': set(), 'start': {'run_id', 'admission_sha256'},
                  'stop': {'request_id', 'request_sha256', 'acknowledgement_sha256'}}
        if operation not in shapes or set(pins) != shapes[operation]:
            raise StopUnavailable('Unknown fixed Linux operation')
        argv = ['/usr/bin/ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=10',
                'hc-server', *ROOT_COMMAND, operation]
        for field, value in pins.items():
            pattern = r'apr_[a-f0-9]{32}' if field == 'run_id' else (
                r'tcwh_[a-f0-9]{32}' if field == 'request_id' else r'sha256:[a-f0-9]{64}')
            if not re.fullmatch(pattern, str(value)):
                raise StopUnavailable('Invalid exact Linux command pin')
            argv.extend(['--' + field.replace('_', '-'), value])
        return argv

    @staticmethod
    def environment():
        # SSH uses the explicitly configured hc-server alias and host verification.
        return {'PATH': '/usr/bin:/bin:/usr/sbin:/sbin', 'HOME': str(Path.home())}

    def call(self, operation, **pins):
        result = subprocess.run(self.command(operation, **pins), capture_output=True,
            text=True, timeout=15, env=self.environment(), cwd='/')
        if result.returncode != 0 or len(result.stdout.encode()) > 256 * 1024:
            raise StopUnavailable('Fixed Linux operation is unavailable')
        try:
            return json.loads(result.stdout)
        except ValueError as exc:
            raise StopUnavailable('Invalid fixed Linux response') from exc

    def start(self, run_id, admission_sha256):
        return subprocess.Popen(self.command('start', run_id=run_id, admission_sha256=admission_sha256),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding='utf-8', errors='replace', bufsize=1,
            shell=False, start_new_session=True, env=self.environment(), cwd='/')


class RemoteControl:
    """Existing lifecycle's spawn callback; no run allocator or pending registry."""
    def __init__(self, *, transport=None, wait_seconds=240):
        if not 0 < wait_seconds <= 240:
            raise ValueError('Admission wait must fit the current five-minute native transfer')
        self.transport = transport or FixedSshTransport()
        self.wait_seconds = wait_seconds
        self.manager = self.exact = None
        self.admission = None
        self._ticket = threading.local()

    def bind(self, manager, exact):
        if self.manager is not None or exact.run_manager is not manager:
            raise StopUnavailable('A control belongs to one native manager')
        self.manager, self.exact = manager, exact

    def _current(self, scope, run_id, *, revalidate, for_stop=False):
        if self.manager is None or self.exact is None:
            raise StopUnavailable('Canonical native lifecycle is not attached')
        with self.manager._lock:
            record = self.manager._record(run_id)
            if not for_stop and (record.cancel_requested or record.done.is_set() or self.manager._closed):
                raise StopUnavailable('Native dispatch was cancelled or interrupted')
            context, sdd, request = record.execution_context, record.sdd_execution, record.request
        if context is None or sdd is None or request.runner != RUNNER or scope != {
            name: getattr(context, name) for name in ('tenant_id', 'project_group_id', 'work_item_id')}:
            raise StopUnavailable('Native run has a different exact scope')
        if revalidate:
            bound = self.manager._guard_external_dispatch(request, context, sdd, stage='pre_popen')
            if bound is None:
                raise StopUnavailable('QA requires the actual full source-bound native acknowledgement')
            artifacts = execution_source_artifacts(self.manager._workspace, request, context,
                state_root=self.manager._store.state_root, source_binding_context=bound)
            self.manager._bind_execution_source_artifacts(ARGV, RUNNER, artifacts)
        rows = self.exact._update(lambda rows: copy.deepcopy(rows))
        matches = [r for r in rows if r['intent_id'] == context.intent_id
                   and r['status'] in ('consuming', 'consumed') and r.get('ack') is not None]
        if len(matches) != 1 or matches[0].get('run_id') not in (None, run_id):
            raise StopUnavailable('Run has no unique canonical native association')
        binding = matches[0]['ack']['native_binding']
        from apatch import governed_work_delivery as D
        config = D.load_config(str(self.manager._workspace))
        return {'workspace_id': self.exact.workspace_id, 'request_key_id': config['service_request_key_id'],
                'binding_ids': [binding['binding_id']], 'expected_run_ids': [run_id]}

    @staticmethod
    def _match(admission, scope, expected):
        value = validate_admission(admission)
        if value['scope'] != scope or value['argv'] != ARGV or any(
            value['observer'][k] != v for k, v in expected.items()):
            raise StopUnavailable('Root admission differs from the actual native run')
        return value

    def spawn(self, scope, run_id, start):
        expected = self._current(scope, run_id, revalidate=False)
        deadline = time.monotonic() + self.wait_seconds
        # The retained native journal already contains run_id and its exact scope.
        # Root reads that existing record when preparing its one-run admission.
        while True:
            self._current(scope, run_id, revalidate=False)
            try:
                admission = self.transport.call('admission')
            except StopUnavailable:
                if time.monotonic() >= deadline:
                    raise StopUnavailable('No root admission arrived for this native run')
                time.sleep(min(0.25, max(0, deadline-time.monotonic())))
                continue
            admission = self._match(admission, scope, expected)
            # Waiting for an operator never stretches a native admission's lifetime.
            if self._current(scope, run_id, revalidate=True) != expected:
                raise StopUnavailable('Native authority changed while awaiting Linux admission')
            self.admission = admission
            self._ticket.value = (run_id, digest(admission))
            try:
                return start()
            finally:
                self._ticket.value = None

    def restore_observer(self, handoff_id):
        """Resume only stop delivery from the existing immutable run/association."""
        if self.exact is None:
            raise StopUnavailable('Canonical native lifecycle is not attached')
        row = self.exact._update(lambda rows: copy.deepcopy(self.exact._find(rows, handoff_id)))
        self.exact._read_bundle(row, historical=True)
        if row['status'] != 'consumed' or row.get('run_id') is None:
            raise StopUnavailable('No existing admitted native run to observe')
        run = self.manager.get(row['run_id'])
        if run.get('execution_context') is None:
            raise StopUnavailable('The retained run has no exact context')
        scope = {k: run['execution_context'][k] for k in ('tenant_id', 'project_group_id', 'work_item_id')}
        expected = self._current(scope, row['run_id'], revalidate=False, for_stop=True)
        self.admission = self._match(self.transport.call('admission'), scope, expected)
        return run

    def popen(self, argv, **kwargs):
        ticket = getattr(self._ticket, 'value', None)
        if (ticket is None or list(argv) != ARGV or kwargs.get('shell') is not False
                or kwargs.get('start_new_session') is not True
                or Path(kwargs.get('cwd', '')).resolve() != self.manager._workspace):
            raise StopUnavailable('Linux launch is available only inside exact native spawn')
        # Host env/prompt/paths cannot change the fixed root command or image argv.
        return self.transport.start(*ticket)


class OperatorQaRunManager(AgentRunManager):
    request_model = QaRunRequest

    def __init__(self, workspace, *, control, state_root=None):
        self.qa_control = control
        super().__init__(workspace, max_concurrent=1, max_pending=1,
            state_root=state_root, handoff_process_control=control, popen=control.popen)

    def start(self, request, *, execution_context=None, sdd_execution=None, **kwargs):
        request = QaRunRequest.model_validate(request.model_dump() if isinstance(request, AgentRunRequest) else request)
        if execution_context is None or sdd_execution is None or self._external_dispatch_guard is None:
            raise RunStateError('Operator QA requires the current exact native contract')
        return super().start(request, execution_context=execution_context, sdd_execution=sdd_execution, **kwargs)

    def _runner_command(self, request):
        if not isinstance(request, QaRunRequest):
            raise RunStateError('Only the explicit operator QA runner is supported')
        return list(ARGV)

    def _bind_execution_source_artifacts(self, argv, runner, artifacts):
        if list(argv) != ARGV or runner != RUNNER:
            raise RunStateError('Only the fixed QA work command may be dispatched')
        # The inherited resolver has verified these references against the current
        # source binding. Fixed QA work performs no external reads and needs no MCP.
        # Retaining references in its ordinary native prompt does not claim use.
        return list(ARGV)

    def runners(self):
        return [{'id': RUNNER, 'label': 'Operator Linux stop QA', 'available': True}]


class RemoteObserver:
    """Existing WorkHandoffDelivery interface; root alone measures and signs."""
    def __init__(self, control):
        self.control = control
        self.last_query = None
        self.containment = self  # marker: implementation is root's measured container control

    @property
    def qualification(self):
        admission = self.control.admission
        return None if admission is None else copy.deepcopy(admission['observer'])

    def stop(self, authenticated_request, *, accepted_ack_hash=None):
        request = authenticated_request
        admission = self.control.admission
        if admission is None or set(request) != {'request_id', 'request_hash', 'scope', 'binding_ids', 'expected_run_ids'}:
            raise StopUnavailable('No matching exact server stop request')
        if request['scope'] != admission['scope'] or any(request[k] != admission['observer'][k]
                for k in ('binding_ids', 'expected_run_ids')):
            raise StopUnavailable('Stop request belongs to another native run')
        self.last_query = {'schema': 'trustchain.cowork.qa-handoff-authority-query.v1',
                           'request': copy.deepcopy(request), 'acknowledgement_hash': accepted_ack_hash}
        # Root compares the complete retained native query; none of these pins is authority.
        ack = self.control.transport.call('stop', request_id=request['request_id'],
            request_sha256=digest(request), acknowledgement_sha256=digest(accepted_ack_hash))
        for key in ('request_id', 'request_hash', 'scope', 'binding_ids', 'expected_run_ids'):
            if ack.get(key) != request[key]:
                raise StopUnavailable('Root acknowledgement differs from the native request')
        # The unchanged Platform route checks root's signature and all claims.
        return ack


def create_session(workspace, *, trust, state_root=None, transport=None, **exact_options):
    control = RemoteControl(transport=transport)
    runs = OperatorQaRunManager(workspace, control=control, state_root=state_root)
    try:
        exact = ExactContractManager(workspace, run_manager=runs, trust=trust,
            state_root=state_root, run_request_model=QaRunRequest, **exact_options)
        control.bind(runs, exact)
    except BaseException:
        runs.close()
        raise
    return runs, exact, RemoteObserver(control)
