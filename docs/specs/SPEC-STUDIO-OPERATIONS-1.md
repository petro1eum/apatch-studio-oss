# SPEC-STUDIO-OPERATIONS-1 -- Operational Agent Workspace

> **apatch artifact:** `spec:SPEC-STUDIO-OPERATIONS-1`
> **Anchors:** RFP-002

## R0 RFP traceability gate

| RFP id | SPEC Rk | Disposition |
|---|---|---|
| OP-1 | R1 | covered |
| OP-2 | R2 | covered |
| OP-3 | R3 | covered |
| OP-4 | R4 | covered |
| OP-5 | R5 | covered |
| OP-6 | R6 | covered |
| OP-7 | R7 | covered |
| OP-8 | R8 | covered |
| OP-9 | R9 | covered |

(verify: python3 -m pytest tests/test_operations_contract.py::test_rfp_traceability -q)

## R1 Typed work requests

Define bounded new_change, requirement and recovery request models. Exact SPEC,
requirement and session identifiers are validated before a process can start.

(verify: python3 -m pytest tests/test_operations_contract.py::test_typed_requests_reject_ambiguous_work -q)

## R2 Allowlisted local runners

Detect Codex CLI and Claude Code, build fixed argv arrays and send user-authored
work over stdin. The request cannot choose an executable, cwd, shell, permission
bypass, environment override or arbitrary runner flag.

(verify: python3 -m pytest tests/test_agent_runs.py::test_runner_catalog_and_argv_are_allowlisted -q)

## R3 Managed run lifecycle

Provide bounded concurrency, queued/running/terminal states, timestamps,
process-group cancellation and retry linkage without persisting runner secrets.

(verify: python3 -m pytest tests/test_agent_runs.py::test_run_lifecycle_and_cancel -q)

## R4 Governed agent instructions

New work, exact requirement and recovery prompts must require the APatch
governed lifecycle, exact ownership, verification and attestation or rollback,
and must prohibit implicit push or deployment.

(verify: python3 -m pytest tests/test_agent_runs.py::test_prompts_enforce_apatch_lifecycle -q)

## R5 Safe run projection

Expose only typed status, runner, mode, user-authored objective, timestamps,
progress phase, terminal outcome and opaque run/thread identifiers. Never expose
raw runner JSONL, source, diffs, paths, credentials, private keys, prompts or
APatch session capabilities.

(verify: python3 -m pytest tests/test_agent_runs.py::test_safe_projection_redacts_raw_runner_output -q)

## R6 Fixed-purpose operational API

Add authenticated same-origin runner discovery, start, list/detail, cancel and
retry endpoints.

(verify: python3 -m pytest tests/test_operations_api.py -q)

## R7 Developer workflow UI

Make Start work and Runs primary views. Support new change, exact existing
requirement and recovery modes, runner selection, validation, polling,
cancellation, retry and actionable terminal states on desktop and mobile.

(verify: npm --prefix frontend run build)

## R8 Operational API security

Reject arbitrary command/MCP fields and preserve the RFP-001 loopback, process
token and content-safety boundary.

(verify: python3 -m pytest tests/test_operations_api.py::test_api_rejects_arbitrary_command_fields -q)

## R9 Deterministic operational smoke

Use an injected fake runner for deterministic tests and execute one disposable
managed process that completes through the manager without modifying source.

(verify: python3 -m pytest tests/test_operations_smoke.py -q)
