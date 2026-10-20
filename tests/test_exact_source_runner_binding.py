"""Exact admission reaches the runner without fabricating a legacy journal row."""
from types import SimpleNamespace
import pytest
from apatch import governed_work as G
from apatch import spec_executor
from apatch_studio.agent_runs import execution_source_artifacts,RunStateError
from apatch_studio.intent_store import IntentStore
from apatch_studio.operations import AgentRunRequest,ExecutionContext

@pytest.fixture
def case(monkeypatch,tmp_path):
    context=ExecutionContext(intent_id='tcapsei_'+'1'*32,tenant_id='11111111-1111-4111-8111-111111111111',project_group_id='tcpg_'+'2'*32,work_item_id='tcpwi_'+'3'*32,work_item_hash='sha256:'+'4'*64,authority_version=1,work_program_id='tcwp_'+'5'*32,work_program_hash='sha256:'+'6'*64,document_hash='sha256:'+'7'*64,envelope_hash='sha256:'+'8'*64)
    request=AgentRunRequest(mode='requirement',runner='codex',objective='TEST ONLY',spec_id='SPEC-CONTROL',requirement_id='R1')
    source={k:getattr(context,k) for k in ('tenant_id','project_group_id','work_program_id','work_program_hash')}
    source.update(binding_id='tcpsb_'+'9'*32)
    artifact='project-source-binding:TEST-ONLY'
    bound=SimpleNamespace(tenant_id=context.tenant_id,project_group_id=context.project_group_id,work_item_id=context.work_item_id,requirement='SPEC-CONTROL#R1',source_binding_id=source['binding_id'],source_binding_hash='sha256:'+'a'*64,source_binding_envelope_hash='sha256:'+'b'*64,artifacts=(artifact,))
    monkeypatch.setattr(IntentStore,'load',lambda self:pytest.fail('Exact admission must not borrow the legacy journal'))
    monkeypatch.setattr(G,'load_project_source_binding',lambda root,identity:source)
    monkeypatch.setattr(G,'document_hash',lambda value:'sha256:'+'a'*64)
    monkeypatch.setattr(G,'envelope_hash',lambda value:'sha256:'+'b'*64)
    monkeypatch.setattr(G,'source_binding_artifact',lambda value:artifact)
    calls=[]
    def resolve(root,spec,artifacts,**kw):calls.append((root,spec,artifacts,kw));return [{'kind':'TEST-ONLY verified SDK result'}]
    monkeypatch.setattr(spec_executor,'resolve_source_binding_artifacts',resolve)
    return tmp_path,request,context,source,bound,calls

def test_exact_source_is_revalidated_and_forwarded_to_native_sdk(case):
    root,request,context,source,bound,calls=case
    assert execution_source_artifacts(root,request,context,source_binding_context=bound)==[{'kind':'TEST-ONLY verified SDK result'}]
    assert calls==[(str(root),'SPEC-CONTROL',['project-source-binding:TEST-ONLY'],{'requirement_id':'R1'})]

@pytest.mark.parametrize('field,value',[('tenant_id','other'),('work_item_id','tcpwi_'+'f'*32),('requirement','SPEC-CONTROL#R2'),('source_binding_hash','sha256:'+'c'*64),('source_binding_envelope_hash','sha256:'+'d'*64),('artifacts',())])
def test_mismatched_exact_source_cannot_launch_or_fall_back_to_legacy(case,field,value):
    root,request,context,source,bound,calls=case
    setattr(bound,field,value)
    with pytest.raises(RunStateError):execution_source_artifacts(root,request,context,source_binding_context=bound)
    assert not calls

def test_source_work_program_must_match_the_accepted_assignment(case):
    root,request,context,source,bound,calls=case
    source['work_program_hash']='sha256:'+'e'*64
    with pytest.raises(RunStateError):execution_source_artifacts(root,request,context,source_binding_context=bound)
    assert not calls
