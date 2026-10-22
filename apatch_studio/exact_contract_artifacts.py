"""Explicit delivery of bounded, exact contract files; never a workspace ZIP.

Runs only behind Studio's existing local session/same-origin guard. Uses the
already enrolled native identity and existing evidence-admission route. No
cross-origin file reader, shell execution, new keys or Core changes.
"""
from __future__ import annotations

import base64
import fnmatch
import hashlib
import json
import os
import stat
from pathlib import PurePosixPath
from types import SimpleNamespace

from apatch import governed_work as G, governed_work_delivery as D, governed_work_transport as T
from apatch_studio.exact_contract_delivery import denied

PLAN = "acceptance/work-plan.json"
SCHEMA = "trustchain.cowork.studio-artifacts.v1"
LIMIT = 2 * 1024 * 1024


def verify_run_outputs(manager, source_binding_id, built, candidates, files, expected_profile=None):
    """Reuse native source-bound attestations and OSS persisted-record crypto.

    A current working-tree hash or mutable notarization cache is insufficient.
    This profile exports candidate outputs recorded by an attested mutation of
    this exact Change; arbitrary later edits never inherit a completed run.
    """
    from apatch.trustchain_helper import TrustChainHelper
    from apatch.enforcement import _ledger_entry_order
    helper = TrustChainHelper(str(manager.workspace), auto_init=False, read_only=True)
    rows = helper.iter_ledger_entries()
    source = G.load_project_source_binding(str(manager.workspace), source_binding_id)
    facts = G.derive_source_bound_attestation_facts(rows, binding=source)
    expected = {(a["attestation_id"], a["attestation_hash"]) for a in built["evidence_bundle"]["attestation_refs"]}
    selected = [f for f in facts if (f["attestation_id"], f["attestation_hash"]) in expected and f["outcome"] == "passed"]
    if len(selected) != len(expected) or not selected:
        denied("The selected run has no exact source-bound attestation", "artifact_output_unconfirmed")
    provider = manager.gateway._workspace_key_provider()
    def verified(row):
        path = row.get("object_path")
        if not isinstance(path, str) or not path.startswith(("objects/", "chain/block_")) or ".." in PurePosixPath(path).parts:
            return False
        try:
            record = json.loads((manager.workspace / ".trustchain" / path).read_bytes())
            value = record.get("value", record)
            # Verification is pinned to the same already enrolled provider as
            # the native evidence, not a public key supplied by the record.
            _, valid = helper._pinned_record(record, SimpleNamespace(agent_id=value.get("key_id"), key_provider=provider))
            actual = helper._parse_ledger_object(record)
            return valid and all(actual[k] == row[k] for k in ("id", "tool_id", "signature", "timestamp", "payload", "key_id", "algorithm"))
        except (ValueError, OSError, TypeError, KeyError):
            return False
    attestations = {}
    for f in selected:
        matches = [r for r in rows if r["id"] == f["attestation_id"] and r["tool_id"] == "apatch_attest"
                   and r["payload"].get("governed_session_id", r["payload"].get("session_id")) == f["governed_session_id"]]
        if len(matches) != 1 or not verified(matches[0]):
            denied("The native attestation signature is unconfirmed", "artifact_output_unconfirmed")
        attestations[f["governed_session_id"]] = matches[0]
    for path in candidates:
        eligible = [r for r in rows if r["tool_id"] in {"apatch", "apatch_expert"}
                    and r["payload"].get("governed_session_id", r["payload"].get("session_id")) in attestations
                    and path in r["payload"].get("files", {})]
        eligible = [r for r in eligible if _ledger_entry_order(r) < _ledger_entry_order(
            attestations[r["payload"].get("governed_session_id", r["payload"].get("session_id"))])]
        if not eligible:
            # A new agreed scheme can reverify already-correct source without
            # inventing a mutation. Only a fresh signature-bound native content
            # snapshot for this exact current profile can qualify those bytes.
            from apatch_studio.exact_verified_outputs import verified_content
            if expected_profile is not None:
                try:
                    witnesses = [verified_content(manager, a, *expected_profile) for a in attestations.values()]
                    if witnesses and all(w.get(path, {}).get('sha256') == 'sha256:' + hashlib.sha256(files[path]).hexdigest() for w in witnesses):
                        continue
                except (ValueError, OSError, KeyError, TypeError):
                    pass
            denied("This output was not recorded by the attested run", "artifact_output_unconfirmed")
        row = max(eligible, key=_ledger_entry_order)
        digest = row["payload"]["files"][path].get("sha256", "")
        if not verified(row) or digest.removeprefix("sha256:") != hashlib.sha256(files[path]).hexdigest():
            denied("The output changed after its signed run", "artifact_output_changed")


