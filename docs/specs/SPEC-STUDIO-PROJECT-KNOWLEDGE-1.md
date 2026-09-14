# SPEC-STUDIO-PROJECT-KNOWLEDGE-1 -- Project Knowledge and Decision Workspace

> **apatch artifact:** `spec:SPEC-STUDIO-PROJECT-KNOWLEDGE-1`
> **Anchors:** RFP-011
> **Status:** Implementing

## R0 RFP traceability gate (meta)

| RFP id | SPEC Rk | Disposition |
|--------|---------|-------------|
| KNOW-1 | R1 | covered |
| KNOW-2 | R2 | covered |
| KNOW-3 | R3 | covered |
| KNOW-4 | R4 | covered |
| KNOW-5 | R5 | covered |
| KNOW-6 | R6 | covered |
| KNOW-7 | R7 | covered |
| KNOW-8 | R8 | covered |
| KNOW-9 | R9 | covered |
| KNOW-10 | R10 | covered |

(verify: python3 -m pytest tests/project_knowledge/test_project_knowledge_contract.py -q)

## R1 Project briefing

Home derives a bounded plain-language project purpose from repository-owned README content and presents it with safe repository, branch and local-operator identity.

(verify: python3 -m pytest tests/project_knowledge/test_project_briefing.py -q)

## R2 Plans catalog

Plans pairs every discovered RFP and executable SPEC and presents a human title, purpose, state, progress and an explicit Open plan action.

(verify: python3 -m pytest tests/project_knowledge/test_document_catalog.py -q)

## R3 Proposal reader

A fixed-purpose local reader renders each RFP's decision, observed problem, acceptance criteria and non-goals as bounded structured content without raw Markdown, JSON or filesystem paths.

(verify: python3 -m pytest tests/project_knowledge/test_document_reader.py -q)

## R4 Executable plan reader

The specification reader exposes every requirement statement, current APatch-derived state and verification basis while keeping protocol details progressively disclosed.

(verify: python3 -m pytest tests/project_knowledge/test_spec_reader.py -q)

## R5 Exact decision lineage

RFP acceptance IDs and SPEC requirement IDs are linked from explicit traceability tables in both directions; missing, duplicate or ambiguous links are reported and never guessed.

(verify: python3 -m pytest tests/project_knowledge/test_traceability.py -q)

## R6 Result decision basis

Every SPEC-linked result places requirement text, mapped proposal criterion and verification outcome before technical proof and links directly to the proposal and specification readers.

(verify: python3 -m pytest tests/project_knowledge/test_change_decision_basis.py -q)

## R7 Contextual actions

Plan and requirement views provide bounded Open, Run, Re-check, Inspect proof and Back actions using existing Studio workflows rather than arbitrary browser commands.

(verify: python3 -m pytest tests/project_knowledge/test_document_actions.py -q)

## R8 Human-first language

Primary project, plan and result surfaces use user goals and outcomes; machine IDs, hashes, signer keys and raw verification commands remain inside an expandable technical audit.

(verify: python3 -m pytest tests/project_knowledge/test_product_language.py -q)

## R9 Bounded document API

Session-guarded loopback APIs accept only canonical discovered document IDs, bound content and reject traversal, raw paths, executable HTML/script and external resource loading.

(verify: python3 -m pytest tests/project_knowledge/test_document_api.py -q)

## R10 Release journey

Focused parser, traceability, API and UI journeys, the full suite, production build and desktop/mobile walkthroughs prove that a developer can understand and act on one project without protocol knowledge.

(verify: python3 -m pytest tests/project_knowledge/test_project_knowledge_journey.py -q)
