# SPEC-STUDIO-PROJECT-HOME-1 -- Comprehensible Project Home

> **apatch artifact:** `spec:SPEC-STUDIO-PROJECT-HOME-1`
> **Anchors:** RFP-009
> **Status:** Implementing

## R0 RFP traceability gate (meta)

| RFP id | SPEC Rk | Disposition |
|--------|---------|-------------|
| HOME-1 | R1 | covered |
| HOME-2 | R2 | covered |
| HOME-3 | R3 | covered |
| HOME-4 | R4 | covered |
| HOME-5 | R5 | covered |
| HOME-6 | R6 | covered |
| HOME-7 | R7 | covered |
| HOME-8 | R8 | covered |

(verify: python3 -m pytest tests/project_home/test_project_home_contract.py -q)

## R1 Project briefing

Home presents project identity, deterministic current state and plain-language project counts before history.

(verify: python3 -m pytest tests/project_home/test_project_home_projection.py::test_project_briefing_precedes_history -q)

## R2 One primary action

Home asks what the user wants to change and keeps runner, plan binding and verification options collapsed.

(verify: python3 -m pytest tests/project_home/test_project_home_ui.py::test_primary_action_is_plain_and_advanced_controls_are_collapsed -q)

## R3 Meaningful recent outcomes

The default projection returns no more than six substantive results and excludes attest-only imported records.

(verify: python3 -m pytest tests/project_home/test_project_home_projection.py::test_recent_outcomes_exclude_attest_only_records_and_are_bounded -q)

## R4 One result per project change

All requirement sessions of one SPEC collapse into one newest project-level result on Home while canonical per-session history remains unchanged.

(verify: python3 -m pytest tests/project_home/test_project_home_projection.py::test_one_spec_collapses_to_one_newest_project_result -q)

## R5 Human-facing result cards

Primary cards hide protocol anchors and use human titles and statuses while proof retains exact identifiers.

(verify: python3 -m pytest tests/project_home/test_project_home_ui.py::test_result_cards_hide_protocol_anchors_until_proof -q)

## R6 Progressive full history

One action reveals canonical history and selected deep links remain reachable even when outside the recent set.

(verify: python3 -m pytest tests/project_home/test_project_home_ui.py::test_full_history_and_deep_link_remain_reachable -q)

## R7 Deterministic current state

Current state follows the Working, Needs attention, Ready for review and Ready for a new change priority contract.

(verify: python3 -m pytest tests/project_home/test_project_home_projection.py::test_current_state_priority_is_deterministic -q)

## R8 Release journey

The full suite, production build and desktop/mobile browser checks prove comprehension without weakening governance.

(verify: python3 -m pytest tests/project_home/test_project_home_journey.py -q)
