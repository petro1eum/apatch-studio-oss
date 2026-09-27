"""Projection tests: an active versioned candidate must replace no draft."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from apatch_studio.sdd_workflow import SddWorkflowFacade, SddWorkflowError

ROOT = Path(__file__).resolve().parents[2]
fixture_spec = importlib.util.spec_from_file_location("successor_projection_fixture", ROOT / "tests/sdd/test_sdd_owner_execution_flow.py")
fixtures = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(fixtures)


def selected_candidate(tmp_path):
    from apatch.sdd_integrity import freeze_contract, validate_task_envelope
    original = fixtures._write_prepared(tmp_path)
    before = original.read_bytes()
    package = json.loads(before)
    package["objective"] = "Selected immutable successor candidate"
    candidate = original.with_name("SPEC-DEMO-1-v2.json")
    candidate.write_text(json.dumps(package))
    facade = SddWorkflowFacade(tmp_path)
    # This tests only projection; actual promotion authority is tested by Core.
    frozen = freeze_contract({**facade._freeze_input(package, package["contract_request"], owner="studio-laptop", frozen_at="2026-09-16T00:00:00Z"),
                              "candidate_path": candidate.relative_to(tmp_path).as_posix(),
                              "candidate_hash": "sha256:" + hashlib.sha256(candidate.read_bytes()).hexdigest(),
                              "supersedes_hash": "sha256:" + "a" * 64})
    (tmp_path / ".apatch/sdd_verification_contract.json").write_text(json.dumps(frozen))
    pins = {asset["path"] for item in frozen["obligations"] for asset in item["judge_assets"]}
    for requirement, envelope in package["task_envelopes"].items():
        value = validate_task_envelope({**envelope, "contract_hash": frozen["document_hash"], "forbidden_paths": sorted(set(envelope["forbidden_paths"]) | pins | {".apatch/**", ".trustchain/**", ".git/**"})})
        path = tmp_path / ".apatch/sdd/envelopes/SPEC-DEMO-1" / (requirement + ".json")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value))
    return facade, candidate, original, before


def test_active_successor_shows_frozen_without_overwriting_canonical_draft(tmp_path):
    facade, candidate, original, before = selected_candidate(tmp_path)
    review = facade.contract_review("SPEC-DEMO-1", "R1")
    assert review["status"] == "frozen"
    assert review["objective"] == "Selected immutable successor candidate"
    assert original.read_bytes() == before


def test_candidate_drift_blocks_projection(tmp_path):
    facade, candidate, _, _ = selected_candidate(tmp_path)
    candidate.write_text(candidate.read_text() + "\n")
    with pytest.raises(SddWorkflowError, match="candidate changed"):
        facade.contract_review("SPEC-DEMO-1", "R1")


def test_modified_envelope_cannot_look_like_approved_successor(tmp_path):
    from apatch.sdd_integrity import validate_task_envelope
    facade, _, _, _ = selected_candidate(tmp_path)
    path = tmp_path / ".apatch/sdd/envelopes/SPEC-DEMO-1/R1.json"
    envelope = json.loads(path.read_text())
    envelope.pop("document_hash")
    envelope["budgets"]["files"] += 1
    path.write_text(json.dumps(validate_task_envelope(envelope)))
    with pytest.raises(SddWorkflowError, match="envelope changed"):
        facade.contract_review("SPEC-DEMO-1", "R1")
