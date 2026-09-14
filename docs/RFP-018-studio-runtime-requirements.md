# RFP-018: Studio runtime requirements

Status: accepted 2026-09-03. Owner: APatch Studio.

## 1. Decision

APatch Studio declares the minimum public APatch runtime it works with and checks
it at start-up, in the workspace API and in Admin. The package requires
`apatch[mcp]>=0.8.45` and also probes the exact capabilities on which the planning
loop depends, rather than trusting a version string alone.

## 2. Reproduced defect

On 2026-09-03 the installed wheel `apatch 0.8.42` carried the session-binding fix but not the local SPEC bootstrap channel. Studio started without a word, and every fresh `Prepare plan` failed inside APatch with `SPEC_WORKFLOW_REQUIRED`. The user saw a failed change with no hint that the runtime, not the request, was the cause. A version pin (`apatch>=0.8.42`) would not have caught it.

## 3. Required fixes

| Id | Probe | Why Studio needs it |
|---|---|---|
| session_binding | `apatch.spec_executor.bind_runtime_to_active_session` | Plan sessions stay bound when several changes share the workspace |
| spec_bootstrap | `apatch.spec_ownership._bootstrap_authorization` | A fresh plan may create its own new specification through the contract-authoring session |

The probe list lives in `apatch_studio/runtime_requirements.py` and is the only
place a new runtime capability requirement is added.

## 4. Surfaces

- `apatch-studio serve` prints `APatch runtime: <version> · required fixes: <present>/<total>` and, on a mismatch, a warning with what is missing and one next step. It keeps serving so the user can read the explanation in Admin.
- The workspace overview carries `runtime.requirements` (schema `apatch.studio.runtime-requirements.v1`).
- Admin › Local runtime shows a `Required fixes` row and the runtime check headline.
- The sidebar runtime card turns to attention and names the cause when a fix is missing.
- `pyproject.toml` requires the public MCP-enabled APatch distribution.

## 5. Non-goals

Studio does not embed or fork APatch. It does not refuse to start solely to hide
the diagnosis: a user must still be able to open Admin and read what to update.

## Acceptance

| Id | Requirement | Level |
|---|---|---|
| RT-1 | The probe reports each required fix as present or missing and treats an unimportable module as missing | MUST |
| RT-2 | A runtime missing a fix is explained in product language with the exact missing capabilities and one next step; an older version carrying every fix is accepted and says so | MUST |
| RT-3 | `serve` prints the runtime line and the mismatch warning before the first request | MUST |
| RT-4 | The workspace API, Admin and the runtime card expose the requirement state without protocol vocabulary | MUST |

Verification: `python3 -m pytest tests/runtime/test_runtime_requirements.py -q`.
