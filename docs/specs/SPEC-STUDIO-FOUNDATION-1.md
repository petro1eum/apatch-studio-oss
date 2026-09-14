# SPEC-STUDIO-FOUNDATION-1 -- APatch Studio Foundation

> **apatch artifact:** `spec:SPEC-STUDIO-FOUNDATION-1`
> **Anchors:** RFP-001

## R0 RFP traceability gate

| RFP id | SPEC Rk | Disposition |
|---|---|---|
| ST-1 | R1 | covered |
| ST-2 | R2 | covered |
| ST-3 | R3 | covered |
| ST-4 | R4 | covered |
| ST-5 | R5 | covered |
| ST-6 | R6 | covered |
| ST-7 | R7 | covered |
| ST-8 | R8 | covered |

(verify: python3 -m pytest tests/test_contracts.py::test_rfp_traceability -q)

## R1 Standalone public client

Provide one standalone public Studio client over the public APatch governed
runtime. Cowork is an optional connected surface and cannot fork or weaken local
runtime semantics. No organization control-plane implementation is distributed.

(verify: python3 -m pytest tests/test_contracts.py::test_product_boundary -q)

## R2 Loopback request boundary

Implement loopback Host validation, process-scoped API authentication and exact
same-origin checks for state-changing requests.

(verify: python3 -m pytest tests/test_security.py -q)

## R3 Content-safe local projection

Keep browser and APatch session secrets out of persistence and reject forbidden
projection keys recursively.

(verify: python3 -m pytest tests/test_projection.py -q)

## R4 APatch read-model adapter

Build one bounded workspace projection from APatch project status, doctor,
session/evidence state and WorkAssets. Return useful degraded states when an
optional subsystem is unavailable.

(verify: python3 -m pytest tests/test_adapter.py -q)

## R5 Functional product views

Implement Home, Plans, Library and Admin, plus configured Inbox, as real views
over the live projection.

(verify: npm --prefix frontend run build)

## R6 Stable responsive states

Cover loading, empty and failure states, and verify desktop/mobile layouts do
not overlap or reflow primary controls unexpectedly.

(verify: npm --prefix frontend run build)

## R7 Live local smoke

Serve the production frontend through the loopback backend and read a real
APatch workspace through the authenticated API.

(verify: python3 -m pytest tests/test_api.py -q)

## R8 Fixed-purpose API boundary

Assert the API contains no arbitrary command, shell, MCP relay, direct mutation,
rollback or session-capability endpoint. RFP-002 may add only its enumerated
fixed-purpose run operations.

(verify: python3 -m pytest tests/test_contracts.py::test_api_is_fixed_purpose_without_shell_or_mcp_relay -q)
