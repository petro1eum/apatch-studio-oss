"""Actual prompt/retry rules. No live execution or authority claims."""
from types import SimpleNamespace
import pytest
from apatch_studio.agent_runs import build_governed_prompt, _can_retry_exact
from apatch_studio.operations import AgentRunRequest


def record():
    return SimpleNamespace(status='succeeded',contribution=None,
        request=SimpleNamespace(mode='requirement'),execution_context=object(),
        sdd_execution=SimpleNamespace(contract={'supersedes_hash':'sha256:'+'a'*64}))


def test_same_context_retry_does_not_require_a_fake_source_edit():
    assert _can_retry_exact(record())


@pytest.mark.parametrize('field,value',[('status','running'),('contribution',{'status':'emitted'}),
    ('execution_context',None),('sdd_execution',None)])
def test_retry_is_closed_for_unrelated_or_already_attributed_work(field,value):
    r=record();setattr(r,field,value)
    assert not _can_retry_exact(r)


def test_retry_does_not_open_other_completed_modes_or_initial_contracts():
    r=record();r.request.mode='specification'
    assert not _can_retry_exact(r)
    r=record();r.sdd_execution.contract={}
    assert not _can_retry_exact(r)


def test_revision_prompt_uses_all_exact_anchors_and_fresh_native_verification():
    request=AgentRunRequest(mode='requirement',runner='codex',objective='TEST ONLY',spec_id='SPEC-CONTROL',requirement_id='R1')
    sdd=SimpleNamespace(spec_id='SPEC-CONTROL',requirement_id='R1',actor_id='studio:implementation',
        contract_hash='sha256:'+'a'*64,envelope_hash='sha256:'+'b'*64,
        contract={'supersedes_hash':'sha256:'+'c'*64},task_envelope={})
    anchors=('project-source-binding:TEST-ONLY','cowork-exact-association:TEST-ONLY','work-item-execution-binding:TEST-ONLY')
    text=build_governed_prompt(request,sdd_execution=sdd,
        source_binding_context=SimpleNamespace(artifacts=anchors),source_artifacts=[{'kind':'project-source-binding','id':'TEST-ONLY'}])
    assert all(a in text for a in anchors)
    assert 'fresh verification-only session' in text and 'Run apatch_sdd_verify' in text
    assert 'do NOT fabricate a source edit' in text and 'dedicated lane' in text
    assert 'preserve the following verified ProjectSourceBinding' not in text
    assert 'concise public, factual completion summary' in text
    assert 'Do not include private material or claim customer acceptance' in text
    assert 'do not search private evidence stores or publish' in text
