# SPEC-STUDIO-SDD-LIFECYCLE-1 -- APatch Studio Next-Generation SDD Lifecycle

> **apatch artifact:** `spec:SPEC-STUDIO-SDD-LIFECYCLE-1`
> **Anchors:** RFP-012 frozen by `docs/contracts/RFP-012-owner-freeze.json`
> **Implementation state:** R0 freezes traceability and the pre-implementation judge. R1-R20 remain pending until their exact tests pass.
> **Core dependency:** `SPEC-SDD-INTEGRITY-1` consumes the same RFP-012 hash; Studio does not reimplement Core enforcement.

## R0 RFP traceability gate (meta)

| RFP id | SPEC Rk | Disposition |\n|--------|---------|-------------|\n
| SDD-1 | R1 | covered |
| SDD-2 | R2 | covered |
| SDD-3 | R3 | covered |
| SDD-4 | R4 | covered |
| SDD-5 | R5 | covered |
| SDD-6 | R6 | covered |
| SDD-7 | R7 | covered |
| SDD-8 | R8 | covered |
| SDD-9 | R9 | covered |
| SDD-10 | R10 | covered |
| SDD-11 | R11 | covered |
| SDD-12 | R12 | covered |
| SDD-13 | R13 | covered |
| SDD-14 | R14 | covered |
| SDD-15 | R15 | covered |
| SDD-16 | R16 | covered |
| SDD-17 | R17 | covered |
| SDD-18 | R18 | covered |
| SDD-19 | R19 | covered |
| SDD-20 | R20 | covered |

The owner-freeze record pins the byte-exact public RFP and the twenty acceptance
identifiers above. Every requirement below names a stable test node.

(verify: python3 -m pytest tests/sdd/test_sdd_spec_contract.py::test_rfp_012_owner_freeze_and_traceability_are_exact -q)

## R1 Preserve the implemented APatch baseline

Studio consumes the existing APatch runtime, session, evidence, probe and timesheet facts through adapters. It must not add a second execution state, ledger, specification store or proof calculation.

(verify: python3 -m pytest tests/sdd/test_sdd_lifecycle.py::test_existing_apatch_remains_canonical -q)

## R2 Versioned assignment or technical brief

A user can create or import a bounded brief with author, source, timestamp, content hash and revision lineage before RFP authoring. Studio projects the artifact without becoming a document database.

(verify: python3 -m pytest tests/sdd/test_sdd_lifecycle.py::test_brief_is_versioned_and_hashed -q)

## R3 Complete RFP to SPEC coverage

Studio reports every RFP acceptance id as mapped exactly once, waived by named authority, missing or ambiguous. It never guesses a relationship from prose.

(verify: python3 -m pytest tests/sdd/test_sdd_lifecycle.py::test_acceptance_to_requirement_coverage_is_complete -q)

## R4 Frozen verification contract before implementation

The freeze action presents and pins exact RFP, SPEC, test, fixture, schema, command, baseline and plan hashes before any source mutation capability can be issued.

Preparation, manifest and envelope reads and writes stay within their opened
ordinary directory ancestry. A redirected destination fails before freezing;
cleanup removes only superseded envelopes belonging to this SPEC, preserving
unrelated documents and sibling envelopes for the current contract.

(verify: python3 -m pytest tests/sdd/test_sdd_lifecycle.py::test_verification_contract_is_frozen_before_mutation tests/sdd/test_sdd_owner_execution_flow.py::test_owner_freeze_persists_exact_contract_and_requirement_envelope tests/sdd/test_sdd_state_containment.py -q)

## R5 Multi-perspective judging contract

Behavioral acceptance requires positive, negative, boundary and regression perspectives plus each risk-specific perspective promised by the RFP. Missing perspectives block freeze.

(verify: python3 -m pytest tests/sdd/test_sdd_lifecycle.py::test_behavioral_contract_requires_multiple_perspectives -q)

## R6 Observed red and targeted falsification

Studio distinguishes baseline red, expected falsification red, restored green and final ratification. A material gate that never reacts to its reversible seeded defect cannot become Proven.

(verify: python3 -m pytest tests/sdd/test_sdd_lifecycle.py::test_falsification_must_observe_red_before_ratification -q)

## R7 Frozen judge is outside implementation authority

The implementation capability cannot modify frozen RFP, SPEC, tests, fixtures, schemas or verify commands. Studio offers a proposed amendment, never an in-place weakening.

(verify: python3 -m pytest tests/sdd/test_sdd_lifecycle.py::test_implementation_actor_cannot_change_frozen_judge tests/sdd/test_sdd_owner_execution_flow.py::test_tampered_frozen_envelope_fails_closed_before_runner_dispatch -q)

## R8 Complete task envelope

Before execution Studio renders the exact requirement, contract revision, allowed reads/writes/symbols/effects, forbidden surfaces, tools, commands, network, remote/service permissions, budgets, checks and rollback ownership.

