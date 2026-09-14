# RFP-016 -- APatch Studio Fast and Observable Plan Preparation

> **Status:** Approved for implementation
> **Owner:** APatch Studio
> **Date:** 2026-09-02
> **Depends on:** RFP-014, RFP-015; APatch runtime 0.8.40 or newer
> **Executable contract:** docs/specs/SPEC-STUDIO-PLAN-ORCHESTRATION-1.md

## 1. Decision

APatch already provides the canonical RFP, SPEC, frozen verification contract, governed session and evidence lifecycle. Studio must make its existing `Prepare plan` action fast, bounded and observable without creating another planner or weakening the owner-freeze boundary.

A planning run is a latency-sensitive contract-authoring operation, not an invitation to inventory the repository. Studio supervises it with a fixed discovery budget, a monotonic time budget, safe structured progress and a fail-closed handoff.

## 2. Reproduced defect

During live Studio dogfood on 2026-09-02, a `Prepare plan` run spent more than six minutes reading repository material. The UI showed only `Agent is working through APatch`, although the runner emitted structured command and tool events. No valid preparation package was produced before the owner cancelled the run.

The defect has two causes: the prompt asks for broad repository inspection, and the event adapter projects only APatch tool names while ignoring ordinary structured runner work.

## 3. Bounded preparation path

For `new_change`, the runner must use this order:

1. consume a private bounded Studio context capsule containing a concise operating contract, project summary, exact-lineage partial contract, existing preparation package when present and a titles-only contract index;
2. run APatch doctor as the only pre-authoring tool call and perform no additional repository inspection;
3. draft the RFP, SPEC, frozen verification tests and preparation package completely before writing;
4. for a fresh lineage, open one contract-authoring session bound to the preallocated `spec-bootstrap:<SPEC-ID>#R0` and `rfp:<RFP-ID>` artifacts (APatch authorizes creating a not-yet-existing SPEC only for such a session), then create the complete RFP, complete SPEC, frozen test and fixture files, and preparation package in one governed batch of that session;
5. when an exact-lineage scaffold already exists, call `apatch_session_start` once for its exact `SPEC#R0`, then call `apatch_execute_next` with the same session capability, the complete ordered needle set and no `finalize` flag;
6. repeat `apatch_execute_next` for the same session without new needles while each response reports `continue=true`; only after `continue=false`, call it once with `finalize=true` and no needles; do not place generic generation, resume or rollback between those calls;
7. write the preparation package in the exact shape of the Studio-supplied template (top-level keys, schema, one task envelope per SPEC requirement heading) and verify the contract-authoring session with an explicit collect-only check of the frozen tests plus RFP/SPEC lint, never with the project default suite whose intentionally red frozen tests would fail the session (REC-bf36f1001fd7).


Studio launches every runner with an explicit apatch MCP server (the Studio interpreter, the plain launcher bound to the workspace, the full professional catalog) instead of the consumer's `.apatch/mcp.json` or a global runner configuration; the consumer default is the compact profile, which lacks the governed mutation tools and fails silently.

The capsule is assembled locally from allowlisted contract/document paths and the exact existing preparation package with per-file and total byte caps. The operating contract is capped more tightly so retry evidence is not truncated. The capsule is sent only to the selected local runner, is never written to the run journal or projected to the browser, and never includes application source.

`apatch_spec_scaffold` is forbidden in this Studio flow because it materializes an incomplete SPEC before the package is ready and activates SPEC path ownership. Studio authors a complete new SPEC directly; a retry repairs an existing exact-lineage scaffold through an exact R0 session, one mutation `apatch_execute_next`, zero or more continuation calls while `continue=true`, then one finalization call. A generic batch after `session_start` is forbidden because it collides with SPEC ownership.
Studio preallocates collision-free, versioned RFP and SPEC identifiers from the opaque planning run id. The runner must use those exact identifiers and must not spend a recovery cycle selecting, reusing or repairing a document identity.

Before the first contract write, Studio permits at most 8 structured repository-inspection command starts. The ninth is terminated as `plan_discovery_budget_exceeded`. After contract authoring begins, no further repository inspection is permitted; only validation of the exact package may run. An RFP-only or SPEC-only subset must never be attested and closed as a successful planning unit.

Studio never parses or persists raw command text to make this decision. It uses only structured event types and allowlisted APatch tool identities.

## 4. Latency policy

`new_change` uses a runner-specific latency profile when the selected runner supports one. Codex planning is pinned to the fast `gpt-5.6-luna` model with `model_reasoning_effort="low"`; implementation, recovery and rollback modes keep the user's normal runner configuration. Claude keeps its installed default until an equivalent bounded planning profile is available.

The default planning limits are:

