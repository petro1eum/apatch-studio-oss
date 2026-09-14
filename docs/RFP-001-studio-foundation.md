# RFP-001 — APatch Studio OSS foundation

Status: implemented
Owner: APatch Studio OSS
Executable contract: `docs/specs/SPEC-STUDIO-FOUNDATION-1.md`

## Objective

Provide a standalone, local-first human workspace over the public APatch governed
runtime. Studio must make agent work understandable and controllable without
creating a second mutation runtime, uploading source code or requiring a cloud
account.

## Product boundary

APatch owns Change/SPEC/requirement state, governed sessions, mutation admission,
path leases, verification, attestation, recovery, rollback and WorkAssets. Studio
owns the loopback human interface, fixed-purpose application API and supervision of
locally installed Codex or Claude Code runners.

Studio consumes stable APatch read models. It never copies `.apatch` into a second
database and never exposes arbitrary MCP or shell execution to the browser.

TrustChain Cowork is an optional collaboration surface. Connecting it can add
signed assignments and content-safe acknowledgements; it never weakens the local
contract or turns the OSS client into an organization control plane.

## Architecture

```text
local browser
  -> same-origin loopback API
  -> fixed-purpose Studio workflows
  -> public APatch runtime
  -> local Git repository and signed ledger
```

The browser receives a process-scoped session secret in the initial document and
sends it in a custom API header. The secret never appears in URLs, cookies, logs,
local storage or source-controlled files.

## Safe projection

The local browser may receive workspace display metadata, Git branch/head, policy
state, requirement identifiers and status, human intent, verification outcomes,
signed operation identifiers and WorkAsset metadata. It excludes file contents,
prompts, patch bytes, full diffs, credentials, private keys and APatch capabilities.

## Acceptance

| ID | Requirement | Level |
| --- | --- | --- |
| ST-1 | APatch Studio OSS is a public, standalone local client; Cowork is optional and no Pro server implementation is present | MUST |
| ST-2 | The service binds to loopback, rejects non-loopback Host values, guards non-health APIs with a process secret and requires same-origin for mutations | MUST |
| ST-3 | Session secrets are not persisted or placed in URLs, cookies or logs, and projections contain no source, prompts, credentials, private keys or APatch capabilities | MUST |
| ST-4 | Workspace, policy, session, SPEC, evidence and WorkAsset views derive from canonical APatch state without a second truth database | MUST |
| ST-5 | The UI provides functional Home, Plans, Library, Admin and optionally configured Inbox journeys on desktop and mobile | MUST |
| ST-6 | Loading, empty, degraded and refresh-failure states remain usable and keep primary controls stable | MUST |
| ST-7 | Backend tests, frontend production build and live loopback smoke against an APatch workspace pass | MUST |
| ST-8 | No arbitrary shell/MCP relay exists; source mutation is delegated to APatch through fixed-purpose workflows or an allowlisted local runner | MUST |

## Non-goals

- Hosted organization administration, membership, entitlement or fleet rollout.
- A second project, task or timesheet database.
- Source upload, remote telemetry or mandatory accounts.
- Browser-controlled arbitrary commands.
