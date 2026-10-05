# RFP-026-INTAKE-AUTHORING-COMPATIBILITY — bounded optional lineage reader

Status: proposal, preparation only. No owner freeze or implementation approval is asserted.
This closes the existing Studio intake R5 regression gap, not a new lineage implementation.

## Problem

AuthoringWorkflow imports an unavailable optional signed-lineage reader before checking
whether the current flow needs it. Empty profiles, direct approved parents and existing
verified snapshots fail before the unchanged validation path can run.

## Acceptance

| ID | Level | Requirement |
| --- | --- | --- |
| IC-S1 | MUST | An absent profile returns no activated successor without importing the optional lineage reader or writing state. |
| IC-S2 | MUST | A direct approved parent is recognized only with its exact seal, immutable archive and matching grant/parent hashes, without loading an unnecessary reader. |
| IC-S3 | MUST | Wrong grant, bad seal and changed archive remain rejected. No reader availability or cached rows may bypass those validations. |
| IC-S4 | MUST | A real ancestry step loads the reader only when verified rows are not already supplied. If unavailable, fail closed with an explicit signed-lineage error, never infer approval or leak a bare import exception as apparent success. Empty verified rows cannot prove activation. |
| IC-S5 | MUST | The original authoring judge and the original 23 intake judge plus fixture retain exact bytes. The exact complete Studio R5 selection passes without skips, xfail or allowed failures. |

## Proposed exact surface

EDIT apatch_studio/authoring_workflow.py: optional reader import location and explicit
unavailable-reader refusal inside _activated_successor_of only.
Preserve existing caller-owned contract/signed_rows arguments and every existing validation.
CREATE tests/authoring/test_intake_authoring_compatibility.py as the judge before implementation.
No changes to sdd_workflow.py, contract_recovery.py, Core policy, keys, grants, profiles,
signed-row construction, existing tests or customer/production configuration.

## Qualification

The new tests isolate control flow and immutable archive validation; they do not claim
native owner identity or signed activation. Genuine owner/signature behavior remains covered
by the unchanged existing SDD/security/intake tests. First record RED baseline; after exact
owner freeze verify these judges and the unchanged full Studio R5 command using candidate Core.
Browser owner intake remains an explicit following gate, not waived by ASGI success.
