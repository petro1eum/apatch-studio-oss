import json

import pytest

from apatch_studio.sdd_workflow import SddWorkflowError, SddWorkflowFacade
from test_sdd_owner_execution_flow import SPEC_ID, _write_prepared


@pytest.mark.parametrize("relative", [
    ".apatch/sdd/envelopes", f".apatch/sdd/envelopes/{SPEC_ID}", ".apatch/sdd/frozen",
    ".apatch/sdd_verification_contract.json", f".apatch/sdd/envelopes/{SPEC_ID}/R1.json",
])
def test_reviewed_freeze_rejects_redirected_destination_before_writes(tmp_path, relative):
    root, outside = tmp_path / "workspace", tmp_path / "outside"
    outside.mkdir()
    _write_prepared(root)
    facade = SddWorkflowFacade(root)
    snapshot = facade.approval_snapshot(SPEC_ID, "R1")
    sentinel = outside / "unrelated.json"
    sentinel.write_text('{"business":"unrelated"}')
    link = root / relative
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(sentinel if relative.endswith(".json") else outside,
                    target_is_directory=not relative.endswith(".json"))
    with pytest.raises(SddWorkflowError):
        facade.freeze_requirement(SPEC_ID, "R1", owner_actor_id="owner:test", confirmed=True,
                                   expected_snapshot=snapshot)
    assert sentinel.read_text() == '{"business":"unrelated"}'
    assert sorted(p.name for p in outside.iterdir()) == ["unrelated.json"]
    assert not list((root / ".apatch/sdd/frozen").glob("[0-9a-f]" * 64 + ".json"))


@pytest.mark.parametrize("relative", [".apatch", ".apatch/sdd", ".apatch/sdd/prepared"])
def test_preparation_ancestry_cannot_redirect_the_review(tmp_path, relative):
    root = tmp_path / "workspace"
    _write_prepared(root)
    facade = SddWorkflowFacade(root)
    directory = root / relative
    moved = tmp_path / "moved-state"
    directory.rename(moved)
    directory.symlink_to(moved, target_is_directory=True)
    with pytest.raises(SddWorkflowError):
        facade.contract_review(SPEC_ID, "R1")


def test_cleanup_preserves_unrelated_json_and_current_sibling_envelopes(tmp_path):
    _write_prepared(tmp_path)
    facade = SddWorkflowFacade(tmp_path)
    folder = tmp_path / f".apatch/sdd/envelopes/{SPEC_ID}"
    folder.mkdir(parents=True)
    unrelated = folder / "unrelated.json"
    unrelated.write_text('{"business":"unrelated"}')
    stale = folder / "R9.json"
    stale.write_text(json.dumps({"schema": "apatch.sdd.task-envelope.v1",
                                  "requirement": f"{SPEC_ID}#R9", "contract_hash": "old"}))
    first = facade.freeze_requirement(SPEC_ID, "R1", owner_actor_id="owner:test", confirmed=True)
    assert not stale.exists()
    assert unrelated.read_text() == '{"business":"unrelated"}'
    sibling = (folder / "R1.json").read_bytes()
    second = facade.freeze_requirement(SPEC_ID, "R2", owner_actor_id="owner:test", confirmed=True)
    assert second["contract_hash"] == first["contract_hash"]
    assert (folder / "R1.json").read_bytes() == sibling
    assert facade.freeze_requirement(SPEC_ID, "R2", owner_actor_id="owner:test", confirmed=True) == second


def test_execution_binding_cannot_read_manifest_through_a_link(tmp_path):
    _write_prepared(tmp_path)
    facade = SddWorkflowFacade(tmp_path)
    facade.freeze_requirement(SPEC_ID, "R1", owner_actor_id="owner:test", confirmed=True)
    manifest = tmp_path / ".apatch/sdd_verification_contract.json"
    saved = tmp_path / "saved-manifest.json"
    manifest.rename(saved)
    manifest.symlink_to(saved)
    with pytest.raises(SddWorkflowError):
        facade.execution_binding(SPEC_ID, "R1", actor_id="agent:test")
