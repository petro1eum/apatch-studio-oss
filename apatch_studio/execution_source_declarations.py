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


def publish_execution_source(manager, context):
    """Retain signed bytes before I/O, then publish by the native client transport.

    This is called only for the actual guarded full-delivery context. It never
    syncs unrelated workspaces or mints a key. Retry reuses the same declaration.
    """
    from apatch import governed_work_transport as T
    from apatch_studio.state_io import StateDirectory
    import json
    provider = manager.gateway._workspace_key_provider()
    root = str(manager.workspace)
    config = D.load_config(root)
    filename = 'execution-source-' + context.canonical_binding_id + '.json'
    with manager.store._transaction():
        with StateDirectory(manager.store.directory, create=True) as directory:
            try:
                retained = directory.read_json(filename, limit=16384)
            except FileNotFoundError:
                retained = None
            issued_at = retained.get('issued_at') if isinstance(retained, dict) else None
            declaration = execution_source_declaration(root, source_binding_id=context.source_binding_id,
                execution_binding_id=context.canonical_binding_id, key_provider=provider, issued_at=issued_at)
            if retained is not None and retained != declaration:
                raise ExecutionSourceError('Retained execution source changed')
            if retained is None:
                directory.write_json(filename, declaration)
    path = '/api/internal/project-groups/' + declaration['project_group_id'] + '/governed-work/execution-source-declarations'
    raw = json.dumps({'subject':config['client_id'], 'tenant_id':declaration['tenant_id'], 'declaration':declaration},
        sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    headers = {'Content-Type':'application/json', 'X-Apatch-Client-Id':config['client_id'],
        **T.signed_service_headers(root,method='POST',path=path,raw_body=raw,
            tenant_id=declaration['tenant_id'],subject=config['client_id'],
            expected_key_id=config['service_request_key_id'],key_provider=provider)}
    import httpx
    try:
        with manager.http_client_factory() as client:
            response = client.post(config['platform_url'] + path,content=raw,headers=headers)
    except httpx.HTTPError as exc:
        raise ExecutionSourceError('Execution source transport is unavailable') from exc
    if response.status_code not in (200,201):
        raise ExecutionSourceError('Platform has not acknowledged this execution source')
    try:
        reply = response.json()
        envelope_hash = 'sha256:' + hashlib.sha256(json.dumps(declaration,sort_keys=True,separators=(',',':'),
            ensure_ascii=False,allow_nan=False).encode()).hexdigest()
        if (reply['schema'] != 'trustchain.cowork.execution-source-publication.v1'
                or reply['declaration'] != declaration or reply['envelope_hash'] != envelope_hash
                or reply['published'] is not True or reply['customer_accepted'] is not False):
            raise ValueError()
    except (ValueError,TypeError,KeyError) as exc:
        raise ExecutionSourceError('Platform execution source acknowledgement is inconsistent') from exc
    return reply
