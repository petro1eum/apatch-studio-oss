"""Bounded package template: the prompt hands the runner the exact shape Studio accepts (REC-bf36f1001fd7)."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from apatch_studio.agent_runs import (
    DEFAULT_PLAN_TIMEOUT_SECONDS,
    AgentRunManager,
    build_governed_prompt,
    planning_contract_ids,
)
from apatch_studio.operations import AgentRunRequest
from apatch_studio.plan_handoff import (
    PREPARATION_REQUIRED_KEYS,
    PREPARATION_SCHEMA,
    PlanHandoffCollector,
    preparation_package_template,
    render_preparation_template,
)

SPEC_ID = "SPEC-STUDIO-CHANGE-ABCDEF123456"
FORBIDDEN_CONTRACT_FIELDS = {
    "authority",
    "document_hash",
    "frozen_at",
    "implementation_allowed",
    "source_mutation_count",
    "status",
}


def _request() -> AgentRunRequest:
    return AgentRunRequest.model_validate(
        {
            "mode": "new_change",
            "runner": "codex",
            "objective": "Show the workspace branch name in the tab title",
            "acceptance_criteria": ["The tab title carries the branch name"],
        }
    )


def test_bounded_template_matches_the_accepted_package_shape() -> None:
    package = preparation_package_template(SPEC_ID, "Show the branch name", requirement_ids=("R1", "R2"))

    assert set(package) == set(PREPARATION_REQUIRED_KEYS)
    assert package["schema"] == PREPARATION_SCHEMA
    assert package["spec_id"] == SPEC_ID
    assert package["source_mutation_count"] == 0
    assert set(package["task_envelopes"]) == {"R1", "R2"}
    assert package["task_envelopes"]["R2"]["requirement"] == f"{SPEC_ID}#R2"
    assert not FORBIDDEN_CONTRACT_FIELDS & set(package["contract_request"])
    assert "contract_hash" not in package["task_envelopes"]["R1"]
    assert "document_hash" not in package["task_envelopes"]["R1"]
    assert package["contract_request"]["obligations"][0]["baseline"]["kind"] == "observed_red"


def test_bounded_template_is_accepted_by_the_plan_handoff_collector(tmp_path: Path) -> None:
    spec = tmp_path / "docs" / "specs" / f"{SPEC_ID}.md"
    spec.parent.mkdir(parents=True)
    spec.write_text(
        f"# {SPEC_ID} — Branch name in the tab title\n"
        f"> **apatch artifact:** `spec:{SPEC_ID}`\n\n"
        "## R1 Branch name in the tab title\n"
        "(verify: python3 -m pytest tests/frozen/test_branch_title.py -q)\n",
        encoding="utf-8",
    )
    prepared = tmp_path / ".apatch" / "sdd" / "prepared" / f"{SPEC_ID}.json"
    prepared.parent.mkdir(parents=True)
    prepared.write_text(render_preparation_template(SPEC_ID, "Show the branch name"), encoding="utf-8")

    handoff = PlanHandoffCollector(tmp_path).resolve({})

    assert handoff["status"] == "review_ready"
    assert handoff["spec_id"] == SPEC_ID
    assert handoff["requirement_ids"] == ["R1"]


def test_bounded_prompt_embeds_the_template_and_explicit_verification() -> None:
    run_id = "apr_" + "c" * 32
    _, spec_id = planning_contract_ids(run_id)
    prompt = build_governed_prompt(
        _request(),
        studio_run_id=run_id,
        planning_contract_run_id=run_id,
        planning_context="",
    )

    assert f".apatch/sdd/prepared/{spec_id}.json" in prompt
    assert "Preparation package template" in prompt
    start = prompt.index('{\n  "contract_request"')
    end = prompt.index("\n}\n", start) + 2
    package = json.loads(prompt[start:end])
    assert set(package) == set(PREPARATION_REQUIRED_KEYS)
    assert package["spec_id"] == spec_id
    assert package["task_envelopes"]["R1"]["requirement"] == f"{spec_id}#R1"
    assert package["objective"] == "Show the workspace branch name in the tab title"
    assert "--collect-only" in prompt
    assert "never run them as the blocking verification" in prompt
    assert "apatch_resume_session" in prompt
    assert "using schema apatch.studio.sdd-preparation.v1 so Studio can present it" not in prompt


def test_bounded_prompt_without_a_run_id_keeps_a_placeholder_spec_id() -> None:
    prompt = build_governed_prompt(_request(), planning_context="")

    assert ".apatch/sdd/prepared/<preallocated SPEC id>.json" in prompt
    assert '"requirement": "<preallocated SPEC id>#R1"' in prompt


def test_bounded_timeout_budget_is_three_hundred_seconds() -> None:
    assert DEFAULT_PLAN_TIMEOUT_SECONDS == 300.0
    parameter = inspect.signature(AgentRunManager).parameters["planning_timeout_seconds"]
    assert parameter.default == 300.0
