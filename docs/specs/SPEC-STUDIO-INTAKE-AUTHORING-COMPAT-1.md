# SPEC-STUDIO-INTAKE-AUTHORING-COMPAT-1 — SPEC-STUDIO-INTAKE-AUTHORING-COMPAT-1 (scaffolded from RFP-026-INTAKE-AUTHORING-COMPATIBILITY)

> **apatch artifact:** `spec:SPEC-STUDIO-INTAKE-AUTHORING-COMPAT-1`  
> **ownership mode:** strict  
> **Anchors:** RFP-026-INTAKE-AUTHORING-COMPATIBILITY  
> _Scaffolded from RFP-026-INTAKE-AUTHORING-COMPATIBILITY acceptance by `apatch spec scaffold --from-contract`. Fill each `(verify:)` with a real command (one green test per requirement)._

## R0 RFP traceability gate (meta)

owns: docs/specs/SPEC-STUDIO-INTAKE-AUTHORING-COMPAT-1.md

| RFP id | SPEC Rk | Disposition |
|--------|---------|-------------|
| IC-S1 | R1 | covered |
| IC-S2 | R2 | covered |
| IC-S3 | R3 | covered |
| IC-S4 | R4 | covered |
| IC-S5 | R5 | covered |

(verify: env PYTHONPATH=/Users/edcher/Documents/GitHub/_codex/apatch-source-intake-20260923/apatch /Users/edcher/Documents/GitHub/apatch-studio-oss/.venv/bin/python -m apatch.cli spec lint --spec SPEC-STUDIO-INTAKE-AUTHORING-COMPAT-1 --json)

## R1 Absent profile without an optional reader

owns: apatch_studio/authoring_workflow.py

An absent profile returns no activated successor without importing the optional lineage reader or writing state.

(verify: env PYTHONPATH=/Users/edcher/Documents/GitHub/_codex/apatch-source-intake-20260923/apatch /Users/edcher/Documents/GitHub/apatch-studio-oss/.venv/bin/python -m pytest tests/authoring/test_intake_authoring_compatibility.py -k empty_profile -q)

## R2 Exact direct approved parent without optional reader

owns: apatch_studio/authoring_workflow.py

A direct approved parent is recognized only with its exact seal, immutable archive and matching grant/parent hashes, without loading an unnecessary reader.

(verify: env PYTHONPATH=/Users/edcher/Documents/GitHub/_codex/apatch-source-intake-20260923/apatch /Users/edcher/Documents/GitHub/apatch-studio-oss/.venv/bin/python -m pytest tests/authoring/test_intake_authoring_compatibility.py -k direct_exact -q)

## R3 Grant/seal/archive validation remains mandatory

owns: apatch_studio/authoring_workflow.py

Wrong grant, bad seal and changed archive remain rejected. No reader availability or cached rows may bypass those validations.

(verify: env PYTHONPATH=/Users/edcher/Documents/GitHub/_codex/apatch-source-intake-20260923/apatch /Users/edcher/Documents/GitHub/apatch-studio-oss/.venv/bin/python -m pytest tests/authoring/test_intake_authoring_compatibility.py -k 'unrelated_grant or bad_active or different_immutable' -q)

## R4 Required-reader refusal and supplied verified-row validation

owns: apatch_studio/authoring_workflow.py

A real ancestry step loads the reader only when verified rows are not already supplied. If unavailable, fail closed with an explicit signed-lineage error, never infer approval or leak a bare import exception as apparent success. Empty verified rows cannot prove activation.

(verify: env PYTHONPATH=/Users/edcher/Documents/GitHub/_codex/apatch-source-intake-20260923/apatch /Users/edcher/Documents/GitHub/apatch-studio-oss/.venv/bin/python -m pytest tests/authoring/test_intake_authoring_compatibility.py -k 'supplied_empty or needed_but_unavailable' -q)

## R5 Unchanged judges and full native API regression qualification

owns: apatch_studio/authoring_workflow.py

The original authoring judge and the original 23 intake judge plus fixture retain exact bytes. The exact complete Studio R5 selection passes without skips, xfail or allowed failures.

(verify: env PYTHONPATH=/Users/edcher/Documents/GitHub/_codex/apatch-source-intake-20260923/apatch /Users/edcher/Documents/GitHub/apatch-studio-oss/.venv/bin/python -m pytest tests/authoring/test_intake_authoring_compatibility.py tests/authoring/test_contract_intake_api.py tests/authoring/test_studio_authoring.py tests/sdd/test_sdd_owner_execution_flow.py tests/test_security.py -q)
