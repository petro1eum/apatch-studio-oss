# RFP-013 -- APatch Studio Delivery Pack

> **Status:** Approved for implementation
> **Owner:** APatch Studio
> **Date:** 2026-09-01
> **Depends on:** RFP-006, RFP-011, RFP-012
> **Executable contract:** docs/specs/SPEC-STUDIO-DELIVERY-1.md
> **Evidence source:** owner request for complete tests, acceptance acts and timesheets after the live Studio walkthrough

## 1. Decision

APatch Studio adds one human-readable Delivery Pack to every governed change. The pack composes the already implemented APatch requirement contract, scope record, verification evidence, signed-event effort derivation and proof. It then adds two explicit human decisions: acceptance of the exact delivered result and, separately, acceptance or rejection of the reported time.

The four statements remain independent:

1. The frozen tests passed meaningfully.
2. A named owner accepted the exact delivered result.
3. APatch derived a draft effort estimate from signed events.
4. A named owner accepted a bounded amount of time.

No statement implies another. A green test run is not an acceptance act. An accepted result does not accept hours. A timesheet draft is not payroll, an invoice or business value.

## 2. Existing foundation

This RFP does not propose a replacement execution system. APatch already owns and operates RFP/SPEC traceability, governed sessions, strict mutation scope, checkpoints, non-mutating verification, falsification, attestation, contribution receipts and signed-event timesheet derivation.

Studio consumes those canonical facts through existing adapters. It must not recalculate verification, infer acceptance from an attestation, estimate effort from Git timestamps or introduce another ledger. Missing historic detail is shown as not recorded.

## 3. User outcome

From one change screen a solo developer or team reviewer can answer:

- What was requested and which frozen scope governed the work?
- Which checks were agreed before implementation?
- Did they execute, exercise the required perspectives and survive falsification?
- What exact result and proof does the decision cover?
- Was the result accepted, accepted with reservations, sent back or rejected?
- How much effort did APatch derive and how reliable is that estimate?
- Was any amount of time separately accepted?
- Can the complete content-safe delivery record be exported?

The user should not need to assemble these answers from Plans, Proof, Library and administrative screens.

## 4. Test protocol

The Delivery Pack projects a deterministic test protocol from the frozen verification contract and the recorded APatch result. It binds the exact change, requirement, contract hash, envelope hash and evidence hash where available.

The protocol shows collected, executed, passed, failed and skipped counts; required perspectives; falsification red/green outcome; check identities and oracles when retained; and explicit reasons when the gate is incomplete. It may call a result meaningful only when APatch recorded acceptance, at least one check executed and passed, no check failed, required perspectives are present and the promised falsification completed.

Zero collected tests, zero executed tests, all-skipped tests, failed tests, drifted assets, missing perspectives, absent falsification or incomplete APatch evidence cannot be presented as a passed protocol. Historic records without enough detail remain readable but cannot support an unconditional acceptance.

## 5. Acceptance act

A human owner may record an immutable local acceptance act for the exact Delivery Pack basis. Decisions are:

- accepted;
- accepted with reservations;
- changes requested;
- rejected.

An unconditional acceptance requires a meaningful test protocol. Acceptance with reservations requires an explicit reason and visibly preserves every technical gap. Sending back or rejecting work never requires green tests.

The act includes its own ID, revision, exact basis hash, test protocol hash, decision, note, actor, timestamp, signer identity and purpose-separated Ed25519 signature. The browser cannot choose the signer or rewrite actor identity. A later decision appends a revision and never edits prior bytes.

APatch Studio OSS provides a local owner signer and labels its trust as local and self-controlled. A signed Cowork decision may supply named external authority, but it cannot weaken the protocol, make missing evidence green or alter local records.

## 6. Timesheet draft and accepted time

The effort draft comes only from APatch signed-event timesheet derivation. Studio displays its method, quality limits and the existing disclosure that operation spacing is an estimate rather than a stopwatch. The draft is content-safe and is bound by hash to the Delivery Pack.

Accepted time is a separate immutable decision. It references the exact effort draft and basis hashes and records accepted or rejected. Accepted hours must be explicit, non-negative and no greater than the draft hours. Rejecting time does not reject the code; accepting code does not accept time.

