"""Native Studio maintenance app for one original-owner dot-path collision.

Governed Studio source, not an implementation capability or a source writer.
The trusted boot process chooses the workspace and identity root. API callers
cannot choose the owner, principal, role, workspace or new envelope content.
"""
from __future__ import annotations
import base64, hashlib, json, os, re, stat
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from apatch.sdd_integrity import _seal, _verify_seal, canonical_hash, validate_task_envelope, compare_envelopes
from apatch.sdd_authoring import _path, _read
from apatch.sdd_successor import _immutable
from apatch.sdd_draft_amendment import assert_can_freeze, freeze_lock
from apatch.runtime.atomic_io import atomic_write_json
from apatch.sdd_judge_amendment import _write_judge
from apatch.path_leases import acquire_path_lease, release_path_leases, load_active_leases, PathLeaseConflict
from apatch.ledger_actor import enrich_payload_with_actor
from apatch.strict_existing_signer import ExistingSignerBinding, ExistingSignerRefused
from apatch.trustchain_helper import TrustChainHelper
from apatch.external_dependency import _signed_rows, _ledger_paths, _workspace_verifier
from apatch_studio.lock_authority import approver_for
from apatch_studio.run_store import default_state_root
from apatch_studio.endpoint_enrollment import IDENTITY_FILE
from apatch_studio.security import StudioRequestGuard, security_headers
from trustchain import TrustChainVerifier
from trustchain.v2.chain_store import verify_record_signature

TOOL='apatch_studio_scope_collision_amendment'
REF='SPEC-VERIFIER-AMENDMENT-1#R6'
PROFILE='.apatch/sdd_verification_contract.json'
ENVELOPE='.apatch/sdd/envelopes/SPEC-VERIFIER-AMENDMENT-1/R6.json'
PENDING='.apatch/sdd/draft-amendment-pending.json'
SOURCE='apatch/spec_rebind.py'
ADMIN_SOURCE='apatch_studio/scope_admin_workflow.py'
ADMIN_REF='SPEC-STUDIO-SCOPE-COLLISION-ADMIN-1#R1'
EXPECTED_PROFILE='sha256:4f4b5a8ef946b8f0fd1388befd6cb72c890f7b31ddf502e5bc71e6df0e3ee1b1'
EXPECTED_ENVELOPE='sha256:b05910e04c79acf5f3b4cb39c89735afbee65954aad1a913d853ced125de6f03'
EXPECTED_OWNER='edcher-mac'
EXPECTED_SOURCE='sha256:8513d4023c1243d5c0d06081c8549b5e10dc4dc5156d792799fa97f3fef63627'
DIRECTORIES={'authority','backups','debug','diagnostics','hygiene','history','intents','lanes','locks','plans','policy','registry','remote','sdd','specs','state','tmp','verify_jobs'}
FILES={'agent-identity.json','config.json','conformance.json','enforcement.json','events.jsonl','hooks.json','lane_registry.json','lane_registry.json.lock','mcp.json','mcp_tool_fingerprint.json','notarized_index.json','notarized_index.json.lock','policy.json','reality.jsonl','remote.json','request_journal.json','request_journal.json.lock','sandbox.json','sdd_verification_contract.json','session_state.json','trustchain_ledger.lock','workspace.json','workspaces.json','write_lease.json','write_lease.json.lock','write_leases.json','write_leases.json.lock'}
CONTROL_PATTERNS=sorted(['.apatch/'+x+'/**' for x in DIRECTORIES]+['.apatch/'+x for x in FILES])

class Refused(ValueError): pass

def digest(data): return 'sha256:'+hashlib.sha256(data).hexdigest()

def capture(root,relative):
 p=_path(root,relative)
 fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW)
 try:
  before=os.fstat(fd)
  if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1: raise Refused('canonical single-link file required')
  with os.fdopen(os.dup(fd),'rb') as stream: raw=stream.read()
  after=os.fstat(fd);current=p.stat(follow_symlinks=False)
  if (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns) or (after.st_dev,after.st_ino)!=(current.st_dev,current.st_ino): raise Refused('canonical file changed while reading')
  return raw
 finally:os.close(fd)