(verify: python3 -m pytest tests/sdd/test_sdd_lifecycle.py::test_task_envelope_is_complete_and_human_readable tests/sdd/test_sdd_owner_execution_flow.py::test_fixed_purpose_prompt_binds_exact_contract_without_authority_role -q)

## R9 One admission decision across effect surfaces

Studio receives one Core admission vocabulary for mutation, MCP, local runner, sandbox, network, remote and service effects and exposes unsupported direct-shell containment honestly.

(verify: python3 -m pytest tests/sdd/test_sdd_lifecycle.py::test_supported_effect_surfaces_share_one_admission_result -q)

## R10 Fail-closed violation outcome

Denied effects are attributed to the exact actor and session, shown without leaking source or paths, leave unrelated work untouched and keep the change out of Proven until resolved.

(verify: python3 -m pytest tests/sdd/test_sdd_lifecycle.py::test_denied_effect_is_visible_and_blocks_proof -q)

## R11 Blocking plan adherence

Undeclared path, symbol, operation or effect mismatch is a blocking condition in strict mode. Studio cannot downgrade it to a warning or hide it behind a green test count.

(verify: python3 -m pytest tests/sdd/test_sdd_lifecycle.py::test_plan_mismatch_is_blocking -q)

## R12 Solo owner temporal separation

A solo developer may author every stage, but an explicit owner freeze timestamp and hash precede the implementation capability; the executing agent cannot approve its amendment or proof.

(verify: python3 -m pytest tests/sdd/test_sdd_lifecycle.py::test_solo_freeze_precedes_implementation tests/sdd/test_sdd_owner_execution_flow.py::test_requirement_run_is_blocked_until_visible_owner_freeze -q)

## R13 Connected authority separation

Cowork projects named authority, contributor and verifier roles. A contributor may execute or request amendment but cannot widen or approve the issued contract.

(verify: python3 -m pytest tests/sdd/test_sdd_lifecycle.py::test_team_authority_and_contributor_do_not_collapse -q)

## R14 Visible allowed and forbidden contour

The change screen keeps human-readable allowed scope, forbidden scope, checks, budgets, live violations and amendment state visible before and during execution.

(verify: python3 -m pytest tests/sdd/test_sdd_lifecycle.py::test_studio_projects_allowed_and_forbidden_scope -q)

## R15 Meaningful non-mutating verification

Studio reports collected, executed, failed and skipped counts and required perspectives from a non-mutating verifier. Zero-collected, all-skipped, tautological, drifted or incomplete gates cannot pass.

(verify: python3 -m pytest tests/sdd/test_sdd_lifecycle.py::test_verifier_rejects_empty_skipped_drifted_and_incomplete_gates -q)

## R16 Exact proof binding

The Proof surface binds exact contract and envelope hashes, actor, mutations, adherence, test results, falsification, environment, checkpoints and ledger references without requiring raw protocol interpretation.

(verify: python3 -m pytest tests/sdd/test_sdd_lifecycle.py::test_proof_binds_exact_contract_and_envelope -q)

## R17 Human causal replay

One change replay answers what was requested, why decisions were made, who approved, what was allowed, what occurred, what was denied, how it was tested and what was attested.

(verify: python3 -m pytest tests/sdd/test_sdd_lifecycle.py::test_causal_replay_uses_human_language -q)

## R18 Verifiable effort without payroll inference

Studio reuses APatch signed-event timesheet derivation, exposes method and quality limits, and never labels draft effort as accepted time, payroll or business value.

(verify: python3 -m pytest tests/sdd/test_sdd_lifecycle.py::test_effort_is_rederived_and_not_accepted_time -q)

## R19 Explicit amendment and exact invalidation

A signed amendment preserves the superseded revision and reason, changes exact hashes and invalidates only affected capabilities, requirements and attestations.

(verify: python3 -m pytest tests/sdd/test_sdd_lifecycle.py::test_amendment_invalidates_only_affected_work -q)

## R20 Shared local and connected integrity floor

Studio exposes the same strict execution and meaningful verification floor for solo
and Cowork-connected work. Hosted authority and coordination cannot turn correctness
into an online-only feature.

(verify: python3 -m pytest tests/sdd/test_sdd_lifecycle.py::test_oss_and_cowork_share_integrity_floor -q)

## Verification contract

The exact test files named above are committed before product-source mutation. Their
final freeze manifest also pins fixtures, command strings, the observed red baseline,
the Core source pin and the implementation plan. Changing a test, fixture or command
after that freeze requires the RFP-012 amendment flow and invalidates affected work.

## Non-goals

This SPEC does not replace APatch sessions, SPEC execution, sandbox, leases, probe,
attestation, contribution or timesheet. It does not claim containment of an agent that
also holds unrestricted shell or network capability outside a sealed APatch runner.
