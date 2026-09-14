# RFP-007 -- APatch Studio Outside-In Experience

> **Status:** Implemented; release proof pending
> **Owner:** APatch Studio
> **Date:** 2026-09-01
> **Depends on:** RFP-005, RFP-006; public APatch governed runtime
> **Executable contract:** docs/specs/SPEC-STUDIO-OUTSIDE-IN-1.md

## 1. Decision

Studio passes the RFP-005 functional-tab contract and still fails the
first-session test: a developer opening the product cannot intuitively
understand either the design or the function. The cause is architectural, not
cosmetic. The interface projects APatch's internal ontology - sessions,
attestations, artifacts, staleness, hygiene - as the primary product surface,
so the user must learn the protocol before they can see their own work.

This RFP reorganizes Studio around the user's object of work: the change they
asked for. APatch remains the engine and the sole truth. The interface stops
speaking its wire format.

RFP-006 closes truth and loop gaps (coverage parity, local diff, cleanup,
Git handoff, signed Inbox and contribution views). This RFP assumes those
capabilities and governs how the product presents them. It revises the RFP-005
section 6 information architecture without removing any capability and without
weakening any RFP-004 or RFP-005 boundary.

## 2. Verified problems

From the owner walkthrough:

1. The primary object - the change the user asked for - has no single surface.
   Its objective lives in Work Start, its execution in Work Runs, its outcome
   in Review, its proof in Evidence and its origin in Specs. No screen answers:
   what did I ask for, what happened to it, what do I do next.
2. Primary labels use protocol vocabulary: attested, stale, rebind, notarize,
   ratify, inclusion, governed session, execution intent, WorkAsset, hygiene.
   Evidence expects a raw `spec:SPEC-X#R2` artifact string in a text field.
3. Starting work requires choosing between four modes (new change, exact
   requirement, recovery, rollback preview) before any value is produced.
   Recovery and rollback are start-screen peers instead of contextual actions
   on a failed change.
4. Navigation offers too many protocol-oriented destinations with no hierarchy;
   policy, evidence and setup compete visually with daily work.
5. The runtime's strongest differentiator - out-of-scope agent writes are
   blocked and reverted - is invisible in the product. A user cannot see that
   the discipline happened.
6. Design floor: 8-9 px metadata type, one glyph reused for delete, restore,
   rotate and refresh, native window.confirm for destructive actions, no dark
   theme.

These are presentation-architecture defects. The runtime capabilities behind
them already exist and stay owned by APatch.

## 3. Product principle

Outside-in. Every surface is named for the user's goal and organized around the
user's object. Protocol nouns appear only inside proof panels, tooltips and
exports. Every screen must answer one sentence: what did I ask for, what is
happening to it, and what is the one next action.

The principle does not soften governance; it makes governance legible.

## 4. Information architecture

Target primary navigation: four local destinations and one optional configured
Inbox.

| Destination | Content | Absorbs (RFP-005 tabs) | Availability |
|---|---|---|---|
| Home | Changes feed; one card per change from request to proof | Work, runs, changes and local review | Always |
| Plans | RFPs and executable requirements in task language | Specifications | Always |
| Library | Proven methods, evidence and verified time | Assets, evidence and time | Always |
| Admin | Runtime, policy, workspaces and diagnostics | Policy and settings | Always |
| Inbox | Signed Cowork proposals | External work intake | Only with configured issuer trust |

A change card carries: the objective in the user's words; live status; delta
summary (safe counts from the RFP-006 review contract); scope report (section
6); proof state; and exactly one suggested next action. Timeline, local diff,
proof details and reviewer notes are drill-ins of the card, never parallel
top-level destinations.

The migration preserves every RFP-005 capability and deep link through a
deterministic redirect map. Existing run, intent and evidence identifiers
remain unchanged.

## 5. Vocabulary contract

A versioned, machine-checkable dictionary (a contract file alongside
`navigation.contract.json`) maps protocol terms to product language. Primary
labels, buttons, empty states and notifications must draw from the product
column. Protocol terms remain available in proof panels, tooltips, exports and
the API. Minimum dictionary:

| Protocol term | Primary UI language |
|---|---|
| attested, attestation | proven, proof |
| stale (file drift) | needs re-check |
| rebind | re-check |
| notarized | recorded |
| governed session | protected run |
| execution intent | signed task |
| WorkAsset | proven method |
| hygiene degraded or critical | cleanup needed |
| ratify | gate re-check |
| inclusion proof | independent log check |
| artifact reference `spec:X#Rk` | requirement picker, never a raw string field |

A CI lint fails the build when a term from the protocol column appears as a
primary label outside proof surfaces.

## 6. Scope honesty

Every change card reports the scope outcome of its run: the authorized paths,
and the count of out-of-scope writes that were blocked or reverted, with
content-safe paths available on drill-in. A clean run states that only the
requested scope changed.

This surfaces the runtime's core guarantee - the agent cannot silently do
unrequested work - as a visible product moment instead of a ledger
internality. The projection reuses the existing sandbox audit results; Studio
does not create a second audit truth.

## 7. Start contract

Creating a change requires one input: the result that must be true, in the
user's words. Optional refinements (link a backlog requirement, choose an
agent, adjust verification) are progressive, collapsed by default, and carry
working defaults. Recovery, rollback preview and exact-requirement execution
are reachable only from context - a failed change card or a backlog row -
never as first-screen peer modes.

## 8. First run

An empty connected workspace proposes exactly one action. Completing it
produces the user's first proven change without reading documentation. If no
workspace is connected, connecting is the one action. Onboarding introduces at
most three concepts: your request, its proof, and what is left.

## 9. Design floor

Dark and light themes with a system default; minimum 11 px for all persistent
text; one glyph means one action class across the product; destructive
confirmations are in-product dialogs naming the exact bounded effect,
extending the RFP-006 cleanup dialog rule to every destructive action;
focus-visible states and reduced-motion behavior from the RFP-005
accessibility contract are preserved.

## 10. Release proof

Interaction tests prove the outside-in contract: the change card answers
request, status and next action from one screen; the vocabulary lint runs in
CI; the scope report renders blocked and reverted counts from a seeded sandbox
audit; the first-run journey completes to a proven change in a disposable
workspace; the migration preserves deep links. The complete Python suite,
frontend production build and desktop plus mobile browser passes remain
required as in RFP-005 and RFP-006. No test may claim the contract satisfied
because a component compiles or a label exists.

## Acceptance

| Id | Requirement | Level |
|---|---|---|
| OUT-1 | Home is a changes feed where one card per change presents objective, live status, delta summary, scope report, proof state and exactly one suggested next action without visiting another destination | MUST |
| OUT-2 | Primary navigation has four local destinations and one optional configured Inbox, with deterministic redirects preserving every RFP-005 capability and deep link | MUST |
| OUT-3 | A versioned vocabulary contract maps protocol terms to product language, all primary labels draw from it, and a CI lint fails when protocol terms leak into primary surfaces | MUST |
| OUT-4 | Every change card reports scope honesty from the existing sandbox audit, showing authorized paths plus blocked or reverted out-of-scope writes, and a clean run states that only the requested scope changed | MUST |
| OUT-5 | Starting a change requires one input with progressive optional refinements, while recovery, rollback preview and exact-requirement modes are contextual actions rather than start-screen peers | MUST |
| OUT-6 | Protocol machinery such as attestation ids, artifact references, ledger records and operation ids is reachable only through expandable proof panels that render full fidelity on demand | MUST |
| OUT-7 | An empty workspace proposes exactly one action and the first-run journey ends in a proven change without documentation | MUST |
| OUT-8 | The product ships dark and light themes, at least 11 px persistent text, one-glyph-one-meaning iconography and in-product destructive confirmation dialogs for every destructive action | MUST |
| OUT-9 | Interaction, vocabulary-lint, scope-report, first-run, migration, full-suite, build and browser tests prove the outside-in contract rather than rendering or compilation | MUST |

## Non-goals

This RFP does not rename anything inside APatch itself: the CLI, MCP, ledger
and wire vocabulary are canon. It does not weaken sandbox, governance or
evidence semantics for the sake of simplicity. It does not duplicate RFP-006
deliverables. It does not add project management, payroll, business acceptance
or a second source of truth for any APatch-owned state, and it does not remove
any RFP-005 capability from the product.