def trusted_owner(identity_root):
 p=Path(identity_root).absolute()
 if p!=p.resolve() or not p.is_dir() or p.stat().st_uid!=os.getuid(): raise Refused('trusted OS identity directory required')
 for parent in [p,*p.parents]:
  mode=parent.stat().st_mode
  if parent.is_symlink():raise Refused('linked native identity directory denied')
  if mode & 0o022 and not (mode & stat.S_ISVTX and parent!=p):raise Refused('native identity parent writable by another principal')
 file=p/IDENTITY_FILE
 if not file.is_file() or file.is_symlink() or file.stat().st_nlink!=1 or file.stat().st_uid!=os.getuid(): raise Refused('trusted OS identity file required')
 if file.stat().st_mode & 0o022:raise Refused('native identity is writable by another principal')
 party=approver_for(p)
 if party.get('certified') is not True:raise Refused('certified native owner required')
 return party

class ReviewRequest(BaseModel):
 model_config=ConfigDict(extra='forbid',strict=True)
 actor_id:str=Field(min_length=3,max_length=256)
 reason:str=Field(min_length=16,max_length=4096)
 existing_signer_agent_id:str=Field(min_length=3,max_length=256)
 existing_signer_public_key_sha256:str=Field(pattern=r'^[0-9a-f]{64}$')

class ApprovalRequest(BaseModel):
 model_config=ConfigDict(extra='forbid',strict=True)
 review:dict
 expected_snapshot:str=Field(pattern=r'^sha256:[0-9a-f]{64}$')
 confirmed:bool

