"""Read unchanged outputs only when a fresh native verifier signed their bytes.

This is not a replacement mutation or a synthetic attestation. Core's original
SDD judge, falsification, content snapshot and signature remain authoritative.
"""
from pathlib import Path

from apatch import sdd_integrity as S
from apatch_studio.state_io import StateDirectory


def verified_content(manager, attestation, contract, envelope, *, expected_mutation_ids=()):
    proof = attestation['payload'].get('sdd_evidence')
    if not contract.get('supersedes_hash') or not isinstance(proof, dict):
        raise ValueError('Fresh native revision verification required')
    S._verify_seal(proof, 'native attestation evidence')
    verification = proof.get('verification') or {}
    S._verify_seal(verification, 'native verification')
    sid = attestation['payload'].get('governed_session_id', attestation['payload'].get('session_id'))
    decision = verification.get('decision') or {}
    required = sum(len(o['expected_case_ids']) for o in contract['obligations'] if o['acceptance_id'] in envelope['checks'])
    if (proof.get('schema') != 'apatch.sdd.attestation-evidence.v1'
            or verification.get('schema') != 'apatch.sdd.session-verification.v1'
            or (proof.get('actor') or {}) != {'actor_id': manager.actor_id, 'role':'implementation'}
            or proof.get('contract_hash') != contract['document_hash']
            or proof.get('envelope_hash') != envelope['document_hash']
            or proof.get('task_envelope') != envelope or proof.get('mutation_ids') != list(expected_mutation_ids)
            or verification.get('session_id') != sid
            or (proof.get('adherence') or {}).get('status') != 'compliant'
            or decision.get('accepted') is not True or required < 1
            or decision.get('executed') != required or decision.get('collected') != required
            or decision.get('failed') != 0 or decision.get('skipped') != 0):
        raise ValueError('The fresh verification is not complete for this frozen revision')
    if any(o.get('material') for o in contract['obligations'] if o['acceptance_id'] in envelope['checks']):
        S._verify_seal(proof.get('falsification') or {}, 'native falsification')
        if any((proof.get('falsification') or {}).get(k) is not True for k in ('observed_red', 'restored_green', 'bytes_restored', 'mode_restored')):
            raise ValueError('The frozen material gate was not satisfied')
    digest = verification.get('content_snapshot_hash')
    import re
    if not isinstance(digest, str) or not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise ValueError('A signed native content snapshot is required')
    # Private cache is only a witness. Its hash must equal the hash INSIDE the
    # verified signed native attestation, never just its own self-seal.
    cache = manager.store.directory / 'exact-verified-outputs'
    name = digest[7:] + '.json'
    try:
        with StateDirectory(cache) as directory:
            snapshot = directory.read_json(name)
    except FileNotFoundError:
        from apatch.lane import lane_state_path_for
        with StateDirectory(manager.workspace / '.apatch/state') as directory:
            finals = directory.read_json('finalizations.json')
        final = finals.get('records', {}).get(sid, {})
        if final.get('session_id') != sid or not isinstance(final.get('lane_id'), str):
            raise ValueError('The exact native session has not finalized')
        path = Path(lane_state_path_for(str(manager.workspace), final['lane_id'], 'session_state.json'))
        path.relative_to(manager.workspace)
        with StateDirectory(path.parent) as directory:
            state = directory.read_json(path.name)
        if state.get('session_id') != sid or not state.get('ended_at'):
            raise ValueError('The exact finalized native content snapshot is unavailable')
        snapshot = (state.get('sdd') or {}).get('verification_content_snapshot')
    if not isinstance(snapshot, dict):
        raise ValueError('The native content snapshot is unavailable')
    S._verify_seal(snapshot, 'native content snapshot')
    if (snapshot.get('schema') != 'apatch.sdd.verification-content.v1'
            or snapshot['document_hash'] != digest or snapshot.get('contract_hash') != contract['document_hash']
            or snapshot.get('envelope_hash') != envelope['document_hash']
            or snapshot.get('environment_hash') != proof.get('environment_hash')):
        raise ValueError('The output witness is not the signed verification content')
    with StateDirectory(cache, create=True) as directory:
        try:
            existing = directory.read_json(name)
        except FileNotFoundError:
            directory.write_json(name, snapshot)
        else:
            if existing != snapshot:
                raise ValueError('The immutable native output witness changed')
    return snapshot['files']
