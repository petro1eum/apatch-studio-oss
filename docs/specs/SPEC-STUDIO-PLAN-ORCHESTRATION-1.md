# SPEC-STUDIO-PLAN-ORCHESTRATION-1 — Fast and Observable Plan Preparation

> **apatch artifact:** `spec:SPEC-STUDIO-PLAN-ORCHESTRATION-1`
> **Anchors:** RFP-016
> **Implementation boundary:** Existing APatch RFP/SPEC/preparation/freeze contracts remain canonical.

## RFP traceability table

| RFP id | SPEC Rk | Disposition |
|--------|---------|-------------|
| FAST-1 | R1 | covered |
| FAST-2 | R2 | covered |
| FAST-3 | R3 | covered |
| FAST-4 | R4 | covered |
| FAST-5 | R5 | covered |
| FAST-6 | R6 | covered |
| FAST-7 | R7 | covered |
| FAST-8 | R8 | covered |
| FAST-9 | R9 | covered |

## R0 Contract coverage gate (meta)

The executable contract maps every RFP-016 acceptance exactly once, freezes all test modules before implementation and contains no placeholder command.

(verify: python3 -m pytest tests/plan_orchestration/test_plan_contract.py -q)

## R1 Bounded discovery path

Studio builds a private byte-bounded context capsule from concise allowlisted project documents, exact-lineage partial contracts and the existing preparation package, never application source or journal projection. The new-change prompt permits APatch doctor as the only pre-authoring tool call, gives collision-free run-owned RFP/SPEC identifiers, terminates the ninth structured inspection start, forbids partial `spec_scaffold`, creates a fresh complete package in one batch and repairs an existing exact-lineage scaffold through an exact R0 session, one mutation `apatch_execute_next` without `finalize`, continuation calls while `continue=true`, then one finalization call.

(verify: python3 -m pytest tests/plan_orchestration/test_prompt_and_runner.py tests/plan_orchestration/test_limits.py -q -k "bounded or discovery")

## R2 Latency-oriented planning profile

Codex planning uses the dedicated fast `gpt-5.6-luna` model with low reasoning effort. Ordinary implementation, recovery and rollback argv remain byte-compatible with their established configuration.

(verify: python3 -m pytest tests/plan_orchestration/test_prompt_and_runner.py -q -k latency_profile)

## R3 Safe structured progress

Runner event types and allowlisted APatch tool identities map to human planning stages while private command/source/path content cannot enter the projection.

(verify: python3 -m pytest tests/plan_orchestration/test_progress.py -q -k "structured or private")

## R4 Deduplicated freshness

Identical structured work events update last activity and event counters while the durable human timeline contains one stage transition.

(verify: python3 -m pytest tests/plan_orchestration/test_progress.py -q -k deduplicated)

## R5 Stall and timeout watchdog

A soft stall is projected after the configured no-event interval; the hard deadline terminates the exact process and returns retryable `plan_timeout`.

(verify: python3 -m pytest tests/plan_orchestration/test_limits.py -q -k "stall or timeout")

## R6 Fail-closed planning limits

Discovery exhaustion, timeout and missing handoff cannot become `plan_ready`, expose implementation actions or alter an application source sentinel.

(verify: python3 -m pytest tests/plan_orchestration/test_limits.py -q -k "discovery or source")

## R7 Exact cancellation, retry and privacy

Existing cancellation/retry ownership remains green. Every planning child receives one opaque run-owned APatch lane; timeout, cancellation and partial failure reconcile only that lane while pre-existing and sibling sessions remain untouched. A retry keeps the first attempt's exact RFP/SPEC identity in a fresh lane so valid partial work is completed rather than duplicated, but it must still write exactly one preparation-package revision attributable to the current run and may not use an empty mutation as completion. When attribution metadata is the only change, the retry mutates only the prepared package using byte-exact supplied JSON anchors and must not rewrite RFP/SPEC labels or guess unnecessary Markdown anchors. The run takes a private pre-start fingerprint baseline of sandbox findings and projects only newly observed violations; no path or fingerprint enters the journal or browser. The safe projection contains bounded stages, counters, timestamps and cleanup outcome only.

(verify: python3 -m pytest tests/test_agent_runs.py tests/plan_handoff/test_plan_attribution.py tests/plan_orchestration/test_progress.py tests/plan_orchestration/test_run_ownership.py -q -k "cancel or retry or safe_projection or private or owned_lane or cleanup")

## R8 Human planning budget UI

The running plan card shows elapsed time, last activity, remaining hard budget and Stop through a responsive human-language view.

(verify: python3 -m pytest tests/plan_orchestration/test_ui_contract.py -q && npm --prefix frontend run build)

## R9 Multi-perspective release gate

Focused planning tests, plan-handoff regressions, the complete Python suite and production frontend build pass before the same browser scenario is repeated. The generated RFP identifier remains paired to its SPEC so owner review shows complete decision links and each implementation requirement's exact proposal criterion.

(verify: python3 -m pytest tests/plan_orchestration tests/plan_handoff tests/actionable/test_work_workflow.py -q && python3 -m pytest tests/ -q && npm --prefix frontend run build)

## Non-goals

This SPEC does not implement a second planner, change APatch evidence truth, permit source work before owner freeze, or alter non-planning run budgets.
