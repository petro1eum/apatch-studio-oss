"""Independent full native Studio/SDK temporary-fixture scope maintenance judge.

SCOPE_ADMIN_SOURCE selects exactly the source-under-test during outside proposal
qualification; its frozen production argv fixes the canonical source path.
"""
from pathlib import Path
from types import SimpleNamespace
from datetime import datetime,timedelta,timezone
import base64,hashlib,importlib.util,json,os,re,shutil
import pytest
from fastapi.testclient import TestClient
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization
from trustchain import TrustChain,TrustChainConfig,TrustChainVerifier
from trustchain.v2.chain_store import verify_record_signature
from apatch.trust_identity import _PemKeyProvider
from apatch.runtime.atomic_io import atomic_write_json
from apatch_studio.endpoint_enrollment import RECORD_SCHEMA,IDENTITY_FILE
CAPSULE=Path(os.environ.get('SCOPE_ADMIN_CAPSULE',str(Path(__file__).parent/'fixtures/studio_scope_admin_original_core.v1.json')))
CAPSULE_SHA256='708235632be25eed6f9f3b09200d015f16a7fe8da7b1c16f8adc36909544035c'

def original_public_files():
 raw=CAPSULE.read_bytes();assert hashlib.sha256(raw).hexdigest()==CAPSULE_SHA256
 result={}
 for rel,item in json.loads(raw)['files'].items():
  data=base64.b64decode(item['base64'],validate=True);assert hashlib.sha256(data).hexdigest()==item['sha256'];result[rel]=data
 return result
SOURCE=Path(os.environ.get('SCOPE_ADMIN_SOURCE','/Users/edcher/Documents/GitHub/apatch-studio-oss/apatch_studio/scope_admin_workflow.py'))

def load_module():
 assert SOURCE.is_file(),'native module absent before governed implementation'
 s=importlib.util.spec_from_file_location('apatch_studio.scope_admin_workflow',SOURCE)
 m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def snapshot(root):return {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file() and not p.is_symlink()}

@pytest.fixture
def case(tmp_path,monkeypatch):
 return lambda:build_case(tmp_path,monkeypatch,load_module())