class ScopeAdministration:
 def __init__(self,workspace,*,identity_root=None,source_workspace=None):
  root=Path(workspace).absolute()
  if root!=root.resolve() or not root.is_dir(): raise Refused('canonical trusted workspace required')
  self.root=root
  self.identity_root=Path(identity_root) if identity_root is not None else default_state_root()
  self.source_root=Path(source_workspace).absolute() if source_workspace is not None else Path(__file__).resolve().parents[1]

 def _binding(self,request):
  binding=ExistingSignerBinding(request.existing_signer_agent_id,request.existing_signer_public_key_sha256)
  # Public expectation binds the native provider before any journal or sign.
  binding.resolve(str(self.root))
  return binding

 def _source_admission(self,binding):
  from apatch.spec_ownership import _strict_ownership_declarations,_declared_owners_for_path
  from apatch.runtime.finalization import load_finalization
  root=self.source_root
  if root!=root.resolve() or not root.is_dir():raise Refused('canonical Studio source workspace required')
  agent,verifier=_workspace_verifier(root)
  public=base64.b64decode(verifier._public_key_b64,validate=True)
  if agent!=binding.agent_id or hashlib.sha256(public).hexdigest()!=binding.public_key_sha256:raise Refused('source and operational native public signers differ')
  source=digest(capture(root,ADMIN_SOURCE))
  if source!=digest(Path(__file__).read_bytes()):raise Refused('running administration module differs from governed Studio source')
  contract=json.loads(capture(root,PROFILE));_verify_seal(contract,'frozen Studio administration source profile')
  envelope=validate_task_envelope(json.loads(capture(root,'.apatch/sdd/envelopes/SPEC-STUDIO-SCOPE-COLLISION-ADMIN-1/R1.json')))
  if contract.get('status')!='frozen' or contract.get('implementation_allowed') is not True or contract.get('authority')!={'role':'authority','actor_id':trusted_owner(self.identity_root)['id']} or envelope['contract_hash']!=contract['document_hash'] or envelope['requirement']!=ADMIN_REF or envelope['allowed_writes']!=[ADMIN_SOURCE]:raise Refused('original native Studio source owner admission required')
  declarations,errors=_strict_ownership_declarations(str(root))
  owners=_declared_owners_for_path(ADMIN_SOURCE,declarations)
  if errors or len(owners)!=1 or owners[0].get('requirement')!=ADMIN_REF:raise Refused('unique strict native administration source ownership required')
  for obligation in contract['obligations']:
   for asset in obligation['judge_assets']:
    if digest(capture(root,asset['path']))!=asset['sha256']:raise Refused('native administration source judge drift')
  rows=_signed_rows(str(root));mutations={}
  for row in rows:
   payload=row['payload'];files=payload.get('files') or {};item=files.get(ADMIN_SOURCE) if isinstance(files,dict) else None
   value=item.get('sha256') if isinstance(item,dict) else item
   if row['tool_id'] in {'apatch','apatch_expert'} and value in (source,source.removeprefix('sha256:')) and payload.get('governed_session_id') and any(x.get('kind')=='spec' and x.get('id')==ADMIN_REF for x in payload.get('artifacts',[])):
    mutations.setdefault(payload['governed_session_id'],set()).add(row['id'])
  for row in rows:
   payload=row['payload'];proof=payload.get('sdd_evidence') or {};sid=payload.get('governed_session_id')
   if row['tool_id']!='apatch_attest' or sid not in mutations:continue
   _verify_seal(proof,'native administration source attestation')
   verification=(proof.get('verification') or {}).get('decision') or {};falsification=proof.get('falsification') or {}
   finalized=load_finalization(str(root),sid)
   if proof.get('contract_hash')==contract['document_hash'] and proof.get('envelope_hash')==envelope['document_hash'] and verification.get('accepted') is True and verification.get('executed',0)>0 and verification.get('failed')==0 and verification.get('skipped')==0 and falsification.get('observed_red') is True and falsification.get('restored_green') is True and set(proof.get('mutation_ids',[])) & mutations[sid] and finalized and finalized.get('status')=='complete':
    return {'module_hash':source,'profile_hash':contract['document_hash'],'envelope_hash':envelope['document_hash'],'session_id':sid,'attestation_signature':row['signature']}
  raise Refused('accepted finalized genuine administration source proof required before authority use')

 def _snapshot(self,request,*,expected_envelope=None):
  owner=trusted_owner(self.identity_root)
  admission=self._source_admission(self._binding(request))
  contract=json.loads(capture(self.root,PROFILE));_verify_seal(contract,'native frozen profile')
  old=validate_task_envelope(json.loads(capture(self.root,ENVELOPE)))
  if owner['id']!=EXPECTED_OWNER or contract['document_hash']!=EXPECTED_PROFILE or old['document_hash']!=(expected_envelope or EXPECTED_ENVELOPE) or digest(capture(self.root,SOURCE))!=EXPECTED_SOURCE: raise Refused('exact frozen original R6 provenance required')
  if contract.get('authority')!={'role':'authority','actor_id':owner['id']} or contract.get('status')!='frozen' or contract.get('implementation_allowed') is not True: raise Refused('original certified frozen owner required')
  if request.actor_id==owner['id'] or request.actor_id.strip()!=request.actor_id: raise Refused('separate named implementation actor required')
  if len(contract.get('obligations',[]))!=9 or old.get('requirement')!=REF or old.get('contract_hash')!=contract['document_hash'] or old.get('allowed_writes')!=[SOURCE] or old.get('containment')!='mediated_only': raise Refused('exact existing nine-check R6 scope required')
  # Use the real unchanged strict ownership parser, preserving leading dots.
  from apatch.spec_ownership import _strict_ownership_declarations,_declared_owners_for_path
  declarations,errors=_strict_ownership_declarations(str(self.root))
  if errors or not any(x.get('requirement')==REF for x in _declared_owners_for_path(SOURCE,declarations)): raise Refused('original strict source owner required')
  if any(x.get('requirement')==REF for x in _declared_owners_for_path('.apatch/spec_rebind.py',declarations)): raise Refused('hidden alias ownership denied')
  assets={}
  for obligation in contract['obligations']:
   for asset in obligation['judge_assets']:
    actual=digest(capture(self.root,asset['path']))
    if actual!=asset['sha256']: raise Refused('frozen judge drift')
    assets[asset['path']]=actual
  controls=sorted(x.name for x in _path(self.root,'.apatch/sdd').parent.iterdir())
  if not set(controls)<=DIRECTORIES|FILES: raise Refused('unknown control path requires new review')
  for name in controls:
   if (_path(self.root,'.apatch/sdd').parent/name).is_symlink(): raise Refused('linked control inventory denied')
  records=_signed_rows(str(self.root))
  if capture(self.root,'.trustchain/HEAD').decode().strip() not in {x['signature'] for x in records}:raise Refused('baseline native SDK HEAD is not authenticated')
  authenticated={x['object_path'] for x in records}
  for relative in _ledger_paths(self.root):
   raw=json.loads(capture(self.root,relative));entry=raw.get('value',raw);data=entry.get('data') or {};proof=data.get('sdd_evidence') or {}
   selected=proof.get('envelope_hash')==EXPECTED_ENVELOPE or any(x.get('kind')=='spec' and x.get('id')==REF for x in data.get('artifacts',[]) if isinstance(x,dict))
   if selected and (data.get('files') or 'attest' in str(entry.get('tool','')).lower() or data.get('action')=='attest'):
    if relative.removeprefix('.trustchain/') not in authenticated:raise Refused('ambiguous selected source evidence cannot establish zero history')
    raise Refused('selected R6 source already has applied/accepted evidence')
  for record in records:
   data=record.get('payload') or {};proof=data.get('sdd_evidence') or {}
   if proof.get('envelope_hash')==EXPECTED_ENVELOPE and (data.get('files') or 'attest' in str(record.get('tool_id','')).lower() or data.get('action')=='attest'): raise Refused('selected R6 envelope already has applied/accepted evidence')
  return {'owner':owner,'source_admission':admission,'contract':contract,'envelope':old,'profile_bytes_hash':digest(capture(self.root,PROFILE)),
   'envelope_bytes_hash':digest(capture(self.root,ENVELOPE)),'assets':assets,'controls':sorted(set(controls)-{'write_leases.json','write_leases.json.lock','write_lease.json','write_lease.json.lock'}),
   'source_hash':digest(capture(self.root,SOURCE)),'spec_hash':digest(capture(self.root,'docs/specs/SPEC-VERIFIER-AMENDMENT-1.md')),
   'native_identity_hash':digest(capture(self.identity_root,IDENTITY_FILE)),
   'agent_identity_hash':digest(capture(self.root,'.apatch/agent-identity.json')),
   'head_value':capture(self.root,'.trustchain/HEAD').decode().strip(),
   'head_hash':digest(capture(self.root,'.trustchain/HEAD'))}

 def review(self,request):
  assert_can_freeze(self.root)
  if _path(self.root,'.apatch/sdd/contract-intake-pending.json').exists(): raise Refused('another intake incomplete')
  binding=self._binding(request)
  if load_active_leases(str(self.root)):raise Refused('active writer lease prevents administration')
  baseline=self._snapshot(request);old=baseline['envelope']
  if old['forbidden_paths'].count('.apatch/**')!=1: raise Refused('exact original blanket collision required')
  body={k:v for k,v in old.items() if k!='document_hash'}
  body['forbidden_paths']=sorted(set(old['forbidden_paths'])-{'.apatch/**'}|set(CONTROL_PATTERNS))
  new=validate_task_envelope(body);comparison=compare_envelopes(old,new)
  if comparison['added']!={'removed_forbidden_paths':['.apatch/**']} or comparison['non_widening']: raise Refused('explicit exact widening required')
  return _seal({'schema':'apatch.studio.scope-collision-review.v1','workspace':str(self.root),'requirement_ref':REF,
   'authority_id':baseline['owner']['id'],'request':request.model_dump(),'baseline':baseline,
   'new_envelope':new,'comparison':comparison,'scope_expansion':True,'functional_acceptance':False,
   'implementation_actor_may_approve':False,'profile_changed':False})

 def _folder(self,review):return '.apatch/sdd/scope-amendments/'+review['document_hash'][7:]

 def _body(self,review,stage,binding):
  return enrich_payload_with_actor({'schema':'apatch.studio.scope-collision-decision.v1','review_hash':review['document_hash'],
   'authority_id':review['authority_id'],'requester_actor_id':review['request']['actor_id'],'stage':stage,
   'scope_expansion':True,'functional_acceptance':False,'profile_changed':False,
   'contract_hash':review['baseline']['contract']['document_hash'],'old_envelope_hash':review['baseline']['envelope']['document_hash'],
   'new_envelope_hash':review['new_envelope']['document_hash'],
   'native_signer':{'agent_id':binding.agent_id,'public_key_sha256':binding.public_key_sha256}},agent_id=binding.agent_id)

 def _receipt(self,review,stage,binding,*,required=False):
  path=self._folder(review)+'/'+stage+'.json'
  if not _path(self.root,path).exists():
   if required:raise Refused('required native SDK receipt unavailable')
   return None
  locator=_read(self.root,path);_verify_seal(locator,'native SDK receipt locator')
  relative=locator.get('object_path')
  if not isinstance(relative,str) or not re.fullmatch(r'objects/op_[0-9]+\.json',relative):raise Refused('canonical SDK receipt locator required')
  raw=json.loads(capture(self.root,'.trustchain/'+relative));record=raw.get('value',raw)
  identity=binding.resolve(str(self.root));public=identity.key_provider.get_public_key()
  if verify_record_signature(record,TrustChainVerifier(base64.b64encode(public).decode(),binding.agent_id,max_age_seconds=None)) is not True:raise Refused('native SDK signature invalid')
  data=record.get('data') or {};expected=self._body(review,stage,binding)
  if record.get('tool')!=TOOL or record.get('key_id')!=binding.agent_id or data!=expected or canonical_hash(data)!=locator.get('payload_hash') or record.get('signature')!=locator.get('signature') or record.get('parent_signature')!=locator.get('parent_signature'):raise Refused('native signed decision outside exact original owner snapshot')
  return record

 def _idle(self,review,*,lease=None):
  assert_can_freeze(self.root,own_review=review['document_hash'])
  if _path(self.root,'.apatch/sdd/contract-intake-pending.json').exists():raise Refused('another intake incomplete')
  current=load_active_leases(str(self.root))
  if lease is None:
   if current:raise Refused('active writer lease prevents administration')
  elif len(current)!=1 or current[0].get('lease_id')!=lease.get('lease_id') or current[0].get('governed_session_id')!=lease.get('governed_session_id') or current[0].get('pid')!=os.getpid() or current[0].get('canonical_paths')!=lease.get('canonical_paths'):raise Refused('exclusive native owner lease expired or changed')

 def _pinned(self,review,*,new=False,head=None,lease=None):
  self._idle(review,lease=lease)
  snapshot=self._snapshot(ReviewRequest.model_validate(review['request']),expected_envelope=review['new_envelope']['document_hash'] if new else None)
  baseline=dict(review['baseline']);observed=dict(snapshot)
  for key in ('head_hash','head_value'):baseline.pop(key);observed.pop(key)
  if new:
   baseline['envelope']=review['new_envelope'];baseline['envelope_bytes_hash']=observed['envelope_bytes_hash']
  if baseline!=observed:raise Refused('pinned native inputs drifted during administration')
  if head is not None and snapshot['head_value']!=head:raise Refused('native SDK writer head drift; retain fence')

 def _lease(self,review):
  paths=[PROFILE,ENVELOPE,SOURCE,'.apatch/agent-identity.json','.apatch/session_state.json','.apatch/lanes','docs/specs/SPEC-VERIFIER-AMENDMENT-1.md',*review['baseline']['assets']]
  return acquire_path_lease(str(self.root),paths,tool=TOOL,governed_session_id='scope-amendment:'+review['document_hash'],max_seconds=300)

 def _commit(self,review,stage,binding,*,previous_head):
  prior=self._receipt(review,stage,binding)
  if prior is not None:return prior
  pending=_read(self.root,PENDING)
  if pending.get('stage')=='signing_'+stage:raise ExistingSignerRefused('EXISTING_SIGNER_RECONCILIATION_REQUIRED',reconciliation_required=True)
  if capture(self.root,'.trustchain/HEAD').decode().strip()!=previous_head:raise Refused('native SDK head drift before signature')
  tc=TrustChainHelper(str(self.root),auto_init=False,existing_signer=binding);body=self._body(review,stage,binding)
  atomic_write_json(str(_path(self.root,PENDING)),_seal({'schema':'apatch.studio.scope-collision-pending.v1','review_hash':review['document_hash'],'stage':'signing_'+stage}))
  if not tc.commit_action(TOOL,body):raise ExistingSignerRefused('EXISTING_SIGNER_RECEIPT_INVALID',reconciliation_required=True)
  evidence=tc.last_commit_evidence
  raw=json.loads(capture(self.root,'.trustchain/'+evidence['object_path']));record=raw.get('value',raw)
  if record.get('parent_signature')!=previous_head or evidence.get('merkle_root') or capture(self.root,'.trustchain/HEAD').decode().strip()!=record.get('signature'):raise ExistingSignerRefused('EXISTING_SIGNER_HEAD_MISMATCH',reconciliation_required=True)
  _immutable(self.root,self._folder(review)+'/'+stage+'.json',_seal({'object_path':evidence['object_path'],'payload_hash':canonical_hash(record['data']),'signature':record['signature'],'parent_signature':record['parent_signature']}))
  result=self._receipt(review,stage,binding,required=True)
  atomic_write_json(str(_path(self.root,PENDING)),_seal({'schema':'apatch.studio.scope-collision-pending.v1','review_hash':review['document_hash'],'stage':stage}))
  return result

 def _validate_request(self,request):
  review=request.review;_verify_seal(review,'exact native review')
  if request.confirmed is not True or request.expected_snapshot!=review['document_hash'] or review.get('workspace')!=str(self.root):raise Refused('exact confirmed original owner snapshot required')
  prepared=ReviewRequest.model_validate(review['request']);binding=self._binding(prepared)
  if trusted_owner(self.identity_root)['id']!=review['authority_id'] or review['authority_id']!=EXPECTED_OWNER or review['baseline']['contract']['document_hash']!=EXPECTED_PROFILE or review['baseline']['envelope']['document_hash']!=EXPECTED_ENVELOPE:raise Refused('original owner and provenance changed')
  return review,prepared,binding

 def approve(self,request):
  review,prepared,binding=self._validate_request(request);folder=self._folder(review)
  if _path(self.root,folder+'/completed.json').exists():
   with freeze_lock(self.root):
    if _path(self.root,PENDING).exists():raise Refused('incomplete transaction cannot replay')
    approved=self._receipt(review,'approved',binding,required=True);completed=self._receipt(review,'completed',binding,required=True)
    if approved['parent_signature']!=review['baseline']['head_value'] or completed['parent_signature']!=approved['signature']:raise Refused('receipt lineage mismatch')
    self._pinned(review,new=True)
    return {'ok':True,'replayed':True,'review_hash':review['document_hash'],'functional_acceptance':False,'profile_changed':False,'envelope_hash':review['new_envelope']['document_hash']}
  # Refuse caller/baseline drift before creating a lock or journal.
  if self.review(prepared)!=review:raise Refused('native approval snapshot drift')
  with freeze_lock(self.root):
   if self.review(prepared)!=review:raise Refused('native approval snapshot drift under lock')
   lease=self._lease(review)
   try:
    self._pinned(review,head=review['baseline']['head_value'],lease=lease)
    original=capture(self.root,ENVELOPE)
    _immutable(self.root,folder+'/review.json',review)
    _immutable(self.root,folder+'/before.json',_seal({'envelope_base64':base64.b64encode(original).decode(),'envelope_bytes_hash':digest(original),'envelope_mode':stat.S_IMODE(_path(self.root,ENVELOPE).stat().st_mode),'profile_bytes_hash':review['baseline']['profile_bytes_hash']}))
    atomic_write_json(str(_path(self.root,PENDING)),_seal({'schema':'apatch.studio.scope-collision-pending.v1','review_hash':review['document_hash'],'stage':'prepared'}))
    self._pinned(review,head=review['baseline']['head_value'],lease=lease)
    approved=self._commit(review,'approved',binding,previous_head=review['baseline']['head_value'])
    self._pinned(review,head=approved['signature'],lease=lease)
    try:
     _immutable(self.root,'.apatch/sdd/frozen-envelopes/'+EXPECTED_ENVELOPE[7:]+'.json',review['baseline']['envelope'])
     atomic_write_json(str(_path(self.root,ENVELOPE)),review['new_envelope'])
     self._pinned(review,new=True,head=approved['signature'],lease=lease)
    except Exception:
     self._restore(review,lease,approved['signature'])
     rolled=self._commit(review,'rolled_back',binding,previous_head=approved['signature'])
     self._pinned(review,head=rolled['signature'],lease=lease)
     _path(self.root,PENDING).unlink()
     raise
    completed=self._commit(review,'completed',binding,previous_head=approved['signature'])
    self._pinned(review,new=True,head=completed['signature'],lease=lease)
    _path(self.root,PENDING).unlink()
    return {'ok':True,'replayed':False,'review_hash':review['document_hash'],'functional_acceptance':False,'profile_changed':False,'envelope_hash':review['new_envelope']['document_hash']}
   finally:release_path_leases(str(self.root),governed_session_id=lease['governed_session_id'])

 def _restore(self,review,lease,head):
  self._idle(review,lease=lease)
  if capture(self.root,'.trustchain/HEAD').decode().strip()!=head or digest(capture(self.root,PROFILE))!=review['baseline']['profile_bytes_hash']:raise Refused('rollback conflicts with native state; retain fence')
  before=_read(self.root,self._folder(review)+'/before.json');_verify_seal(before,'immutable native preimage')
  raw=base64.b64decode(before['envelope_base64'],validate=True)
  if digest(raw)!=review['baseline']['envelope_bytes_hash'] or before['profile_bytes_hash']!=review['baseline']['profile_bytes_hash']:raise Refused('original native preimage mismatch')
  _write_judge(_path(self.root,ENVELOPE),raw,before['envelope_mode'])
  if digest(capture(self.root,ENVELOPE))!=review['baseline']['envelope_bytes_hash']:raise Refused('exact rollback serialization mismatch; retain fence')

 def reconcile(self,request):
  review,prepared,binding=self._validate_request(request)
  with freeze_lock(self.root):
   pending=_read(self.root,PENDING);_verify_seal(pending,'native pending transaction')
   if pending.get('schema')!='apatch.studio.scope-collision-pending.v1' or pending.get('review_hash')!=review['document_hash']:raise Refused('unrelated pending transaction')
   if str(pending.get('stage','')).startswith('signing_'):raise ExistingSignerRefused('EXISTING_SIGNER_RECONCILIATION_REQUIRED',reconciliation_required=True)
   self._idle(review)
   if _read(self.root,self._folder(review)+'/review.json')!=review:raise Refused('immutable review provenance mismatch')
   approved=self._receipt(review,'approved',binding,required=True)
   if approved['parent_signature']!=review['baseline']['head_value']:raise Refused('native approved lineage mismatch')
   stage=pending.get('stage');lease=self._lease(review)
   try:
    if stage=='approved':
     current=validate_task_envelope(_read(self.root,ENVELOPE))
     if current not in (review['new_envelope'],review['baseline']['envelope']):raise Refused('unrecognized envelope during approved recovery')
     self._pinned(review,new=current==review['new_envelope'],head=approved['signature'],lease=lease)
     self._restore(review,lease,approved['signature'])
     terminal=self._commit(review,'rolled_back',binding,previous_head=approved['signature']);stage='rolled_back'
    elif stage in {'completed','rolled_back'}:
     terminal=self._receipt(review,stage,binding,required=True)
    else:raise Refused('native transaction remains fenced; no automatic acceptance')
    if terminal['parent_signature']!=approved['signature']:raise Refused('native terminal lineage mismatch')
    self._pinned(review,new=stage=='completed',head=terminal['signature'],lease=lease)
    _path(self.root,PENDING).unlink()
    return {'ok':True,'stage':stage,'functional_acceptance':False,'profile_changed':False}
   finally:release_path_leases(str(self.root),governed_session_id=lease['governed_session_id'])


