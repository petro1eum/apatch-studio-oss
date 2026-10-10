# SPEC-STUDIO-SCOPE-COLLISION-ADMIN-1 Native bounded original-owner scope collision maintenance

> **apatch artifact:** `spec:SPEC-STUDIO-SCOPE-COLLISION-ADMIN-1`
> **RFP artifact:** `rfp:RFP-2026100805`
> **RFP:** [RFP-2026100805](../RFP-2026100805.md)
> **ownership mode:** strict

## RFP traceability

| RFP id | SPEC Rk | Disposition |
|---|---|---|
| SCOPE-OWNER | R1 | covered |
| SCOPE-SNAPSHOT | R1 | covered |
| SCOPE-COLLISION | R1 | covered |
| SCOPE-RECEIPTS | R1 | covered |
| SCOPE-ATOMIC | R1 | covered |
| SCOPE-GUARDS | R1 | covered |
| SCOPE-SOURCE-ADMISSION | R1 | covered |

## Implementation source and containment

Use only `tests/frozen/fixtures/studio_scope_admin_source_policy.v1.json` approved inputs. Existing primary source changes and other chat worktrees are excluded. Exact new source path has no prior native owner. The new SPEC cannot claim existing Core or Studio paths. Original Core R6 profile and nine obligations are authority inputs to the later native transaction; Studio source freeze does not change them.

## R0 Prepare the exact independent source-governance inputs

owns: docs/RFP-2026100805.md, docs/specs/SPEC-STUDIO-SCOPE-COLLISION-ADMIN-1.md, tests/frozen/test_native_scope_administration.py, tests/frozen/fixtures/studio_scope_admin_source_policy.v1.json, tests/frozen/fixtures/studio_scope_admin_original_core.v1.json, .apatch/sdd/prepared/SPEC-STUDIO-SCOPE-COLLISION-ADMIN-1.json

Create exactly these six absent preparation artifacts in one native governed bootstrap session. Bind both the genuine bootstrap token and the exact precomputed R0 SPEC artifact; literal verification, existing-signer SDK checks, attestation and closure establish actual preparation coverage. Preserve immutable judge bytes and honest actual qualification provenance. This task creates no module and grants no owner or implementation authority.

(verify: /var/folders/yb/hvlh1bpd023__hxlxt4p_nx40000gn/T/trustchain-platform-native-runtime-40imkjl6/venv/bin/python -B -P -c 'import ast,hashlib,json;from pathlib import Path;s='"'"'SPEC-STUDIO-SCOPE-COLLISION-ADMIN-1'"'"';p=json.loads(Path('"'"'tests/frozen/fixtures/studio_scope_admin_source_policy.v1.json'"'"').read_text());assert p['"'"'schema'"'"']=='"'"'apatch.studio.scope-admin-source-policy.v1'"'"';assert p['"'"'write_allowlist'"'"']==['"'"'apatch_studio/scope_admin_workflow.py'"'"'];from apatch.spec import parse_spec_file;assert parse_spec_file('"'"'docs/specs/'"'"'+s+'"'"'.md'"'"').strict_ownership;assert '"'"'RFP-2026100805'"'"' in Path('"'"'docs/specs/'"'"'+s+'"'"'.md'"'"').read_text();assert Path('"'"'docs/RFP-2026100805.md'"'"').read_text().startswith('"'"'# RFP-2026100805 '"'"');h=lambda b:'"'"'sha256:'"'"'+hashlib.sha256(b).hexdigest();assert h(Path('"'"'tests/frozen/test_native_scope_administration.py'"'"').read_bytes())==p['"'"'judge_sha256'"'"'];assert h(Path('"'"'tests/frozen/fixtures/studio_scope_admin_original_core.v1.json'"'"').read_bytes())==p['"'"'fixture_sha256'"'"'];ast.parse(Path('"'"'tests/frozen/test_native_scope_administration.py'"'"').read_text());c=json.loads(Path('"'"'.apatch/sdd/prepared/SPEC-STUDIO-SCOPE-COLLISION-ADMIN-1.json'"'"').read_text());assert c['"'"'schema'"'"']=='"'"'apatch.studio.sdd-preparation.v1'"'"' and c['"'"'source_mutation_count'"'"']==0;assert c['"'"'spec_id'"'"']==s and c['"'"'task_envelopes'"'"']['"'"'R1'"'"']['"'"'allowed_writes'"'"']==['"'"'apatch_studio/scope_admin_workflow.py'"'"'];assert c['"'"'contract_request'"'"']['"'"'rfp_hash'"'"']==h(Path('"'"'docs/'"'"'+p['"'"'rfp_id'"'"']+'"'"'.md'"'"').read_bytes());assert c['"'"'contract_request'"'"']['"'"'spec_hash'"'"']==h(Path('"'"'docs/specs/'"'"'+s+'"'"'.md'"'"').read_bytes());assert all(a['"'"'sha256'"'"']==h(Path(a['"'"'path'"'"']).read_bytes()) for o in c['"'"'contract_request'"'"']['"'"'obligations'"'"'] for a in o['"'"'judge_assets'"'"']);t=Path('"'"'apatch_studio/scope_admin_workflow.py'"'"');assert not t.exists() or h(t.read_bytes())==p['"'"'candidate_source_sha256'"'"'];print('"'"'exact six preparation artifacts verified; no source or authority grant'"'"')')

## R1 Create the bounded native Studio authority-maintenance module

owns: apatch_studio/scope_admin_workflow.py

After actual R0 completion and existing certified owner freeze, create only the reviewed module. Satisfy all seven linked RFP conditions through genuine SDK receipts, native original owner and real atomic/lease boundaries. Public signer subject/digest never grants a caller authority role. Record explicit exact scope expansion, preserve nine frozen obligations and every other envelope/profile/source field, and retain reconciliation on signing ambiguity. Expose the dedicated guarded app only after genuine native source admission; no standard Core MCP parity is claimed. Frozen independent judges, fixture and source policy remain byte exact.

(verify: env PYTHONPATH=/Users/edcher/Documents/Codex/2026-10-08/ai-trust-completion-review-kp11urdu/extensions/clean-studio-20194f9-20261008T122244Z/runtime-package SCOPE_ADMIN_SOURCE=/Users/edcher/Documents/GitHub/apatch-studio-oss/apatch_studio/scope_admin_workflow.py SCOPE_ADMIN_CAPSULE=/Users/edcher/Documents/GitHub/apatch-studio-oss/tests/frozen/fixtures/studio_scope_admin_original_core.v1.json /var/folders/yb/hvlh1bpd023__hxlxt4p_nx40000gn/T/trustchain-platform-native-runtime-40imkjl6/venv/bin/python -B -P -m pytest -p no:cacheprovider tests/frozen/test_native_scope_administration.py --import-mode=importlib --basetemp=/private/tmp/apatch-native-scope-governed -q)