def build_case(tmp_path,monkeypatch,module):
 for name in list(os.environ):
  if name.startswith('APATCH_'):monkeypatch.delenv(name,raising=False)
 root=tmp_path/'workspace';root.mkdir();(root/'pyproject.toml').write_text("[project]\nname='native-scope-fixture'\nversion='0.0.0'\n")
 private=Ed25519PrivateKey.generate();key=tmp_path/'generated-fixture-only.pem'
 key.write_bytes(private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));key.chmod(0o600)
 subject='fixture-scope-administration-agent';public=private.public_key().public_bytes_raw()
 name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,subject)]);now=datetime.now(timezone.utc)
 cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(private.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=2)).not_valid_after(now+timedelta(days=1)).add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True).sign(private,None)
 certpath=root/'.apatch/sdd/fixture.crt';certpath.parent.mkdir(parents=True);certpath.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
 atomic_write_json(str(root/'.apatch/agent-identity.json'),{'agent_id':subject,'key_backend':'pem','key':str(key),'cert':str(certpath),'public_key':base64.b64encode(public).decode()})
 for n,v in {'APATCH_AGENT_ID':subject,'APATCH_AGENT_KEY':str(key),'APATCH_AGENT_CERT':str(certpath),'APATCH_KEY_BACKEND':'pem'}.items():monkeypatch.setenv(n,v)
 tc=TrustChain(TrustChainConfig(enable_chain=True,chain_storage='file',chain_dir=str(root/'.trustchain'),key_provider=_PemKeyProvider(str(key),subject),enable_pki=False));tc.sign('fixture_genesis',{'generated_ephemeral_fixture':True})
 for rel,data in original_public_files().items():
  p=root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 from apatch.sdd_draft_amendment import freeze_lock
 with freeze_lock(root):pass
 from apatch.runtime.atomic_io import exclusive_file_lock
 with exclusive_file_lock(str(root/'.apatch/trustchain_ledger')):pass
 identity=tmp_path/'native-machine-state';identity.mkdir();identity_file=identity/IDENTITY_FILE
 atomic_write_json(str(identity_file),{'schema':RECORD_SCHEMA,'machine_name':'edcher-mac','certified':True,'key_path':str(key),'certificate_path':str(certpath)})
 identity_file.chmod(0o600)
 source_root=tmp_path/'disposable-studio-source-admission';source_root.mkdir()
 for rel,data in original_public_files().items():
  p=source_root/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(data)
 p=source_root/module.ADMIN_SOURCE;p.parent.mkdir(parents=True);p.write_bytes(SOURCE.read_bytes())
 atomic_write_json(str(source_root/'.apatch/agent-identity.json'),json.loads((root/'.apatch/agent-identity.json').read_bytes()))
 spec=source_root/'docs/specs/SPEC-STUDIO-SCOPE-COLLISION-ADMIN-1.md'
 spec.write_text('# SPEC-STUDIO-SCOPE-COLLISION-ADMIN-1\n\n> **apatch artifact:** `spec:SPEC-STUDIO-SCOPE-COLLISION-ADMIN-1`\n> **ownership mode:** strict\n\n## R1 Native maintenance source fixture\n\nowns: apatch_studio/scope_admin_workflow.py\n\n(verify: python -m pytest)\n')
 source_contract=json.loads((source_root/module.PROFILE).read_bytes())
 source_envelope=json.loads((source_root/module.ENVELOPE).read_bytes());source_envelope.pop('document_hash');source_envelope.update({'requirement':module.ADMIN_REF,'allowed_writes':[module.ADMIN_SOURCE]});source_envelope=module.validate_task_envelope(source_envelope)
 atomic_write_json(str(source_root/'.apatch/sdd/envelopes/SPEC-STUDIO-SCOPE-COLLISION-ADMIN-1/R1.json'),source_envelope)
 source_tc=TrustChain(TrustChainConfig(enable_chain=True,chain_storage='file',chain_dir=str(source_root/'.trustchain'),key_provider=_PemKeyProvider(str(key),subject),enable_pki=False))
 sid='fixture-native-administration-source-only'
 source_tc.sign('apatch',{'action':'apply','files':{module.ADMIN_SOURCE:{'sha256':hashlib.sha256(SOURCE.read_bytes()).hexdigest()}},'governed_session_id':sid,'artifacts':[{'kind':'spec','id':module.ADMIN_REF}],'fixture_source_admission_parser_only':True})
 mutation=sorted((source_root/'.trustchain/objects').glob('op_*.json'))[-1].stem
 from apatch.sdd_integrity import build_attestation_evidence
 evidence=build_attestation_evidence(contract_hash=source_contract['document_hash'],envelope_hash=source_envelope['document_hash'],actor={'actor_id':'fixture:source-implementation','role':'implementation'},mutation_ids=[mutation],adherence={'status':'compliant'},verification={'decision':{'accepted':True,'collected':1,'executed':1,'failed':0,'skipped':0}},falsification={'observed_red':True,'restored_green':True},environment_hash='sha256:'+'1'*64,checkpoint_refs=['fixture:checkpoint'],ledger_refs=[mutation],task_envelope=source_envelope)
 source_tc.sign('apatch_attest',{'governed_session_id':sid,'sdd_evidence':evidence,'fixture_source_admission_parser_only':True})
 from apatch.runtime.finalization import begin_finalization,finalize_session
 atomic_write_json(str(source_root/'.apatch/session_state.json'),{'session_id':sid,'started_at':now.isoformat()})
 finalized=finalize_session(str(source_root),begin_finalization(str(source_root),session_id=sid,lane_id='default',session_token_hash='fixture-token'))
 assert finalized.get('ok') and finalized.get('status')=='complete',finalized
 app=module.create_scope_administration_app(root,identity_root=identity,source_workspace=source_root)
 client=TestClient(app,base_url='http://127.0.0.1')
 token=re.search(r'content="([^"]+)"',client.get('/').text).group(1)
 headers={'x-apatch-studio-session':token,'origin':'http://127.0.0.1'}
 req={'actor_id':'agent:independent-scope-fixture','reason':'Original native owner explicitly corrects the bounded dot-path scope collision',
 'existing_signer_agent_id':subject,'existing_signer_public_key_sha256':hashlib.sha256(public).hexdigest()}
 return SimpleNamespace(root=root,key=key,keybytes=key.read_bytes(),public=public,subject=subject,identity=identity,source_root=source_root,client=client,headers=headers,request=req,module=module)

