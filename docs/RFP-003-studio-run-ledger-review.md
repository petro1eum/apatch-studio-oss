# RFP-003 -- Durable Local Run Ledger and Review

> **Status:** Approved for P0 implementation
> **Owner:** APatch Studio
> **Date:** 2026-08-31
> **Depends on:** RFP-002; private APatch governed runtime 0.8.36 or newer
> **Executable contract:** `docs/specs/SPEC-STUDIO-RUN-LEDGER-1.md`

## Objective

Make APatch Studio useful across process restarts. A developer must retain a
bounded local history of agent runs, distinguish an interrupted Studio process
from a failed governed change, retry exact prior work, and review safe before/after
workspace metrics without storing raw agent output or copying APatch authority state.

## User workflows

### Resume after Studio restart

Studio loads the journal for the selected workspace. Records that were queued or
running when the prior process stopped become terminal `interrupted` records. The
user can retry them; Studio never claims to have reattached an unknown child process.

### Review a completed run

The Runs view opens a stable detail surface containing lifecycle timestamps, runner,
mode, retry ancestry and aggregate workspace observations captured before and after
the run. Counts are observations, not proof of attribution or business acceptance.
APatch evidence remains the authority for governed mutation and attestation.

### Operate without polluting the repository

The journal lives in the operating-system user state directory under a one-way
workspace identity. It is never written into the Git working tree.

## Data model

The document schema is `apatch.studio.run-journal.v1`. Each record may contain the
validated AgentRunRequest fields required for local retry, lifecycle timestamps,
opaque run/thread identifiers, event count, terminal outcome, and safe review
snapshots. It must not contain generated prompts, raw stdout/JSONL, source, file
paths, diffs, environment, argv, credentials, private keys, session tokens or
APatch capabilities.

A review snapshot may contain only captured_at, branch, short Git head, dirty file
count, tracked insertions/deletions, attested/stale requirement counts, evidence
event count and WorkAsset count. Workspace-wide deltas are labelled observations.

## Storage and failure semantics

- Parent directories use owner-only permissions where supported.
- The journal file uses mode 0600 and temp-file + fsync + atomic replace.
- A process-local lock serializes manager transitions; a file lock prevents lost
  updates between two Studio processes using the same workspace journal.
- Corrupt or wrong-schema state is quarantined and surfaced as a journal warning;
  it is never executed or silently interpreted as valid history.
- Retention is bounded to 200 records by default. Active records are never evicted.
- No child-process PID is persisted or reused after restart.

## Acceptance

| Id | Requirement | Level |
|---|---|---|
| RL-1 | Studio stores a versioned workspace-scoped run journal outside the Git workspace | MUST |
| RL-2 | Journal writes are owner-private, locked, fsynced and atomically replaced | MUST |
| RL-3 | Persisted records use an explicit allowlist and exclude raw output, source, paths, secrets and APatch capabilities | MUST |
| RL-4 | On startup queued/running records become interrupted and can be retried without pretending to reattach a process | MUST |
| RL-5 | Terminal history has deterministic bounded retention while active work is never evicted | MUST |
| RL-6 | Runs capture safe before/after workspace observations and derive non-attributive deltas | MUST |
| RL-7 | Existing fixed-purpose run APIs return journal health and review data without adding shell/MCP relay | MUST |
| RL-8 | Runs UI provides durable history and a local review/detail surface on desktop and mobile | MUST |
| RL-9 | Tests cover restart, corruption, privacy, retention, atomic storage and disposable-workspace persistence | MUST |

## Non-goals

- Multi-user authority, team queues, WorkRelease or accepted timesheets.
- Persisting or displaying raw agent transcripts, source code, paths or full diffs.
- Reattaching a child process after the Studio server has terminated.
- Treating Git counts as APatch evidence or human acceptance.
- Cloud synchronization or a mandatory APatch Studio account.
