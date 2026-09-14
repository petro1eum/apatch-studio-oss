# SPEC-STUDIO-OUTSIDE-IN-1 — APatch Studio Outside-In Experience

> **apatch artifact:** `spec:SPEC-STUDIO-OUTSIDE-IN-1`
> **Anchors:** RFP-007
> **Implementation state:** R0 freezes traceability. R1-R9 become attested only after their named product and interaction gates pass.

## R0 RFP traceability gate

| RFP id | SPEC Rk | Disposition |
|--------|---------|-------------|
| OUT-1 | R1 | covered |
| OUT-2 | R2 | covered |
| OUT-3 | R3 | covered |
| OUT-4 | R4 | covered |
| OUT-5 | R5 | covered |
| OUT-6 | R6 | covered |
| OUT-7 | R7 | covered |
| OUT-8 | R8 | covered |
| OUT-9 | R9 | covered |

The executable contract maps every mandatory RFP-007 outcome exactly once and preserves the outside-in privacy and authority boundaries.

(verify: python3 -m pytest tests/test_studio_outside_in_contract.py -q)

## R1 Change feed as Home

Home projects each durable Studio run as one change card containing the user's objective, live product-language status, safe delta, scope outcome, proof state and exactly one suggested next action. Review, delivery and proof are card drill-ins rather than parallel destinations.

(verify: python3 -m pytest tests/outside_in/test_change_feed.py -q)

## R2 Outside-in navigation and migration

Studio exposes Home, Plans, Library and Admin. Inbox is added only when signed
issuer trust is configured. Every legacy route has a deterministic canonical
redirect that preserves its capability and resource identifier.

(verify: python3 -m pytest tests/outside_in/test_navigation_contract.py -q)

## R3 Product vocabulary contract

A versioned machine-readable contract maps APatch protocol terms to human product language. CI rejects those protocol terms in primary navigation, actions and empty states while allowing full fidelity inside explicit proof surfaces and APIs.

(verify: python3 -m pytest tests/outside_in/test_vocabulary_contract.py -q)

## R4 Scope honesty

Change cards consume the existing APatch sandbox audit projection. They report requested scope, blocked and reverted out-of-scope write counts, and claim a clean scope only after an explicit clean audit. Browser projections contain bounded logical areas and counts, never source or raw repository paths.

(verify: python3 -m pytest tests/outside_in/test_scope_honesty.py -q)

## R5 One-field start and contextual recovery

Starting a change requires only the intended outcome. A working agent and acceptance default are selected automatically; optional requirement, agent and verification refinements are collapsed. Recovery and rollback appear only as actions on the affected failed change or backlog row.

(verify: python3 -m pytest tests/outside_in/test_start_contract.py -q)

## R6 Progressive proof disclosure

Primary cards show Proven, Needs re-check or Recorded. Exact requirement refs, operation ids, ledger records and delivery receipts are hidden by default and available in a labelled expandable Proof panel. Full local diff remains an explicit local-only action.

(verify: python3 -m pytest tests/outside_in/test_proof_disclosure.py -q)

## R7 First-run path

A workspace with no runs presents one primary action and no competing setup choices. Starting that request and receiving a successful governed result produces the first Proven change without consulting documentation.

(verify: python3 -m pytest tests/outside_in/test_first_run_journey.py -q)

## R8 Design and accessibility floor

Studio supports system, light and dark themes; persistent text is at least 11px; each action class has one stable icon; all destructive effects use bounded in-product confirmation dialogs; focus-visible and reduced-motion behavior remain enforced.

(verify: python3 -m pytest tests/outside_in/test_design_floor.py -q)

## R9 Outside-in release proof

Focused contract and interaction tests, a disposable first-run journey, the complete Python suite, production frontend build, and desktop/mobile browser QA prove the outside-in experience without weakening RFP-006 functionality or APatch governance.

(verify: python3 -m pytest tests/outside_in/test_outside_in_journey.py -q)
