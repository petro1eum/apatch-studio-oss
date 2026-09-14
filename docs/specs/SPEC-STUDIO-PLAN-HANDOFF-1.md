# SPEC-STUDIO-PLAN-HANDOFF-1 — Honest Plan Handoff and Owner Continuation

> **apatch artifact:** `spec:SPEC-STUDIO-PLAN-HANDOFF-1`
> **Anchors:** RFP-015
> **Implementation boundary:** Existing APatch preparation, freeze and requirement execution remain canonical.

## RFP traceability table

| RFP id | SPEC Rk | Disposition |
|--------|---------|-------------|
| PLAN-1 | R1 | covered |
| PLAN-2 | R2 | covered |
| PLAN-3 | R3 | covered |
| PLAN-4 | R4 | covered |
| PLAN-5 | R5 | covered |
| PLAN-6 | R6 | covered |
| PLAN-7 | R7 | covered |
| PLAN-8 | R8 | covered |

## R0 Contract coverage gate (meta)

The executable contract must map every RFP-015 acceptance exactly once and must contain no placeholder verification commands.

(verify: python3 -m pytest tests/plan_handoff/test_plan_handoff_contract.py -q)

## R1 Exact plan attribution and fail-closed completion

A successful `new_change` run must be attributed to exactly one newly created or changed valid APatch preparation package. Missing, malformed, stale or ambiguous output fails closed without claiming that a plan is ready.

(verify: python3 -m pytest tests/plan_handoff/test_plan_attribution.py -q -k "valid or missing or malformed or ambiguous")

## R2 Durable content-safe handoff

The run journal and public projection persist only the bounded plan handoff needed to continue: SPEC id, ordered requirement ids, objective, preparation time, package hash and review-ready state. Existing journals without this field remain readable.

(verify: python3 -m pytest tests/plan_handoff/test_run_store_plan_handoff.py -q)

## R3 Plan-ready Home card and exact route

Home names the result `Plan ready`, states that source is unchanged and offers one primary `Review plan` action that opens the exact prepared SPEC and its first requirement.

(verify: python3 -m pytest tests/plan_handoff/test_plan_ui_contract.py -q -k "card or exact_route")

## R4 Plan-only action isolation

A plan-only run exposes no code delivery, commit, push, pull request, source diff, implementation acceptance or implementation proof actions.

(verify: python3 -m pytest tests/plan_handoff/test_plan_ui_contract.py -q -k "plan_only or implementation_actions")

## R5 Existing owner freeze continuation

The plan route reuses the existing contract review, owner freeze and requirement execution surfaces. Studio does not create a second specification store, verification contract or execution runtime.

(verify: python3 -m pytest tests/plan_handoff/test_plan_ui_contract.py -q -k owner_continuation)

## R6 Non-destructive scope audit instruction

The governed runner requests a report-only sandbox audit and must never instruct an agent to auto-revert writes unless APatch has first proven exact ownership by that run.

(verify: python3 -m pytest tests/plan_handoff/test_runner_prompt.py -q)

## R7 Preparation validation and privacy boundary

The handoff collector rejects unsafe identifiers, symlinks, oversized files, invalid schemas, stale packages and cross-run ambiguity. Failure projections remain content-safe and never expose local paths, prompts, source, raw commands or package bodies.

(verify: python3 -m pytest tests/plan_handoff/test_plan_attribution.py -q -k "unsafe or symlink or oversized or invalid or stale")

## R8 Multi-perspective release gate

Positive, negative, boundary, privacy, restart and regression checks must pass with the production frontend build before the slice is complete.

(verify: python3 -m pytest tests/plan_handoff tests/project_knowledge/test_traceability.py -q && npm --prefix frontend run build)

## Non-goals

This SPEC does not replace APatch Core preparation/freeze/execute contracts, implement source changes during planning, invent a second plan store, accept work on behalf of the owner, or add TrustChain coupling.
