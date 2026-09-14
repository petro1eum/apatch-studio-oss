from pathlib import Path

from apatch_studio.agent_runs import (
    RunnerCatalog,
    build_governed_prompt,
    build_planning_context,
)
from apatch_studio.operations import AgentRunRequest


def _request(mode: str = "new_change") -> AgentRunRequest:
    payload = {
        "mode": mode,
        "runner": "codex",
        "objective": "Prepare one bounded contract",
    }
    if mode == "new_change":
        payload["acceptance_criteria"] = ["The owner can review exact checks"]
    elif mode == "requirement":
        payload.update(spec_id="SPEC-DEMO-1", requirement_id="R1")
    else:
        payload["governed_session_id"] = "apatch_sess_1234_a1b2c3"
    return AgentRunRequest.model_validate(payload)


def test_new_change_retry_prompt_has_one_bounded_preparation_path() -> None:
    prompt = build_governed_prompt(_request())
    assert "Bounded preparation path (in this order)" in prompt
    assert "at most 8 structured repository inspection" in prompt
    assert "Do not inventory the whole source tree" in prompt
    assert "Use only the Studio-supplied context capsule" in prompt
    assert "complete RFP, complete SPEC, frozen test/fixture files and preparation package" in prompt
    assert "call apatch_session_start once for the exact SPEC#R0" in prompt
    assert "the complete ordered needles list and no finalize flag" in prompt
    assert "while each response says continue=true" in prompt
    assert "Only after continue=false" in prompt
    assert "with finalize=true and no needles" in prompt
    assert "Do not place generate_batch, resume_session or rollback between these calls" in prompt
    assert "bind the session to its R0 requirement" not in prompt
    assert "Never attest or close an RFP-only or SPEC-only partial package" in prompt
    assert "Do not call apatch_spec_scaffold" in prompt
    assert "apatch_spec_lint" in prompt



def test_bounded_planning_context_capsule_contains_contract_context_not_source(tmp_path: Path) -> None:
    run_id = "apr_11111111111111111111111111111111"
    (tmp_path / "docs" / "specs").mkdir(parents=True)
    (tmp_path / ".apatch" / "sdd" / "prepared").mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("Operate through APatch.\n", encoding="utf-8")
    (tmp_path / "README.md").write_text("# Demo project\n", encoding="utf-8")
    (tmp_path / "application_secret.py").write_text("TOKEN = 'never-project-this'\n", encoding="utf-8")
    (tmp_path / "docs" / "RFP-STUDIO-111111111111-demo.md").write_text(
        "# Existing partial contract\n\nPlanning run remains review-only.\n",
        encoding="utf-8",
    )
    (tmp_path / "docs" / "specs" / "SPEC-OTHER-1.md").write_text(
        "# SPEC-OTHER-1 -- Existing contract\n",
        encoding="utf-8",
    )

    (tmp_path / ".apatch" / "sdd" / "prepared" / "SPEC-STUDIO-CHANGE-111111111111.json").write_text(
        '{"schema":"apatch.studio.sdd-preparation.v1","status":"awaiting_owner_review"}\n',
        encoding="utf-8",
    )

    context = build_planning_context(tmp_path, run_id)
    prompt = build_governed_prompt(
        _request(),
        retry=True,
        studio_run_id="apr_22222222222222222222222222222222",
        planning_contract_run_id=run_id,
        planning_context=context,
    )

    assert "Operate through APatch" in context
    assert "Demo project" in context
    assert "Existing partial contract" in context
    assert "apatch.studio.sdd-preparation.v1" in context
    assert "awaiting_owner_review" in context
    assert "SPEC-OTHER-1" in context
    assert "never-project-this" not in context
    assert "only authorized pre-authoring context" in prompt
    assert "APatch doctor is the only permitted pre-authoring tool call" in prompt

def test_planning_latency_profile_pins_fast_model_without_changing_other_modes() -> None:
    catalog = RunnerCatalog(which={"codex": "/fixed/codex", "claude": "/fixed/claude"}.get)
    workspace = Path("/fixed/workspace")
    ordinary = catalog.command("codex", workspace)
    planning = catalog.planning_command("codex", workspace)
    assert 'model_reasoning_effort="low"' in planning
    assert planning[planning.index("--model") + 1] == "gpt-5.6-luna"
    assert "--model" not in ordinary
    assert "gpt-5.6-luna" not in ordinary
    assert 'model_reasoning_effort="low"' not in ordinary
    assert planning[-1] == ordinary[-1] == "-"
    assert "Bounded preparation path" not in build_governed_prompt(_request("requirement"))
