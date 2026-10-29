"""A bound operation waits before starting, without borrowing a completed run."""
import copy
from datetime import datetime,timezone,timedelta
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from apatch import governed_work as G
from apatch_studio.exact_contract_handoffs import ExactContractManager
from apatch_studio.execution_intents import ExecutionIntentError

@pytest.fixture
def waiting(tmp_path,monkeypatch):
    # This fixture starts AFTER native binding/receipt verification. Native
    # Ed25519 receipt validation has separate real-document tests.
    manager=ExactContractManager.__new__(ExactContractManager)
    manager.workspace=tmp_path;manager.workspace_id='0'*32
    now=datetime(2026,10,23,16,tzinfo=timezone.utc);manager.clock=lambda:now+timedelta(minutes=10)
    row=dict(handoff_id='tceh_'+'1'*32,intent_id='tcapsei_'+'2'*32,status='awaiting_company',requirement='SPEC-CONTROL#R1',
        run_id=None,bundle_hash='sha256:'+'3'*64,ack={'retained':'original'},facts={'change_id':'apchg_'+'4'*32},
        company_waiting=True,company_runner='codex')
    manager._update=lambda fn:copy.deepcopy(fn([row]))
    manager._find=lambda rows,identity:rows[0]
    proposal=dict(intent_id=row['intent_id'],tenant_id='11111111-1111-4111-8111-111111111111',project_group_id='tcpg_'+'5'*32,
        work_item_id='tcpwi_'+'6'*32,work_item_hash='sha256:'+'7'*64,authority_version=1,work_program_id='tcwp_'+'8'*32,
        work_program_hash='sha256:'+'9'*64,objective='TEST ONLY already admitted operation')
    def read(chosen,*,historical=False):
        assert historical is True and chosen['ack']=={'retained':'original'}
        return {'legacy_intent':proposal}
    manager._read_bundle=read
    manager._preflight=lambda *a,**kw:SimpleNamespace(spec_id='SPEC-CONTROL',requirement_id='R1')
    manager._company_admission_enabled=lambda:True
    source=SimpleNamespace(canonical_binding_id='tcawieb_'+'a'*32,source_binding_id='tcpsb_'+'b'*32)
    monkeypatch.setattr('apatch_studio.exact_contract_handoffs.SourceBoundExecutionContext.model_validate',lambda v:source)
    manager.delivery=SimpleNamespace(selected=lambda identity:{'context':{'TEST':'retained source'}})
    monkeypatch.setattr(G,'load_change',lambda *args:{'TEST':'original change'})
    gate=Mock(return_value={'required':True,'admitted':False,'execution_permitted':False})
    monkeypatch.setattr('apatch_studio.execution_source_declarations.check_company_execution_admission',gate)
    manager.run_request_model=lambda **kw:SimpleNamespace(**kw)
    manager.run_manager=SimpleNamespace(start=Mock(return_value={'run_id':'apr_'+'c'*32}),list=lambda:[],get=Mock())
    confirmation=SimpleNamespace(workspace_id=manager.workspace_id,requirement=row['requirement'],runner_id='codex')
    return manager,row,gate,confirmation


def test_no_company_admission_never_starts_a_run(waiting):
    manager,row,gate,confirmation=waiting
    assert manager._confirm(row['handoff_id'],confirmation,for_delivery=True)['status']=='awaiting_company'
    manager.run_manager.start.assert_not_called()
    assert row['run_id'] is None and row['ack']=={'retained':'original'}


def test_same_operation_can_continue_after_short_handoff_expiry(waiting):
    manager,row,gate,confirmation=waiting
    gate.return_value={'required':True,'admitted':True,'execution_permitted':True}
    before=copy.deepcopy(row['ack'])
    result=manager._confirm(row['handoff_id'],confirmation,for_delivery=True)
    assert result['run_id']=='apr_'+'c'*32 and result['status']=='consumed'
    assert row['ack']==before and manager.run_manager.start.call_count==1


@pytest.mark.parametrize('field,value',[('runner_id','claude'),('requirement','SPEC-CONTROL#R2'),('workspace_id','f'*32)])
def test_company_wait_cannot_change_original_execution_choice(waiting,field,value):
    manager,row,gate,confirmation=waiting
    setattr(confirmation,field,value)
    with pytest.raises(ExecutionIntentError):manager._confirm(row['handoff_id'],confirmation,for_delivery=True)
    manager.run_manager.start.assert_not_called();gate.assert_not_called()


def test_transport_failure_retains_wait_and_no_execution(waiting):
    manager,row,gate,confirmation=waiting
    gate.side_effect=RuntimeError('TEST ONLY unavailable native admission')
    with pytest.raises(RuntimeError):manager._confirm(row['handoff_id'],confirmation,for_delivery=True)
    assert row['status']=='awaiting_company' and row['run_id'] is None
    manager.run_manager.start.assert_not_called()


def test_explicit_reselection_before_dispatch_retains_scope_and_company_gate(waiting):
    manager,row,gate,confirmation=waiting
    before=copy.deepcopy(row['ack'])
    confirmation.runner_id='claude';confirmation.replace_waiting_runner='codex'
    result=manager._confirm(row['handoff_id'],confirmation,for_delivery=True)
    assert result['status']=='awaiting_company' and row['ack']==before
    assert row['company_runner']=='claude' and row['runner_reselections'][0]['previous']=='codex'
    manager.run_manager.start.assert_not_called();assert gate.call_count==1
    gate.return_value={'required':True,'admitted':True,'execution_permitted':True}
    manager._confirm(row['handoff_id'],confirmation,for_delivery=True)
    assert manager.run_manager.start.call_count==1 and len(row['runner_reselections'])==1


@pytest.mark.parametrize('conflict',['stale','allocated','uncertain'])
def test_reselection_cannot_borrow_or_replace_a_native_run(waiting,conflict):
    manager,row,gate,confirmation=waiting
    confirmation.runner_id='claude';confirmation.replace_waiting_runner='codex'
    if conflict=='stale':confirmation.replace_waiting_runner='claude'
    if conflict=='allocated':row['run_id']='apr_'+'d'*32
    if conflict=='uncertain':manager.run_manager.list=lambda:[{'execution_context':{'intent_id':row['intent_id']}}]
    with pytest.raises(ExecutionIntentError):manager._confirm(row['handoff_id'],confirmation,for_delivery=True)
    assert row['company_runner']=='codex' and 'runner_reselections' not in row
    manager.run_manager.start.assert_not_called();gate.assert_not_called()
