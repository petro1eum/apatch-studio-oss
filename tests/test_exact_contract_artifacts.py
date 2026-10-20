"""Actual bounded filesystem reads and SDK signatures; native/HTTP are doubles."""
import base64
import copy
import hashlib
import json
import os
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from apatch import governed_work as G
from apatch_studio import exact_contract_artifacts as a
from apatch_studio.execution_intents import ExecutionIntentError


@pytest.fixture
def scenario(tmp_path, monkeypatch):
    key = Ed25519PrivateKey.generate()
    provider = SimpleNamespace(sign=key.sign, get_public_key=lambda: key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
    plan = {"schema": "trustchain.cowork.acceptance-plan.v1", "tenant_id": "company", "project_group_id": "tcpg_" + "a" * 32,
            "work_item_id": "tcpwi_" + "b" * 32, "candidate_paths": ["src/result.py"]}
    files = {a.PLAN: json.dumps(plan).encode(), "tests/test_result.py": b"agreed immutable checks", "src/result.py": b"answer = 42\n"}
    for path, data in files.items():
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    native = {"obligations": [{"judge_assets": [{"path": p, "sha256": "sha256:" + hashlib.sha256(v).hexdigest()}
                                              for p, v in files.items() if p != "src/result.py"]}]}
    bundle = {"snapshot": {"frozen_contract": native, "task_envelopes": {"R1": {
        "requirement": "SPEC-TEST#R1", "allowed_reads": list(files), "allowed_writes": ["src/result.py"], "forbidden_paths": ["private/*"]}}},
        "handoff": {**{k: plan[k] for k in ("tenant_id", "project_group_id", "work_item_id")},
            "contract_id": "tciwc_" + "c" * 32, "snapshot_hash": "sha256:" + "d" * 64,
            "native_contract_hash": "sha256:" + "e" * 64}}
    evidence = {"bundle_id": "apweb_" + "f" * 32}
    built = {"evidence_bundle": evidence, "timesheet": {"TEST_ONLY": True}, "evidence_bundle_hash": G.document_hash(evidence)}
    row = {"requirement": "SPEC-TEST#R1"}
    manager = SimpleNamespace(workspace=tmp_path, build_for_delivery=Mock(return_value={"evidence_bundle_hash": built["evidence_bundle_hash"]}),
        _find=lambda rows, identity: row, _update=lambda fn: fn([row]), _read_bundle=lambda *args, **kwargs: bundle,
        delivery=SimpleNamespace(selected=lambda identity: {"context": {"source_binding_id": "tcpsb_" + "a" * 32}}, evidence_time=lambda identity: "2026-10-20T00:00:00Z"),
        gateway=SimpleNamespace(_workspace_key_provider=lambda: provider))
    monkeypatch.setattr(G, "build_workspace_evidence", lambda *args, **kwargs: copy.deepcopy(built))
    # This fixture tests bounded transport. Native output seals have a separate
    # genuine SDK-record test below; never treat this double as live attestation.
    monkeypatch.setattr(a, "verify_run_outputs", lambda *args: None)
    monkeypatch.setattr(a.D, "load_config", lambda root: {"platform_url": "https://clients.example.test", "client_id": "TEST-ONLY", "service_request_key_id": "sha256:" + "a" * 64})
    return SimpleNamespace(manager=manager, bundle=bundle, files=files, provider=provider)


def test_exact_selection_uses_real_sdk_signature_and_no_arbitrary_workspace_export(scenario):
    s = scenario
    package, _ = a.build_package(s.manager, "tceh_" + "1" * 32, "apr_" + "2" * 32)
    assert [f["path"] for f in package["files"]] == sorted(s.files)
    assert all(base64.b64decode(f["content_base64"]) == s.files[f["path"]] for f in package["files"])
    G.verify_document_signature(package["manifest"], {G.signer_key_id(s.provider): s.provider.get_public_key()})
    s.manager.build_for_delivery.assert_called_once()


@pytest.mark.parametrize("path", ["/etc/passwd", "../key", ".env", "src/.key", "src//result.py", "src/./result.py", "src\\key", "src/\nx"])
def test_read_is_bounded_to_canonical_non_hidden_paths(scenario, path):
    with pytest.raises(ExecutionIntentError): a.read_exact(scenario.manager.workspace, path)


@pytest.mark.parametrize("kind", ["symlink", "parent_symlink", "hardlink", "fifo", "directory", "large"])
def test_links_special_files_and_size_limit_are_denied_without_following(scenario, tmp_path, kind):
    root = scenario.manager.workspace
    target = root / "src/result.py"
    outside = tmp_path / "private.txt"
    outside.write_bytes(b"must not be exported")
    target.unlink()
    if kind == "symlink": target.symlink_to(outside)
    if kind == "parent_symlink":
        (root / "src").rmdir(); (root / "src").symlink_to(tmp_path, target_is_directory=True)
    if kind == "hardlink": os.link(outside, target)
    if kind == "fifo": os.mkfifo(target)
    if kind == "directory": target.mkdir()
    if kind == "large": target.write_bytes(b"x" * 9)
    with pytest.raises(ExecutionIntentError): a.read_exact(root, "src/result.py", limit=8)
    assert outside.read_bytes() == b"must not be exported"


def test_modified_agreed_test_is_not_exported_as_original(scenario):
    (scenario.manager.workspace / "tests/test_result.py").write_bytes(b"changed assertion")
    with pytest.raises(ExecutionIntentError, match="immutable"):
        a.build_package(scenario.manager, "tceh_" + "1" * 32, "apr_" + "2" * 32)


def test_preview_does_not_transmit_files_and_changed_candidate_requires_new_preview(scenario):
    s = scenario
    preview = a.preview_artifacts(s.manager, "tceh_" + "1" * 32, "apr_" + "2" * 32)
    assert preview["customer_accepted"] is False and "content_base64" not in json.dumps(preview)
    s.manager.http_client_factory = Mock(side_effect=AssertionError("No HTTP allowed before exact preview match"))
    (s.manager.workspace / "src/result.py").write_bytes(b"changed result")
    with pytest.raises(ExecutionIntentError, match="changed after preview"):
        a.publish_artifacts(s.manager, preview["handoff_id"], preview["run_id"], expected_package_hash=preview["package_hash"])
    s.manager.http_client_factory.assert_not_called()


def test_artifact_delivery_replays_native_admission_instead_of_reinserting_evidence(scenario, monkeypatch):
    s=scenario
    preview=a.preview_artifacts(s.manager,"tceh_"+"1"*32,"apr_"+"2"*32)
    expected="evidence-admission:apweb_"+"f"*32
    def post(url, *, content, headers):
        body=json.loads(content)
        assert body["idempotency_key"]==headers["Idempotency-Key"]==expected
        assert body["artifact_package"]["manifest"]["files"]==preview["files"]
        # Test double models the existing native admission's immutable identity.
        return SimpleNamespace(status_code=201,json=lambda:{"schema":"trustchain.cowork.artifact-admission.v1",
            "native_ack":{"TEST_ONLY":"same existing native acknowledgement"},"package_hash":preview["package_hash"],
            "file_count":len(preview["files"]),"delivered":True,"customer_accepted":False})
    client=SimpleNamespace(post=post)
    from contextlib import nullcontext
    s.manager.http_client_factory=lambda:nullcontext(client)
    monkeypatch.setattr(a.T,"signed_service_headers",lambda *args,**kwargs:{"TEST_ONLY":"no real HTTP"})
    for _ in range(2):
        result=a.publish_artifacts(s.manager,preview["handoff_id"],preview["run_id"],expected_package_hash=preview["package_hash"])
        assert result["delivered"] is True and result["customer_accepted"] is False


@pytest.fixture
def native_records(tmp_path, monkeypatch):
    """Genuine SDK-signed persisted records; source lookup is a test double."""
    from trustchain import TrustChain, TrustChainConfig
    from apatch.trustchain_helper import TrustChainHelper
    tc = TrustChain(TrustChainConfig(chain_storage="memory", enable_nonce=False))
    public = base64.b64decode(tc.export_public_key())
    def verify(data, signature):
        try: Ed25519PublicKey.from_public_bytes(public).verify(signature, data); return True
        except Exception: return False
    provider=SimpleNamespace(get_public_key=lambda:public,verify=verify)
    (tmp_path/".git").mkdir()
    objects=tmp_path/".trustchain/objects";objects.mkdir(parents=True)
    source={"binding_id":"tcpsb_"+"1"*32,"spec_id":"SPEC-OUTPUT-CONTROL",
            "requirement_refs":[{"requirement_id":"R1","requirement_hash":"sha256:"+"2"*16}]}
    path="src/result.py";files={path:b"answer = 42\n"};session="test-native-session"
    artifacts=[f"project-source-binding:{source['binding_id']}@{G.document_hash(source)}",
               "spec:SPEC-OUTPUT-CONTROL#R1@sha256:"+"2"*16]
    def record(n,tool,data):
        signed=tc.sign(tool,data=data)
        value=asdict(signed)
        value["tool"]=value.pop("tool_id")
        value["response_timestamp"]=value["timestamp"]
        value.update(algorithm="ed25519",key_id="TEST-ONLY provider")
        raw={"id":f"op_{n:04d}","value":value}
        (objects/f"op_{n:04d}.json").write_text(json.dumps(raw))
        return raw
    mutation=record(1,"apatch",{"action":"chunk","governed_session_id":session,
        "files":{path:{"sha256":hashlib.sha256(files[path]).hexdigest()}}})
    record(2,"apatch_attest",{"governed_session_id":session,"artifacts":artifacts})
    rows=TrustChainHelper(str(tmp_path),auto_init=False,read_only=True).iter_ledger_entries()
    facts=G.derive_source_bound_attestation_facts(rows,binding=source)
    built={"evidence_bundle":{"attestation_refs":[{k:f[k] for k in ("attestation_id","attestation_hash")} for f in facts]}}
    manager=SimpleNamespace(workspace=tmp_path,gateway=SimpleNamespace(_workspace_key_provider=lambda:provider))
    monkeypatch.setattr(G,"load_project_source_binding",lambda *args:source)
    return SimpleNamespace(manager=manager,source=source,path=path,files=files,built=built,objects=objects,mutation=mutation)


def test_actual_sdk_native_output_seals_and_attestation_are_verified(native_records):
    n=native_records
    a.verify_run_outputs(n.manager,n.source["binding_id"],n.built,[n.path],n.files)
    changed={n.path:b"edited after the completed native run"}
    with pytest.raises(ExecutionIntentError,match="changed after"):
        a.verify_run_outputs(n.manager,n.source["binding_id"],n.built,[n.path],changed)


def test_signed_mutation_payload_tampering_cannot_be_exported_as_a_native_output(native_records):
    n=native_records
    n.mutation["value"]["data"]["files"][n.path]["sha256"]=hashlib.sha256(b"forged").hexdigest()
    (n.objects/"op_0001.json").write_text(json.dumps(n.mutation))
    with pytest.raises(ExecutionIntentError):
        a.verify_run_outputs(n.manager,n.source["binding_id"],n.built,[n.path],{n.path:b"forged"})
