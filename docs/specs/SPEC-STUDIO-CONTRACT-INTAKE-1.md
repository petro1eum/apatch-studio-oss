# SPEC-STUDIO-CONTRACT-INTAKE-1 — SPEC-STUDIO-CONTRACT-INTAKE-1 (scaffolded from RFP-025)

> **apatch artifact:** `spec:SPEC-STUDIO-CONTRACT-INTAKE-1`  
> **Anchors:** RFP-025  
> **Status:** proposed API package, exact owner freeze pending; browser acceptance is still open.  
> **ownership mode:** strict
> _Scaffolded from RFP-025 acceptance by `apatch spec scaffold --from-contract`. Fill each `(verify:)` with a real command (a real behavioral gate per requirement; current baseline is intentionally RED)._

## R0 RFP traceability gate (meta)

owns: docs/specs/SPEC-STUDIO-CONTRACT-INTAKE-1.md

| RFP id | SPEC Rk | Disposition |
|--------|---------|-------------|
| STINT-1 | R1 | covered |
| STINT-2 | R2 | covered |
| STINT-3 | R3 | covered |
| STINT-4 | R4 | covered |
| STINT-5 | R5 | covered |

(verify: env PYTHONPATH=/Users/edcher/Documents/GitHub/_codex/apatch-source-intake-20260923/apatch /Users/edcher/Documents/GitHub/apatch-studio-oss/.venv/bin/python -m apatch.cli spec lint --spec SPEC-STUDIO-CONTRACT-INTAKE-1 --json)

## R1 GET/POST /api/v1/contract-intake/{spec_id} are available through crea…

owns: apatch_studio/contract_intake_workflow.py, apatch_studio/app.py

GET/POST /api/v1/contract-intake/{spec_id} are available through create_app. POST accepts only request_id, rfp_id, actor_id, reason and exact path/content files. It calls the real candidate Core, returns awaiting_approval plus its sealed review, stores local immutable review history (no target writes until approval), and creates no agent run, active grant, lock, source mutation or contract switch. IDs are retained.

(verify: env PYTHONPATH=/Users/edcher/Documents/GitHub/_codex/apatch-source-intake-20260923/apatch /Users/edcher/Documents/GitHub/apatch-studio-oss/.venv/bin/python -m pytest tests/authoring/test_contract_intake_api.py -k http_review -q)

## R2 POST /api/v1/contract-intake/{spec_id}/approve accepts only request_i…

owns: apatch_studio/contract_intake_workflow.py

POST /api/v1/contract-intake/{spec_id}/approve accepts only request_id, confirmed:true and the exact snapshot. Studio resolves the existing certified enrolled owner from identity_root, never from request data, then uses the native Core transaction. Completion remains preparation-only and requires later owner freeze.

(verify: env PYTHONPATH=/Users/edcher/Documents/GitHub/_codex/apatch-source-intake-20260923/apatch /Users/edcher/Documents/GitHub/apatch-studio-oss/.venv/bin/python -m pytest tests/authoring/test_contract_intake_api.py -k 'owner_approval or owner_enrollment' -q)

## R3 Retrying a request ID with identical inputs is idempotent across adap…

owns: apatch_studio/contract_intake_workflow.py

Retrying a request ID with identical inputs is idempotent across adapter recreation; changed reuse conflicts, even after a later request. A later proposal archives the previous review. A stale snapshot and a review copied to another SPEC/workspace are denied without writes or signing.

(verify: env PYTHONPATH=/Users/edcher/Documents/GitHub/_codex/apatch-source-intake-20260923/apatch /Users/edcher/Documents/GitHub/apatch-studio-oss/.venv/bin/python -m pytest tests/authoring/test_contract_intake_api.py -k 'replay or reused or revised or copied' -q)

## R4 Existing loopback session and same-origin guards apply to every new e…

owns: apatch_studio/contract_intake_workflow.py

Existing loopback session and same-origin guards apply to every new endpoint. Unknown keys, caller-selected authority/certification/role, false confirmation, and malformed snapshots are rejected. Missing/old Core is an explicit 503, not approval, a runner fallback or a green status.

(verify: env PYTHONPATH=/Users/edcher/Documents/GitHub/_codex/apatch-source-intake-20260923/apatch /Users/edcher/Documents/GitHub/apatch-studio-oss/.venv/bin/python -m pytest tests/authoring/test_contract_intake_api.py -k 'security or request or old_core' -q)

## R5 Native end-to-end API qualification uses real generated fixture keys…

owns: apatch_studio/contract_intake_workflow.py

Native end-to-end API qualification uses real generated fixture keys and actual signed receipts, not a monkeypatched Core approval. Uncertified or foreign enrolled owner, profile/judge/input drift and a planted symlink store fail closed. Existing authoring, locked-judge and endpoint security tests remain intact.

(verify: env PYTHONPATH=/Users/edcher/Documents/GitHub/_codex/apatch-source-intake-20260923/apatch /Users/edcher/Documents/GitHub/apatch-studio-oss/.venv/bin/python -m pytest tests/authoring/test_contract_intake_api.py tests/authoring/test_studio_authoring.py tests/sdd/test_sdd_owner_execution_flow.py tests/test_security.py -q)
