# RFP-025 — Studio fixed-identity contract intake

> **apatch artifact:** `rfp:RFP-025`
> **Status:** proposed exact test contract, 2026-10-05; owner freeze is pending.

## Objective

Expose Core's owner-reviewed preparation transaction in APatch Studio without
allocating replacement RFP-STUDIO/SPEC-STUDIO IDs, starting a model runner,
borrowing an unrelated release or replacing the active frozen profile.

This first implementation package qualifies the real ASGI/HTTP adapter. The owner
interface is also required for the complete workflow, but browser behavior is
not qualified by API tests; its executable browser package must be reviewed
before the interface is accepted. Neither package claims HOST implementation.

## Acceptance

| ID | Level | Criterion |
|---|---|---|
| STINT-1 | MUST | GET/POST /api/v1/contract-intake/{spec_id} are available through create_app. POST accepts only request_id, rfp_id, actor_id, reason and exact path/content files. It calls the real candidate Core, returns awaiting_approval plus its sealed review, stores local immutable review history (no target writes until approval), and creates no agent run, active grant, lock, source mutation or contract switch. IDs are retained. |
| STINT-2 | MUST | POST /api/v1/contract-intake/{spec_id}/approve accepts only request_id, confirmed:true and the exact snapshot. Studio resolves the existing certified enrolled owner from identity_root, never from request data, then uses the native Core transaction. Completion remains preparation-only and requires later owner freeze. |
| STINT-3 | MUST | Retrying a request ID with identical inputs is idempotent across adapter recreation; changed reuse conflicts, even after a later request. A later proposal archives the previous review. A stale snapshot and a review copied to another SPEC/workspace are denied without writes or signing. |
| STINT-4 | MUST | Existing loopback session and same-origin guards apply to every new endpoint. Unknown keys, caller-selected authority/certification/role, false confirmation, and malformed snapshots are rejected. Missing/old Core is an explicit 503, not approval, a runner fallback or a green status. |
| STINT-5 | MUST | Native end-to-end API qualification uses real generated fixture keys and actual signed receipts, not a monkeypatched Core approval. Uncertified or foreign enrolled owner, profile/judge/input drift and a planted symlink store fail closed. Existing authoring, locked-judge and endpoint security tests remain intact. |

## Owner interface follow-through

The complete feature must offer Import prepared contract from Plans, accept the
existing fixed IDs and a local JSON array of exact files, show the exact Core
review including every diff/hash/operation and preserved active contract, then
require a separate explicit owner confirmation of that snapshot.

There must be no auto-approval on import, no runner/provider selector, no
HTML execution from document contents, no false feature acceptance, and no
implicit navigation to implementation after approval. A visible error keeps
the reviewed data available. Existing pending reviews must remain visible after
reopening Studio. Browser acceptance is an open, separate qualification gate,
not silently waived by this ASGI package.

## Exact implementation surface for the API package

CREATE `apatch_studio/contract_intake_workflow.py`.
EDIT `apatch_studio/app.py` only for import and route installation.
Do not rewrite the user's dirty authoring_workflow.py, sdd_workflow.py,
contract_recovery.py or existing round-trip/resume tests.

Judges: `tests/authoring/test_contract_intake_api.py` and
`tests/authoring/contract_intake_fixture.py`.
UI source and browser judges will be explicitly added in the interface package,
not mutated under this API-only allowlist.

## Qualification environment

Use the reviewed candidate Core source, not the older installed wheel. Report
which Core/Studio commits and interpreter were tested. All test state, keys,
leases and owner enrollment live under disposable pytest tmp_path; no actual
consumer profile or owner's key is changed.
