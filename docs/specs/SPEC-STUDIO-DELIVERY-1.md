# SPEC-STUDIO-DELIVERY-1 -- Test Protocol, Acceptance Act and Verified Time

> **apatch artifact:** `spec:SPEC-STUDIO-DELIVERY-1`
> **Anchors:** RFP-013
> **Status:** Implementing

## R0 RFP traceability gate (meta)

| RFP id | SPEC Rk | Disposition |
|--------|---------|-------------|
| DEL-1 | R1 | covered |
| DEL-2 | R2 | covered |
| DEL-3 | R3 | covered |
| DEL-4 | R4 | covered |
| DEL-5 | R5 | covered |
| DEL-6 | R6 | covered |
| DEL-7 | R7 | covered |
| DEL-8 | R8 | covered |
| DEL-9 | R9 | covered |
| DEL-10 | R10 | covered |

(verify: python3 -m pytest tests/delivery_pack/test_delivery_pack_contract.py -q)

## R1 Canonical composition

Delivery Pack consumes existing APatch change detail, frozen execution contract, proof and signed-event effort projections. It persists only human decisions and their immutable basis, never a second execution, verification, evidence or effort state.

(verify: python3 -m pytest tests/delivery_pack/test_delivery_pack_projection.py::test_pack_composes_canonical_facts_without_duplicate_truth -q)

## R2 Exact test protocol

The protocol binds available contract, envelope and evidence hashes and exposes verification counts, required perspectives, falsification, retained check identities and explicit limitations.

(verify: python3 -m pytest tests/delivery_pack/test_delivery_pack_projection.py::test_test_protocol_binds_exact_available_evidence -q)

## R3 Meaningful gate

Zero-collected, zero-executed, all-skipped, failed, drifted, missing-perspective, absent-falsification and incomplete evidence remain non-meaningful and cannot authorize unconditional acceptance.

(verify: python3 -m pytest tests/delivery_pack/test_delivery_pack_projection.py::test_incomplete_gates_fail_closed tests/delivery_pack/test_delivery_pack_decisions.py::test_unconditional_acceptance_requires_meaningful_protocol -q)

## R4 Immutable acceptance act

A confirmed owner decision appends a purpose-separated signed act for one exact basis. Supported decisions are accepted, accepted_with_reservations, changes_requested and rejected; reservations require a reason.

(verify: python3 -m pytest tests/delivery_pack/test_delivery_pack_decisions.py::test_acceptance_act_is_signed_and_append_only -q)

## R5 Separate accepted time

The effort draft remains an APatch-derived estimate bound to the displayed change's exact governed session. Before Studio enables a time decision, it re-verifies the attested ContributionEvent public-key binding and Ed25519 signature, then re-derives its claimed volume from the APatch ledger. Missing, ambiguous, untrusted, unsigned, invalid-signature or drifted events fail closed with a visible reason. Accepted time is a distinct signed decision referencing exact basis and effort hashes; accepting a result never accepts hours and accepted hours cannot exceed the verified draft.

(verify: python3 -m pytest tests/delivery_pack/test_delivery_pack_decisions.py::test_time_decision_is_separate_and_bounded tests/delivery_pack/test_delivery_pack_verified_effort.py -q)

## R6 Local and connected authority

OSS signs with a disclosed local owner identity held outside the project. Reads and retries pin the configured authority and verify the signed workspace-scoped journal, every act, ordered revisions and exact request-to-result binding. The basis fingerprints the available file projection byte-exactly, so replacing a displayed patch, path, mode or digest invalidates consent even when counts are unchanged; omitted/truncated source remains an explicit upstream limitation. Legacy project keys and decisions remain explicitly unverified and are never automatically adopted. Cowork may provide a signed named-authority decision while retaining the same canonical bytes and integrity floor; a local signature never implies organization consent.

(verify: python3 -m pytest tests/delivery_pack/test_delivery_pack_signing.py::test_local_owner_signature_verifies tests/delivery_pack/test_delivery_pack_signing.py::test_connected_authority_cannot_weaken_semantics tests/delivery_pack/test_delivery_pack_integrity.py tests/delivery_pack/test_delivery_pack_content_basis.py -q)

## R7 Atomic replay-safe decisions

Decision storage is atomic, append-only and serialized in owner-private OS state, not project-controlled files. Exact request retries are byte-identical; changed replays, stale basis and stale effort hashes fail closed. Signed history remains available but only its newest decision matching the current basis (and exact effort for time) may be shown as current consent.

(verify: python3 -m pytest tests/delivery_pack/test_delivery_pack_decisions.py::test_decisions_are_idempotent_and_stale_safe -q)

## R8 Content-safe record

The exported Delivery Pack and printable act exclude source, diff bodies, prompts, secrets, environment values, absolute paths and raw command output while retaining canonical IDs, hashes, outcomes and signer identity.

(verify: python3 -m pytest tests/delivery_pack/test_delivery_pack_privacy.py -q)

## R9 Outside-in change experience

Change detail presents Tests, Result acceptance, Time report and Delivery record in one workflow with real actions and progressive technical disclosure.

(verify: python3 -m pytest tests/delivery_pack/test_delivery_pack_ui.py -q)

## R10 Release journey

The guarded API journey records an acceptance act and a separate time decision, survives exact retry and exports a verifiable content-safe record. Full Python tests, frontend production build and desktop/mobile browser checks remain green.

(verify: python3 -m pytest tests/delivery_pack/test_delivery_pack_api.py tests/delivery_pack/test_delivery_pack_journey.py -q)

## Verification contract

The exact tests named above are committed and observed red before product-source mutation. Their freeze record pins test hashes, commands, fixtures, the observed baseline and implementation plan. Any post-freeze test change requires a recorded amendment and invalidates affected proof.

## Non-goals

This SPEC does not replace APatch sessions, verification, attestation, contribution or timesheet derivation. It does not implement payroll, invoices, business-value inference, cloud source upload, TrustChain authority or a second project state store.
