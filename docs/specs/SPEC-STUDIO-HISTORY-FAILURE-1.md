# SPEC-STUDIO-HISTORY-FAILURE-1 — Usable history failure
> **apatch artifact:** `spec:SPEC-STUDIO-HISTORY-FAILURE-1`
> **Anchors:** RFP-025
> **ownership mode:** strict

## RFP traceability

| RFP id | SPEC Rk | Disposition |
|---|---|---|
| HF-1 | R1 | covered |
| HF-2 | R2 | covered |
| HF-3 | R3 | covered |
| HF-4 | R4 | covered |

Supplemental judge `tests/read_model/test_history_failure.py` was prepared and
signed before source implementation. The original 11 READ-INDEX tests and
their pinned bytes are not changed. No ledger recovery or publication is claimed.

## R1 Retry cache without a partial published generation

owns: apatch_studio/read_index.py

Retain successful parses and classified failures in disposable RAM keyed by
the exact file stamp. Scan every canonical object, reuse unchanged successes
and errors on Retry, and read only changed bytes after repair. A failed scan
must not advance generation or publish any partial row set. Prune removed
failures and keep valid source bytes unchanged.

(verify: python3 -m pytest tests/read_model/test_history_failure.py -k 'retry or removal' -q)

## R2 Bounded safe diagnostics

owns: apatch_studio/read_index.py, docs/specs/SPEC-STUDIO-HISTORY-FAILURE-1.md

Classify every invalid object as a count and a bounded list of 16 safe op ids,
SHA-256 byte digests and enum reasons. Never expose raw text, absolute paths,
exception messages or mutable internal diagnostic references. Failure remains
unavailable; no bad record is silently skipped. Removal/repair clears the
diagnostic. Implemented by the same R1 index mutation, not a marker file.
The owner authorized the exact R2 ownership declaration correction on
2026-10-04; acceptance commands and frozen test bytes remain unchanged.

(verify: python3 -m pytest tests/read_model/test_history_failure.py -k diagnostics -q)

## R3 Independent runtime and truthful failure projection

owns: apatch_studio/adapter.py

Preserve canonical lightweight runtime configuration separately from signed
history. The posture survives history failure and never invokes full doctor.
The failure projection exposes safe index diagnostics, never old attested
totals or old signed evidence as current. It does not grant execution authority.

(verify: python3 -m pytest tests/read_model/test_history_failure.py -k 'runtime or failed_refresh or diagnostic_is_projected' -q)

## R4 Reachable diagnostic and document views

owns: frontend/src/readModelVisibility.ts, frontend/src/OutsideInApp.tsx, frontend/src/OutsideInAdmin.tsx, frontend/src/types.ts

During building/unavailable keep Plans and Admin reachable. Replace unavailable
evidence views with an explanation and working links to Plans/Admin rather than
a blank main panel. Display bounded diagnostics in a technical-details disclosure.
Unknown protection must say not checked, not Audit. Execute the real navigation
helper via Node assertions. In addition to this gate, click the actual local
browser through failure, Admin, Plans and document detail before handoff.

(verify: python3 -m pytest tests/read_model/test_history_failure.py -k navigation -q)
