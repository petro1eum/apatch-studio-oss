# RFP-025 — Usable Studio during a history-read failure

Implementation authorized by the owner on 2026-10-04 ("давай делать нормально").
This is a bounded follow-up to RFP-026, not publication approval or authority
to rewrite signed history. Original READ-INDEX acceptance bytes remain unchanged.
Contract: `docs/specs/SPEC-STUDIO-HISTORY-FAILURE-1.md`.

## Problem and value

A corrupt historical object currently hides Admin, makes the protection mode
look unknown, and forces another full archive read on Retry. The user needs
documents and diagnostics without a fabricated ready/evidence state.

## Source policy and exact allowlist

Implementation may change only `apatch_studio/read_index.py`,
`apatch_studio/adapter.py`, `frontend/src/OutsideInApp.tsx`,
`frontend/src/OutsideInAdmin.tsx`, `frontend/src/types.ts`, and create
`frontend/src/readModelVisibility.ts`.
Supplemental judge: `tests/read_model/test_history_failure.py`.
Prepare and sign this judge before implementation; never weaken the original
`tests/read_model/test_read_index.py` (SHA-256
`cbcf36b4925ed5488dcf8f0771be7545f797a84581a35f100e865d8b3611b5df`).
No changes to Agent source, ledger bytes, keys, other agent's dirty work,
production, package versions, or publication.

## Acceptance

| ID | Criterion | Level |
|---|---|---|
| HF-1 | Failed scans retain disposable parse/error caches in RAM, not a partially published generation. Retry reads no unchanged objects; repairing one object reads only that object and publishes all rows atomically. Removed failures disappear without rewriting valid bytes. | MUST |
| HF-2 | Report all failures as a count plus at most 16 safe object ids, byte digests and enum reasons. No raw payload, exception text, absolute path or mutable internal diagnostic leaks; history never becomes ready from skipping bad records. | MUST |
| HF-3 | Canonical lightweight runtime configuration remains independently available after a ledger failure, never invokes full doctor, and failed refreshes never present old signed evidence as current. | MUST |
| HF-4 | Plans and Admin remain reachable during building/unavailable. Other evidence views show an explicit explanation and working navigation instead of an empty screen. Unknown protection is never labeled Audit. Verify the navigation function with executed Node assertions and click the real local app. | MUST |

## Limits and data incident

The cache remains process-local and rebuilds on restart. It grants no writer
authority and never changes APatch admission or verification semantics.
Known invalid Agent objects: op_163372, op_163377, op_163382, op_163400.
Available release/archive copies checked on 2026-10-04 have identical bad bytes;
no recovery from them is claimed. Do not delete, normalize, re-sign or silently
skip these objects to report success. Original recovery needs independently
verified canonical bytes.