def read_exact(root, relative, limit=LIMIT):
    parts = PurePosixPath(relative).parts if isinstance(relative, str) else ()
    if (not parts or relative != str(PurePosixPath(relative)) or len(relative) > 256
            or PurePosixPath(relative).is_absolute() or "\\" in relative
            or any(p.startswith(".") or any(ord(c) < 32 for c in p) for p in parts)):
        denied("Artifact path is outside the supported profile", "artifact_path_denied")
    fds = []
    try:
        fds.append(os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW))
        for part in parts[:-1]:
            fds.append(os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fds[-1]))
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fds[-1])
        fds.append(fd)
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
            denied("Only bounded regular, non-linked files may be delivered", "artifact_path_denied")
        chunks, size = [], 0
        while True:
            data = os.read(fd, min(65536, limit + 1 - size))
            if not data:
                break
            chunks.append(data)
            size += len(data)
            if size > limit:
                denied("Artifact package is too large", "artifact_size_limit")
        after = os.fstat(fd)
        if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
            denied("Artifact changed while being read", "artifact_content_changed")
        return b"".join(chunks)
    except OSError:
        denied("An agreed artifact is missing or unsafe to read", "artifact_read_unconfirmed")
    finally:
        for fd in reversed(fds):
            os.close(fd)


def build_package(manager, handoff_id, run_id):
    # Full existing historical/current authority guard, genuine successful run,
    # exact native attestations and current frozen judge bytes remain mandatory.
    ready = manager.build_for_delivery(handoff_id, run_id)
    row = manager._update(lambda rows: dict(manager._find(rows, handoff_id)))
    bundle = manager._read_bundle(row, historical=True)
    snapshot, h = bundle["snapshot"], bundle["handoff"]
    obligations = snapshot["frozen_contract"]["obligations"]
    judges = {a["path"]: a["sha256"] for o in obligations for a in o["judge_assets"]}
    if PLAN not in judges:
        denied("This contract has no agreed sandbox plan", "artifact_plan_required")
    raw_plan = read_exact(manager.workspace, PLAN, 65536)
    if "sha256:" + hashlib.sha256(raw_plan).hexdigest() != judges[PLAN]:
        denied("The immutable plan changed", "artifact_content_changed")
    try:
        plan = json.loads(raw_plan)
        candidates = plan["candidate_paths"]
        if (plan["schema"] not in {"trustchain.cowork.acceptance-plan.v1","trustchain.cowork.acceptance-plan.v2"} or not isinstance(candidates, list)
                or not 0 < len(candidates) <= 128 or len(set(candidates)) != len(candidates)
                or any(plan[k] != h[k] for k in ("tenant_id", "project_group_id", "work_item_id"))):
            raise ValueError()
        if plan['schema']=='trustchain.cowork.acceptance-plan.v2':
            from .exact_scheme_validation import validate_plan_delta
            validate_plan_delta(plan,plan,snapshot['task_envelopes'])
            if {c['check_id'] for c in plan['checks']}!={c['acceptance_id'] for c in obligations}:
                raise ValueError('acceptance check inventory changed')
    except (ValueError, KeyError, TypeError):
        denied("The agreed artifact inventory is invalid", "artifact_plan_invalid")
    for envelope in snapshot["task_envelopes"].values():
        for path in candidates:
            if (not any(fnmatch.fnmatchcase(path, p) for p in envelope["allowed_reads"] + envelope["allowed_writes"])
                    or any(fnmatch.fnmatchcase(path, p) for p in envelope["forbidden_paths"])):
                denied("Candidate is outside an agreed requirement", "artifact_path_denied")
    if set(candidates).intersection(judges):
        denied("Candidate overlaps immutable checks", "artifact_path_denied")
    selected = [e for e in snapshot["task_envelopes"].values() if e["requirement"] == row["requirement"]]
    if len(selected) != 1 or any(not any(fnmatch.fnmatchcase(path, pattern)
            for pattern in selected[0]["allowed_reads"] + selected[0]["allowed_writes"])
            for path in set(candidates) | set(judges)):
        denied("Artifact reads exceed the selected requirement", "artifact_path_denied")
    files = {p: read_exact(manager.workspace, p) for p in sorted(set(candidates) | set(judges))}
    if sum(map(len, files.values())) > LIMIT:
        denied("Artifact package is too large", "artifact_size_limit")
    pins = [{"path": p, "sha256": "sha256:" + hashlib.sha256(data).hexdigest()} for p, data in files.items()]
    if any(next(p["sha256"] for p in pins if p["path"] == path) != digest for path, digest in judges.items()):
        denied("An immutable check changed", "artifact_content_changed")
    source = manager.delivery.selected(handoff_id)["context"]
    from apatch_studio.exact_native_evidence import build_or_reuse_workspace_evidence
    try:
        try:
            built = G.build_workspace_evidence(str(manager.workspace), binding_id=source["source_binding_id"],
                key_provider=manager.gateway._workspace_key_provider(), issued_at=manager.delivery.evidence_time(handoff_id))
        except G.GovernedWorkError:
            # The native agent may already have stored the immutable pair.
            # Reuse is allowed only after fresh facts and full issuer validation.
            built = build_or_reuse_workspace_evidence(str(manager.workspace), binding_id=source["source_binding_id"],
                key_provider=manager.gateway._workspace_key_provider(), issued_at=manager.delivery.evidence_time(handoff_id))
    except (G.GovernedWorkError, ValueError, OSError):
        denied("The current native evidence could not be confirmed", "artifact_output_unconfirmed")
    if built["evidence_bundle_hash"] != ready["evidence_bundle_hash"]:
        denied("Native evidence changed during delivery", "artifact_native_evidence_changed")
    envelope = next(e for e in snapshot['task_envelopes'].values() if e['requirement'] == row['requirement'])
    verify_run_outputs(manager, source["source_binding_id"], built, candidates, files,
        (snapshot['frozen_contract'], envelope))
    if any(read_exact(manager.workspace, p) != data for p, data in files.items()):
        denied("An artifact changed during preparation", "artifact_content_changed")
    manifest = G.sign_document({"schema": SCHEMA,
        **{k: h[k] for k in ("tenant_id", "project_group_id", "work_item_id", "contract_id", "snapshot_hash", "native_contract_hash")},
        "requirement": row["requirement"], "run_id": run_id,
        "evidence_bundle_id": built["evidence_bundle"]["bundle_id"],
        "evidence_bundle_hash": built["evidence_bundle_hash"], "files": pins,
    }, manager.gateway._workspace_key_provider())
    return {"manifest": manifest, "files": [{"path": p, "content_base64": base64.b64encode(data).decode("ascii")}
                                              for p, data in files.items()]}, built


