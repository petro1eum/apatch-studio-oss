"""Real native generated-key Source/SDD/end and guarded Studio HTTP qualification.
Only the selected Studio source is substituted. Old37 fixture bytes are pinned.
No production identities, aliases, fake SDK readers or signed proof builders.
"""
from pathlib import Path
import base64,hashlib,importlib.util,json,os
from types import SimpleNamespace
import pytest
from apatch import sdd_contract_intake as core
from apatch.sdd_integrity import _seal,validate_task_envelope
from apatch.runtime import MutationRuntime
from apatch.runtime.finalization import load_finalization
from apatch.workflows import generate_patch_jsonl_batch,simulate_workspace
from apatch.trust_identity import _PemKeyProvider
from trustchain import TrustChain,TrustChainConfig
from trustchain.v2.chain_store import verify_record_signature
from trustchain.v2.verifier import TrustChainVerifier

OLD=Path('/Users/edcher/Documents/GitHub/apatch-studio-oss/tests/frozen/test_intake_historical_parent_r1.py')
OLD_SHA='4128d786ff8ff1dbe50f153d8ac46a391c116ab6555c4cf9c96502ef279c3df4'
assert hashlib.sha256(OLD.read_bytes()).hexdigest()==OLD_SHA,'Old37 immutable fixture drift'
s=importlib.util.spec_from_file_location('_unchanged37_generated_fixture',OLD);old=importlib.util.module_from_spec(s);s.loader.exec_module(old)
REL='.apatch/sdd/envelopes/SPEC-FIXTURE-BASE-1/R1.json'
REQ='SPEC-FIXTURE-BASE-1#R1'

def records(c):
 v=TrustChainVerifier(base64.b64encode(c.public).decode(),old.OWNER['id'],max_age_seconds=None)
 rows={}
 for p in (c.root/'.trustchain/objects').glob('op_*.json'):
  raw=json.loads(p.read_bytes());r=raw.get('value',raw)
  assert verify_record_signature(r,v) is True
  rows[p.stem]=r
 return rows

def signed(c,tool,payload):
 before=set(records(c));tc=TrustChain(TrustChainConfig(enable_chain=True,chain_storage='file',chain_dir=str(c.root/'.trustchain'),key_provider=_PemKeyProvider(str(c.key),old.OWNER['id']),enable_pki=False))
 tc.sign(tool,payload);rows=records(c);added=set(rows)-before;assert len(added)==1
 return added.pop()

@pytest.fixture
def c(tmp_path,monkeypatch):
 generator=old.c.__wrapped__(tmp_path,monkeypatch);c=next(generator)
 try:
  value=json.loads((c.root/REL).read_bytes());value.pop('document_hash')
  value['tools']=['apatch_session_start','apatch_generate_batch','apatch_simulate','apatch_apply_session','apatch_verify_run','apatch_sdd_verify','apatch_attest','apatch_session_end','apatch_resume_session']
  env=validate_task_envelope(value)
  # Native Studio encoding retained before original intake captures its exact raw pin.
  from apatch_studio.state_io import write_json
  write_json(c.root/REL,env)
  rt=MutationRuntime(str(c.root));opened=rt.open_session('Generated fixture source hardening',artifacts=[{'kind':'spec','id':REQ}],sdd_contract=c.contract,task_envelope=env,actor={'actor_id':old.ACTOR,'role':'implementation'})
  assert opened.get('ok') is True,opened
  generated=generate_patch_jsonl_batch(needles=[{'action':'replace','target_file':'feature.py','find_text':'def public_result():','replace_text':'# generated native fixture source revision\ndef public_result():'}],target_dir=str(c.root),out_path='.apatch/tmp/independent-source.jsonl',governed_session_id=rt.session_id)
  assert generated.get('ok') is True,generated
  log=generated.get('logs_path') or generated.get('out_path');assert log,generated
  simulated=simulate_workspace(str(c.root),logs_path=log);assert simulated.get('ok') is True,simulated
  applied=rt.apply_session(log,verify_deferred=True,quiet=True);assert applied.get('ok') is True,applied
  while applied.get('continue'):applied=rt.apply_session(log,verify_deferred=True,quiet=True);assert applied.get('ok') is True,applied
  verified=rt.sdd_verify(timeout=45);assert verified.get('ok') is True,verified
  assert rt.resume_session().get('ok') is True
  attested=rt.attest(message='Independent generated fixture Source/SDD/end proof');assert attested.get('ok') is True,attested
  assert rt.close_session().get('ok') is True
  assert load_finalization(str(c.root),rt.session_id)['status']=='complete'
  rows=records(c);c.attest_op=next(k for k,r in rows.items() if r['tool']=='apatch_attest' and r['data'].get('governed_session_id')==rt.session_id)
  c.source_sid=rt.session_id;c.source_env=env;c.source_proof=rows[c.attest_op]['data']['sdd_evidence']
  assert c.source_proof['mutation_ids'] and c.source_proof['verification']['decision']['accepted'] is True
  assert c.source_proof['falsification']['observed_red'] is True and c.source_proof['falsification']['restored_green'] is True
  c.first=old.completed(c);old.grow(c);c.raw_env=(c.root/REL).read_bytes();(c.root/REL).unlink()
  yield c
 finally:
  try:next(generator)
  except StopIteration:pass

