"""Additive, closed profiles for consented acceptance-plan.v2.

This module contains no credentials, transport, database access or authority.
The runtime and Platform must independently validate the same pinned document.
"""
from __future__ import annotations
import ipaddress
import re
from urllib.parse import urlsplit

EXTENDED_SCHEMA = 'trustchain.cowork.acceptance-plan.v2'
RESOURCES = {'memory_bytes': 1610612736, 'cpu_millis': 1000, 'pids': 256, 'scratch_bytes': 33554432}
PROFILES = {'managed-sandbox.v2': 'none', 'managed-public-network.v1': 'public_http'}
HASH = re.compile(r'sha256:[a-f0-9]{64}\Z')
IDENT = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')

class ProfileError(ValueError):
    pass

def require(ok, reason):
    if not ok:
        raise ProfileError(reason)

def public_service_url(value):
    require(isinstance(value, str) and 0 < len(value) <= 2048 and not any(ord(c) < 33 for c in value), 'service_url')
    p = urlsplit(value)
    require(p.scheme in {'http', 'https'} and p.hostname and not p.username and not p.password
            and not p.fragment and not p.query and p.port in {None, 80, 443}, 'service_url')
    host = p.hostname.lower()
    require(host != 'localhost' and not host.endswith(('.localhost', '.local', '.internal')) and '.' in host,
            'service_url')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return value
    require(address.is_global, 'service_url')
    return value

def _validate_environment(env):
    require(type(env) is dict and set(env) == {'executor','profile','image_digest','network_mode','resources','services','secret_refs'}, 'environment_shape')
    require(env['executor'] == 'platform_sandbox' and env['profile'] in PROFILES
            and env['network_mode'] == PROFILES[env['profile']]
            and isinstance(env['image_digest'], str) and HASH.fullmatch(env['image_digest']) is not None,
            'environment')
    require(type(env['resources']) is dict and env['resources'] == RESOURCES
            and all(type(v) is int for v in env['resources'].values()), 'environment_resources')
    require(type(env['secret_refs']) is list and len(env['secret_refs']) <= 16
            and len(set(env['secret_refs'])) == len(env['secret_refs'])
            and all(isinstance(s,str) and re.fullmatch(r'secret-ref:[A-Za-z0-9_.:-]{1,128}',s) for s in env['secret_refs']), 'secret_reference')
    require(type(env['services']) is list and len(env['services']) <= 16, 'environment_services')
    ids=set()
    for s in env['services']:
        require(type(s) is dict and set(s) == {'service_id','url','response_sha256','timeout_seconds'}, 'environment_service')
        require(isinstance(s['service_id'],str) and IDENT.fullmatch(s['service_id']) and s['service_id'] not in ids
                and isinstance(s['response_sha256'],str) and HASH.fullmatch(s['response_sha256'])
                and type(s['timeout_seconds']) is int and 1 <= s['timeout_seconds'] <= 10, 'environment_service')
        public_service_url(s['url']); ids.add(s['service_id'])
    require(not env['services'] or env['network_mode'] == 'public_http', 'offline_services')

def _validate_inputs(inputs, work_item_id):
    require(type(inputs) is list and len(inputs) <= 64, 'acceptance_inputs')
    ids=set()
    shapes={
        'work_result': {'input_id','kind','work_item_id','work_item_hash','authority_version','release_id','release_hash','required_state'},
        'folder': {'input_id','kind','folder_id','authority_version','grant_id','grant_authority_version'},
        'result': {'input_id','kind','release_id','release_hash','required_state'},
        'human': {'input_id','kind','work_item_id','authority_version','decision','decision_hash'},
        'human_wait': {'input_id','kind','work_item_id','authority_version','work_item_hash','decision','actor_role'},
        'resource': {'input_id','kind','binding_id','binding_hash','authority_version','actions'},
    }
    for v in inputs:
        require(type(v) is dict and v.get('kind') in shapes and set(v)==shapes[v['kind']], 'acceptance_input_shape')
        require(isinstance(v['input_id'],str) and IDENT.fullmatch(v['input_id']) and v['input_id'] not in ids, 'acceptance_input_id')
        ids.add(v['input_id'])
        if v['kind']=='work_result':
            require(re.fullmatch(r'tcpwi_[a-f0-9]{32}',str(v['work_item_id'])) and v['work_item_id'] != work_item_id
                    and HASH.fullmatch(str(v['work_item_hash']))
                    and type(v['authority_version']) is int and 1 <= v['authority_version'] <= (1 << 53) - 1
                    and re.fullmatch(r'tcwr_[a-f0-9]{32}',str(v['release_id'])) and HASH.fullmatch(str(v['release_hash']))
                    and v['required_state'] in {'submitted','accepted'}, 'acceptance_work_result_input')
        elif v['kind']=='folder':
            require(re.fullmatch(r'tcpfr_[a-f0-9]{32}',str(v['folder_id']))
                    and re.fullmatch(r'tcpfg_[a-f0-9]{32}',str(v['grant_id']))
                    and all(type(v[k]) is int and 1 <= v[k] <= (1 << 53) - 1 for k in ('authority_version','grant_authority_version')),
                    'acceptance_folder_input')
        elif v['kind']=='result':
            require(re.fullmatch(r'tcwr_[a-f0-9]{32}',str(v['release_id'])) and HASH.fullmatch(str(v['release_hash']))
                    and v['required_state'] in {'submitted','accepted'}, 'acceptance_result_input')
        elif v['kind']=='human_wait':
            require(re.fullmatch(r'tcpwi_[a-f0-9]{32}',str(v['work_item_id'])) and v['work_item_id'] != work_item_id
                    and type(v['authority_version']) is int and v['authority_version'] >= 1
                    and v['decision'] in {'close','return','cancel'} and v['actor_role'] in {'owner','reviewer'}
                    and HASH.fullmatch(str(v['work_item_hash'])), 'acceptance_human_wait_input')
        elif v['kind']=='human':
            require(re.fullmatch(r'tcpwi_[a-f0-9]{32}',str(v['work_item_id'])) and v['work_item_id'] != work_item_id
                    and type(v['authority_version']) is int and v['authority_version'] >= 1
                    and v['decision'] in {'close','return','cancel'} and HASH.fullmatch(str(v['decision_hash'])), 'acceptance_human_input')
        else:
            require(re.fullmatch(r'tcnrb_[a-f0-9]{32}',str(v['binding_id'])) and HASH.fullmatch(str(v['binding_hash']))
                    and type(v['authority_version']) is int and v['authority_version'] >= 1
                    and type(v['actions']) is list and 0 < len(v['actions']) <= 2
                    and len(set(v['actions'])) == len(v['actions'])
                    and all(a in {'read','write'} for a in v['actions']), 'acceptance_resource_input')
    return ids


def validate_environment(env):
    try:
        return _validate_environment(env)
    except ProfileError:
        raise
    except (TypeError,ValueError,KeyError,AttributeError):
        raise ProfileError('environment_shape') from None

def validate_inputs(inputs,work_item_id):
    try:
        return _validate_inputs(inputs,work_item_id)
    except ProfileError:
        raise
    except (TypeError,ValueError,KeyError,AttributeError):
        raise ProfileError('acceptance_input_shape') from None
