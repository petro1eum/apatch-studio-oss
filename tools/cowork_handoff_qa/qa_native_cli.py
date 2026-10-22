#!/usr/bin/env python3
"""Explicit headless QA entry. Uses the enrolled workspace's existing native key.

Keep this process alive while root admits the allocated run. Then enter status,
stop or quit. There is no browser route and no command creates a signing key.
"""
import argparse
import json
from pathlib import Path
import sys

from apatch_studio.exact_contract_handoffs import ExactContractTrust
from apatch_studio.work_handoff_delivery import WorkHandoffDelivery
from qa_native_lifecycle import create_session, QaConfirmation


def emit(kind, **data):
    print(json.dumps({'schema': 'trustchain.cowork.qa-native-session.v1', 'event': kind, **data},
                     sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--trust-file', type=Path, required=True)
    mode=parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--bundle', type=Path)
    mode.add_argument('--retry-run', help='Actual failed native run; allocate a normal exact retry')
    mode.add_argument('--resume-stop', help='Retained exact handoff ID; cannot launch a new run')
    parser.add_argument('--requirement')
    parser.add_argument('--state-root', type=Path, required=True)
    args = parser.parse_args()
    trust = ExactContractTrust.from_path(args.trust_file)
    runs, exact, observer = create_session(args.workspace, trust=trust, state_root=args.state_root)
    try:
        if args.resume_stop is not None:
            if args.requirement is not None:
                parser.error('--resume-stop does not accept a new requirement')
            handoff_id = args.resume_stop
            run = observer.control.restore_observer(handoff_id)
            run_id = run['run_id']
            emit('existing_stop_session', run=run)
        elif args.retry_run is not None:
            if args.requirement is not None:
                parser.error('--retry-run preserves the existing exact requirement')
            rows = exact._update(lambda rows: [r for r in rows
                if r['status'] == 'consumed' and exact._delivery_attempt(r) is not None
                and exact._delivery_attempt(r)['run_id'] == args.retry_run])
            if len(rows) != 1:
                parser.error('--retry-run needs one retained exact native association')
            row = rows[0]
            handoff_id = row['handoff_id']
            # The unchanged native manager enforces retryable parent and current
            # exact/source guard; no caller chooses a new run identity.
            selected = runs.retry(args.retry_run)
            run_id = selected['run_id']
            emit('awaiting_root_admission', run=runs.get(run_id),
                 binding_id=row['ack']['native_binding']['binding_id'], workspace_id=exact.workspace_id)
        else:
            if args.requirement is None:
                parser.error('--bundle requires --requirement')
            imported = exact.import_raw(args.bundle.read_bytes())
            handoff_id = imported['handoff_id']
            selected = exact.confirm_for_delivery(handoff_id, QaConfirmation(
                confirmed=True, workspace_id=exact.workspace_id, requirement=args.requirement))
            run_id = selected['run_id']
            row = exact._update(lambda rows: exact._find(rows, handoff_id))
            emit('awaiting_root_admission', run=runs.get(run_id),
                 binding_id=row['ack']['native_binding']['binding_id'], workspace_id=exact.workspace_id)
        delivery = WorkHandoffDelivery(exact, observer)
        for line in sys.stdin:
            command = line.strip()
            if command == 'quit':
                break
            if command == 'status':
                emit('status', run=runs.get(run_id), root_admitted=observer.qualification is not None)
            elif command == 'stop':
                try:
                    result = delivery.stop(handoff_id, {'workspace_id': exact.workspace_id})
                    emit('stop_delivered', result=result)
                except Exception as exc:
                    # Exact current server query is public scope/inventory, not a secret.
                    # Operator retains it under root ownership before repeating stop.
                    emit('stop_pending', reason=type(exc).__name__, reason_detail=str(exc), authority_query=observer.last_query)
            else:
                emit('command_rejected', allowed=['status', 'stop', 'quit'])
    finally:
        runs.close()
        # Closing the SSH client is NEVER treated as proof of remote containment.
        emit('session_closed', remote_stop_requires_root_observation=True)


if __name__ == '__main__':
    main()
