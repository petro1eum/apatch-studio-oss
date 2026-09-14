# RFP-010 -- APatch Studio Interactive Project Change

> **Status:** Approved for implementation
> **Owner:** APatch Studio
> **Date:** 2026-09-01
> **Depends on:** RFP-006, RFP-007, RFP-008, RFP-009
> **Executable contract:** docs/specs/SPEC-STUDIO-INTERACTIVE-CHANGE-1.md
> **Evidence source:** owner walkthrough of the live deep link `#/home/apchg_39080442cb391daab99fa4fbe20cff13`

## 1. Decision

APatch Studio is not release-acceptable while a change link only expands a row in a long history list. A project developer must be able to open one change and understand the project, requested outcome, actor, files, patch, verification and next action without knowing APatch protocol terms.

Studio adds a dedicated local change workspace. It is a projection over the existing APatch ledger and Studio run journal, not a new execution database. The signed ledger remains authoritative for imported mutations and proof.

## 2. Observed failure

The current deep link enables Full history, leaves the selected record below the fold and exposes only counts. It does not identify the repository beyond a folder name, distinguish the local operator from the signing identity, show changed files or patches, or provide a useful action. An attest-only record incorrectly resembles an empty code result instead of a verification checkpoint.

This is a missing product workflow, not a copy or styling defect.

## 3. Project identity

Home and change detail show a safe local project identity: project name, repository slug when derivable, current branch, upstream branch, head and local Git operator name. Credentials, email addresses, absolute paths and raw remote URLs are never projected.

The local operator is context, not inferred authorship. Imported APatch history identifies its signer separately; Studio-managed runs identify their configured runner.

## 4. Dedicated change workspace

The route `#/home/<change_id>` renders a dedicated detail screen above the fold. It never toggles Full history or expands a card in place. The screen contains:

1. Back to changes.
2. Project and branch context.
3. Human outcome title and status.
4. Who recorded or executed it, when, and why.
5. Changed files and local patch when mutations exist.
6. Verification and exact technical anchors under progressive disclosure.
7. One meaningful next action.

Unknown or malformed identifiers fail safely without exposing local state.

## 5. Canonical local detail

The backend exposes a session-guarded, loopback-only detail endpoint derived on demand from existing signed APatch ledger entries. It does not persist a second copy. A change identifier resolves deterministically to one governed session, and only records from that exact session contribute to the response.

Recorded file paths must be repository-relative and traversal-safe. Patch output is bounded per file and for the complete response. Binary, missing and truncated content is represented explicitly.

## 6. Honest result types

A change with signed file mutations is a code change and shows its file list, line delta and recorded patch. A session with no file mutation is a verification checkpoint and states “No files were changed.” It must not offer an empty diff or imply code authorship.

When a SPEC requirement anchor exists, the checkpoint or change links to the exact backlog item. APatch terms and raw IDs remain in an optional technical section.

## 7. Real interactions

The detail workspace provides:

- Back to changes for every record.
- Open recorded patch in an allowlisted local viewer when a patch exists.
- Open backlog item when a SPEC anchor exists.
- Existing review, retry, recovery, rollback preview and delivery actions for Studio-managed runs.

The local viewer uses the recorded ledger patch for imported changes, not the current working-tree diff. No arbitrary command, path or MCP relay is exposed to the browser.

## 8. Privacy and trust boundary

Full patches are a local-only privacy band. They are served only through the existing authenticated Studio loopback session and never included in Cowork or other remote projections. The normal change feed remains path- and diff-free.

Studio does not infer business acceptance from proof, infer a human author from Git config, or weaken APatch verification and rollback rules.

## 9. Release proof

Release qualification requires deterministic detail-projection tests, traversal and size-bound tests, API authorization and not-found tests, UI journeys for both a real mutation and an attest-only checkpoint, the complete Python suite, production frontend build, and desktop/mobile browser checks with no console errors.

## Acceptance

| Id | Requirement | Level |
|---|---|---|
| CHANGE-1 | Home and detail expose safe project identity including repository slug, branch, upstream, head and local operator without credentials, email, raw remote URL or absolute path | MUST |
| CHANGE-2 | `#/home/<change_id>` renders a dedicated change screen above the fold and never expands Full history in place | MUST |
| CHANGE-3 | A session-guarded local API derives one exact change detail from the existing APatch ledger without secondary persistence | MUST |
| CHANGE-4 | Mutation detail shows traversal-safe repository-relative files, bounded recorded patches, line deltas, mode/hash metadata and explicit truncation state | MUST |
| CHANGE-5 | Detail distinguishes Studio runner, APatch signing identity and local Git operator without inferring false authorship | MUST |
| CHANGE-6 | Attest-only sessions render as verification checkpoints with “No files were changed” and no empty-diff action | MUST |
| CHANGE-7 | Detail provides Back to changes, local recorded-patch review when available and exact backlog navigation when a SPEC anchor exists | MUST |
| CHANGE-8 | Existing Studio-run review, retry, recovery, rollback-preview and delivery interactions remain available on their dedicated detail route | MUST |
| CHANGE-9 | Focused security/projection/API/UI tests, full suite, production build and desktop/mobile browser journeys prove the interactive workflow | MUST |

## Non-goals

This RFP does not create a cloud source-code store, a second ledger, a second project database, a generic local file browser, a browser-accessible shell, an arbitrary MCP proxy, inferred business acceptance or inferred code authorship. It does not change APatch Core ledger bytes, TrustChain contracts or ContributionEvent.