def propose(c):
 r=c.client.post('/api/v1/scope-amendment/review',json=c.request,headers=c.headers)
 assert r.status_code==200,r.text;return r.json()

def approve(c,r,**kw):return c.client.post('/api/v1/scope-amendment/approve',json={'review':r,'expected_snapshot':r['document_hash'],'confirmed':True,**kw},headers=c.headers)

def records(c):
 verifier=TrustChainVerifier(base64.b64encode(c.public).decode(),c.subject,max_age_seconds=None);result=[]
 for p in (c.root/'.trustchain/objects').glob('op_*.json'):
  raw=json.loads(p.read_bytes());v=raw.get('value',raw);assert verify_record_signature(v,verifier) is True;result.append(v)
 assert c.key.read_bytes()==c.keybytes
 return result

def test_full_authenticated_review_approval_two_genuine_sdk_receipts(case):
 c=case();before=snapshot(c.root);r=propose(c);assert snapshot(c.root)==before
 result=approve(c,r);assert result.status_code==200,result.text
 assert result.json()['profile_changed'] is False and result.json()['functional_acceptance'] is False
 assert (c.root/c.module.PROFILE).read_bytes()==before[c.module.PROFILE]
 assert (c.root/c.module.SOURCE).read_bytes()==before[c.module.SOURCE]
 rows=[x for x in records(c) if x['tool']==c.module.TOOL]
 assert {x['data']['stage'] for x in rows}=={'approved','completed'}
 assert all(x['data']['authority_id']=='edcher-mac' and x['data']['scope_expansion'] is True for x in rows)
 assert not (c.root/c.module.PENDING).exists()
 new=json.loads((c.root/c.module.ENVELOPE).read_bytes());old=json.loads(before[c.module.ENVELOPE])
 for field in old:
  if field not in {'document_hash','forbidden_paths'}:assert old[field]==new[field]

@pytest.mark.parametrize('headers',[{}, {'x-apatch-studio-session':'wrong','origin':'http://127.0.0.1'}, {'origin':'https://evil.invalid'}])
def test_auth_boundary_rejects_before_any_effect(case,headers):
 c=case();before=snapshot(c.root);r=c.client.post('/api/v1/scope-amendment/review',json=c.request,headers=headers)
 assert r.status_code in {401,403};assert snapshot(c.root)==before

def test_foreign_origin_even_with_real_token_denied(case):
 c=case();before=snapshot(c.root);r=c.client.post('/api/v1/scope-amendment/review',json=c.request,headers={**c.headers,'origin':'http://evil.invalid'})
 assert r.status_code==403;assert snapshot(c.root)==before

@pytest.mark.parametrize('field,value',[('owner','edcher-mac'),('authority_id','edcher-mac'),('identity_root','/tmp/elsewhere'),('role','authority'),('workspace','/tmp/elsewhere')])
def test_owner_and_workspace_cannot_be_selected_by_request(case,field,value):
 c=case();before=snapshot(c.root);r=c.client.post('/api/v1/scope-amendment/review',json={**c.request,field:value},headers=c.headers)
 assert r.status_code==422;assert snapshot(c.root)==before

@pytest.mark.parametrize('changes',[{'existing_signer_public_key_sha256':'0'*64},{'existing_signer_agent_id':'foreign'}, {'actor_id':'edcher-mac'}])
def test_wrong_signer_or_owner_persona_no_effects(case,changes):
 c=case();before=snapshot(c.root);r=c.client.post('/api/v1/scope-amendment/review',json={**c.request,**changes},headers=c.headers)
 assert r.status_code==409,r.text;assert snapshot(c.root)==before

@pytest.mark.parametrize('change',[{'certified':False},{'machine_name':'foreign-owner'}])
def test_real_native_owner_parser_rejects_uncertified_foreign_owner(case,change):
 c=case();p=c.identity/IDENTITY_FILE;v=json.loads(p.read_bytes());v.update(change);atomic_write_json(str(p),v);p.chmod(0o600);before=snapshot(c.root)
 r=c.client.post('/api/v1/scope-amendment/review',json=c.request,headers=c.headers)
 assert r.status_code==409;assert snapshot(c.root)==before

