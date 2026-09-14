# RFP-015 -- APatch Studio Plan Handoff and Contract Closure

> **Status:** Approved for implementation
> **Owner:** APatch Studio
> **Date:** 2026-09-02
> **Depends on:** RFP-007, RFP-012, RFP-014; APatch runtime 0.8.40 or newer
> **Executable contract:** docs/specs/SPEC-STUDIO-PLAN-HANDOFF-1.md

## 1. Decision

APatch already separates contract preparation from source implementation: a planning agent creates a review package, the owner freezes exact scope and tests, and only then can an implementation capability be issued. Studio must turn that implemented integrity boundary into one continuous user workflow.

A successful `new_change` run is a prepared plan, not a completed code change. Studio must verify the resulting preparation package, persist only a safe plan reference, lead the owner directly to review and freeze, and refuse to call an incomplete planning run successful.

## 2. Observed product break

The current Home action correctly says **Prepare plan**, but its terminal card uses the ordinary completed-change presentation. It can say **Verified**, offer **Review result**, expose Git delivery actions and omit the exact SPEC that the owner must review. A zero exit code is accepted even when no valid `.apatch/sdd/prepared/<SPEC>.json` package exists.

This breaks the central SDD journey: request -> prepared contract -> owner decision -> bounded implementation.

## 3. Canonical handoff

The APatch preparation package remains the sole execution truth. Studio adds no second RFP, SPEC, test or plan store.

For each planning run Studio records only a content-safe handoff:

- exact SPEC id;
- ordered requirement ids;
- objective;
- preparation timestamp;
- review state;
- package fingerprint.

It never persists or projects repository paths, source, prompts, raw runner output, commands, credentials, session tokens or full package contents.

The package is accepted only when its schema and exact keys are valid, the SPEC id is canonical, the referenced SPEC document exists in `docs/specs`, at least one requirement envelope exists, every key is a valid requirement id, and the package was created or changed by the exact run.

## 4. Terminal semantics

A `new_change` process with exit code zero is successful only when one exact valid preparation handoff is attributable to that run.

- Valid handoff: terminal state **Plan ready**, primary action **Review plan**, source status **Source unchanged**.
- Missing or invalid handoff: terminal state **Needs attention**, one retry action and a safe explanation.
- Multiple attributable packages: fail closed as ambiguous; Studio never guesses.
- Other run modes retain their existing execution, proof, recovery and delivery semantics.

A plan-only result never exposes commit, push, pull-request, source-diff, attestation or accepted-result actions. Those remain attached to later implementation results.

## 5. Owner continuation

**Review plan** opens the exact SPEC and first prepared requirement. The owner can inspect allowed reads and writes, forbidden paths, budgets, positive/negative/boundary/regression checks, observed red baseline and falsification expectation. Existing Studio actions then freeze the exact contract and run the selected requirement.

No owner is asked to locate a SPEC id, requirement id, governed session or hidden APatch file manually.

## 6. Safe scope auditing

Planning instructions require an explicit sandbox report, but they must not invoke destructive automatic reversion over pre-existing user-owned files. Automatic reversion is allowed only by an exact APatch operation that can prove ownership of the newly attempted out-of-scope mutation. Otherwise Studio reports the violation and blocks success for human review.

## 7. Verification contract

Tests are frozen before implementation and cover:

- positive attribution of one newly created valid package;
- negative missing, malformed and ambiguous package outcomes;
- boundary validation for schema, ids, requirement count and package size;
- restart persistence and old-journal compatibility;
- privacy rejection of paths, source, prompts and raw output;
- UI routing and absence of code-delivery actions for plan-only runs;
- regression of requirement execution, recovery and completed-change delivery;
- a production frontend build and real browser journey from Home to owner contract review.

## Acceptance

| Id | Requirement | Level |
|---|---|---|
| PLAN-1 | A successful new-change run requires exactly one valid preparation package created or changed by that exact run; missing, malformed, stale or ambiguous packages fail closed with one retryable explanation | MUST |
| PLAN-2 | The durable run journal stores a bounded plan handoff containing only canonical SPEC id, ordered requirement ids, objective, prepared timestamp, review state and package fingerprint, while existing journals remain readable | MUST |
| PLAN-3 | A plan-ready Home card uses plan language, reports that source is unchanged and opens the exact SPEC plus first prepared requirement as its primary action | MUST |
| PLAN-4 | Plan-only runs expose no commit, push, pull-request, source-diff, attestation, acceptance or accepted-time action; normal implementation results retain those actions | MUST |
| PLAN-5 | Owner continuation uses the existing contract-review and freeze surfaces and never asks the owner to identify hidden files, protocol ids or sessions manually | MUST |
| PLAN-6 | Runner instructions perform non-destructive scope reporting and never request unconditional sandbox auto-revert over pre-existing user-owned files | MUST |
| PLAN-7 | Preparation attribution and persistence reject unsafe fields, symlinks, oversized documents, invalid ids, unsupported shapes and cross-run reuse without exposing local paths | MUST |
| PLAN-8 | Positive, negative, boundary, privacy, restart, regression, frontend-build and real-browser tests prove the request-to-freeze handoff | MUST |

## Non-goals

This RFP does not implement another APatch runtime, generate RFP or SPEC content inside Studio, auto-approve a contract, permit source work before freeze, add cloud storage, expose arbitrary filesystem browsing, infer business acceptance, or weaken existing requirement execution and evidence semantics.
