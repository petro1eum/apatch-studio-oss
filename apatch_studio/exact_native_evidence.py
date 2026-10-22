"""Build or reuse exact native proof without rewriting immutable documents."""
from __future__ import annotations

from pathlib import Path
from apatch import governed_work as G
from apatch.trustchain_helper import TrustChainHelper
from apatch_studio.state_io import StateDirectory


def _stored_or_built(root, section, id_field, build, validate, keys, issued_at):
    expected = build(issued_at=issued_at, store=False)["document"]
    filename = expected[id_field] + ".json"
    try:
        with StateDirectory(root / section) as directory:
            existing = directory.read_json(filename, limit=1_048_576)
    except FileNotFoundError:
        return build(issued_at=issued_at, store=True)["document"]
    # An existing record is usable only with the current issuer and freshly
    # derived facts. Each immutable document retains its own signed timestamp.
    validate(existing, trusted_actor_keys=keys)
    fresh = build(issued_at=existing["issued_at"], store=False)["document"]
    if fresh != existing:
        raise G.GovernedWorkError("existing native evidence differs from current verified facts")
    return existing


def build_or_reuse_workspace_evidence(target_dir, *, binding_id,
        contribution_store_dir=None, key_provider=None, issued_at=None):
    provider = G._load_local_provider(target_dir, key_provider)
    binding = G.load_project_source_binding(target_dir, binding_id)
    change = G.load_change(target_dir, str(binding["change_id"]))
    facts = G.derive_source_bound_attestation_facts(
        TrustChainHelper(target_dir).iter_ledger_entries(), binding=binding)
    if not facts or any(fact["outcome"] != "passed" for fact in facts):
        raise G.GovernedWorkError("current passing native attestations are required")
    events = G._load_source_bound_contributions(target_dir,
        session_ids={str(fact["governed_session_id"]) for fact in facts},
        binding=binding, store_dir=contribution_store_dir, key_provider=provider)
    sessions = G._source_bound_session_refs(events)
    keys = {G.signer_key_id(provider): provider.get_public_key()}
    root = Path(G.governed_work_root(target_dir))
    def time_build(**options):
        return G.build_timesheet_draft(target_dir, binding=binding,
            sessions=sessions, contribution_events=events, key_provider=provider, **options)
    timesheet = _stored_or_built(root, "timesheets", "timesheet_id", time_build,
        G.validate_timesheet_draft, keys, issued_at)
    def evidence_build(**options):
        return G.build_work_evidence_bundle(target_dir, change=change, binding=binding,
            attestation_facts=facts, contribution_events=events, timesheet=timesheet,
            key_provider=provider, **options)
    evidence = _stored_or_built(root, "evidence", "bundle_id", evidence_build,
        G.validate_work_evidence_bundle, keys, issued_at)
    return {"ok": True, "binding_id": binding_id, "binding_hash": G.document_hash(binding),
        "change_id": change["change_id"], "change_hash": G.document_hash(change),
        "timesheet": timesheet, "timesheet_hash": G.document_hash(timesheet),
        "evidence_bundle": evidence, "evidence_bundle_hash": G.document_hash(evidence),
        "attestation_count": len(facts), "contribution_event_count": len(events)}
