# RFP-006 -- APatch Studio Product Loop Closure

> **Status:** Approved for implementation
> **Owner:** APatch Studio
> **Date:** 2026-08-31
> **Depends on:** RFP-003, RFP-005; public APatch governed runtime
> **Executable contract:** docs/specs/SPEC-STUDIO-LOOP-CLOSURE-1.md

## 1. Decision

APatch Studio must close the developer loop that begins with governed work and
ends with a locally reviewed, deliverable result. A green dashboard is not
acceptable when the canonical APatch ledger reports stale evidence. A completed
run is not reviewable when the product cannot open its local diff. A critical
runtime warning is not actionable when recovery is hidden in another tab.

This RFP closes those gaps without creating a second execution engine, copying
source into a browser response, or weakening APatch governance.

## 2. Verified problems

The following observations were reproduced against the current product:

1. project status reported all requirements attested while canonical coverage
   reported seven file-drift stale requirements;
2. Review exposed counts and evidence actions but could not open the local diff;
3. critical hygiene was visible on Home but safe cleanup was not available there;
4. the solo workflow stopped before commit, push and pull-request handoff;
5. signed external work did not have a truthful configured/unconfigured Inbox;
6. Studio exposed no canonical contribution timesheet, attestation receipt or
   Avatar delivery health even though APatch already produces all three.

These are product defects, not requests for a new APatch runtime.

## 3. Product boundary

APatch remains the sole authority for SPEC state, file-drift coverage, governed
sessions, mutations, verification, attestation and rollback. Studio composes
those capabilities into local human workflows.

Full source, file paths, raw diffs, prompts, reasoning, runner transcripts,
stdout, stderr, credentials and session capabilities must not appear in HTTP
responses. A local diff may be written to an owner-only temporary artifact and
opened by a fixed-purpose local launcher. The browser receives only an operation
receipt and aggregate status.

Git delivery is local and bounded:

- Studio never stages arbitrary workspace content automatically;
- commit operates only on the user's already staged set;
- APatch staged notarization must pass before commit;
- push targets only the current branch and configured upstream or origin, never
  force-pushes and never accepts a remote or ref supplied by the browser;
- pull-request handoff opens a provider create page derived from the existing
  remote and current branch; it does not upload source through Studio.

## 4. Truthful status contract

Every Studio summary, specification row, badge and rebind action must use
file-drift-aware APatch coverage. The projection may cache one coherent snapshot,
but it may not combine a stale list from one calculation with totals from
another. If canonical coverage cannot be calculated, Studio shows unavailable or
attention rather than zero.

The calculation must reuse a single ledger read per refresh so the correction
does not turn a workspace with hundreds of specifications into N ledger scans.

## 5. Review and delivery contract

A completed local run provides:

- safe before/after counts and APatch evidence actions;
- a bounded safe phase timeline, never the raw transcript;
- Open local diff, implemented as a fixed-purpose local launch;
- durable local reviewer notes stored in the owner-only Studio journal;
- delivery status for staged changes, current branch, upstream readiness and
  notarization result;
- explicit Commit staged changes, Push current branch and Open pull request
  actions with confirmations for external effects.

The UI must distinguish technical verification, local reviewer notes, Git
delivery and team or business acceptance.

## 6. Hygiene recovery contract

When hygiene is degraded or critical, Work shows an attention band with Preview
cleanup and Run safe cleanup. The destructive action uses an in-product
confirmation dialog that names the bounded effect. Completion refreshes the
canonical overview and reports deleted and reclaimed counts.

A clean workspace does not show a false warning.

## 7. Optional Cowork workflow contract

Studio remains a complete local product. When an owner configures exact issuer
trust, Inbox adds one collaboration entry point:

- import and verify a signed work proposal;
- show the human-readable request and exact signed envelope status;
- require explicit local binding to a SPEC before governed execution;
- preserve expiry, decline and replay outcomes.

An unconfigured client presents one actionable setup path and no disabled fake
decision controls. No local or remote read model may infer accepted work from a
green test.

## 8. Contribution and timesheet contract

Studio must project this workflow from the existing APatch contribution APIs. It
must not independently aggregate ContributionEvent records, infer missing work,
or create a second timesheet truth.

APatch Studio OSS provides a local contribution view derived by `run_timesheet`
(or the byte-equivalent MCP operation), grouped by project, specification and
day. The user can request canonical verification, which re-derives reported
volume from the signed ledger. The UI labels all draft hours as estimates based
on governed operation spacing, not a stopwatch, payroll record or accepted time.
A separate authority decision remains required for accepted time.

Review displays the allowlisted contribution receipt and Avatar synchronization
outcome returned by attestation. A missing optional Avatar contract or unavailable
credential is visible with its stable error code and retryability; Studio never
silently converts delivery failure into successful completion. Admin shows
content-safe delivery health: pending outbox count, last acknowledged state and
Tracker availability, without exposing tokens, URLs, paths or event payloads.
Provider absence or stale data is displayed as unavailable; local execution and
timesheet verification remain usable.

## 9. Interaction quality

Actions use distinct icons and product language. User-facing operational terms
that are not standard Git vocabulary have contextual help. Essential labels and
mobile navigation use at least 11 px text. Destructive actions use Studio
dialogs, not window.confirm. Dark theme and operating-system notifications are
valuable follow-up work but do not block this loop-closure release.

## 10. Release proof

The release requires focused backend and frontend interaction tests, the complete
Python suite, frontend production build and browser verification on desktop and
mobile. Browser QA covers stale attention, cleanup confirmation, local review,
delivery states and the optional signed Inbox. No test may claim a workflow complete only
because a component compiles or a label exists.

## 11. Acceptance

| Id | Requirement | Level |
|---|---|---|
| LOOP-1 | All Studio requirement summaries and stale actions use one file-drift-aware APatch coverage snapshot and fail visibly rather than reporting false zero | MUST |
| LOOP-2 | Degraded or critical hygiene is actionable from Work through preview and explicitly confirmed safe cleanup with refreshed outcome | MUST |
| LOOP-3 | Review opens a full local diff through a fixed-purpose owner-only handoff, stores bounded notes durably and shows a safe event timeline without returning source, paths or transcripts | MUST |
| LOOP-4 | Studio exposes bounded staged-commit, current-branch push and pull-request handoff with notarization, confirmation and no arbitrary Git command or automatic staging | MUST |
| LOOP-5 | Optional Cowork Inbox has truthful configured and unavailable states, verifies signed proposals and never starts work on import | MUST |
| LOOP-6 | Studio shows the canonical verifiable contribution timesheet, allowlisted attestation and Avatar outcomes, and content-safe sync health while accepted time remains separate | MUST |
| LOOP-7 | Focused interaction, privacy, API, full-suite, build and browser tests prove the closed loop and preserve local execution while Cowork is unavailable | MUST |

## 12. Non-goals

This RFP does not add a cloud source repository, raw runner log viewer, arbitrary
shell or Git relay, automatic business acceptance, force push, automatic staging,
or a second Project, SPEC, task, approval or evidence authority.
