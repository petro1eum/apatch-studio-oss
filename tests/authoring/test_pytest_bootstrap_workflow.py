
"""Native Studio only exposes the bounded Core owner amendment; not a verify override."""
from pathlib import Path
from types import SimpleNamespace
import pytest
from apatch_studio import judge_amendment_workflow as workflow
from apatch_studio.authoring_workflow import AuthoringApprovalRequest

HASH = "sha256:"+"a"*64
def request(**changes):
    fields = dict(request_id="apsreq_bootstrap_correction",acceptance_id="AC-4",
        judge_path="tests/test_doc.py",replacement_text="def test_doc():\n    assert True\n",
        reason="Prevent duplicate explicit conftest loading",disable_pytest_conftest_autoload=True)
    fields.update(changes)
    return workflow.JudgeAmendmentRequest(**fields)

@pytest.mark.parametrize("value",["true",1,None])
def test_bootstrap_option_is_not_truthy_coercion(value):
    with pytest.raises(ValueError):
        request(disable_pytest_conftest_autoload=value)

@pytest.mark.parametrize("field",["command","verify_override","authority_id","role"])
def test_caller_cannot_supply_command_or_authority(field):
    with pytest.raises(ValueError):
        request(**{field:"anything"})

def test_old_core_explicitly_refuses_bootstrap_without_writing_a_proposal(tmp_path,monkeypatch):
    api=SimpleNamespace(prepare_judge_amendment=lambda *args,**kwargs:pytest.fail("must not call old Core"))
    monkeypatch.setattr(workflow,"amendment_core",lambda:api)
    with pytest.raises(workflow.SddWorkflowError) as exc:
        workflow.JudgeAmendmentWorkflow(tmp_path).propose("SPEC-DEMO-1","R4",request())
    assert exc.value.status_code==503
    assert not list(tmp_path.rglob("*.json"))

def test_native_proposal_routes_the_boolean_and_owner_approval_separately(tmp_path,monkeypatch):
    calls=[]
    def prepare(root,**kwargs):
        calls.append(("prepare",kwargs))
        return {"spec_id":"SPEC-DEMO-1","requirement_id":"R4","document_hash":HASH,
                "functional_acceptance":False,"disable_pytest_conftest_autoload":True}
    def activate(root,review,**kwargs):
        calls.append(("approve",kwargs))
        return {"contract_hash":"sha256:"+"b"*64,"functional_acceptance":False}
    api=SimpleNamespace(PYTEST_BOOTSTRAP_AMENDMENT=True,prepare_judge_amendment=prepare,activate_judge_amendment=activate)
    monkeypatch.setattr(workflow,"amendment_core",lambda:api)
    flow=workflow.JudgeAmendmentWorkflow(tmp_path)
    review=flow.propose("SPEC-DEMO-1","R4",request())
    assert calls==[("prepare",dict(spec_id="SPEC-DEMO-1",requirement_id="R4",acceptance_id="AC-4",
        judge_path="tests/test_doc.py",replacement_text="def test_doc():\n    assert True\n",
        reason="Prevent duplicate explicit conftest loading",disable_pytest_conftest_autoload=True))]
    approval=AuthoringApprovalRequest(request_id="apsreq_bootstrap_approve",confirmed=True,snapshot=review["snapshot"])
    accepted=flow.approve("SPEC-DEMO-1","R4",approval,authority_id="server-resolved-owner")
    assert calls[-1]==("approve",dict(authority_id="server-resolved-owner",expected_snapshot=HASH))
    assert accepted["functional_acceptance"] is False

def test_legacy_request_fingerprint_is_unchanged(tmp_path,monkeypatch):
    from apatch.sdd_integrity import canonical_hash
    def prepare(root,**kwargs):
        return {"spec_id":"SPEC-DEMO-1","requirement_id":"R4","document_hash":HASH,"functional_acceptance":False}
    api=SimpleNamespace(prepare_judge_amendment=prepare)
    monkeypatch.setattr(workflow,"amendment_core",lambda:api)
    req=request(disable_pytest_conftest_autoload=False)
    result=workflow.JudgeAmendmentWorkflow(tmp_path).propose("SPEC-DEMO-1","R4",req)
    legacy=req.model_dump()
    legacy.pop("disable_pytest_conftest_autoload")
    assert result["request_fingerprint"]==canonical_hash({"spec_id":"SPEC-DEMO-1","requirement_id":"R4","request":legacy})
