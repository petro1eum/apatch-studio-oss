# RFP-011 -- APatch Studio Project Knowledge and Decision Workspace

> **Status:** Approved for implementation
> **Owner:** APatch Studio
> **Date:** 2026-09-01
> **Depends on:** RFP-007, RFP-009, RFP-010
> **Executable contract:** docs/specs/SPEC-STUDIO-PROJECT-KNOWLEDGE-1.md
> **Evidence source:** owner rejection of the live RFP-010 walkthrough because the product exposed machine records without readable project, RFP, SPEC or decision context

## 1. Decision

APatch Studio is not a usable spec-driven development product while it presents counts, hashes and signed records without letting a developer read the proposal, executable requirements and reasons that justify a result.

Studio adds a human-readable Project Knowledge and Decision Workspace. It makes repository-owned README, RFP and SPEC documents first-class local product objects and links them to the existing APatch execution and evidence chain. APatch remains the sole authority for requirement status, verification and attestation. Studio renders that authority in language a developer can understand.

This supersedes the RFP-010 assumption that navigating to a highlighted backlog row is sufficient context. The row is only an index entry; the user must be able to open the actual plan and its decision basis.

## 2. User jobs

A developer opening Studio must first understand what project is open and what is it for, then answer the remaining questions without documentation or protocol knowledge:

1. What project is open and what is it for?
2. What proposals and executable plans exist?
3. What does each requirement actually say?
4. Which requirements are complete, pending or need another check?
5. Why is a result marked proven?
6. Which proposal acceptance criterion does the result satisfy?
7. What can I do next: read, run, re-check, review or return?

A screen that answers only with IDs, counters, hashes or tool output fails these jobs even when those values are correct.

## 3. Project briefing

Home presents a bounded project briefing derived from the repository README and safe Git identity. It contains the project name, a plain-language purpose, repository slug, branch and local operator. It does not present a folder name and requirement counters as a sufficient project description.

README is repository-owned content. Studio reads it locally on demand, bounds its size and renders only safe text structure. It does not invent a product purpose when no README is present; it states that the project description is missing and offers the document workspace.

## 4. Plans and proposals

Backlog becomes the project's Plans surface rather than a list of opaque SPEC counters.

The default view lists proposal/specification pairs with human titles, purpose, status, progress and a clear Open plan action. A plan detail shows:

- the linked RFP proposal and its decision;
- the executable SPEC and every requirement statement;
- current APatch-derived state for each requirement;
- the acceptance criterion mapped to each requirement;
- the verification basis and latest proof outcome;
- contextual Run, Re-check or Inspect proof actions.

RFP and SPEC source remains in versioned repository files. Studio persists no second document database and never edits a document through an ungoverned browser write.

## 5. Readable document contract

Studio exposes allowlisted, session-guarded local read endpoints for discovered repository documents only. A caller selects a canonical document ID, never an arbitrary path.

Markdown is parsed through a structured parser into bounded headings, paragraphs, lists, tables, quotes and code blocks. The primary UI renders those blocks as product content, not raw Markdown or JSON. Source paths, absolute paths, HTML, scripts and external resource loading are not projected.

RFP detail emphasizes Decision, observed problem, acceptance criteria and non-goals. SPEC detail emphasizes requirement statements, current state and verification basis. Full source fidelity may be available in a local technical export later, but is not the primary reader.

## 6. Decision lineage

Studio makes the existing lineage visible in both directions:

```
RFP acceptance criterion
  -> SPEC requirement
  -> governed change/checkpoint
  -> verification result
  -> signed proof
```

The mapping comes from repository RFP/SPEC traceability and APatch coverage. Studio does not infer acceptance from filenames or prose similarity. Missing or ambiguous links are shown as missing context, never silently guessed.

Primary labels use human titles and outcomes. Canonical IDs, document hashes, session IDs, signer keys and verification commands remain available in an expandable technical audit.

## 7. Result explanation

Every imported change or verification checkpoint with a SPEC anchor shows a Decision basis section before technical proof. It contains:

- the requirement title and statement;
- whether it changed code or verified existing state;
- the linked proposal and acceptance criterion when mapped;
- the verification outcome that supports Proven;
- direct actions to View specification and View proposal.

“Proven” means the exact requirement's configured verification passed and APatch recorded proof. It does not mean business acceptance, code quality beyond the configured check, or human approval unless a separate authority decision exists.

## 8. Interactions

The first release supports real navigation and contextual actions:

- Open project plans from Home or Backlog.
- Open a proposal and read its complete structured decision.
- Open a specification and read all requirements.
- Expand one requirement to see its statement, acceptance mapping and verification basis.
- Run the exact pending requirement with an available local agent.
- Re-check stale requirements through the existing APatch operation.
- Navigate from a result to its exact specification and proposal.
- Return from every detail to the previous human-facing list.

Raw operation payloads are not substituted for any of these actions.

## 9. Privacy and authority

All project documents and decision lineage remain local unless the user explicitly exports them through a separate bounded feature. The browser receives only content from allowlisted repository documents and existing safe APatch projections.

Studio does not become a second SPEC state store, approval engine, source control system or document editor. It does not claim that APatch proof equals business acceptance. It does not expose arbitrary file reads, raw filesystem paths, shell commands, MCP relay, credentials, prompts or secrets.

## 10. Release proof

Release qualification requires document discovery and path-confusion tests, structured Markdown parser tests, exact traceability tests, session-guarded API tests, project briefing tests, RFP and SPEC reader interaction tests, result-to-basis navigation tests, full Python suite, frontend production build and desktop/mobile browser walkthroughs on both an implementation change and a verification-only checkpoint.

## Acceptance

| Id | Requirement | Level |
|---|---|---|
| KNOW-1 | Home explains what project is open and what it is for using bounded repository-owned briefing content plus safe Git identity | MUST |
| KNOW-2 | Plans lists every discovered RFP/SPEC pair with human title, purpose, current state, progress and an Open plan action | MUST |
| KNOW-3 | A user can open and read a structured RFP decision, problem, acceptance criteria and non-goals without raw Markdown, JSON or filesystem paths | MUST |
| KNOW-4 | A user can open and read a structured SPEC with every requirement statement, current APatch-derived state and verification basis | MUST |
| KNOW-5 | Exact traceability links RFP acceptance criteria to SPEC requirements in both directions and reports missing or ambiguous links honestly | MUST |
| KNOW-6 | Every SPEC-linked result explains why it is proven using requirement text, mapped acceptance criterion, verification outcome and direct proposal/specification links | MUST |
| KNOW-7 | Plan and requirement details provide real contextual Open, Run, Re-check, Inspect proof and Back actions without arbitrary browser commands | MUST |
| KNOW-8 | Machine IDs, hashes, signer keys and raw verification commands appear only in expandable technical audit while primary content uses human language | MUST |
| KNOW-9 | Document APIs accept canonical discovered IDs only, remain loopback/session guarded, bound content and prevent traversal, HTML/script execution and external loading | MUST |
| KNOW-10 | Focused parser, traceability, API and UI journeys plus full suite, production build and desktop/mobile checks prove the knowledge workspace | MUST |

## Non-goals

This RFP does not add a cloud document store, WYSIWYG editor, generic repository browser, second requirement database, second approval authority, automatic business acceptance, arbitrary Markdown HTML, external image fetching, browser shell or MCP proxy. It does not change APatch ledger bytes, Change/SPEC/Rk semantics, TrustChain contracts or ContributionEvent.
