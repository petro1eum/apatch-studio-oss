# RFP-008 -- APatch Studio Existing Work Continuity

> **Status:** Implemented and locally release-qualified
> **Owner:** APatch Studio
> **Date:** 2026-09-01
> **Depends on:** RFP-006, RFP-007; APatch governed runtime 0.8.38 or newer
> **Executable contract:** docs/specs/SPEC-STUDIO-CONTINUITY-1.md

## 1. Decision

APatch already works before Studio is installed. Opening an established governed
workspace must continue the user's existing work instead of presenting an empty
product that only knows runs launched by Studio.

Studio will project signed APatch sessions into the same Changes feed as its
private runner journal. The signed ledger remains the sole source for imported
work, and the Studio journal remains the source only for runner supervision,
review notes and contextual actions. Entries are merged by exact governed
session id and never copied into a second mutable history.

The verified-time surface will also become a usable workflow. It defaults to the
selected workspace and a bounded recent period, shows meaningful totals before
detail, and lets the user regroup, verify and export the canonical draft without
turning estimated time into accepted time.

## 2. Observed failure

On the APatch Studio repository the runtime reports hundreds of signed operations
and completed requirements, while Home says "Start your first change" because
the Studio runner journal is empty. Time initially renders hundreds of rows from
the identity-wide contribution store and an unexplained account-wide delivery
count. Both surfaces contradict the selected-workspace mental model.

## 3. Canonical sources

Imported changes are derived directly from the APatch Ed25519 ledger. A session
projection may expose only the user intent, timestamps, requirement reference,
signed mutation/attestation counts and content-safe aggregate file/line counts.
It must never expose source, full diff, paths, prompts, credentials or session
capabilities.

Time is always produced by APatch `run_timesheet`. Studio passes the exact
selected project id and period to that canonical function; it does not read or
aggregate ContributionEvent files itself. Verification invokes the same function
with canonical re-derivation enabled.

## 4. Unified Changes feed

Home orders Studio runs and imported signed sessions in one feed. If a Studio run
already references an imported governed session, only the richer Studio card is
shown. Stable imported ids are derived from the governed session id.

An imported card shows what was requested, whether it is Proven or merely
Recorded, when it happened, its safe delta and its exact requirement when known.
Its proof drill-in exposes bounded signed-event metadata. It must not pretend that
retry, review-note, rollback or Git delivery actions are available when Studio did
not supervise that historical run.

"First change" is shown only when both the Studio journal and signed APatch
history are empty.

## 5. Verified time workflow

The default view is the selected workspace over the last seven calendar days.
The user can choose seven days, thirty days or a custom date range and group by
day or requirement. The view leads with total estimated hours, governed changes,
operations and files before rendering bounded detail.

A verification action states whether the draft re-derives from signed records.
CSV export is generated only from the currently displayed canonical draft and
includes its estimate basis. It is a local file operation and does not submit,
accept or synchronize time.

Identity-wide delivery health is labelled as such and remains separate from the
workspace-scoped time draft. Large pending counts are not presented as a
workspace failure.

The draft includes current-workspace local records even when their separate
contribution signature is absent, so established APatch work is not silently
shown as zero. The verification action then reports unsigned and drifted records
separately; only a zero-error result may be described as matching signed records.

## 6. Edition boundary

This continuity and local verified-time workflow is APatch Studio OSS
functionality. Cowork may consume separately authorized aggregate projections,
but it cannot replace the local truth. RFP-008 does not add
person-level surveillance, payroll, team acceptance or a second contribution
store.

## 7. Privacy and authority

Studio never uploads code, paths, prompts or full diffs. Signed proof does not
equal business acceptance. Draft hours remain operation-spacing estimates, not a
stopwatch, payroll record, invoice approval or accepted time. Any accepted-time
decision belongs to an external authority and is outside this RFP.

## 8. Release proof

Tests must use signed-ledger-shaped fixtures and prove grouping, ordering,
deduplication, first-run continuity, project/period forwarding, canonical
verification, bounded export and content-safe projections. A browser pass must
show a non-empty established workspace on Home and a bounded useful Time view on
desktop and mobile.

## Acceptance

| Id | Requirement | Level |
|---|---|---|
| CONT-1 | Home projects existing signed APatch sessions as changes even when the Studio runner journal is empty | MUST |
| CONT-2 | Studio runs and imported sessions are ordered together and deduplicated by exact governed session id | MUST |
| CONT-3 | Imported cards expose truthful safe aggregates and proof state without source, paths, full diffs or unavailable mutation actions | MUST |
| CONT-4 | First-run UI appears only when neither canonical ledger history nor Studio runs exist | MUST |
| CONT-5 | Time defaults to the selected workspace and last seven days, with explicit 7-day, 30-day and custom controls | MUST |
| CONT-6 | Time shows totals, bounded detail, day/requirement grouping and canonical signed-record verification | MUST |
| CONT-7 | Local CSV export is derived from the displayed canonical draft and preserves estimate/acceptance disclaimers | MUST |
| CONT-8 | Focused, full-suite, build and desktop/mobile browser gates prove the workflow end to end | MUST |

## Non-goals

No ledger migration, APatch protocol rename, cloud source mirror, historical
runner transcript reconstruction, fabricated diff, automatic time acceptance,
payroll, invoicing or TrustChain authority change is part of this RFP.
