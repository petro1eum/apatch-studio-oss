# RFP-009 -- APatch Studio Comprehensible Project Home

> **Status:** Implemented and release-qualified
> **Owner:** APatch Studio
> **Date:** 2026-09-01
> **Depends on:** RFP-006, RFP-007, RFP-008
> **Executable contract:** docs/specs/SPEC-STUDIO-PROJECT-HOME-1.md
> **Evidence source:** owner walkthrough of the live Home screen at commit 4c5c344732f88869ceefca3bf8e369412e877baa

## 1. Decision

The current Home is not release-acceptable even though its underlying actions
work. It presents APatch's execution records as the product and therefore asks
the user to infer the project, current state and next action from protocol
history. The owner of APatch could not understand the screen without reading
the implementation. A new user would have less context.

Home becomes a project briefing and action surface. Its order is fixed:
project identity, current state, one primary action, recent meaningful outcomes,
then optional technical history. APatch remains the only source of execution
and proof truth; Studio changes projection and hierarchy, not governance.

## 2. Observed failure

The live screen contains dozens of peer cards titled with
`SPEC-STUDIO-...#R...`, repeated attest-only checkpoints, and badges such as
"Existing APatch work". A successful implementation detail is promoted above
the user's mental model. The screen does not state whether work is running,
whether attention is required, whether the project is ready, or which results
matter now.

The failure is architectural. More tooltips, documentation or decorative
polish cannot repair an information hierarchy that starts from ledger rows.

## 3. Ten-second comprehension contract

Without opening documentation or a proof panel, a developer must be able to
answer all of these questions within ten seconds:

1. Which local project is open?
2. Is work running, blocked, awaiting review or ready for a new change?
3. What is the single primary action available now?
4. What were the latest meaningful outcomes?
5. Is the working tree clean, and how much planned work is proven?

Protocol identifiers, session ids and attestation mechanics must not be needed
to answer any of them.

## 4. Fixed Home hierarchy

### 4.1 Project identity and state

The project name is the H1. Branch is secondary metadata. A compact state line
uses one of four product states: Working, Needs attention, Ready for review or
Ready for a new change. A summary strip shows proven requirements, unfinished
requirements and uncommitted files using plain language.

### 4.2 Primary action

The only primary composer question is "What do you want to change?" and its
command is "Run with agent". Agent, backlog binding and verification controls
stay under collapsed Options. Recovery and rollback remain contextual.

### 4.3 Recent outcomes

Home initially shows at most six meaningful outcomes. A meaningful imported
outcome contains a mutation, touches a file, represents a rollback, or needs
attention. Studio runs are always meaningful. Repeated records for the same
SPEC requirement collapse to the newest meaningful outcome.

Human titles omit a leading `SPEC-ID#Rk:` anchor. Status uses Verified,
Recorded, Rolled back, Working or Needs attention. The technical anchor remains
available in the expanded proof panel.

### 4.4 Full history

The complete canonical history remains reachable through one "Show full
history" action and exact deep links. Attest-only and zero-mutation records are
not deleted; they are progressively disclosed instead of occupying Home by
default.

## 5. Projection and truth boundary

The Home projection is deterministic over the existing
`apatch.studio.change-feed.v1` response. It does not aggregate a second
ledger, mutate APatch records or infer business acceptance. Filtering,
deduplication and title humanization are presentation-only and covered by pure
tests. Exact ids and full-fidelity proof remain unchanged.

## 6. State priority

Home chooses the current state deterministically:

1. Any running or queued Studio run: Working.
2. Any failed, interrupted or retryable Studio run: Needs attention.
3. Any succeeded run not yet reviewed: Ready for review.
4. Otherwise: Ready for a new change.

A dirty working tree is reported separately and never silently reclassified as
a failed APatch run.

## 7. Release proof

Release qualification requires pure projection tests, component journey tests,
the complete Python suite, a production frontend build, and browser checks at
desktop and 390 px mobile widths. The browser check must prove that project
identity, current state, primary action and recent outcomes are visible without
opening proof. No primary card may expose a SPEC anchor as its display title.

## Acceptance

| Id | Requirement | Level |
|---|---|---|
| HOME-1 | Home names the local project as H1 and presents deterministic current state, proven work, remaining work and uncommitted-file counts before any history | MUST |
| HOME-2 | Home presents one primary "What do you want to change?" action with "Run with agent", while advanced controls remain collapsed under Options | MUST |
| HOME-3 | The default recent-outcomes projection contains at most six meaningful items and excludes attest-only zero-mutation imported records | MUST |
| HOME-4 | All requirement sessions of one SPEC collapse into one newest project-level result on Home, while full canonical per-session history remains unchanged and reachable | MUST |
| HOME-5 | Primary titles and status labels use human language and hide leading SPEC/Rk anchors while exact identifiers remain available in expanded proof | MUST |
| HOME-6 | Full canonical history and exact deep links remain reachable through progressive disclosure | MUST |
| HOME-7 | Working, Needs attention, Ready for review and Ready for a new change states are derived deterministically from current Studio runs | MUST |
| HOME-8 | Pure tests, full suite, production build and desktop/mobile browser journeys prove ten-second comprehension without weakening APatch governance | MUST |

## Non-goals

This RFP does not replace APatch history, create project-management state,
remove proof fidelity, infer code quality from counts, or hide failures. It does
not change APatch Core, MCP, CLI, ledger schemas or TrustChain contracts. It
does not add onboarding documentation to compensate for an unclear product.

## Amendment 2026-09-03: a state always names its cause and one next step

`Needs attention` was shown in the Home header, the top bar and the runtime card without saying why or what to do. The project state now carries `detail` (the cause, for example `2 changes did not finish`) and `next_step` (one action in product language) next to `label`; Home renders both under the state pill and the top bar exposes them as the pill's title. The runtime card names its cause (`Storage needs cleanup (N records)`) and opens Admin › Local runtime, where safe cleanup lives. No protocol vocabulary is used in any of these texts.