- soft stall: 30 seconds without a structured event;
- hard timeout: 300 seconds from process launch (the initial 180-second budget sat at the observed median of a complete governed package, REC-2361d9414463);
- UI refresh: the existing 2.5-second active-run polling cycle.

A soft stall is visible and reversible when a later event arrives. A hard timeout terminates the exact process group, refuses partial handoff success and leaves source implementation unauthorized.

## 5. Safe progress projection

Studio maps structured events to human stages: starting, inspecting the minimum project contract, preparing the review package, validating scope and tests, and finalizing the handoff. Repeated identical events refresh last activity but do not append duplicate timeline rows.

The projection may contain stage, timestamps, elapsed/remaining budget and bounded counters. It must not contain raw commands, paths, source, prompts, environment values, credentials, process ids or runner output.

## 6. Terminal and recovery semantics

A planning run succeeds only under the RFP-015 exact handoff rule. Discovery exhaustion, timeout, cancellation, runner failure, malformed output and partial output all end in a retryable `Needs attention` state. Retry creates a new supervised run and the collector still requires one package attributable to that exact retry.

Studio does not claim rollback or source cleanup that APatch cannot prove. Cancellation and timeout kill only the exact child process group; any governed recovery remains explicit.

Every planning run receives one opaque run-owned APatch lane. Contract authoring may recover, attest, roll back or close only sessions created in that exact lane; pre-existing and sibling sessions are forbidden. After a terminal planning failure, Studio reconciles the exact run lane, rolls back its own checkpoint when present and closes the session. The human projection reports only the bounded cleanup outcome, never lane names, session capabilities or tokens.

A retry uses a fresh process and run-owned lane but preserves the first attempt's preallocated RFP/SPEC identifiers. It may complete valid partial artifacts in that exact contract lineage; it must not create duplicate contract identities or recover the prior lane. Even when the carried contract is complete, the retry must write exactly one new preparation-package revision bound to the current run before handoff; an empty mutation or unchanged package is not attributable completion. Scope reporting compares the final report-only sandbox audit with a private pre-run violation fingerprint set so pre-existing user-owned findings are never presented as effects of the current run.

## 7. Human interface

An expanded running card shows the current human stage, elapsed time, last activity, remaining hard budget and Stop. It never shows command lines or protocol jargon. A stalled card explains that Studio is still supervising the bounded plan. A budget failure names the limit and offers one Retry action. A card for a change that did not finish states what happened and one next step in product language (run projection `failure`, schema `apatch.studio.run-failure.v1`); run messages themselves use product language and never protocol vocabulary.

## 8. Verification contract

The frozen tests cover positive, negative, boundary, timeout, cancellation, privacy and regression perspectives before source implementation starts. Release requires the full Python suite, production frontend build and a repeated browser journey using the same objective that reproduced the defect.

## Acceptance

| Id | Requirement | Level |
|---|---|---|
| FAST-1 | New-change preparation follows the fixed bounded context order, allows at most 8 pre-contract structured inspection command starts, hands the runner the exact preparation-package template with an explicit contract verification, and writes RFP, SPEC and preparation data as one governed package | MUST |
| FAST-2 | Codex planning uses the dedicated fast `gpt-5.6-luna` low-reasoning profile without changing requirement, recovery or rollback runner configuration | MUST |
| FAST-3 | Structured runner and APatch events produce human progress within the existing active-run refresh cycle without reading raw command content | MUST |
| FAST-4 | Repeated events refresh a safe last-activity timestamp but do not create duplicate timeline rows | MUST |
| FAST-5 | A 30-second no-event interval becomes a visible soft stall and a 300-second planning deadline terminates the exact run | MUST |
| FAST-6 | Discovery exhaustion, timeout and partial handoff fail closed, remain retryable and never authorize application source implementation | MUST |
| FAST-7 | Stop, timeout and retry preserve exact process ownership, require one current-run preparation revision, exclude pre-existing sandbox findings from run effects, retain retry-stable contract identity and journal safety, and respect explicit APatch recovery boundaries; a metadata-only retry mutates only the prepared package with byte-exact supplied anchors and does not rewrite RFP/SPEC labels | MUST |
| FAST-8 | The running Home card shows human stage, elapsed time, last activity, remaining budget and Stop without protocol or command leakage; a change that did not finish shows what happened and what to do next in product language | MUST |
| FAST-9 | Multi-perspective tests, the complete Python suite, production frontend build and repeated real-browser dogfood pass before release; Studio-generated RFP identifiers remain paired to their SPEC so review shows complete decision links | MUST |

## Non-goals

This RFP does not replace APatch planning, weaken frozen verification, auto-approve contracts, add a cloud planner, expose raw runner telemetry, promise deterministic model latency, or change implementation/recovery execution budgets.
