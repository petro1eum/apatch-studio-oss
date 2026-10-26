"""Additive execution-project statement, signed by an existing enrolled key.

This statement identifies a source. It grants no role, runtime, acceptance,
contract, payment or Tracker ownership. Consumers independently verify the
current enrolled key and the exact canonical execution/source bindings.
The caller supplies its Ed25519 implementation; this contract has no crypto
runtime dependency and never reads or creates a signing key.
"""
from copy import deepcopy
from datetime import datetime
import base64
import hashlib
import json
import re
from uuid import UUID

EXECUTION_SOURCE_SCHEMA = 'trustchain.cowork.execution-source-declaration.v1'
SIGNING_DOMAIN = b'TrustChain-Cowork-Execution-Source\x00v1\x00'
_FIELDS = {
    'schema', 'tenant_id', 'project_group_id', 'work_item_id',
    'execution_binding_id', 'execution_binding_hash',
    'source_binding_id', 'source_binding_hash', 'apatch_project_id',
    'executor_key_id', 'issued_at',
}
_PATTERNS = {
    'project_group_id': r'tcpg_[0-9a-f]{32}',
    'work_item_id': r'tcpwi_[0-9a-f]{32}',
    'execution_binding_id': r'tcawieb_[0-9a-f]{32}',
    'source_binding_id': r'tcpsb_[0-9a-f]{32}',
    'execution_binding_hash': r'sha256:[0-9a-f]{64}',
    'source_binding_hash': r'sha256:[0-9a-f]{64}',
    'apatch_project_id': r'[0-9a-f]{16}',
    'executor_key_id': r'sha256:[0-9a-f]{64}',
}


class ExecutionSourceError(ValueError):
    pass


def _fail(field):
    # Refusals never echo rejected private values.
    raise ExecutionSourceError('Invalid execution source field: ' + field)


def canonical_bytes(document):
    return json.dumps(document, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _body(document):
    if type(document) is not dict or set(document) != _FIELDS:
        _fail('body')
    if document['schema'] != EXECUTION_SOURCE_SCHEMA:
        _fail('schema')
    tenant = document['tenant_id']
    try:
        if type(tenant) is not str or str(UUID(tenant)) != tenant or UUID(tenant).int == 0:
            _fail('tenant_id')
    except (ValueError, AttributeError):
        _fail('tenant_id')
    for field, pattern in _PATTERNS.items():
        value = document[field]
        if type(value) is not str or re.fullmatch(pattern, value) is None:
            _fail(field)
    issued = document['issued_at']
    if type(issued) is not str or re.fullmatch(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z', issued) is None:
        _fail('issued_at')
    try:
        datetime.fromisoformat(issued.replace('Z', '+00:00'))
    except ValueError:
        _fail('issued_at')
    return deepcopy(document)


def declaration_id(body):
    """Stable identity of exact unsigned source facts, including issue time."""
    return 'sha256:' + hashlib.sha256(SIGNING_DOMAIN + canonical_bytes(_body(body))).hexdigest()


def signing_input(body):
    checked = _body(body)
    return SIGNING_DOMAIN + canonical_bytes(checked)


def _signature(raw):
    if type(raw) is not dict or set(raw) != {'algorithm', 'value'} or raw['algorithm'] != 'Ed25519':
        _fail('signature')
    value = raw['value']
    if type(value) is not str or re.fullmatch(r'[A-Za-z0-9_-]{86}', value) is None:
        _fail('signature.value')
    try:
        decoded = base64.urlsafe_b64decode(value + '==')
    except (ValueError, TypeError):
        _fail('signature.value')
    if len(decoded) != 64 or base64.urlsafe_b64encode(decoded).rstrip(b'=').decode() != value:
        _fail('signature.value')
    return decoded


def validate_execution_source_declaration(document):
    """Validate closed shape/content identity only; this is not signature proof."""
    if type(document) is not dict or set(document) != _FIELDS | {'declaration_id', 'signature'}:
        _fail('document')
    body = _body({field: document[field] for field in _FIELDS})
    if document['declaration_id'] != declaration_id(body):
        _fail('declaration_id')
    _signature(document['signature'])
    return deepcopy(document)


def build_execution_source_declaration(body, *, sign):
    """Use the explicitly supplied existing signer; never choose or create one."""
    checked = _body(body)
    signed = sign(signing_input(checked))
    if type(signed) is not bytes or len(signed) != 64:
        _fail('signature')
    return validate_execution_source_declaration({**checked,
        'declaration_id': declaration_id(checked),
        'signature': {'algorithm': 'Ed25519', 'value': base64.urlsafe_b64encode(signed).rstrip(b'=').decode()}})


def verify_execution_source_declaration(document, *, trusted_public_key, verify):
    """Verify with caller-resolved current public key and Ed25519 primitive.

    verify(message, signature) must raise on any invalid signature. The key must
    come from the authoritative enrollment/source binding, never this document.
    Current status, tenant, work item, and binding lineage remain consumer checks.
    """
    checked = validate_execution_source_declaration(document)
    if type(trusted_public_key) is not bytes or len(trusted_public_key) != 32:
        _fail('trusted_public_key')
    if checked['executor_key_id'] != 'sha256:' + hashlib.sha256(trusted_public_key).hexdigest():
        _fail('executor_key_id')
    try:
        result = verify(signing_input({field: checked[field] for field in _FIELDS}), _signature(checked['signature']))
        if result is False:
            raise ValueError('signature refused')
    except Exception:
        _fail('signature')
    return checked
