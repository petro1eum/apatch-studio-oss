# RFP-014 -- APatch Studio First-User Operability Gate

> **Status:** Approved for implementation
> **Owner:** APatch Studio
> **Date:** 2026-09-01
> **Depends on:** RFP-005, RFP-007, RFP-013; APatch runtime 0.8.40 or newer
> **Observed reality:** REC-ea73c3c7a55c
> **Executable contract:** docs/specs/SPEC-STUDIO-FIRST-USER-1.md

## 1. Decision

APatch Studio already has governed execution, plans, proof, delivery packs,
verified-time drafts and signed external-work intake. The owner walkthrough found
that several existing capabilities could not be completed or understood through
the shipped application. This RFP closes those integration regressions; it does
not create a new runtime or a parallel source of truth.

## 2. User outcome

A first user can start a real local Codex run, understand proof and administrative
actions without reading wire JSON, distinguish reusable methods from reference-only
records, interpret time verification honestly and understand whether signed Cowork
intake is configured.

## 3. Safety and product boundaries

- Studio continues to invoke allowlisted local runners with APatch governance and automatic approval review; it never bypasses sandbox or APatch.
- Raw runner output, source, prompts, paths, credentials and secrets are not persisted or projected.
- Human summaries are derived from the same APatch action receipt; technical JSON remains available through progressive disclosure.
- A local process is never represented as an organization control plane. Signed
  external work remains unavailable until exact issuer trust is configured.
- Timesheet output remains an estimate and a draft. Signature coverage and ledger drift are separate facts; neither implies accepted time.

## 4. Verification contract

Implementation begins only after deterministic regression tests exist. The runner
test must execute a parser-compatible fake Codex binary through the real
RunnerCatalog and AgentRunManager, reject conflicting CLI flags, and prove a
structured completion event is consumed. API tests cover positive,
unavailable-provider, invalid-input and idempotent paths. Frontend tests assert
product-language summaries and configured action reachability; the production
build and an owner browser pass cover local work and signed Inbox.

## Acceptance

| Id | Requirement | Level |
|---|---|---|
| FJ-1 | The actual Codex argv used by Studio is accepted by current Codex CLI semantics, retains automatic approval review, contains no approval or sandbox bypass, and a deterministic process-level regression proves a local run progresses beyond launch | MUST |
| FJ-2 | A nonzero runner exit produces one safe actionable cause when Studio can classify it, while arbitrary runner output remains absent from every persisted and browser-visible projection | MUST |
| FJ-3 | Runtime, proof, cleanup and rule actions present a product-language outcome and next step before optional technical JSON; selected proof scope is not misrepresented | MUST |
| FJ-4 | Reference-only WorkAssets do not render a disabled primary action, reusable assets remain runnable, and verified-time failure distinguishes unsigned audit history from ledger drift and accepted time | MUST |
| FJ-5 | Admin runs local diagnostics, reports machine identity honestly and never offers organization-only controls | MUST |
| FJ-6 | Inbox explains whether issuer trust is configured, imports only verified signed proposals and never implies that local runs are organization-wide data | MUST |
| FJ-7 | The Home primary action says whether it will prepare a governed plan or execute an exact requirement, and the completed browser journey covers start, proof, time, acceptance review and signed Inbox | MUST |
| FJ-8 | Focused tests include positive, negative, boundary and regression perspectives; the complete Python suite and frontend production build remain green | MUST |

## Non-goals

This RFP does not weaken APatch governance, add arbitrary browser-to-MCP access,
accept business work automatically, embed a Cowork control plane into Studio, or
claim that an unconfigured local process provides organization-wide data.
