# RFP-026 — Incremental Studio workspace read model

Status: approved for implementation by the owner on 2026-10-04.
Executable contract: `docs/specs/SPEC-STUDIO-READ-INDEX-1.md`.

## Objective

Opening a large workspace must show a usable Studio immediately and must not
repeatedly read its full TrustChain archive. Preserve canonical APatch coverage,
file drift, amendment debt, change history and protected-action admission.

## Design boundary

Maintain a disposable process-local index of canonical ledger rows and file
identity stamps. Read each unchanged object once per process; append, replacement
and deletion invalidate the appropriate rows. Rebuild the index on restart.
No raw ledger, source, prompts or credentials are persisted in a Studio database.
Persistent indexing may be added later as a separate contract.

Build artifact membership once per ledger generation. Evaluate each SPEC with
its assigned records plus the context records and global judge amendments needed
to preserve APatch semantics. Continue using APatch's coverage and policy APIs.
Opening Studio uses the canonical lightweight policy snapshot; full doctor/audit
remains an explicit diagnostic action. Mutation admission remains APatch-owned.

The loopback app returns a safe initial projection while the first build runs.
It reports building, ready or unavailable; a failed build must never display old
evidence as current. Concurrent requests share the same background build.
Source drift is evaluated against live files when coverage is rebuilt.

## Acceptance

| ID | Requirement | Level |
|---|---|---|
| READ-1 | Unchanged ledger objects are not reread; an append reads only the new object and replacement/deletion updates the next snapshot | MUST |
| READ-2 | Artifact filtering preserves implicit legacy assignment and global judge amendment records; unrelated records do not inflate per-SPEC work | MUST |
| READ-3 | The overview uses canonical lightweight APatch policy and does not invoke full doctor or its signed-block archive scan | MUST |
| READ-4 | Concurrent readers coalesce, changed files become stale using canonical coverage, and malformed ledger objects cause explicit unavailability | MUST |
| READ-5 | A cold loopback overview returns within one second under a deliberately blocked builder, exposes building status, and eventually returns ready; failures are retryable | MUST |
| READ-6 | No additional source/ledger database is written, the UI visibly reports indexing/failure, and authorization and existing projection/privacy tests remain green | MUST |
