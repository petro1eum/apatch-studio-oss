# RFP-023 — APatch Studio OSS public distribution

Status: accepted for implementation
Owner: Ed Cherednik
Product: APatch Studio OSS
Source basis: private APatch Studio commit `4a1d70f2e7b92f62fc0b595510c223886036a27b`

## Problem

APatch is publicly installable, and TrustChain Cowork can issue governed work, but
a user still needs a complete local product in which they can inspect the request,
choose a workspace and agent, execute the exact contract, recover interrupted work,
review evidence and deliver the result. Publishing the combined private Studio
repository would also disclose and distribute the organization control plane.

The release therefore needs a clean, independently installable OSS client rather
than a visibility change on the private repository.

## Product boundary

APatch Studio OSS is the local human workspace. It works without an account,
subscription or network connection. It may be explicitly connected to TrustChain
Cowork, but Cowork remains the shared project and human-authority surface.

The public source and artifacts include local governed execution, RFP/SPEC work,
runner supervision, recovery, review, delivery packs, evidence, WorkAssets, Avatar
evidence export, time drafts, local identity and the signed Cowork Inbox.

They exclude the hosted organization authority, membership and entitlement
services, fleet and rollout management, hosted persistence, organization admin UI,
and generic remote execution.

## User journeys

### Solo work

A developer installs Studio, selects an existing Git repository, prepares or opens
an exact RFP/SPEC requirement, starts Codex or Claude Code through APatch, reviews
the verified result and exports evidence. No account or network call is required.

### Cowork assignment

A developer explicitly configures TrustChain authority pins and the APatch
governed-work endpoint. A signed Cowork assignment appears in Inbox. Importing it
does not start an agent. The user selects an existing SPEC and confirms locally.
Studio then requires Cowork acceptance and source-binding acknowledgements before
starting exactly one local run. Only separately authorized, content-safe evidence
is queued for return.

### Failure and recovery

If the agent, verification or network fails, the local contract and checkpoint
remain available. A Cowork outage does not disable solo work, review, recovery,
rollback or local export.

## Security boundary

Studio binds only to a loopback interface. The browser API is fixed-purpose and
session guarded. Source, diffs, prompts, raw runner output, local paths, environment,
credentials, private keys and APatch capabilities are not Cowork payloads. The
public artifact contains no private control-plane implementation or private Git
history.

## Release rule

Both the public Git repository and the package artifacts are release subjects.
A green source checkout is insufficient: the exact built wheel and sdist must be
inspected and an isolated wheel must serve the bundled UI.

## Acceptance

| ID | Requirement | Priority |
| --- | --- | --- |
| OSSPUB-1 | Public source has a new history, MIT license matching TrustChain OSS, English primary documentation and no private control-plane implementation | MUST |
| OSSPUB-2 | Wheel and sdist contain only the declared OSS package/source boundary, carry the exact license and have no direct-URL dependency | MUST |
| OSSPUB-3 | An isolated wheel exposes only the OSS CLI and serves its bundled UI on loopback without Node or a source checkout | MUST |
| OSSPUB-4 | A fresh local workspace remains useful without an account, subscription, Cowork configuration or network access | MUST |
| OSSPUB-5 | Signed Cowork import is opt-in, verifies the exact envelope, remains inert until local confirmation and starts once only after both acknowledgements | MUST |
| OSSPUB-6 | The public backend and compiled UI expose no organization, fleet, entitlement, Local Team or Pro-server route | MUST |
| OSSPUB-7 | Secret, private-path and repository-history scans fail closed before publication | MUST |
| OSSPUB-8 | Public documentation accurately describes the before/after value, standalone boundary, Cowork connection and data-handling limits | MUST |
| OSSPUB-9 | Release evidence records the private source commit, public commit, artifact hashes and executed commands without copying private history | MUST |