@pytest.mark.parametrize('kw',[{'confirmed':False},{'expected_snapshot':'sha256:'+'0'*64}])
def test_exact_confirmed_cas_required(case,kw):
 c=case();r=propose(c);before=snapshot(c.root);result=approve(c,r,**kw)
 assert result.status_code==409;assert snapshot(c.root)==before

@pytest.mark.parametrize('target',['source','profile','judge','inventory'])
def test_snapshot_drift_denied_before_signature(case,target):
 c=case();r=propose(c)
 if target=='source':(c.root/c.module.SOURCE).write_bytes(b'altered')
 elif target=='profile':
  p=c.root/c.module.PROFILE;v=json.loads(p.read_bytes());v['obligations']=v['obligations'][:-1];v=c.module._seal({k:x for k,x in v.items() if k!='document_hash'});atomic_write_json(str(p),v)
 elif target=='judge':(c.root/next(iter(r['baseline']['assets']))).write_bytes(b'altered')
 else:(c.root/'.apatch/new-secret').write_bytes(b'unknown')
 before=snapshot(c.root);result=approve(c,r)
 assert result.status_code==409,result.text;assert snapshot(c.root)==before

def test_replay_no_duplicate_signatures_and_source_drift_refusal(case):
 c=case();r=propose(c);assert approve(c,r).status_code==200;before=snapshot(c.root)
 second=approve(c,r);assert second.status_code==200,second.text;assert second.json()['replayed'] is True;assert snapshot(c.root)==before
 (c.root/c.module.SOURCE).write_bytes(b'changed after native publication');before=snapshot(c.root)
 assert approve(c,r).status_code==409;assert snapshot(c.root)==before

def test_active_session_denied_before_review(case):
 c=case();atomic_write_json(str(c.root/'.apatch/session_state.json'),{'session_id':'fixture-active','started_at':datetime.now(timezone.utc).isoformat()});before=snapshot(c.root)
 r=c.client.post('/api/v1/scope-amendment/review',json=c.request,headers=c.headers)
 assert r.status_code==409,r.text;assert snapshot(c.root)==before

def test_exact_path_lease_conflict_denied_before_approval(case):
 from apatch.path_leases import acquire_path_lease,release_path_leases
 c=case();r=propose(c);acquire_path_lease(str(c.root),[c.module.ENVELOPE],tool='fixture-other',governed_session_id='fixture-other',max_seconds=300);before=snapshot(c.root)
 try:
  result=approve(c,r);assert result.status_code==409,result.text;assert snapshot(c.root)==before
 finally:release_path_leases(str(c.root),governed_session_id='fixture-other')

def test_known_publication_failure_restores_exact_original_bytes(case,monkeypatch):
 c=case();r=propose(c);before=snapshot(c.root);original=c.module.atomic_write_json
 def failing(path,data):
  if str(path).endswith(c.module.ENVELOPE):raise OSError('temporary fixture I/O fault after approved signature')
  return original(path,data)
 monkeypatch.setattr(c.module,'atomic_write_json',failing)
 with pytest.raises(OSError):approve(c,r)
 assert (c.root/c.module.ENVELOPE).read_bytes()==before[c.module.ENVELOPE]
 assert (c.root/c.module.PROFILE).read_bytes()==before[c.module.PROFILE]
 assert not (c.root/c.module.PENDING).exists()
 assert {x['data']['stage'] for x in records(c) if x['tool']==c.module.TOOL}=={'approved','rolled_back'}

def test_ambiguous_native_commit_fenced_and_never_retried(case,monkeypatch):
 c=case();r=propose(c);original=c.module.ScopeAdministration._commit;calls=[]
 def ambiguous(self,review,stage,binding,**kwargs):
  calls.append(stage)
  if stage=='completed':
   c.module.atomic_write_json(str(c.root/c.module.PENDING),c.module._seal({'schema':'apatch.studio.scope-collision-pending.v1','review_hash':r['document_hash'],'stage':'signing_completed'}))
   raise c.module.ExistingSignerRefused('EXISTING_SIGNER_COMMIT_FAILED',reconciliation_required=True)
  return original(self,review,stage,binding,**kwargs)
 monkeypatch.setattr(c.module.ScopeAdministration,'_commit',ambiguous)
 result=approve(c,r);assert result.status_code==409,result.text;assert result.json()['reconciliation_required'] is True
 assert (c.root/c.module.PENDING).exists()
 from apatch.sdd_integrity import load_profile_contract
 with pytest.raises(ValueError):load_profile_contract(c.root)
 result=c.client.post('/api/v1/scope-amendment/reconcile',json={'review':r,'expected_snapshot':r['document_hash'],'confirmed':True},headers=c.headers)
 assert result.status_code==409 and result.json()['reconciliation_required'] is True
 assert calls==['approved','completed']