def create_scope_administration_app(workspace,*,identity_root=None,source_workspace=None):
 admin=ScopeAdministration(workspace,identity_root=identity_root,source_workspace=source_workspace);guard=StudioRequestGuard();app=FastAPI()
 @app.middleware('http')
 async def secure(request:Request,call_next):
  denied=guard.authenticate(request)
  response=denied if denied is not None else await call_next(request)
  security_headers(response);return response
 @app.exception_handler(Refused)
 async def refused_handler(request,exc):return JSONResponse({'ok':False,'error_type':'SCOPE_AMENDMENT_REFUSED','error':str(exc)},status_code=409)
 @app.exception_handler(ExistingSignerRefused)
 async def signer_handler(request,exc):return JSONResponse(exc.to_dict(),status_code=409)
 @app.exception_handler(PathLeaseConflict)
 async def lease_handler(request,exc):return JSONResponse({'ok':False,'error_type':'SCOPE_AMENDMENT_LEASE_CONFLICT','error':str(exc)},status_code=409)
 @app.exception_handler(ValueError)
 async def value_handler(request,exc):return JSONResponse({'ok':False,'error_type':'SCOPE_AMENDMENT_REFUSED','error':str(exc)},status_code=409)
 @app.get('/',response_class=HTMLResponse)
 def index():return '<!doctype html><meta name="apatch-studio-session" content="'+guard.token+'"><title>Native scope maintenance</title>'
 @app.post('/api/v1/scope-amendment/review')
 def review(body:ReviewRequest):return admin.review(body)
 @app.post('/api/v1/scope-amendment/approve')
 def approve(body:ApprovalRequest):return admin.approve(body)
 @app.post('/api/v1/scope-amendment/reconcile')
 def reconcile(body:ApprovalRequest):return admin.reconcile(body)
 return app
