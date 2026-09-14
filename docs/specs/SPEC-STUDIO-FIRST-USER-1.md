# SPEC-STUDIO-FIRST-USER-1 — SPEC-STUDIO-FIRST-USER-1 (scaffolded from RFP-014)

> **apatch artifact:** `spec:SPEC-STUDIO-FIRST-USER-1`
> **Anchors:** RFP-014
> _Scaffolded from RFP-014 acceptance by `apatch spec scaffold --from-contract`. Fill each `(verify:)` with a real command (one green test per requirement)._

## R0 RFP traceability gate (meta)

| RFP id | SPEC Rk | Disposition |
|--------|---------|-------------|
| FJ-1 | R1 | covered |
| FJ-2 | R2 | covered |
| FJ-3 | R3 | covered |
| FJ-4 | R4 | covered |
| FJ-5 | R5 | covered |
| FJ-6 | R6 | covered |
| FJ-7 | R7 | covered |
| FJ-8 | R8 | covered |

(verify: python3 -m pytest tests/first_user/test_contract.py -q)

## R1 Real Codex runner compatibility

(verify: python3 -m pytest tests/first_user/test_runner_operability.py -q -k 'argv or process')

## R2 Safe actionable runner failures

(verify: python3 -m pytest tests/first_user/test_runner_operability.py -q -k 'diagnostic or privacy')

## R3 Human action outcomes

(verify: python3 -m pytest tests/first_user/test_action_presentations.py -q)

## R4 Honest methods and verified time

(verify: python3 -m pytest tests/first_user/test_library_and_time.py -q)

## R5 Honest local administration

(verify: python3 -m pytest tests/actionable/test_settings_onboarding.py tests/runtime/test_runtime_requirements.py -q)

## R6 Honest signed Cowork Inbox

(verify: python3 -m pytest tests/actionable/test_inbox_workflow.py -q)

## R7 First-user product journey

(verify: python3 -m pytest tests/first_user/test_first_user_journey.py -q)

## R8 Multi-perspective release gate

(verify: python3 -m pytest tests/first_user -q && npm --prefix frontend run build)
