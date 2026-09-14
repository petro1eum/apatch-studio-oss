# SPEC-STUDIO-INTERACTIVE-CHANGE-1 -- Interactive Project Change

> **apatch artifact:** `spec:SPEC-STUDIO-INTERACTIVE-CHANGE-1`
> **Anchors:** RFP-010
> **Status:** Implementing

## R0 RFP traceability gate (meta)

| RFP id | SPEC Rk | Disposition |
|--------|---------|-------------|
| CHANGE-1 | R1 | covered |
| CHANGE-2 | R2 | covered |
| CHANGE-3 | R3 | covered |
| CHANGE-4 | R4 | covered |
| CHANGE-5 | R5 | covered |
| CHANGE-6 | R6 | covered |
| CHANGE-7 | R7 | covered |
| CHANGE-8 | R8 | covered |
| CHANGE-9 | R9 | covered |

(verify: python3 -m pytest tests/project_detail/test_interactive_change_contract.py -q)

## R1 Safe project identity

Home and detail expose safe repository, branch, upstream, head and local-operator context without credentials, email, raw remote URL or absolute path.

(verify: python3 -m pytest tests/project_detail/test_project_context.py -q)

## R2 Dedicated detail route

An exact Home resource route renders a dedicated change workspace above the fold instead of expanding canonical history.

(verify: python3 -m pytest tests/project_detail/test_change_detail_ui.py::test_deep_link_renders_dedicated_change_workspace -q)

## R3 Canonical detail projection

The authenticated local endpoint derives one exact change from existing signed APatch ledger entries and persists no secondary truth.

(verify: python3 -m pytest tests/project_detail/test_change_detail_projection.py::test_detail_is_derived_from_one_exact_ledger_session -q)

## R4 Safe recorded patches

Mutation detail exposes bounded traversal-safe repository-relative files and recorded patches with delta, mode, hash and truncation metadata.

(verify: python3 -m pytest tests/project_detail/test_change_detail_projection.py::test_recorded_patch_is_safe_bounded_and_complete -q)

## R5 Honest actor context

The detail distinguishes Studio runner, APatch signer and local operator without inferring authorship.

(verify: python3 -m pytest tests/project_detail/test_change_detail_ui.py::test_actor_roles_are_distinct_and_human_readable -q)

## R6 Verification-only records

Attest-only sessions identify themselves as verification checkpoints, state that no files changed and never offer an empty diff.

(verify: python3 -m pytest tests/project_detail/test_change_detail_projection.py::test_attestation_only_session_is_an_honest_checkpoint -q)

## R7 Real imported-change actions

Imported detail can return to changes, open its recorded patch locally and navigate to its exact backlog anchor when those actions apply.

(verify: python3 -m pytest tests/project_detail/test_change_detail_api.py -q)

## R8 Studio-run continuity

A Studio-managed run retains its review, retry, recovery, rollback-preview and delivery controls on the dedicated detail route.

(verify: python3 -m pytest tests/project_detail/test_change_detail_ui.py::test_studio_run_detail_retains_contextual_actions -q)

## R9 Release journey

Focused security, projection, API and UI tests plus full build and desktop/mobile browser checks prove the interactive workflow.

(verify: python3 -m pytest tests/project_detail/test_interactive_change_journey.py -q)
