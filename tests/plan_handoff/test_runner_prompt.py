from apatch_studio.agent_runs import build_governed_prompt
from apatch_studio.operations import AgentRunRequest


def test_runner_requests_report_only_scope_audit_without_unowned_reversion() -> None:
    request = AgentRunRequest.model_validate({
        "mode": "new_change",
        "runner": "codex",
        "objective": "Prepare a bounded plan",
        "acceptance_criteria": ["The owner can review the exact contract"],
    })

    prompt = build_governed_prompt(request)

    assert "apatch_sandbox_audit with auto_revert=false" in prompt
    assert "auto_revert=true" not in prompt
    assert "proves the violating write belongs to this exact run" in prompt
    assert "stop and report it for owner review" in prompt
