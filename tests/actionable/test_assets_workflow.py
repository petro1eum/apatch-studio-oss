from pathlib import Path

import pytest
from pydantic import ValidationError

from apatch_studio.operations import AgentRunRequest


def test_work_asset_reuse_is_an_exact_bounded_new_change():
    request = AgentRunRequest(
        mode="new_change",
        runner="codex",
        objective="Apply the proven lease protocol",
        acceptance_criteria=["The lease behavior remains verified."],
        work_asset_id="wa_lease_protocol_v1",
    )
    assert request.work_asset_id == "wa_lease_protocol_v1"

    with pytest.raises(ValidationError):
        AgentRunRequest(
            mode="requirement",
            runner="codex",
            objective="Execute R2",
            spec_id="SPEC-DEMO-1",
            requirement_id="R2",
            work_asset_id="wa_lease_protocol_v1",
        )


def test_governed_prompt_records_use_only_after_verification():
    from apatch_studio.agent_runs import build_governed_prompt

    prompt = build_governed_prompt(
        AgentRunRequest(
            mode="new_change",
            runner="codex",
            objective="Apply the proven lease protocol",
            acceptance_criteria=["The lease behavior remains verified."],
            work_asset_id="wa_lease_protocol_v1",
        )
    )
    assert "wa_lease_protocol_v1" in prompt
    assert "After successful verification and attestation" in prompt
    assert "Opening or recalling the asset alone must not count as reuse" in prompt


def test_assets_ui_is_actionable_not_a_counter():
    root = Path(__file__).resolve().parents[2]
    app = (root / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
    api = (root / "frontend/src/api.ts").read_text(encoding="utf-8")
    for label in [
        "Search assets", "Suggest for task", "Apply in governed work", "Export asset",
    ]:
        assert label in app
    assert "runAssetAction" in api
    assert "Viewing a method does not record reuse" in app