@pytest.mark.parametrize('path',['.apatch/spec_rebind.py','.apatch/future-control.json','apatch/sdd_integrity.py'])
def test_actual_execute_next_generation_raw_owner_rejects_alias_before_file_write(case,path):
 c=case();r=propose(c);assert approve(c,r).status_code==200
 from apatch.runtime.runtime import MutationRuntime
 from apatch.workflows import generate_patch_jsonl_batch
 runtime=MutationRuntime(str(c.root))
 from apatch.spec import resolve_requirement
 resolved=resolve_requirement(str(c.root),c.module.REF);assert resolved.get('ok'),resolved
 started=runtime.open_session(resolved['intent'],artifacts=[resolved['artifact']],
  sdd_contract=r['baseline']['contract'],task_envelope=r['new_envelope'],actor={'role':'implementation','actor_id':c.request['actor_id']})
 assert started.get('ok'),started
 before=snapshot(c.root)
 result=generate_patch_jsonl_batch(target_dir=str(c.root),needles=[{'action':'create','target_file':path,'content':'foreign = True\n'}],governed_session_id=runtime.session_id)
 assert result.get('ok') is False,result
 assert result.get('error_type')=='SPEC_TARGET_NOT_DECLARED',result
 assert not (c.root/path).exists() or (c.root/path).read_bytes()==before.get(path)
 assert (c.root/c.module.SOURCE).read_bytes()==before[c.module.SOURCE]
 assert (c.root/c.module.PROFILE).read_bytes()==before[c.module.PROFILE]
 runtime.close_session()


def test_native_module_present():
 assert SOURCE.is_file(),'native module absent before governed implementation'

@pytest.mark.parametrize('target',['source','judge','profile'])
def test_post_real_signature_drift_never_publishes(case,monkeypatch,target):
 c=case();r=propose(c);before=snapshot(c.root);native=c.module.TrustChainHelper.commit_action
 def drift_after_real_sign(self,tool,data,*args,**kwargs):
  result=native(self,tool,data,*args,**kwargs)
  if tool==c.module.TOOL and data['stage']=='approved':
   path=c.module.SOURCE if target=='source' else c.module.PROFILE if target=='profile' else next(iter(r['baseline']['assets']))
   (c.root/path).write_bytes(b'temporary fixture concurrent writer')
  return result
 monkeypatch.setattr(c.module.TrustChainHelper,'commit_action',drift_after_real_sign)
 result=approve(c,r);assert result.status_code==409,result.text
 assert (c.root/c.module.ENVELOPE).read_bytes()==before[c.module.ENVELOPE]
 assert (c.root/c.module.PENDING).exists()
 assert {x['data']['stage'] for x in records(c) if x['tool']==c.module.TOOL}=={'approved'}

@pytest.mark.parametrize('target',['source','judge'])
def test_foreign_source_judge_lease_blocks_before_sign(case,target):
 from apatch.path_leases import acquire_path_lease,release_path_leases
 c=case();r=propose(c);path=c.module.SOURCE if target=='source' else next(iter(r['baseline']['assets']))
 acquire_path_lease(str(c.root),[path],tool='fixture-other',governed_session_id='fixture-other',max_seconds=300);before=snapshot(c.root)
 try:
  result=approve(c,r);assert result.status_code==409,result.text;assert snapshot(c.root)==before
 finally:release_path_leases(str(c.root),governed_session_id='fixture-other')

def test_group_writable_native_owner_directory_denied(case):
 c=case();c.identity.chmod(0o770);before=snapshot(c.root)
 result=c.client.post('/api/v1/scope-amendment/review',json=c.request,headers=c.headers)
 assert result.status_code==409;assert snapshot(c.root)==before

