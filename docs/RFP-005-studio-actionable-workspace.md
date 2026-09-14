# RFP-005 — APatch Studio OSS actionable workspace

Status: implemented
Executable contract: `docs/specs/SPEC-STUDIO-ACTIONABLE-UX-1.md`

## Decision

APatch Studio OSS is the human workspace for the public APatch runtime. It turns
contract-driven agent work into a usable local loop: understand the project,
prepare and approve an exact plan, run an agent inside that contract, inspect what
happened, recover safely, and export verifiable results.

Studio is not another execution engine or task database. APatch remains the sole
owner of requirements, governed mutation, verification, evidence and recovery.
Studio exposes fixed-purpose workflows over that state.

TrustChain Cowork is optional. When configured, Inbox can receive a signed work
proposal and bind it to a local SPEC only after explicit local acceptance. Cowork
does not receive source code, raw diffs, prompts, credentials or private keys from
Studio by default.

## Primary journeys

1. **Home:** see active changes and the next honest action; prepare or run work.
2. **Plans:** read the human proposal and machine contract, approve the exact
   snapshot, then run one requirement.
3. **Library:** find proven methods and evidence, suggest a method for the current
   task, apply it through governed work, and export an asset with provenance.
4. **Admin:** diagnose runtime and workspace state, inspect policy, preview safe
   cleanup, and configure local identity.
5. **Inbox, when configured:** import, verify, accept or decline a signed Cowork
   proposal. Imported content is inert until bound to a local SPEC.

## Safety boundary

The loopback browser API is typed and fixed-purpose. It never provides arbitrary
shell, filesystem or MCP relay. Safe projections exclude source, absolute paths,
repository URLs, full diffs, prompts, raw runner output, environment variables,
credentials, private keys and APatch session capabilities.

Local execution, review, recovery, evidence export and method reuse remain useful
without an account, subscription or network connection.

## Acceptance

| ID | Requirement | Level |
| --- | --- | --- |
| UX-1 | Studio reuses APatch as the sole governed runtime and evidence authority | MUST |
| UX-2 | Navigation exposes Home, Plans, Library and Admin, plus Inbox only when trust is configured | MUST |
| UX-3 | Every visible destination has a real action, state transition, result and recovery or honest no-action explanation | MUST |
| UX-4 | Home supports new change, exact requirement, live progress, cancellation, retry and recovery | MUST |
| UX-5 | Inbox verifies, previews and replay-protects signed proposals; import never starts work | MUST |
| UX-6 | Review separates technical proof, local notes and human acceptance | MUST |
| UX-7 | Plans expose RFP/SPEC lineage, coverage and exact requirement execution | MUST |
| UX-8 | Evidence exposes verification, coverage, provenance and bounded export | MUST |
| UX-9 | Library supports search, suggestion, governed use and provenance-preserving export | MUST |
| UX-10 | Admin exposes runtime diagnostics and safe cleanup without arbitrary execution | MUST |
| UX-11 | Policy changes are previewed, bounded, signed, verified and recoverable | MUST |
| UX-12 | Setup explains workspace, runtime, agent, trust and local identity state without hand-authored configuration | MUST |
| UX-13 | Every local journey remains usable without Cowork | MUST |
| UX-14 | APIs and projections enforce the local privacy boundary | MUST |
| UX-15 | Interaction, API, privacy, build and disposable-workspace tests prove behavior rather than label presence alone | MUST |

## Non-goals

- Organization membership, entitlement, fleet rollout or hosted persistence.
- Cloud source storage or a second requirements and evidence database.
- Inferring business acceptance, payment or accepted time from green tests.
- Executing an imported instruction before an exact local contract is accepted.
