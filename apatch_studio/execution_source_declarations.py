"""Produce a portable source statement from two genuine native receipts.

No role, key, task, execution, result, consent or external write is created.
Canonical Platform and Company consumers independently verify current authority.
"""
from datetime import datetime, timezone
import hashlib
import re
from pathlib import Path

from apatch import governed_work as G, governed_work_delivery as D
from apatch import work_item_acceptance as W
from apatch.contribution import project_identity
from apatch_studio._contracts.execution_source_declaration import (
    EXECUTION_SOURCE_SCHEMA, ExecutionSourceError,
    build_execution_source_declaration, verify_execution_source_declaration,
)


def execution_source_declaration(workspace, *, source_binding_id,
                                 execution_binding_id, key_provider, issued_at=None):
    """Validate canonical receipts and sign only this workspace's real source.

    key_provider must be explicitly selected by the native workspace identity
    loader. This function never discovers an ambient signer or generates a key.
    It returns bytes as data; publishing/retaining them is a separate operation.
    """
    for value, pattern in ((source_binding_id, r'tcpsb_[0-9a-f]{32}'),
                           (execution_binding_id, r'tcawieb_[0-9a-f]{32}')):
        if type(value) is not str or re.fullmatch(pattern, value) is None:
            raise ExecutionSourceError('An exact native binding identifier is required')
    root = str(Path(workspace).resolve(strict=True))
    if key_provider is None:
        raise ExecutionSourceError('An existing workspace signer is required')
    public = key_provider.get_public_key()
    if type(public) is not bytes or len(public) != 32:
        raise ExecutionSourceError('The workspace signer is not Ed25519')
    config = D.load_config(root)
    request_key_id = 'sha256:' + hashlib.sha256(public).hexdigest()
    if request_key_id != config['service_request_key_id']:
        raise ExecutionSourceError('The workspace signer differs from its native registration')
    source = G.load_project_source_binding(root, source_binding_id)
    change = G.load_change(root, source['change_id'])
    G.verify_document_signature(change, {G.signer_key_id(key_provider): public})
    source = G.validate_project_source_binding(source, change=change,
        trusted_authority_keys=config['binding_authority_keys'])
    binding = W.validate_binding(G._read_document(W.binding_path(root, execution_binding_id)),
        trusted_keys=config['binding_authority_keys'])
    if (binding['binding_id'] != execution_binding_id or source['binding_id'] != source_binding_id
            or change['actor_key_id'] != G.signer_key_id(key_provider)):
        raise ExecutionSourceError('The native source issuer differs from the executor')
    for field in ('tenant_id', 'project_group_id', 'work_program_id',
                  'work_program_hash', 'change_id', 'change_hash', 'actor_ref'):
        if source[field] != binding[field]:
            raise ExecutionSourceError('The native execution and source receipts disagree: ' + field)
    body = {
        'schema': EXECUTION_SOURCE_SCHEMA, 'tenant_id': binding['tenant_id'],
        'project_group_id': binding['project_group_id'], 'work_item_id': binding['work_item_id'],
        'execution_binding_id': binding['binding_id'], 'execution_binding_hash': G.document_hash(binding),
        'source_binding_id': source['binding_id'], 'source_binding_hash': G.document_hash(source),
        'apatch_project_id': project_identity(root)['id'], 'executor_key_id': request_key_id,
        'issued_at': issued_at or datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
    }
    document = build_execution_source_declaration(body, sign=key_provider.sign)
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    key = Ed25519PublicKey.from_public_bytes(public)
    return verify_execution_source_declaration(document, trusted_public_key=public,
        verify=lambda message, signature: key.verify(signature, message))