def test_missing_approved_locator_cannot_replay_completed(case):
 c=case();r=propose(c);assert approve(c,r).status_code==200
 (c.root/c.module.ScopeAdministration(c.root,identity_root=c.identity)._folder(r)/'approved.json').unlink()
 before=snapshot(c.root);assert approve(c,r).status_code==409;assert snapshot(c.root)==before

def test_actual_command_provider_refusal_has_no_fallback(case,monkeypatch,tmp_path):
 import sys,shlex
 c=case();refuse=tmp_path/'real-command-provider-refusal.py';count=tmp_path/'actual-provider-calls'
 refuse.write_text('from pathlib import Path\nimport sys\np=Path('+repr(str(count))+')\np.write_text(p.read_text()+"called\\n" if p.exists() else "called\\n")\nsys.exit(17)\n')
 monkeypatch.setenv('APATCH_KEY_BACKEND','command');monkeypatch.setenv('APATCH_AGENT_SIGN_CMD',shlex.join([sys.executable,str(refuse)]));monkeypatch.setenv('APATCH_AGENT_PUBKEY',base64.b64encode(c.public).decode())
 identity=c.root/'.apatch/agent-identity.json';stored=json.loads(identity.read_bytes());stored.update({'key_backend':'command','sign_cmd':shlex.join([sys.executable,str(refuse)]),'public_key':base64.b64encode(c.public).decode()});atomic_write_json(str(identity),stored);atomic_write_json(str(c.source_root/'.apatch/agent-identity.json'),stored)
 r=propose(c);before=snapshot(c.root);result=approve(c,r)
 assert result.status_code==409,result.text;assert result.json()['reconciliation_required'] is True
 assert count.read_text().splitlines()==['called']
 assert (c.root/c.module.PENDING).exists()
 assert (c.root/c.module.ENVELOPE).read_bytes()==before[c.module.ENVELOPE]
 assert not [x for x in records(c) if x['tool']==c.module.TOOL]
 result=c.client.post('/api/v1/scope-amendment/reconcile',json={'review':r,'expected_snapshot':r['document_hash'],'confirmed':True},headers=c.headers)
 assert result.status_code==409;assert count.read_text().splitlines()==['called']

def test_approved_crash_before_completed_has_bounded_exact_recovery(case,monkeypatch):
 c=case();r=propose(c);before=snapshot(c.root);original=c.module.ScopeAdministration._commit
 def crash(self,review,stage,binding,**kwargs):
  if stage=='completed':raise KeyboardInterrupt('private fixture process crash before signing terminal stage')
  return original(self,review,stage,binding,**kwargs)
 monkeypatch.setattr(c.module.ScopeAdministration,'_commit',crash)
 with pytest.raises(BaseException):approve(c,r)
 monkeypatch.setattr(c.module.ScopeAdministration,'_commit',original)
 result=c.client.post('/api/v1/scope-amendment/reconcile',json={'review':r,'expected_snapshot':r['document_hash'],'confirmed':True},headers=c.headers)
 assert result.status_code==200,result.text;assert result.json()['stage']=='rolled_back'
 assert (c.root/c.module.ENVELOPE).read_bytes()==before[c.module.ENVELOPE]
 assert (c.root/c.module.PROFILE).read_bytes()==before[c.module.PROFILE]
 assert not (c.root/c.module.PENDING).exists()
 assert {x['data']['stage'] for x in records(c) if x['tool']==c.module.TOOL}=={'approved','rolled_back'}


@pytest.mark.parametrize('target',['module','acceptance','finalization'])
def test_source_launch_admission_requires_actual_bytes_accepted_sdk_and_finalization(case,target):
 c=case();before=snapshot(c.root)
 if target=='module':(c.source_root/c.module.ADMIN_SOURCE).write_bytes(b'stale running administration source')
 elif target=='acceptance':
  for p in (c.source_root/'.trustchain/objects').glob('op_*.json'):
   raw=json.loads(p.read_bytes());record=raw.get('value',raw)
   if record.get('tool')=='apatch_attest':p.unlink()
 else:(c.source_root/'.apatch/state/finalizations.json').unlink()
 result=c.client.post('/api/v1/scope-amendment/review',json=c.request,headers=c.headers)
 assert result.status_code==409,result.text;assert snapshot(c.root)==before

