import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from apatch_studio.action_facade import StudioWorkflowFacade
from apatch_studio.policy_workflow import PolicyActionRequest


def write_policy(root: Path):
    directory = root / ".apatch"
    directory.mkdir()
    (directory / "sandbox.json").write_text(
        json.dumps({"version": 1, "mode": "audit", "watcher": "audit", "lease_max_seconds": 300}),
        encoding="utf-8",
    )
    (directory / "enforcement.json").write_text(
        json.dumps({"governed_mode": "auto_session", "block_commit_without_proof": True}),
        encoding="utf-8",
    )


def test_policy_preview_apply_and_restore_are_bounded(tmp_path):
    write_policy(tmp_path)
    facade = StudioWorkflowFacade(tmp_path)
    preview = facade.policy_action(PolicyActionRequest(
        request_id="apsreq_policy_preview_001", action="preview",
        mode="enforce", governed_mode="strict", watcher="revert", lease_max_seconds=420,
    ))
    assert preview["result"]["mutation_performed"] is False
    assert json.loads((tmp_path / ".apatch/sandbox.json").read_text())["mode"] == "audit"
    applied = facade.policy_action(PolicyActionRequest(
        request_id="apsreq_policy_apply_001", action="apply",
        mode="enforce", governed_mode="strict", watcher="revert",
        lease_max_seconds=420, confirmed=True,
    ))
    assert applied["result"]["current"]["mode"] == "enforce"
    restored = facade.policy_action(PolicyActionRequest(
        request_id="apsreq_policy_restore_001", action="restore", confirmed=True,
    ))
    assert restored["result"]["current"]["mode"] == "audit"


def test_policy_rejects_arbitrary_fields_and_unconfirmed_mutation():
    with pytest.raises(ValidationError):
        PolicyActionRequest.model_validate({
            "request_id": "apsreq_policy_bad_001", "action": "apply",
            "confirmed": True, "json": {"anything": True},
        })
    with pytest.raises(ValidationError):
        PolicyActionRequest(
            request_id="apsreq_policy_bad_002", action="apply", mode="enforce",
        )


def test_policy_ui_exposes_full_local_workflow():
    root = Path(__file__).resolve().parents[2]
    view = (root / "frontend/src/OutsideInAdmin.tsx").read_text(encoding="utf-8")
    for label in ["Preview", "Apply", "Sign", "Verify", "Restore previous"]:
        assert label in view
    assert "runPolicyAction(action" in view