def preview_artifacts(manager, handoff_id, run_id):
    package, _ = build_package(manager, handoff_id, run_id)
    config = D.load_config(str(manager.workspace))
    return {"schema": "apatch.studio.exact-artifact-preview.v1", "handoff_id": handoff_id, "run_id": run_id,
        "project_group_id": package["manifest"]["project_group_id"], "platform_origin": config["platform_url"],
        "package_hash": G.document_hash(package["manifest"]), "files": package["manifest"]["files"],
        "customer_accepted": False}


def publish_artifacts(manager, handoff_id, run_id, *, expected_package_hash):
    package, built = build_package(manager, handoff_id, run_id)
    m = package["manifest"]
    if G.document_hash(m) != expected_package_hash:
        denied("The files changed after preview; preview this version again", "artifact_package_changed")
    config = D.load_config(str(manager.workspace))
    path = f"/api/internal/project-groups/{m['project_group_id']}/governed-work/evidence-admissions"
    # Reuse native admission idempotency. A new transport-only key would try to
    # insert the already admitted immutable evidence bundle a second time.
    key = "evidence-admission:" + built["evidence_bundle"]["bundle_id"]
    body = G.canonical_bytes({"subject": config["client_id"], "tenant_id": m["tenant_id"],
        "evidence_bundle": built["evidence_bundle"], "timesheet_draft": built["timesheet"],
        "artifact_package": package, "idempotency_key": key})
    provider = manager.gateway._workspace_key_provider()
    headers = {"Content-Type": "application/json", "X-Apatch-Client-Id": config["client_id"],
        "Idempotency-Key": key, **T.signed_service_headers(str(manager.workspace), method="POST", path=path,
            raw_body=body, tenant_id=m["tenant_id"], subject=config["client_id"],
            expected_key_id=config["service_request_key_id"], key_provider=provider)}
    with manager.http_client_factory() as client:
        response = client.post(config["platform_url"] + path, content=body, headers=headers)
    if response.status_code not in (200, 201):
        denied("Platform has not acknowledged these exact artifact files", "artifact_delivery_unconfirmed")
    try:
        reply = response.json()
        if (reply["schema"] != "trustchain.cowork.artifact-admission.v1" or reply["package_hash"] != G.document_hash(m)
                or reply["delivered"] is not True or reply["customer_accepted"] is not False
                or reply["file_count"] != len(m["files"]) or not isinstance(reply["native_ack"], dict)):
            raise ValueError()
    except (ValueError, KeyError, TypeError):
        denied("Platform did not acknowledge the selected file manifest", "artifact_delivery_unconfirmed")
    return {"schema": "apatch.studio.exact-artifact-delivery.v1", "handoff_id": handoff_id,
            "run_id": run_id, "package_hash": G.document_hash(m), "delivered": True,
            "file_count": len(m["files"]), "customer_accepted": False}