def fresh(c):return old.propose(c,'apsreq_fixture_fresh',1)
def deny(c):
 before=old.snapshot(c.root);r=fresh(c);assert r.status_code==409,r.text;assert old.snapshot(c.root)==before

def replace_attestation(c,change):
 row=records(c)[c.attest_op];payload=json.loads(json.dumps(row['data']));change(payload)
 # Generated adversarial signed data, never a production receipt or fake verifier.
 signed(c,row['tool'],payload)


def test_closed_actual_source_signed_envelope_allows_fresh_http_review(c):
 before=old.snapshot(c.root);r=fresh(c)
 assert r.status_code==200,'Actual valid archived Source envelope rejected: '+r.text
 assert r.json()['status']=='awaiting_approval' and r.json()['implementation_allowed'] is False
 assert not (c.root/REL).exists()
 assert {p:b for p,b in old.snapshot(c.root).items() if p.startswith('.trustchain/')}=={p:b for p,b in before.items() if p.startswith('.trustchain/')}

def test_archived_envelope_never_reuses_approval(c):
 r=fresh(c);assert r.status_code==200,r.text
 new=r.json();before=old.snapshot(c.root)
 assert old.approve(c,c.first['snapshot'],'apsreq_fixture_stale_approval').status_code==409
 assert old.snapshot(c.root)==before
 assert old.approve(c,new['snapshot'],'apsreq_fixture_current_approval').status_code==200
 assert not (c.root/REL).exists();assert len([r for r in records(c).values() if r['tool']==core.TOOL])==4

def test_public_history_does_not_resolve_fixture_provider(c,monkeypatch):
 def forbidden(*args,**kwargs):raise AssertionError('Historical reader resolved a private signer')
 monkeypatch.setattr(core,'_identity',forbidden)
 r=fresh(c);assert r.status_code==200,r.text

@pytest.mark.parametrize('relative',[ '.apatch/locks/SPEC-FIXTURE-BASE-1/R1.json','tests/frozen/test_base_fixture.py','.apatch/sdd/frozen/'])
def test_missing_non_envelope_inputs_still_refuse(c,relative):
 if relative.endswith('/'):
  relative+=c.contract['document_hash'][7:]+'.json'
 (c.root/relative).unlink();deny(c)

def test_present_changed_envelope_cannot_use_history(c):
 value=dict(c.source_env);value.pop('document_hash');value['allowed_writes']=['another.py']
 old.write(c.root,REL,validate_task_envelope(value));deny(c)

def test_missing_source_attestation_refuses(c):
 (c.root/'.trustchain/objects'/(c.attest_op+'.json')).unlink();deny(c)

def test_corrupt_signature_refuses(c):
 p=c.root/'.trustchain/objects'/(c.attest_op+'.json');raw=json.loads(p.read_bytes());row=raw.get('value',raw);row['signature']=base64.b64encode(b'\0'*64).decode();old.write(c.root,p.relative_to(c.root).as_posix(),raw);deny(c)

def test_foreign_key_even_matching_signed_name_refuses(c):
 from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
 from cryptography.hazmat.primitives import serialization
 key=c.key.parent/'foreign-fixture-only.pem';private=Ed25519PrivateKey.generate();key.write_bytes(private.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()));key.chmod(0o600)
 row=records(c)[c.attest_op];tc=TrustChain(TrustChainConfig(enable_chain=True,chain_storage='file',chain_dir=str(c.root/'.trustchain'),key_provider=_PemKeyProvider(str(key),old.OWNER['id']),enable_pki=False));tc.sign(row['tool'],row['data']);deny(c)

@pytest.mark.parametrize('kind',['no_red','not_restored','wrong_actor','wrong_profile','wrong_envelope','no_mutations','foreign_session'])
def test_genuinely_signed_wrong_source_purpose_or_binding_refuses(c,kind):
 def mutate(payload):
  proof=payload['sdd_evidence']
  if kind in {'no_red','not_restored'}:
   f=proof['falsification'];f.pop('document_hash');f['observed_red' if kind=='no_red' else 'restored_green']=False;proof['falsification']=_seal(f)
  elif kind=='wrong_actor':proof['actor']={'actor_id':old.OWNER['id'],'role':'authority'}
  elif kind=='wrong_profile':proof['contract_hash']='sha256:'+'0'*64
  elif kind=='wrong_envelope':proof['envelope_hash']='sha256:'+'0'*64
  elif kind=='no_mutations':proof['mutation_ids']=[]
  else:payload['governed_session_id']='apatch_sess_foreign'
  proof.pop('document_hash');payload['sdd_evidence']=_seal(proof)
 replace_attestation(c,mutate);deny(c)