@pytest.mark.parametrize('valid',[True,False])
def test_legacy_actual_attest_or_ambiguous_selected_evidence_never_treated_zero(case,valid):
 c=case()
 tc=TrustChain(TrustChainConfig(enable_chain=True,chain_storage='file',chain_dir=str(c.root/'.trustchain'),key_provider=_PemKeyProvider(str(c.key),c.subject),enable_pki=False))
 tc.sign('apatch',{'action':'attest','artifacts':[{'kind':'spec','id':c.module.REF}],'sdd_evidence':{'envelope_hash':c.module.EXPECTED_ENVELOPE}})
 if not valid:
  p=sorted((c.root/'.trustchain/objects').glob('op_*.json'))[-1];raw=json.loads(p.read_bytes());v=raw.get('value',raw);v['data']['tampered']=True;atomic_write_json(str(p),raw)
 before=snapshot(c.root);result=c.client.post('/api/v1/scope-amendment/review',json=c.request,headers=c.headers)
 assert result.status_code==409,result.text;assert snapshot(c.root)==before

@pytest.mark.parametrize('path',['.apatch/spec_rebind.py','.apatch/future-control.json','apatch/sdd_integrity.py'])
def test_real_generated_log_tamper_cannot_reach_apply_writes(case,path):
 c=case();r=propose(c);assert approve(c,r).status_code==200
 from apatch.runtime.runtime import MutationRuntime
 from apatch.spec import resolve_requirement
 from apatch.workflows import generate_patch_jsonl_batch
 runtime=MutationRuntime(str(c.root));resolved=resolve_requirement(str(c.root),c.module.REF)
 started=runtime.open_session(resolved['intent'],artifacts=[resolved['artifact']],sdd_contract=r['baseline']['contract'],task_envelope=r['new_envelope'],actor={'role':'implementation','actor_id':c.request['actor_id']});assert started.get('ok'),started
 original=(c.root/c.module.SOURCE).read_text();first=original.splitlines()[0]
 generated=generate_patch_jsonl_batch(target_dir=str(c.root),needles=[{'action':'replace','target_file':c.module.SOURCE,'find_text':first,'replace_text':first+' # disposable legitimate source candidate'}],governed_session_id=runtime.session_id,created_by_tool='apatch_execute_next')
 assert generated.get('ok'),generated
 log=Path(generated['out_path']);raw=log.read_text();assert c.module.SOURCE in raw
 log.write_text(raw.replace(c.module.SOURCE,path))
 before=snapshot(c.root);result=runtime.apply_session(str(log))
 assert result.get('ok') is False and result.get('error_type')=='PATCH_LOG_DIGEST_MISMATCH',result
 assert (c.root/c.module.SOURCE).read_bytes()==before[c.module.SOURCE]
 assert (c.root/c.module.PROFILE).read_bytes()==before[c.module.PROFILE]
 assert not (c.root/path).exists() or (c.root/path).read_bytes()==before.get(path)
 runtime.close_session()

@pytest.mark.parametrize('path',['.apatch/spec_rebind.py','.apatch/future-control.json'])
def test_opaque_patch_tool_calls_cannot_hide_foreign_raw_targets(case,path):
 c=case();r=propose(c);assert approve(c,r).status_code==200
 from apatch.runtime.runtime import MutationRuntime
 from apatch.spec import resolve_requirement
 from apatch.workflows import generate_patch_jsonl_batch
 runtime=MutationRuntime(str(c.root));resolved=resolve_requirement(str(c.root),c.module.REF)
 started=runtime.open_session(resolved['intent'],artifacts=[resolved['artifact']],sdd_contract=r['baseline']['contract'],task_envelope=r['new_envelope'],actor={'role':'implementation','actor_id':c.request['actor_id']});assert started.get('ok'),started
 before=snapshot(c.root)
 result=generate_patch_jsonl_batch(target_dir=str(c.root),needles=[{'tool_calls':[{'name':'apply_patch','arguments':{'input':'*** Begin Patch\n*** Add File: '+path+'\n+foreign=True\n*** End Patch'}}]}],governed_session_id=runtime.session_id,created_by_tool='apatch_execute_next')
 assert result.get('ok') is False and result.get('error_type')=='SPEC_TARGET_NOT_DECLARED',result
 assert (c.root/c.module.SOURCE).read_bytes()==before[c.module.SOURCE]
 assert not (c.root/path).exists()
 runtime.close_session()
