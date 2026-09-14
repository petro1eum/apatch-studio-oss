# RFP-002 -- APatch Studio Operational Agent Workspace

> **Status:** Approved for P0 implementation
> **Owner:** APatch Studio
> **Date:** 2026-08-31
> **Depends on:** RFP-001; private APatch governed runtime 0.8.36 or newer
> **Executable contract:** `docs/specs/SPEC-STUDIO-OPERATIONS-1.md`

## Objective

Turn APatch Studio from a read-only observability shell into a useful local
developer product. A person must be able to describe work, dispatch a local AI
agent through the APatch governed runtime, observe bounded progress, cancel a
run, and retry or recover failed work without learning the 122-tool agent API.

## User workflows

### New governed change

The user chooses an available local runner, states the intended outcome and
acceptance criteria, and starts work. The runner is instructed to inspect the
workspace, create and lint an RFP/SPEC when needed, execute it through APatch,
verify the result, attest completed requirements, and stop without pushing.

### Existing executable requirement

The user selects an exact SPEC and requirement from the live APatch projection.
Studio dispatches the agent with immutable identifiers. The agent must use that
requirement rather than inventing a parallel task or bypassing governance.

### Recovery

A failed or interrupted run can be retried as recovery work. The follow-up agent
must inspect exact APatch session state, use exact-session recovery when needed,
and continue from existing checkpoints instead of restarting from assumptions.

## Architecture

```text
React Studio UI
  -> authenticated same-origin loopback API
  -> typed AgentRunRequest
  -> fixed-purpose AgentRunManager
  -> allowlisted Codex CLI or Claude Code argv (prompt over stdin, no shell)
  -> agent uses full APatch MCP/CLI in the selected local workspace
  -> APatch remains owner of SPEC/session/mutation/verify/attestation state
```

The manager owns only process-local runner state. It does not copy APatch
session capabilities, source, diffs or private logs into another database.
The browser receives a safe run projection, not raw runner JSONL.

## Security boundary

Runner executable names and argv are code-owned allowlists. The request cannot
supply a binary, shell fragment, environment override, cwd, MCP tool name or
permission flag. User text is sent over stdin and never interpolated into a
shell command. At most a small bounded number of local runs execute at once.

The initial Codex profile uses workspace-write plus automatic approval review.
Claude Code uses its non-interactive automatic permission mode. Studio does not
enable either vendor's unconditional sandbox/permission bypass flag.

## Acceptance

| Id | Requirement | Level |
|---|---|---|
| OP-1 | Studio accepts only typed new_change, requirement and recovery requests with bounded text and exact identifier validation | MUST |
| OP-2 | Studio detects supported local Codex and Claude Code runners and builds argv from a code-owned allowlist without shell execution or request-controlled flags | MUST |
| OP-3 | A run has an observable queued/running/succeeded/failed/cancelled lifecycle, bounded concurrency, timestamps, cancellation and retry/recovery linkage | MUST |
| OP-4 | Generated runner instructions require doctor/lint, exact SPEC ownership, governed mutation, verification, attestation or rollback, and prohibit silent push/deploy | MUST |
| OP-5 | Browser run projections exclude raw runner events, source, diffs, paths, credentials, private keys, prompts and APatch session capabilities | MUST |
| OP-6 | Authenticated same-origin APIs expose runner discovery, start, list/detail, cancel and retry as fixed-purpose operations only | MUST |
| OP-7 | The UI makes Start work and Runs primary workflows, supports new/existing/recovery modes, validates input and shows progress and actionable terminal states | MUST |
| OP-8 | The operational API remains incapable of arbitrary shell/MCP relay and preserves the RFP-001 loopback, token and content-safety boundary | MUST |
| OP-9 | Unit/API tests use deterministic fake runners, and a disposable-workspace smoke proves a real managed process can complete without mutating source | MUST |

## Non-goals

- TrustChain ProjectGroup, ProjectWorkItem, WorkRelease or team authority.
- Cloud source upload or a mandatory account.
- Browser access to raw MCP tools, arbitrary commands or APatch capabilities.
- Automatic business acceptance, git push, deployment or production restart.
- Cross-repository atomic execution.
- Claiming team collaboration before the separate TrustChain integration lands.