Where an external authority such as TrustChain exists, its accepted-time decision may be projected later. The standalone local act remains honest about its authority and never claims payroll, payment or organizational acceptance.

## 7. Idempotency and stale decisions

Every write uses a caller-generated request ID. An exact retry returns the byte-identical result. Reusing a request ID with different bytes fails closed.

The server recomputes the current basis before every decision. A decision carrying an old basis or effort hash is rejected with a refresh instruction. Existing acts remain immutable history, while a new code, contract, verification or effort revision requires a new decision.

Concurrent writes are serialized per workspace through a bounded file lock and committed atomically. Partial files, duplicate revisions and last-writer-wins replacement are forbidden.

## 8. Privacy and export

The Delivery Pack is local-first and content-safe. Its machine-readable export may include canonical IDs, hashes, outcomes, counters, logical project identity, bounded notes, signer public identity and timestamps. It excludes source code, full diffs, prompts, secrets, environment variables, absolute paths and arbitrary command output.

The product also presents a readable printable act. Technical IDs and signatures remain in progressive disclosure. Exporting a local act does not upgrade its trust class.

## 9. Product experience

The change detail is the primary Delivery Pack surface. It presents, in order:

1. requested outcome and frozen scope;
2. test protocol;
3. result and proof;
4. draft effort;
5. result acceptance;
6. separate time decision;
7. export.

Primary labels use Tests, Result acceptance, Time report and Delivery record. Protocol terms, hashes and signatures live in expandable technical audit.

Recovery and rollback remain change actions, not acceptance decisions. The user cannot accept an in-progress or rolled-back result.

## 10. Editions

APatch Studio OSS includes the complete local Delivery Pack, meaningful test protocol, local signed acceptance act, verified effort draft, accepted-time decision and local export. Correctness and evidence integrity are not paid features.

Cowork may add named organization authority, policy, review routing and external decision synchronization. It does not create a second local act format or a second timesheet truth.

## 11. Release proof

Release qualification includes contract tests for derivation and fail-closed semantics, idempotency and stale-basis tests, signature verification and tamper tests, append-only revision tests, API privacy tests, an outside-in UI journey, full Python tests, frontend production build and desktop/mobile browser walkthroughs.

## Acceptance

| Id | Requirement | Level |
|---|---|---|
| DEL-1 | Delivery Pack composes existing APatch change, frozen contract, proof and signed-event timesheet facts without introducing a second execution, verification, evidence or effort truth | MUST |
| DEL-2 | The test protocol binds exact available contract and evidence hashes and reports counts, required perspectives, falsification, retained checks and explicit limitations | MUST |
| DEL-3 | Zero, all-skipped, failed, drifted, incomplete or insufficiently falsified verification cannot be displayed as meaningfully passed or support unconditional acceptance | MUST |
| DEL-4 | A purpose-separated signed immutable acceptance act records accepted, accepted with reservations, changes requested or rejected against one exact Delivery Pack basis | MUST |
| DEL-5 | Accepted time is a separate immutable decision against the exact effort draft; accepting a result never accepts hours and accepted hours cannot exceed the draft | MUST |
| DEL-6 | OSS provides a disclosed local owner signer; Cowork may add named authority but cannot weaken the shared integrity floor or rewrite local decisions | MUST |
| DEL-7 | Decision writes are atomic, append-only, idempotent and fail closed on replay mismatch, stale basis, stale effort or concurrent conflict | MUST |
| DEL-8 | JSON and printable delivery records are content-safe and exclude source, diff content, prompts, secrets, environment values, absolute paths and raw command output | MUST |
| DEL-9 | One change screen exposes Tests, Result acceptance, Time report and Delivery record with contextual actions and progressive technical disclosure | MUST |
| DEL-10 | Focused backend, API, privacy and UI journeys plus full tests, production build and browser checks prove the complete delivery workflow | MUST |

## Non-goals

This RFP does not replace APatch Core verification, create payroll or invoicing, infer business value, accept time automatically, expose raw source to a remote service, create a second team authority, modify TrustChain DTOs, or claim that a local self-signed act is an external organizational decision.
