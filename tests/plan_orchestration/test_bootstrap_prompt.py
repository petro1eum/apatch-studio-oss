"""Fresh-lineage contract bootstrap: the prompt binds the preallocated SPEC (REC-d1e7907f3415)."""

from apatch_studio.agent_runs import build_governed_prompt, planning_contract_ids
from apatch_studio.operations import AgentRunRequest


def _request() -> AgentRunRequest:
    return AgentRunRequest.model_validate(
        {
            "mode": "new_change",
            "runner": "codex",
            "objective": "Prepare one bounded contract",
            "acceptance_criteria": ["The owner can review exact checks"],
        }
    )


def test_fresh_lineage_prompt_binds_the_bootstrap_artifact_to_the_preallocated_spec() -> None:
    run_id = "apr_" + "a" * 32
    rfp_id, spec_id = planning_contract_ids(run_id)
    prompt = build_governed_prompt(
        _request(),
        studio_run_id=run_id,
        planning_contract_run_id=run_id,
        planning_context="",
    )

    assert f"spec-bootstrap:{spec_id}#R0" in prompt
    assert f"rfp:{rfp_id}" in prompt
    assert "apatch_session_start(intent=..., artifacts=['spec-bootstrap:" in prompt
    assert "one generic contract-authoring session" not in prompt
    assert "complete RFP, complete SPEC, frozen test/fixture files and preparation package" in prompt
    assert "bind the session to its R0 requirement" not in prompt
    assert "Preparation package template" in prompt
    assert f'"requirement": "{spec_id}#R1"' in prompt


def test_retry_prompt_keeps_the_exact_lineage_repair_path() -> None:
    run_id = "apr_" + "b" * 32
    prompt = build_governed_prompt(
        _request(),
        retry=True,
        studio_run_id=run_id,
        planning_contract_run_id=run_id,
        planning_context="",
    )

    assert "call apatch_session_start once for the exact SPEC#R0" in prompt
    assert "spec-bootstrap:" in prompt
