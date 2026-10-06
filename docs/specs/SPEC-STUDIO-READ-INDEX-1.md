# SPEC-STUDIO-READ-INDEX-1 — Incremental workspace projection

> **apatch artifact:** `spec:SPEC-STUDIO-READ-INDEX-1`
> **Anchors:** RFP-026
> **ownership mode:** strict

## RFP traceability

| RFP id | SPEC Rk | Disposition |
|---|---|---|
| READ-1 | R1 | covered |
| READ-2 | R2 | covered |
| READ-3 | R3 | covered |
| READ-4 | R4 | covered |
| READ-5 | R5 | covered |
| READ-6 | R6 | covered |

## R1 Incremental canonical ledger reads

owns: apatch_studio/read_index.py, apatch_studio/ledger_events.py, tests/read_model/test_read_index_collisions.py, docs/specs/SPEC-STUDIO-READ-INDEX-1.md

For one Studio process retain canonical rows by source object path and exact
size, inode, mtime and ctime. Every refresh detects append, replacement and
deletion. Unchanged archive files are never parsed again. Concurrent calls
observe one complete generation, never a half-applied delta.

Equal stat metadata is not proof that the content is unchanged: an in-place,
same-size write within filesystem timestamp resolution must invalidate the
one changed object's cached parse and derived membership. Previously published
rows remain unchanged. A same-stamp corruption is visibly unavailable, and a
same-stamp repair is retryable. Existing immutable incremental, concurrency,
no-full-audit and no-ledger-copy judges remain mandatory. Do not compensate by
sleeping, reparsing unchanged archive objects, weakening tests or concealing
content reads through a different API.

(verify: python3 -m pytest tests/read_model/test_read_index.py tests/read_model/test_read_index_collisions.py -k incremental -q)

## R2 Preserve canonical artifact semantics

owns: apatch_studio/read_index.py

Resolve membership using the APatch traceability index. Keep predecessor
context for legacy records with inherited artifacts and all global judge
amendment/SDD attestation records needed by selective invalidation. Invoke
canonical APatch coverage on the resulting bounded subset.

(verify: python3 -m pytest tests/read_model/test_read_index.py -k membership -q)

## R3 Lightweight runtime posture

owns: apatch_studio/read_index.py

Read canonical APatch policy, anchor, MCP/writer and hygiene views without
running full doctor on overview. The explicit doctor workflow remains intact.

(verify: python3 -m pytest tests/read_model/test_read_index.py -k posture -q)

## R4 Coherent freshness and failure

owns: apatch_studio/read_index.py, apatch_studio/adapter.py

A malformed object cannot produce a ready snapshot. Source drift is still
computed by APatch from live bytes. Coalesce concurrent builds and retain
atomic old/new generations internally.

(verify: python3 -m pytest tests/read_model/test_read_index.py -k 'corrupt or concurrent or drift' -q)

## R5 Usable first opening

owns: apatch_studio/adapter.py

A nonblocking adapter returns a content-safe building projection while one
worker builds the index, then ready data. Failure exposes unavailable and can
retry. Background activity never starts agent execution or acquires writer
authority.

(verify: python3 -m pytest tests/read_model/test_read_index.py -k opening -q)

## R6 Privacy and UI continuity

owns: apatch_studio/read_index.py, apatch_studio/adapter.py

No disk copy of the ledger is created. The UI polls while indexing and shows
the indexing/failure state. Existing request guards, safe projection and
coverage regressions remain intact.

(verify: python3 -m pytest tests/read_model/test_read_index.py tests/test_security.py tests/test_projection.py tests/closure/test_stale_projection.py -q)

