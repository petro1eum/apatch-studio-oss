# RFP-018: Studio runtime requirements

Status: accepted 2026-09-03. Owner: APatch Studio.

## 1. Decision

APatch Studio declares the minimum public APatch runtime it works with and checks
it at start-up, in the workspace API and in Admin. The package requires
the floor declared in `pyproject.toml` and also probes required capabilities,
rather than trusting a version string alone. The original floor was 0.8.45.

## 2. Reproduced defect

On 2026-09-03 the installed wheel `apatch 0.8.42` carried the session-binding fix but not the local SPEC bootstrap channel. Studio started without a word, and every fresh `Prepare plan` failed inside APatch with `SPEC_WORKFLOW_REQUIRED`. The user saw a failed change with no hint that the runtime, not the request, was the cause. A version pin (`apatch>=0.8.42`) would not have caught it.

## 3. Required fixes

| Id | Probe | Why Studio needs it |
|---|---|---|
| session_binding | `apatch.spec_executor.bind_runtime_to_active_session` | Plan sessions stay bound when several changes share the workspace |
| spec_bootstrap | `apatch.spec_ownership._bootstrap_authorization` | A fresh plan may create its own new specification through the contract-authoring session |
| existing_signer | `apatch.strict_existing_signer.ExistingSignerBinding` | Approved tasks use the existing workspace signing identity |

The probe list lives in `apatch_studio/runtime_requirements.py` and is the only
place a new runtime capability requirement is added.

## 4. Surfaces

- When the server can load, `apatch-studio serve` prints `APatch runtime: <version> · required fixes: <present>/<total>` and, on a mismatch, a warning. Admin remains available. If a required Core import prevents startup altogether, the launcher explains how to repair the installation without opening the workspace.
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
| RT-5 | The displayed floor matches the package requirement. If a required Core API prevents the server itself from loading, CLI help still opens and start fails before workspace access with release and source recovery instructions. Unrelated import errors are not misreported as a Core mismatch. | MUST |

RT-5 maps to [SPEC-STUDIO-FIRST-USER-1 R5](specs/SPEC-STUDIO-FIRST-USER-1.md#r5-honest-local-administration).
Verification: `python3 -m pytest tests/runtime/test_runtime_requirements.py -q`.
