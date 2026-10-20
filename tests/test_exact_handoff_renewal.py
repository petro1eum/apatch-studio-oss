"""Real Core acceptance with synthetic Ed25519 keys; no live consent or agent."""
import base64
import hashlib
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from apatch import execution_proposal as P, governed_work as G, governed_work_mcp as M
from apatch_studio.exact_contract_handoffs import native_acceptance_purpose

class Provider:
    def __init__(self): self.private = Ed25519PrivateKey.generate()
    def get_public_key(self): return self.private.public_key().public_bytes_raw()
    def sign(self, payload): return self.private.sign(payload)

def test_renewed_handoff_has_its_own_acceptance_and_same_handoff_replays(tmp_path):
    key = Provider()
    public = key.get_public_key()
    key_id = 'ed25519:sha256:' + hashlib.sha256(public).hexdigest()
    now = datetime.now(timezone.utc)
    stamp = lambda value: value.strftime('%Y-%m-%dT%H:%M:%S.%fZ')
    common = {'schema':P.SCHEMA,'tenant_id':'11111111-1111-4111-8111-111111111111',
        'project_group_id':'tcpg_'+'1'*32,'work_item_id':'tcpwi_'+'2'*32,
        'work_item_hash':'sha256:'+'3'*64,'authority_version':1,
        'work_program_id':'tcwp_'+'4'*32,'work_program_hash':'sha256:'+'5'*64,
        'mode':'new_change','objective':'TEST-ONLY same agreed requirement',
        'acceptance_criteria':['TEST-ONLY preserve native acceptance identity'],
        'audience':'apatch-studio','nonce':base64.urlsafe_b64encode(b'n'*32).rstrip(b'=').decode(),
        'issued_at':stamp(now),'expires_at':stamp(now+timedelta(minutes=5))}
    configured = M.configure_governed_work(str(tmp_path), platform_url='https://platform.example',
        client_id='apatch:test',binding_authority_keys={key_id:base64.urlsafe_b64encode(public).rstrip(b'=').decode()},request_key_provider=key)
    assert configured['ok']
    spec = tmp_path/'SPEC-LOCAL.md'
    spec.write_text('# SPEC-LOCAL -- Local contract\n\n> **apatch artifact:** `spec:SPEC-LOCAL`\n\n## R1 Local acceptance\n\nImplement the locally reviewed contract.\n\n(verify: true)\n')
    results=[]
    for mark in ('6','7'):
        proposal={**common,'intent_id':'tcapsei_'+mark*32}
        proposal['signature']={'algorithm':'Ed25519','key_id':key_id,'value':base64.urlsafe_b64encode(key.sign(G._platform_signature_payload(proposal,purpose=P.PURPOSE))).rstrip(b'=').decode()}
        kwargs=dict(proposal=proposal,confirmation=common['work_item_id']+':1',spec_id='SPEC-LOCAL',
            spec_path=str(spec),purpose=native_acceptance_purpose('SPEC-LOCAL#R1','tceh_'+mark*32),
            queue_source_binding=False,request_key_provider=key,now=now)
        first=M.accept_execution_proposal(str(tmp_path),**kwargs)
        assert first['ok'], first
        repeated=M.accept_execution_proposal(str(tmp_path),**kwargs)
        assert repeated['ok'] and repeated['proposal_acceptance']==first['proposal_acceptance']
        assert not first['work_started'] and not repeated['stored']
        results.append(first)
    assert results[0]['change']['change_id'] != results[1]['change']['change_id']
    assert results[0]['proposal_acceptance']['intent_id'] != results[1]['proposal_acceptance']['intent_id']
    assert len(list((tmp_path/'.apatch/governed_work/proposal_acceptances').glob('*.json')))==2
    assert not (tmp_path/'.apatch/session_state.json').exists()