@pytest.mark.parametrize('kind',['incomplete','missing','foreign','future'])
def test_native_finalization_must_be_exact_and_complete(c,kind):
 path=c.root/'.apatch/state/finalizations.json';data=json.loads(path.read_bytes());row=data['records'][c.source_sid]
 if kind=='incomplete':row['status']='finalizing'
 elif kind=='missing':del data['records'][c.source_sid]
 elif kind=='foreign':row['session_id']='apatch_sess_foreign'
 else:row['completed_at']='2999-01-01T00:00:00+00:00'
 old.write(c.root,path.relative_to(c.root).as_posix(),data);deny(c)

def test_current_source_hash_drift_refuses(c):
 (c.root/'feature.py').write_text('def public_result():\n    return 43\n');deny(c)

def test_pending_native_intake_still_refuses(c):
 old.write(c.root,core.PENDING,{'fixture_only':True});deny(c)

def test_workspace_link_cannot_supply_missing_envelope(c):
 outside=c.root.parent/'outside-envelope.json';outside.write_bytes(c.raw_env);(c.root/REL).symlink_to(outside);deny(c)

def test_unsigned_storage_alias_never_selects_source_mutation(c):
 op=c.source_proof['mutation_ids'][0];p=c.root/'.trustchain/objects'/(op+'.json');raw=json.loads(p.read_bytes());r=raw.get('value',raw);r['id']='op_999999999';old.write(c.root,p.relative_to(c.root).as_posix(),raw)
 assert op in records(c)
 response=fresh(c);assert response.status_code==200,response.text

def test_signed_proof_cannot_borrow_unsigned_storage_alias(c):
 def change(payload):
  proof=payload['sdd_evidence'];proof.pop('document_hash');proof['mutation_ids']=['op_999999999'];payload['sdd_evidence']=_seal(proof)
 replace_attestation(c,change);deny(c)

def test_genuinely_signed_foreign_mutation_purpose_refuses(c):
 op=c.source_proof['mutation_ids'][0];original=records(c)[op];payload=json.loads(json.dumps(original['data']));payload['governed_session_id']='apatch_sess_foreign';new=signed(c,original['tool'],payload)
 def change(p):
  proof=p['sdd_evidence'];proof.pop('document_hash');proof['mutation_ids']=[new];p['sdd_evidence']=_seal(proof)
 replace_attestation(c,change);deny(c)

def test_other_envelope_revision_does_not_replace_original_raw_pin(c):
 def change(payload):
  proof=payload['sdd_evidence'];env=dict(proof['task_envelope']);env.pop('document_hash');env['allowed_reads']=[*env['allowed_reads'],'independent-other-revision.py'];env=validate_task_envelope(env)
  proof.pop('document_hash');proof['task_envelope']=env;proof['envelope_hash']=env['document_hash'];payload['sdd_evidence']=_seal(proof)
 replace_attestation(c,change)
 r=fresh(c);assert r.status_code==200,r.text

@pytest.mark.parametrize('kind',['result_failed','wrong_command','no_red_hashes'])
def test_genuine_signature_cannot_replace_native_material_result(c,kind):
 def change(payload):
  proof=payload['sdd_evidence'];proof.pop('document_hash')
  if kind=='no_red_hashes':
   f=proof['falsification'];f.pop('document_hash');f['result_hashes']=[];proof['falsification']=_seal(f)
  else:
   v=proof['verification'];v.pop('document_hash')
   if kind=='result_failed':v['result']['failed']=1
   else:v['result']['commands'][0]['command_hash']='sha256:'+'0'*64
   proof['verification']=_seal(v)
  payload['sdd_evidence']=_seal(proof)
 replace_attestation(c,change);deny(c)

@pytest.mark.parametrize('kind',['missing','foreign','mismatched_hash'])
def test_genuine_signed_attestation_must_anchor_its_exact_source_purpose(c,kind):
 def change(payload):
  if kind=='missing':payload['artifacts']=[]
  elif kind=='foreign':payload['artifacts']=[{'kind':'spec','id':'SPEC-FOREIGN-FIXTURE-1#R1'}]
  else:payload['artifacts']=[{'kind':'spec','id':REQ,'content_hash':'sha256:'+'0'*64}]
 replace_attestation(c,change);deny(c)
