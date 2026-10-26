"""Native compiler owns evidence; Studio keeps same-origin and current-source guards."""
from types import SimpleNamespace
import subprocess
import pytest
from fastapi.testclient import TestClient
from apatch_studio.app import create_app
PATH='/api/v1/exact-contract-handoffs/tceh_'+'1'*32+'/company-capability-evidence'
RUN='apr_'+'2'*32

@pytest.fixture
def client(tmp_path,monkeypatch):
    subprocess.run(['git','init','-q',str(tmp_path)],check=True)
    exact=SimpleNamespace(workspace=tmp_path,trust=SimpleNamespace(trusted_origins=frozenset()))
    calls=[]
    def build(manager,**kw):
        calls.append(kw);return {'TEST':'already verified native compiler result'}
    monkeypatch.setattr('apatch_studio.cowork_capability_evidence.build_company_capability_evidence',build)
    app=create_app(str(tmp_path),exact_contract_manager=exact,run_manager=SimpleNamespace(close=lambda:None))
    with TestClient(app,base_url='http://127.0.0.1:8767') as c:
        c.headers.update({'X-Apatch-Studio-Session':app.state.studio_guard.token,'Origin':'http://127.0.0.1:8767'})
        yield c,calls


def test_export_is_not_a_tracker_delivery_or_customer_acceptance(client):
    c,calls=client;reply=c.post(PATH,json={'confirmed':True,'run_id':RUN})
    assert reply.status_code==200 and reply.json()['tracker_delivered'] is False and reply.json()['customer_accepted'] is False
    assert calls==[{'handoff_id':'tceh_'+'1'*32,'run_id':RUN}]

@pytest.mark.parametrize('fault',['token','origin','extra','run_id','confirmation'])
def test_invalid_authority_or_selection_never_reaches_native_compiler(client,fault):
    c,calls=client;headers={};body={'confirmed':True,'run_id':RUN}
    if fault=='token':headers['X-Apatch-Studio-Session']=''
    if fault=='origin':headers['Origin']='https://attacker.example.test'
    if fault=='extra':body['workspace']='/not-authorized'
    if fault=='run_id':body['run_id']='../private'
    if fault=='confirmation':body['confirmed']=False
    assert c.post(PATH,json=body,headers=headers).status_code in {401,403,422}
    assert calls==[]


def test_source_refusal_is_closed_without_diagnostic_disclosure(client,monkeypatch):
    c,calls=client
    def refused(*a,**kw):raise RuntimeError('TEST-ONLY private path /do/not/disclose')
    monkeypatch.setattr('apatch_studio.cowork_capability_evidence.build_company_capability_evidence',refused)
    result=c.post(PATH,json={'confirmed':True,'run_id':RUN})
    assert result.status_code==409 and result.json()['error_code']=='company_source_evidence_unavailable'
    assert '/do/not/disclose' not in result.text
