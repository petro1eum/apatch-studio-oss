# SPEC-STUDIO-ACTIONABLE-UX-1 — Actionable Studio OSS workspace

> **apatch artifact:** `spec:SPEC-STUDIO-ACTIONABLE-UX-1`
> **Anchors:** RFP-005

## R0 RFP traceability gate (meta)

| RFP id | SPEC Rk | Disposition |
| --- | --- | --- |
| UX-1 | R1 | covered |
| UX-2 | R2 | covered |
| UX-3 | R3 | covered |
| UX-4 | R4 | covered |
| UX-5 | R5 | covered |
| UX-6 | R6 | covered |
| UX-7 | R7 | covered |
| UX-8 | R8 | covered |
| UX-9 | R9 | covered |
| UX-10 | R10 | covered |
| UX-11 | R11 | covered |
| UX-12 | R12 | covered |
| UX-13 | R13 | covered |
| UX-14 | R14 | covered |
| UX-15 | R15 | covered |

(verify: python3 -m pytest tests/oss_publication/test_publication_contract.py::test_readme_describes_the_real_product_and_uses_public_links -q)

## R1 Canonical APatch boundary

All project state and mutations derive from the installed public APatch runtime;
Studio stores only its bounded local presentation and workflow records.

(verify: python3 -m pytest tests/actionable/test_apatch_runtime_boundary.py -q)

## R2 Consolidated navigation

Expose Home, Plans, Library and Admin. Expose Inbox only when signed-intent trust is
configured. Do not publish Team or Fleet destinations.

(verify: python3 -m pytest tests/actionable/test_functional_tabs.py tests/actionable/test_navigation_migration.py -q)

## R3 Functional destinations

Every visible destination provides a primary action, durable state transition,
terminal presentation and recovery or a truthful no-action explanation.

(verify: python3 -m pytest tests/outside_in/test_outside_in_journey.py -q)

## R4 Governed work

Support new change, exact requirement, observable run, cancellation, retry,
fix-forward and recovery without bypassing APatch admission.

(verify: python3 -m pytest tests/actionable/test_work_workflow.py tests/first_user/test_runner_operability.py -q)

## R5 Signed Cowork Inbox

Verify issuer, signature, expiry and replay state before preview. Import is inert;
an explicit local decision binds the proposal to one exact local contract.

(verify: python3 -m pytest tests/actionable/test_inbox_workflow.py -q)

## R6 Local review

Expose verification, proof, local diff handoff, bounded reviewer notes, retry,
recovery and rollback preview while keeping business acceptance separate.

(verify: python3 -m pytest tests/actionable/test_review_workflow.py -q)

## R7 Plans and requirements

Expose RFP/SPEC lineage, requirement text, meaningful coverage and exact governed
execution. Missing live coverage is unknown, never fabricated green progress.

(verify: python3 -m pytest tests/actionable/test_specs_workflow.py tests/outside_in/test_scope_honesty.py -q)

## R8 Evidence

Expose local verification history, signatures, provenance, coverage and bounded
export without source-bearing data.

(verify: python3 -m pytest tests/actionable/test_evidence_workflow.py -q)

## R9 Method library

Support search, task-specific suggestion, governed use and export. Opening an asset
does not record reuse; only an explicit governed application does.

(verify: python3 -m pytest tests/actionable/test_assets_workflow.py -q)

## R10 Runtime administration

Expose local runtime health, diagnostics, hygiene and confirmation-gated cleanup.

(verify: python3 -m pytest tests/closure/test_overview_hygiene.py tests/runtime/test_runtime_requirements.py -q)

## R11 Policies

Policy changes use bounded forms and support preview, signature, verification,
application and recovery.

(verify: python3 -m pytest tests/actionable/test_policies_workflow.py -q)

## R12 Setup and local identity

Explain workspace, APatch, agent, trust and local machine identity state with one
safe next step and no secret-bearing browser projection.

(verify: python3 -m pytest tests/actionable/test_settings_onboarding.py tests/local_identity -q)

## R13 Offline-complete OSS

Home, Plans, Library, Admin, local execution, review, recovery and export work
without Cowork configuration or an account.

(verify: python3 -m pytest tests/first_user/test_first_user_journey.py tests/actionable/test_state_containment.py -q)

## R14 Fixed-purpose privacy boundary

Reject arbitrary command, file and MCP relays. Exclude source, paths, diffs,
prompts, transcripts, environment, credentials, keys and session capabilities.

(verify: python3 -m pytest tests/actionable/test_api_privacy_boundary.py tests/test_security.py -q)

## R15 Release proof

The complete Python suite, production frontend build and installed-wheel smoke must
all pass for the exact public candidate.

(verify: python3 -m pytest tests/oss_publication -q)
