"""CDD-G09: actual import guard, without app, runner or crypto dependencies.

Cowork tests cover exact byte delivery. These test the middleware decisions,
not a simulated importer, a started Studio service or crypto acceptance.
"""
import pytest
from starlette.requests import Request
from starlette.responses import Response
from apatch_studio.security import StudioRequestGuard

PATH = '/api/v1/exact-contract-handoffs/import'
ORIGIN = 'https://cowork.example'


def request(method='POST', path=PATH, **headers):
    return Request({'type':'http','method':method,'path':path,'scheme':'http',
        'headers':[(k.lower().replace('_','-').encode(),v.encode()) for k,v in
                   {'host':'127.0.0.1:8765',**headers}.items()]})


@pytest.fixture
def guard():
    return StudioRequestGuard(trusted_execution_origins=frozenset({ORIGIN,'http://127.0.0.1:8766'}))


@pytest.mark.parametrize('origin', [ORIGIN,'http://127.0.0.1:8766'])
def test_trusted_browser_may_import_but_never_confirm_without_local_session(guard, origin):
    req=request(origin=origin,content_type='application/json')
    assert guard.authenticate(req) is None
    response=Response()
    guard.cors_headers(response,req)
    assert response.headers['access-control-allow-origin'] == origin
    assert 'access-control-allow-credentials' not in response.headers
    assert guard.authenticate(request('POST',PATH.replace('/import','/tceh_'+'5'*32+'/confirm'),
        origin=origin,content_type='application/json')).status_code == 401


@pytest.mark.parametrize('headers', [
    {'origin':'https://attacker.invalid','content_type':'application/json'},
    {'origin':'http://127.0.0.1:9999','content_type':'application/json'},
    {'origin':ORIGIN,'content_type':'text/plain'},
    {'origin':'https://cowork.example:bad','content_type':'application/json'},
])
def test_wrong_origin_or_type_cannot_enter_import(guard, headers):
    assert guard.authenticate(request(**headers)).status_code == 403


def test_cors_does_not_open_list_confirm_or_other_api_even_with_a_cross_origin_token(guard):
    base='/api/v1/exact-contract-handoffs'
    assert guard.authenticate(request('GET',base,origin=ORIGIN)).status_code == 401
    endpoint=base+'/tceh_'+'5'*32+'/confirm'
    assert guard.authenticate(request('POST',endpoint,origin=ORIGIN,
        x_apatch_studio_session=guard.token)).status_code == 403
    assert guard.authenticate(request('OPTIONS',endpoint,origin=ORIGIN)).status_code == 401
    response=Response()
    guard.cors_headers(response,request('POST',endpoint,origin=ORIGIN))
    assert 'access-control-allow-origin' not in response.headers


def test_local_manual_import_still_requires_the_process_session(guard):
    local='http://127.0.0.1:8765'
    assert guard.authenticate(request(origin=local,content_type='application/json')).status_code == 401
    assert guard.authenticate(request(origin=local,content_type='application/json',x_apatch_studio_session=guard.token)) is None


def test_only_import_post_content_type_can_pass_private_network_preflight(guard):
    req=request('OPTIONS',origin=ORIGIN,access_control_request_method='POST',
        access_control_request_headers='content-type',access_control_request_private_network='true')
    response=guard.preflight(req)
    assert response.status_code == 204
    guard.cors_headers(response,req)
    assert response.headers['access-control-allow-private-network'] == 'true'
    assert guard.preflight(request('OPTIONS',origin=ORIGIN,access_control_request_method='POST',
        access_control_request_headers='content-type,authorization')).status_code == 403
    assert guard.preflight(request('OPTIONS',origin=ORIGIN,access_control_request_method='DELETE')).status_code == 403


@pytest.mark.parametrize('origin', ['http://remote.example','https://cowork.example/path','https://user@cowork.example','https://cowork.example:bad'])
def test_invalid_trust_configuration_cannot_enable_remote_http(origin):
    with pytest.raises(ValueError):
        StudioRequestGuard(trusted_execution_origins=frozenset({origin}))


def test_unconfigured_studio_does_not_trust_cowork_by_default():
    guard=StudioRequestGuard()
    assert guard.authenticate(request(origin=ORIGIN,content_type='application/json')).status_code == 403


def test_legacy_import_keeps_the_same_narrow_trust_rule(guard):
    req=request(path='/api/v1/execution-intents/import',origin=ORIGIN,content_type='application/json')
    assert guard.authenticate(req) is None


def test_exact_trust_loader_can_name_the_existing_local_cowork_origin():
    import base64
    import hashlib
    from apatch_studio.exact_contract_handoffs import ExactContractTrust
    # Public shape fixture only. No private key or signature is created.
    public=bytes(32)
    keys={'sha256:'+hashlib.sha256(public).hexdigest():base64.urlsafe_b64encode(public).decode().rstrip('=')}
    trust=ExactContractTrust.from_document({'schema':'apatch.studio.exact-contract-trust.v1',
        'trusted_origins':['http://127.0.0.1:8766'], 'handoff_keys':keys,'association_keys':keys,'legacy_keys':keys})
    guard=StudioRequestGuard(trusted_execution_origins=trust.trusted_origins)
    assert guard.authenticate(request(origin='http://127.0.0.1:8766',content_type='application/json')) is None
