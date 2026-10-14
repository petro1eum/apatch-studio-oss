"""Pinned, single-entry native delivery; no protocol or custody substitution.

The private SDK ACK/store helpers are an explicit compatibility boundary, not
a public selector API. Unsupported bytes/origin/ABI fail before queue access,
signing or HTTP. Source and evidence use this SAME bounded implementation.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import inspect
import json
from pathlib import Path

from apatch import governed_work as G
from apatch import governed_work_delivery as D
from apatch import governed_work_mcp as M
from apatch import governed_work_transport as T


class SelectedDeliveryError(RuntimeError):
    def __init__(self, *, code='publication_entry_invalid'):
        super().__init__('The selected native delivery record is unavailable or changed')
        self.code = code


def qualify_native_delivery():
    pins = {
        G: '739539e4d918c3ec7f3a1b2db13697b4c7c56d7362bc39128a7ac07abdd74225',
        D: '0f0e9aff091fc205d4166011ab07897fd3e705f0f4230d10a6658ba9a67e6bcd',
        M: '706bb92b053e2d5cdb06b976d8a0f0e914e757e325a7ea1f4e86560252f803e7',
        T: 'ad83263d9b60fa42d447f202893a2835ffc83443b28813e70036cb608c93596d',
    }
    try:
        distribution = importlib.metadata.distribution('apatch')
        origin = Path(distribution.locate_file('apatch')).resolve()
        if distribution.version != '0.8.47':
            raise ValueError('unsupported installed native version')
        for module, expected in pins.items():
            path = Path(module.__file__)
            if (path.is_symlink() or path.resolve().parent != origin
                    or hashlib.sha256(path.read_bytes()).hexdigest() != expected):
                raise ValueError('unsupported installed native source')
        signatures = {
            D._find_outbox_entry: {'target_dir','entry_id'},
            D._ack_evidence: {'entry','body','trusted_authority_keys'},
            D._ack_source_binding: {'target_dir','entry','body','trusted_authority_keys'},
            D._ack_path: {'entry_path'},
            D._retirement_is_active: {'target_dir','entry_path','entry','key_provider'},
            G._atomic_json: {'path','document'},
        }
        if any(set(inspect.signature(function).parameters) != parameters
                for function, parameters in signatures.items()):
            raise ValueError('unsupported native private-helper ABI')
    except (AttributeError, ImportError, OSError, ValueError):
        raise SelectedDeliveryError(code='publication_runtime_unsupported') from None


def _selected_documents(entry, scope, provider, request_hash):
    G._expect_exact_keys(scope, {'command','tenant_id','project_group_id','client_id'}, 'selected scope')
    if any(entry[key] != scope[key] for key in scope):
        raise ValueError('selected scope changed')
    command = scope['command']
    actor_keys = {G.signer_key_id(provider): provider.get_public_key()}
    if command == 'source_binding':
        payload = G._expect_exact_keys(entry['payload'], {'change'}, 'source payload')
        change = G.validate_change(payload['change'], trusted_actor_keys=actor_keys)
        if (change['tenant_id'] != scope['tenant_id'] or change['project_group_id'] != scope['project_group_id']
                or G.value_hash({'command':'create_source_binding','payload':change}) != request_hash):
            raise ValueError('selected signed Change changed')
        endpoint = f"/api/internal/project-groups/{scope['project_group_id']}/governed-work/source-bindings"
        idempotency = 'source-binding:' + change['change_id']
    elif command == 'evidence_admission':
        payload = G._expect_exact_keys(entry['payload'], {'evidence_bundle','timesheet_draft'}, 'evidence payload')
        bundle = G.validate_work_evidence_bundle(payload['evidence_bundle'], trusted_actor_keys=actor_keys)
        sheet = G.validate_timesheet_draft(payload['timesheet_draft'], trusted_actor_keys=actor_keys)
        if (bundle['timesheet_ref']['timesheet_id'] != sheet['timesheet_id']
                or bundle['timesheet_ref']['timesheet_hash'] != G.document_hash(sheet)
                or bundle['timesheet_ref']['claimed_active_seconds'] != sheet['claimed_active_seconds']
                or bundle['project_source_binding_id'] != sheet['project_source_binding_id']
                or bundle['project_source_binding_hash'] != sheet['project_source_binding_hash']
                or G.value_hash({'command':'admit_evidence','payload':payload}) != request_hash):
            raise ValueError('selected signed evidence changed')
        endpoint = f"/api/internal/project-groups/{scope['project_group_id']}/governed-work/evidence-admissions"
        idempotency = 'evidence-admission:' + bundle['bundle_id']
    else:
        raise ValueError('unsupported selected command')
    if (entry['endpoint'] != endpoint or entry['idempotency_key'] != idempotency
            or entry['request_hash'] != request_hash
            or entry['entry_id'] != 'apgwo_' + request_hash.split(':',1)[1][:32]):
        raise ValueError('selected immutable envelope changed')
    return payload


def _cached_ack(root, path, entry, config):
    ack_path = D._ack_path(path)
    if not ack_path.exists():
        return None
    keys = {'schema','entry_id','request_hash','command','resource_id','resource_hash','projection_cursor','acknowledged_at'}
    if entry['command'] == 'evidence_admission':
        keys.add('platform_receipt_hash')
    ack = G._expect_exact_keys(G._read_document(ack_path), keys, 'selected cached ACK')
    if (ack['schema'] != 'apatch.governed-work-ack.v1'
            or any(ack[key] != entry[key] for key in ('entry_id','request_hash','command'))):
        raise ValueError('selected cached ACK identity changed')
    G._integer(ack['projection_cursor'], 'projection_cursor')
    G._timestamp(ack['acknowledged_at'], 'acknowledged_at')
    if entry['command'] == 'evidence_admission':
        bundle = entry['payload']['evidence_bundle']
        G._matches(ack['platform_receipt_hash'], D._HASH64_RE, 'platform_receipt_hash')
        if ack['resource_id'] != bundle['bundle_id'] or ack['resource_hash'] != G.document_hash(bundle):
            raise ValueError('selected cached evidence ACK changed')
    else:
        binding = G.validate_project_source_binding(G.load_project_source_binding(root, ack['resource_id']),
            change=entry['payload']['change'], trusted_authority_keys=config['binding_authority_keys'])
        if G.document_hash(binding) != ack['resource_hash']:
            raise ValueError('selected cached source ACK changed')
    return ack


def dispatch_selected(target_dir, *, entry_id, request_hash, key_provider,
                      expected_scope, context_guard=None, response_guard=None, http_client_factory=None):
    """Read/validate/sign/transmit only this exact queued request.

    The caller pins its current authority/connection in context_guard. Queue
    and ACK bytes are never rewritten to repair a mismatch. Existing derived
    ACKs are reported honestly as not newly checked signatures.
    """
    qualify_native_delivery()
    root = str(Path(target_dir).resolve())
    try:
        G._matches(request_hash, D._HASH64_RE, 'selected request_hash')
        path, entry = D._find_outbox_entry(root, entry_id)
        initial_bytes = path.read_bytes()
        if G.canonical_bytes(json.loads(initial_bytes)) != G.canonical_bytes(entry):
            raise ValueError('selected queued request changed during read')
        config = D.load_config(root)
        if config['client_id'] != expected_scope['client_id']:
            raise ValueError('selected connection account changed')
        M._assert_sharing_available(root, config)
        payload = _selected_documents(entry, expected_scope, key_provider, request_hash)
        if D._retirement_is_active(root, path, entry, key_provider=key_provider):
            raise ValueError('selected request was retired')
        prior = _cached_ack(root, path, entry, config)
        if prior is not None:
            return {'ok':True,'status':'not_checked_this_request','delivered':0,'pending':0,'errors':[]}
        if context_guard:
            context_guard()
        if path.read_bytes() != initial_bytes or D.load_config(root) != config:
            raise ValueError('selected request or connection changed before signing')
        identity = T.service_request_identity(root, key_provider=key_provider)
        if identity['service_request_key_id'] != config['service_request_key_id']:
            raise ValueError('selected enrolled physical signer differs')
        body = {'subject':entry['client_id'],'tenant_id':entry['tenant_id'], **payload,'idempotency_key':entry['idempotency_key']}
        raw = G.canonical_bytes(body)
        headers = {'Content-Type':'application/json','Idempotency-Key':entry['idempotency_key'],'X-Apatch-Client-Id':entry['client_id'],
            **T.signed_service_headers(root, method='POST',path=entry['endpoint'],raw_body=raw,
                tenant_id=entry['tenant_id'],subject=entry['client_id'],expected_key_id=config['service_request_key_id'],key_provider=key_provider)}
        if context_guard:
            context_guard()
        if path.read_bytes() != initial_bytes or D.load_config(root) != config:
            raise ValueError('selected request or connection changed before HTTP')
    except (G.GovernedWorkError, KeyError, OSError, TypeError, ValueError):
        raise SelectedDeliveryError() from None
    def incomplete(code):
        return {'ok':False,'status':'queued','delivered':0,'pending':1,'errors':[{'entry_id':entry_id,'code':code}]}
    try:
        if http_client_factory is None:
            import httpx
            http_client_factory = lambda: httpx.Client(timeout=10,follow_redirects=False,trust_env=False)
        with http_client_factory() as client:
            response = client.post(config['platform_url'].rstrip('/') + entry['endpoint'],content=raw,headers=headers)
        if int(response.status_code) not in {200,201}:
            return incomplete('PLATFORM_REJECTED')
        reply = D._response_json(response)
    except G.GovernedWorkError:
        return incomplete('ACK_VALIDATION_FAILED')
    except Exception:
        return incomplete('DELIVERY_FAILED')
    # Composite authorities can impose stricter actor/expiry guards before
    # any native source-binding/ACK write. Preserve their typed refusal.
    try:
        if (path.read_bytes() != initial_bytes
                or D._retirement_is_active(root, path, entry, key_provider=key_provider)):
            raise ValueError('selected immutable request changed during HTTP')
    except (G.GovernedWorkError, OSError, ValueError):
        raise SelectedDeliveryError() from None
    if response_guard:
        response_guard(reply)
    try:
        ack = (D._ack_source_binding(root,entry,reply,trusted_authority_keys=config['binding_authority_keys'])
            if entry['command'] == 'source_binding' else D._ack_evidence(entry,reply,trusted_authority_keys=config['binding_authority_keys']))
        G._atomic_json(D._ack_path(path),ack)
        return {'ok':True,'status':'acknowledged','delivered':1,'pending':0,'errors':[]}
    except G.GovernedWorkError:
        return incomplete('ACK_VALIDATION_FAILED')
    except Exception:
        return incomplete('DELIVERY_FAILED')
