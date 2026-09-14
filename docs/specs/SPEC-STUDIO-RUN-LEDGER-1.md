# SPEC-STUDIO-RUN-LEDGER-1 -- Durable Local Run Ledger and Review

> **apatch artifact:** `spec:SPEC-STUDIO-RUN-LEDGER-1`
> **Anchors:** RFP-003
> This SPEC is the executable contract for RFP-003.

## R0 RFP traceability gate

| RFP id | SPEC Rk | Disposition |
|--------|---------|-------------|
| RL-1 | R1 | covered |
| RL-2 | R2 | covered |
| RL-3 | R3 | covered |
| RL-4 | R4 | covered |
| RL-5 | R5 | covered |
| RL-6 | R6 | covered |
| RL-7 | R7 | covered |
| RL-8 | R8 | covered |
| RL-9 | R9 | covered |

(verify: python3 -m pytest tests/test_run_ledger_contract.py::test_rfp_traceability -q)

## R1 Workspace-scoped durable journal

Create `apatch.studio.run-journal.v1` in the operating-system user state area, keyed by a one-way workspace identity and physically outside the Git workspace.

(verify: python3 -m pytest tests/test_run_store.py::test_run_store_uses_private_workspace_scoped_state -q)

## R2 Atomic private storage

Use owner-only directories, mode 0600, a cross-process lock, fsync and atomic replacement so a crash cannot expose a partial accepted journal.

(verify: python3 -m pytest tests/test_run_store.py::test_atomic_private_write_and_round_trip -q)

## R3 Persistence allowlist

Serialize only documented request, lifecycle and review fields. Reject unknown or forbidden raw output, source, path, argv, environment, secret and APatch capability keys recursively.

(verify: python3 -m pytest tests/test_run_store.py::test_store_rejects_forbidden_fields -q)

## R4 Restart reconciliation

Load durable history at manager startup, convert queued/running records to interrupted terminal records, and permit exact retry without persisted PID reuse.

(verify: python3 -m pytest tests/test_agent_runs.py::test_restart_marks_inflight_interrupted_and_allows_retry -q)

## R5 Bounded retention

Retain at most the configured terminal history limit in deterministic order while never evicting an active record.

(verify: python3 -m pytest tests/test_run_store.py::test_run_store_retains_bounded_terminal_history -q)

## R6 Safe workspace review

Capture safe aggregate Git/APatch observations before and after a run and expose their delta as a non-attributive workspace observation.

(verify: python3 -m pytest tests/test_run_review.py -q)

## R7 Fixed-purpose journal API

Extend list/detail run responses with journal health and safe review data without adding arbitrary command, path, raw log, deletion or MCP endpoints.

(verify: python3 -m pytest tests/test_operations_api.py::test_run_api_returns_persisted_review_metadata -q)

## R8 Durable review UI

Render persistent history, interrupted state, retry ancestry and an expandable safe result review on desktop and mobile.

(verify: npm --prefix frontend run build)

## R9 Persistence smoke

A disposable workspace run must survive manager recreation with byte-valid private state, review metrics and no source or runner transcript in the journal.

(verify: python3 -m pytest tests/test_run_ledger_smoke.py -q)
