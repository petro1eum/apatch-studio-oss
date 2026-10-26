"""Publication uses the selected workspace, then restores ambient SDK identity."""
import json
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
from apatch import governed_work as G, governed_work_mcp as M
from apatch.trust_identity import active_workspace_identity_scope
from apatch_studio.governed_work_gateway import APatchGovernedWorkGateway, GovernedWorkGatewayError


@pytest.fixture
def case(tmp_path, monkeypatch):
    def key(name):
        path = tmp_path / (name + '.pem')
        path.write_bytes(Ed25519PrivateKey.generate().private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
        return path
    selected, ambient = key('selected'), key('ambient')
    (tmp_path / '.apatch').mkdir()
    (tmp_path / '.apatch/agent-identity.json').write_text(json.dumps({
        'agent_id': 'selected-test-only', 'key_backend': 'pem', 'key': str(selected)}))
    for name in ('APATCH_AGENT_SIGN_CMD', 'APATCH_AGENT_PUBKEY', 'APATCH_AGENT_CERT'):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv('APATCH_AGENT_ID', 'ambient-test-only')
    monkeypatch.setenv('APATCH_AGENT_KEY', str(ambient))
    from apatch_studio.governed_work_gateway import _load_exact_workspace_identity
    provider = _load_exact_workspace_identity(str(tmp_path)).key_provider
    previous = G._load_local_provider(str(tmp_path)).get_public_key()
    assert previous != provider.get_public_key()
    config = {'platform_url': 'https://example.invalid', 'client_id': 'test-only',
              'service_request_key_id': G.signer_key_id(provider)}
    body = {'schema': M.SHARE_PLAN_SCHEMA, 'platform_origin': config['platform_url'],
        'client_subject': config['client_id'], 'tenant_id': '11111111-1111-4111-8111-111111111111',
        'project_group_id': 'tcpg_'+'1'*32, 'scope': M._SHARE_SCOPE,
        'evidence_bundle_ref': {'bundle_id': 'apweb_'+'2'*32, 'bundle_hash': 'sha256:'+'3'*64},
        'timesheet_ref': {'timesheet_id': 'aptime_'+'4'*32, 'timesheet_hash': 'sha256:'+'5'*64,
                         'claimed_active_seconds': 1},
        'connection_generation': G.value_hash(config)}
    plan = {**body, 'plan_hash': G.value_hash(body)}
    calls = []
    def check_native_identity():
        assert active_workspace_identity_scope() == str(tmp_path.resolve())
        assert G._load_local_provider(str(tmp_path)).get_public_key() == provider.get_public_key()
    def preview(*args, **kwargs):
        check_native_identity(); calls.append('preview')
        return {'ok': True, 'plan': plan}
    def publish(*args, **kwargs):
        check_native_identity(); calls.append('publish')
        return {'ok': True, 'delivery': {'entry_id': 'test-entry', 'request_hash': 'test-hash'}}
    gateway = APatchGovernedWorkGateway(tmp_path, domain=G,
        api=SimpleNamespace(preview_governed_evidence_publication=preview, publish_governed_evidence=publish),
        delivery=SimpleNamespace(load_config=lambda _: config), work_item_acceptance=SimpleNamespace())
    monkeypatch.setattr(gateway, '_workspace_key_provider', lambda: provider)
    monkeypatch.setattr(gateway, '_selected_delivery_contract', lambda: None)
    monkeypatch.setattr(gateway, '_deliver_selected_evidence', lambda **kw: {'delivered': 1})
    return tmp_path, gateway, calls, plan, previous


def test_preview_and_publication_keep_one_selected_physical_key(case):
    root, gateway, calls, plan, previous = case
    assert gateway.preview_evidence(binding_id='tcpsb_'+'6'*32)['plan'] == plan
    assert active_workspace_identity_scope() is None
    assert G._load_local_provider(str(root)).get_public_key() == previous
    result = gateway.publish_evidence(plan=plan, confirmation='publish:'+plan['plan_hash'])
    assert result['synchronization']['status'] == 'acknowledged'
    assert calls == ['preview', 'publish']
    assert active_workspace_identity_scope() is None
    assert G._load_local_provider(str(root)).get_public_key() == previous


def test_scope_is_restored_after_native_publication_refusal(case):
    root, gateway, calls, plan, previous = case
    gateway.preview_evidence(binding_id='tcpsb_'+'6'*32)
    with pytest.raises(GovernedWorkGatewayError) as error:
        gateway.publish_evidence(plan=plan, confirmation='wrong')
    assert error.value.code == 'publication_confirmation_mismatch'
    assert calls == ['preview']
    assert active_workspace_identity_scope() is None
    assert G._load_local_provider(str(root)).get_public_key() == previous


def test_preview_pins_requested_hash_and_rejects_a_different_native_selection(case):
    root, gateway, calls, plan, previous = case
    selected = plan['evidence_bundle_ref']['bundle_hash']
    original = gateway._api.preview_governed_evidence_publication
    def exact(*args, **kwargs):
        assert kwargs['evidence_bundle_hash'] == selected
        return original(*args, **kwargs)
    gateway._api.preview_governed_evidence_publication = exact
    assert gateway.preview_evidence(binding_id='tcpsb_'+'6'*32, evidence_bundle_hash=selected)['plan'] == plan
    gateway._api.preview_governed_evidence_publication = original
    with pytest.raises(GovernedWorkGatewayError) as error:
        gateway.preview_evidence(binding_id='tcpsb_'+'6'*32, evidence_bundle_hash='sha256:'+'f'*64)
    assert error.value.code == 'publication_evidence_invalid'
    assert gateway._publication_selection is None
    assert active_workspace_identity_scope() is None
    assert G._load_local_provider(str(root)).get_public_key() == previous
