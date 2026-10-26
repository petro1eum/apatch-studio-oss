"""Explicit source-bound export through the native Avatar compiler."""
import copy
from datetime import datetime,timezone
from apatch.avatar_evidence import build_evidence_bundle
from apatch_studio.exact_contract_delivery import SourceBoundExecutionContext
from apatch_studio.execution_source_declarations import check_company_execution_admission,publish_execution_source
from apatch_studio._contracts.execution_source_declaration import ExecutionSourceError


def _time(value):
    value=datetime.fromisoformat(value.replace('Z','+00:00'))
    if value.tzinfo is None:raise ExecutionSourceError('Native evidence time must be aware')
    return value.astimezone(timezone.utc)


def build_company_capability_evidence(manager,*,handoff_id,run_id):
    manager.build_for_delivery(handoff_id,run_id)
    row=manager._update(lambda rows:copy.deepcopy(manager._find(rows,handoff_id)))
    run=manager._delivery_attempt(row)
    if run is None or run['run_id']!=run_id or run['status']!='succeeded':
        raise ExecutionSourceError('The current successful native attempt is required')
    context=SourceBoundExecutionContext.model_validate(manager.delivery.selected(handoff_id)['context'])
    gate=check_company_execution_admission(manager,context)
    if gate['required'] is not True or gate['admitted'] is not True or gate['execution_permitted'] is not True:
        raise ExecutionSourceError('An exact Company source admission is required')
    declaration=publish_execution_source(manager,context)['declaration']
    if not run.get('started_at') or _time(run['started_at'])<_time(gate['admitted_at']):
        raise ExecutionSourceError('An execution completed before Company admission cannot be reused')
    # Native Core alone folds verified ContributionEvents into episodes and
    # adds this capsule before computing the bundle ID/signature.
    import inspect
    if 'execution_source_declaration' not in inspect.signature(build_evidence_bundle).parameters:
        raise ExecutionSourceError('Native exact-source Avatar compiler is unavailable')
    bundle=build_evidence_bundle(str(manager.workspace),execution_source_declaration=declaration)
    if not bundle['episodes']:raise ExecutionSourceError('No reviewable exact-source episodes are ready')
    if any(_time(e['occurred_at'])<_time(gate['admitted_at']) for e in bundle['episodes']):
        raise ExecutionSourceError('Every episode must follow its Company admission')
    return bundle
