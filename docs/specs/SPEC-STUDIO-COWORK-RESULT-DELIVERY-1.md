# SPEC-STUDIO-COWORK-RESULT-DELIVERY-1

> **apatch artifact:** `spec:SPEC-STUDIO-COWORK-RESULT-DELIVERY-1`  
> **Anchors:** RFP-024

## R0 RFP traceability gate (meta)

| RFP id | SPEC Rk | Disposition |
| --- | --- | --- |
| SDR-1 | R1 | covered |
| SDR-2 | R2 | covered |
| SDR-3 | R3 | covered |
| SDR-4 | R4 | covered |
| SDR-5 | R5 | covered |

(verify: python3 -m pytest -q tests/result_delivery/test_contract.py::test_rfp_acceptance_is_fully_mapped)

## R1 Local result and evidence preparation

For one consumed, source-bound Cowork assignment, preview accepts only a non-empty
workspace-relative path whose every component is non-symlink and whose target is a
bounded regular file. It reads through a no-follow descriptor, derives SHA-256 and
size locally, builds signed APatch evidence for the record's exact source binding,
and makes zero HTTP/network mutations. Absolute paths, traversal, directories,
symlinks, oversized files, unbound assignments and foreign bindings fail closed.

(verify: python3 -m pytest -q tests/result_delivery/test_result_delivery.py::test_preview_is_local_bounded_and_uses_exact_source_binding)

## R2 Frozen disclosure and explicit consent

Preview returns one closed canonical plan binding intent, tenant, project, work
item hash/version, WorkProgram pin, source binding, connection generation, result
relative name/hash/size with content_shared=false, evidence bundle id/hash and
claimed active seconds. Submit accepts only relative_path, that exact plan and
`submit:<plan_hash>`; it recomputes current local state first. Any extra input,
changed file, plan, evidence, task pin or confirmation fails before publication.

(verify: python3 -m pytest -q tests/result_delivery/test_result_delivery.py::test_submit_requires_fresh_exact_disclosure_confirmation)

## R3 Signed APatch-to-Cowork round trip

After consent, Studio publishes only the previewed evidence plan, synchronizes it
to a signed Platform admission receipt, then makes the exact signed result-create
and result-submit requests with the enrolled workspace key. Both requests carry
the accepted task/program/version pins, create supplies only outcome hash and
admitted bundle id, and create/submit use distinct deterministic idempotency keys.
The returned receipts are scope-checked and contain only bounded safe fields.

(verify: python3 -m pytest -q tests/result_delivery/test_result_delivery.py::test_submission_publishes_evidence_then_creates_and_submits_release)

## R4 Minimal durable and retry-safe state

After a submitted receipt, Studio atomically persists only plan hash, outcome hash,
evidence bundle id/hash, release id/hash/state and update time in the intent ledger.
It never persists the result path or bytes. An exact retry after a lost local
response returns the same projection without another Platform mutation; conflicting
receipt state or plan hash fails closed.

(verify: python3 -m pytest -q tests/result_delivery/test_result_delivery.py::test_submitted_receipt_is_minimal_durable_and_retry_safe)

## R5 Human-complete Inbox surface

A source-bound consumed Inbox card contains a workspace-relative Result file field,
Prepare submission action, explicit list of disclosed and retained-local data,
exact consent text, Submit to Cowork action and bounded receipt. The frontend calls
only the preview/submit endpoints and never asks for an outcome hash, evidence id,
release id, credential, accept/reject decision or work-completion action.

(verify: python3 -m pytest -q tests/result_delivery/test_result_delivery_ui.py)

## RFP traceability

| RFP id | SPEC Rk | Disposition |
| --- | --- | --- |
| SDR-1 | R1 | covered |
| SDR-2 | R2 | covered |
| SDR-3 | R3 | covered |
| SDR-4 | R4 | covered |
| SDR-5 | R5 | covered |
