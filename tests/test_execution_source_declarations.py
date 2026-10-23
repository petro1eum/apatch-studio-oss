"""Real native documents and two Ed25519 authorities; no network or production."""
import base64,copy,hashlib
from types import SimpleNamespace
import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from apatch import governed_work as G, governed_work_delivery as D, work_item_acceptance as W
from apatch_studio.execution_source_declarations import execution_source_declaration
from apatch_studio._contracts.execution_source_declaration import ExecutionSourceError


@pytest.fixture
def native(tmp_path):
    key=Ed25519PrivateKey.generate();public=key.public_key().public_bytes_raw()
    provider=SimpleNamespace(sign=key.sign,get_public_key=lambda:public)
    authority=Ed25519PrivateKey.generate();pub=authority.public_key().public_bytes_raw()
    pins={'test-platform-source-authority':base64.urlsafe_b64encode(pub).rstrip(b'=').decode()}
    def sign(body,purpose):
        value=copy.deepcopy(body)
        value['signature']={'algorithm':'Ed25519','key_id':'test-platform-source-authority','value':'unused'}
        value['signature']['value']=base64.urlsafe_b64encode(authority.sign(G._platform_signature_payload(value,purpose=purpose))).rstrip(b'=').decode()
        return value
    spec=tmp_path/'SPEC-CONTROL.md';spec.write_text('# SPEC-CONTROL\n\n## R1 Native source\n\n(verify: true)\n')
    change=G.prepare_change(str(tmp_path),tenant_id='11111111-1111-4111-8111-111111111111',project_group_id='tcpg_'+'1'*32,work_program_id='tcwp_'+'2'*32,work_program_hash='sha256:'+'3'*64,spec_id='SPEC-CONTROL',spec_path=str(spec),purpose='TEST ONLY source',key_provider=provider)['change']
    source={k:change[k] for k in ['tenant_id','project_group_id','source_kind','work_program_id','work_program_hash','context_release_id','context_release_manifest_hash','execution_system','spec_id','spec_hash','requirement_refs']}
    source.update(schema=G.SOURCE_BINDING_SCHEMA,binding_id='tcpsb_'+'4'*32,change_id=change['change_id'],change_hash=G.document_hash(change),actor_ref='member:'+'5'*32,authority_version=1,issued_at='2026-10-23T14:00:00Z')
    source=sign(source,G.PLATFORM_SOURCE_BINDING_PURPOSE)
    execution={k:source[k] for k in ['tenant_id','project_group_id','work_program_id','work_program_hash','change_id','change_hash','actor_ref']}
    execution.update(schema=W.BINDING_SCHEMA,binding_id='tcawieb_'+'6'*32,work_item_id='tcpwi_'+'7'*32,accepted_work_item_hash='sha256:'+'8'*64,accepted_authority_version=1,current_work_item_hash='sha256:'+'9'*64,current_authority_version=2,intent_id='tcapsei_'+'a'*32,intent_document_hash='sha256:'+'b'*64,intent_envelope_hash='sha256:'+'c'*64,proposal_acceptance_hash='sha256:'+'d'*64,binding_authority_version=1,accepted_at='2026-10-23T14:00:01Z')
    execution=sign(execution,W.BINDING_PURPOSE)
    def store():
        G._atomic_json(G.governed_work_root(str(tmp_path))/'bindings'/(source['binding_id']+'.json'),source)
        G._atomic_json(W.binding_path(str(tmp_path),execution['binding_id']),execution)
    store();D.write_config(str(tmp_path),{'schema':D.CONFIG_SCHEMA,'platform_url':'https://example.test','client_id':'test-only-native-subject','service_request_key_id':'sha256:'+hashlib.sha256(public).hexdigest(),'binding_authority_keys':pins})
    def build(chosen=provider):
        return execution_source_declaration(tmp_path,source_binding_id=source['binding_id'],execution_binding_id=execution['binding_id'],key_provider=chosen,issued_at='2026-10-23T14:00:02Z')
    return SimpleNamespace(root=tmp_path,provider=provider,source=source,execution=execution,sign=sign,store=store,build=build)


def test_real_native_receipts_keep_project_namespaces_and_no_source_mutation(native):
    before={str(p.relative_to(native.root)):p.read_bytes() for p in native.root.rglob('*') if p.is_file()}
    doc=native.build()
    assert doc['apatch_project_id']==hashlib.sha256(str(native.root.resolve()).encode()).hexdigest()[:16]
    assert doc['project_group_id']==native.source['project_group_id']
    assert doc['work_item_id']==native.execution['work_item_id']
    assert doc['execution_binding_hash']==G.document_hash(native.execution)
    assert doc['source_binding_hash']==G.document_hash(native.source)
    assert native.build()==doc
    assert before=={str(p.relative_to(native.root)):p.read_bytes() for p in native.root.rglob('*') if p.is_file()}


@pytest.mark.parametrize('field,value',[('tenant_id','22222222-2222-4222-8222-222222222222'),('project_group_id','tcpg_'+'f'*32),('change_id','apchg_'+'f'*32),('change_hash','sha256:'+'f'*64),('work_program_id','tcwp_'+'f'*32),('work_program_hash','sha256:'+'f'*64),('actor_ref','member:'+'f'*32)])
def test_valid_but_unrelated_native_execution_cannot_be_joined(native,field,value):
    native.execution[field]=value;native.execution.update(native.sign(native.execution,W.BINDING_PURPOSE));native.store()
    with pytest.raises(ExecutionSourceError):native.build()


@pytest.mark.parametrize('fault',['source_signature','execution_signature','wrong_purpose','other_executor','missing_signer'])
def test_missing_or_foreign_provenance_is_refused(native,fault):
    provider=native.provider
    if fault=='source_signature':native.source['signature']['value']='A'*86
    if fault=='execution_signature':native.execution['signature']['value']='A'*86
    if fault=='wrong_purpose':native.execution.update(native.sign(native.execution,G.PLATFORM_SOURCE_BINDING_PURPOSE))
    if fault=='other_executor':
        k=Ed25519PrivateKey.generate();provider=SimpleNamespace(sign=k.sign,get_public_key=lambda:k.public_key().public_bytes_raw())
    if fault=='missing_signer':provider=None
    native.store()
    with pytest.raises((ExecutionSourceError,G.GovernedWorkError)):native.build(provider)


@pytest.mark.parametrize('bad', ['../private', 'tcawieb_'+'f'*33, 'tcawieb_'+'F'*32, '', True, 1])
def test_invalid_execution_selector_never_reads_any_native_file(native, monkeypatch, bad):
    monkeypatch.setattr(G, '_read_document', lambda *args: pytest.fail('Invalid selector reached native file I/O'))
    with pytest.raises(ExecutionSourceError):
        execution_source_declaration(native.root, source_binding_id=native.source['binding_id'],
            execution_binding_id=bad, key_provider=native.provider)
