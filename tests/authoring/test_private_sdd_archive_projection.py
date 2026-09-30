"""Private sealed archives must not disable public projection containment."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from apatch_studio.projection import (
    UnsafeProjectionError, assert_projection_safe, private_sdd_projection,
)
from apatch_studio.run_store import RunJournalError, RunStore
from apatch_studio.sdd_workflow import SddWorkflowFacade

ROOT = Path(__file__).resolve().parents[2]


def fixture_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fixtures = fixture_module("private_sdd_owner_fixture", "tests/sdd/test_sdd_owner_execution_flow.py")
records = fixture_module("private_sdd_journal_fixture", "tests/test_run_store.py")


def amended_binding(root):
    from apatch.sdd_integrity import freeze_contract, validate_task_envelope

    original = fixtures._write_prepared(root)
    package = json.loads(original.read_text())
    candidate = original.with_name("SPEC-DEMO-1-v2.json")
    candidate.write_text(json.dumps(package))
    old = "# private historical SPEC\n" + "archive line\n" * 600
    new = old + "\napproved bootstrap correction\n"
    digest = lambda text: "sha256:" + hashlib.sha256(text.encode()).hexdigest()
    command = package["task_envelopes"]["R1"]["commands"][0]
    bootstrap = {
        "kind": "pytest_explicit_conftest_bootstrap",
        "old_spec_text": old, "replacement_spec_text": new,
        "old_spec_hash": digest(old), "new_spec_hash": digest(new),
        "old_command": command, "new_command": [*command, "--noconftest"],
    }
    facade = SddWorkflowFacade(root)
    frozen = freeze_contract({
        **facade._freeze_input(package, package["contract_request"],
                              owner="studio-laptop", frozen_at="2026-09-30T00:00:00Z"),
        "spec_hash": digest(new),
        "candidate_path": candidate.relative_to(root).as_posix(),
        "candidate_hash": "sha256:" + hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "supersedes_hash": "sha256:" + "a" * 64,
        "judge_amendment": {"bootstrap": bootstrap},
    })
    (root / ".apatch/sdd_verification_contract.json").write_text(json.dumps(frozen))
    pins = {asset["path"] for item in frozen["obligations"] for asset in item["judge_assets"]}
    for rk, raw in package["task_envelopes"].items():
        envelope = validate_task_envelope({
            **raw, "contract_hash": frozen["document_hash"],
            "commands": [bootstrap["new_command"]],
            "forbidden_paths": sorted(set(raw["forbidden_paths"]) | pins |
                                      {".apatch/**", ".trustchain/**", ".git/**"}),
        })
        path = root / ".apatch/sdd/envelopes/SPEC-DEMO-1" / (rk + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(envelope))
    return facade, frozen


def test_private_binding_preserves_seals_and_public_limit(tmp_path):
    facade, frozen = amended_binding(tmp_path)
    binding = facade.execution_binding("SPEC-DEMO-1", "R1", actor_id="agent:codex")
    before = copy.deepcopy(binding)
    with pytest.raises(UnsafeProjectionError, match="string limit"):
        assert_projection_safe(binding)
    view = private_sdd_projection(binding)
    assert_projection_safe(view)
    assert binding == before and binding["contract"] == frozen
    archive = view["contract"]["judge_amendment"]["bootstrap"]["old_spec_text"]
    assert archive["characters"] > 4096
    assert archive["hash"] == frozen["judge_amendment"]["bootstrap"]["old_spec_hash"]


def test_native_review_is_bounded_but_runner_receives_exact_private_contract(tmp_path):
    _facade, frozen = amended_binding(tmp_path)
    client, headers, runs = fixtures._client(tmp_path)
    review = client.get("/api/v1/specs/SPEC-DEMO-1/requirements/R1/execution-contract", headers=headers)
    assert review.status_code == 200, review.text
    assert review.json()["status"] == "frozen"
    assert_projection_safe(review.json())
    assert "private historical SPEC" not in review.text
    assert "old_spec_text" not in review.text
    started = client.post("/api/v1/runs", headers=headers, json=fixtures._run_payload())
    assert started.status_code == 202, started.text
    assert runs.bindings[0]["contract"] == frozen
    assert runs.bindings[0]["contract_hash"] == frozen["document_hash"]


def test_private_journal_roundtrip_retains_exact_archives(tmp_path):
    facade, _frozen = amended_binding(tmp_path)
    binding = facade.execution_binding("SPEC-DEMO-1", "R1", actor_id="agent:codex")
    store = RunStore(tmp_path, state_root=tmp_path.parent / (tmp_path.name + "-private-journal"))
    record = records.record()
    record["sdd_execution"] = binding
    accepted = store.save([record])
    assert store.load().records == accepted
    assert accepted[0]["sdd_execution"] == binding
    assert "private historical SPEC" in store.journal_path.read_text()


@pytest.mark.parametrize("change", ["archive", "ordinary_large_field", "sensitive_key"])
def test_no_generic_projection_escape_for_private_context(tmp_path, change):
    facade, _frozen = amended_binding(tmp_path)
    binding = facade.execution_binding("SPEC-DEMO-1", "R1", actor_id="agent:codex")
    if change == "archive":
        binding["contract"]["judge_amendment"]["bootstrap"]["old_spec_text"] += "tampered"
    elif change == "ordinary_large_field":
        binding["ordinary_metadata"] = "x" * 4097
    else:
        binding["api_secret"] = "forbidden"
    with pytest.raises(UnsafeProjectionError):
        assert_projection_safe(private_sdd_projection(binding))
    record = records.record()
    record["sdd_execution"] = binding
    store = RunStore(tmp_path, state_root=tmp_path.parent / (tmp_path.name + "-private-journal"))
    with pytest.raises(RunJournalError):
        store.save([record])
    assert not store.journal_path.exists()


def test_unpinned_archive_and_size_bound_are_not_accepted(tmp_path):
    from apatch.sdd_integrity import freeze_contract, validate_task_envelope
    facade, _frozen = amended_binding(tmp_path)
    for kind in ("unpinned", "oversized"):
        binding = facade.execution_binding("SPEC-DEMO-1", "R1", actor_id="agent:codex")
        contract = copy.deepcopy(binding["contract"])
        contract.pop("document_hash")
        archive = contract["judge_amendment"]["bootstrap"]
        if kind == "unpinned":
            archive.pop("old_spec_hash")
        else:
            archive["old_spec_text"] = "x" * 1_048_577
            archive["old_spec_hash"] = "sha256:" + hashlib.sha256(archive["old_spec_text"].encode()).hexdigest()
        frozen = freeze_contract(contract)
        envelope = copy.deepcopy(binding["task_envelope"])
        envelope.pop("document_hash")
        envelope["contract_hash"] = frozen["document_hash"]
        envelope = validate_task_envelope(envelope)
        binding.update(contract=frozen, contract_hash=frozen["document_hash"],
                       task_envelope=envelope, envelope_hash=envelope["document_hash"])
        with pytest.raises(UnsafeProjectionError):
            private_sdd_projection(binding)
