from pathlib import Path

from apatch_studio.action_facade import (
    SpecInspectRequest,
    SpecRebindRequest,
    StudioWorkflowFacade,
)
from apatch_studio.operations import AgentRunRequest


def write_spec(root: Path):
    path = root / "docs/specs/SPEC-DEMO-1.md"
    path.parent.mkdir(parents=True)
    path.write_text(
        "# SPEC-DEMO-1 -- Demo\n\n"
        "## R1 Observable result\n\n"
        "(verify: python3 -c \"print('ok')\")\n",
        encoding="utf-8",
    )


def test_spec_facade_exposes_lint_status_next_and_reality(tmp_path):
    write_spec(tmp_path)
    facade = StudioWorkflowFacade(tmp_path)

    lint = facade.inspect_spec(
        "SPEC-DEMO-1",
        SpecInspectRequest(request_id="apsreq_specs_lint_001", action="lint"),
    )
    status = facade.inspect_spec(
        "SPEC-DEMO-1",
        SpecInspectRequest(request_id="apsreq_specs_status_001", action="status"),
    )
    next_item = facade.inspect_spec(
        "SPEC-DEMO-1",
        SpecInspectRequest(request_id="apsreq_specs_next_001", action="next"),
    )
    reality = facade.inspect_spec(
        "SPEC-DEMO-1",
        SpecInspectRequest(request_id="apsreq_specs_reality_001", action="reality"),
    )

    assert lint["command"] == "spec_lint"
    assert lint["result"]["counts"]["errors"] >= 0
    assert status["result"]["requirements"][0]["id"] == "R1"
    assert next_item["result"]["next"]["id"] == "R1"
    assert reality["result"]["counts"] == {
        "covered": 0,
        "pending": 0,
        "uncovered": 0,
    }


def test_selective_rebind_passes_exact_include_and_exclude(monkeypatch, tmp_path):
    write_spec(tmp_path)
    captured = {}

    def fake_rebind(target_dir, **kwargs):
        captured.update(kwargs)
        return {"ok": True, "rebound": ["R1"], "preserved_stale": ["R2"]}

    monkeypatch.setattr("apatch_studio.action_facade.rebind_stale_requirements", fake_rebind)
    receipt = StudioWorkflowFacade(tmp_path).rebind_spec(
        "SPEC-DEMO-1",
        SpecRebindRequest(
            request_id="apsreq_specs_rebind_001",
            requirement_ids=["R1"],
            exclude_requirement_ids=["R2"],
            confirmed=True,
        ),
    )
    assert receipt["result"]["rebound"] == ["R1"]
    assert captured["requirement_ids"] == ["R1"]
    assert captured["exclude_requirement_ids"] == ["R2"]
    assert captured["run_verify"] is True


def test_agent_requests_cover_exact_requirement_whole_spec_and_rfp_scaffold():
    requirement = AgentRunRequest(
        mode="requirement",
        runner="codex",
        objective="Execute R2",
        spec_id="SPEC-DEMO-1",
        requirement_id="R2",
    )
    whole = AgentRunRequest(
        mode="specification",
        runner="codex",
        objective="Execute all prepared requirements",
        spec_id="SPEC-DEMO-1",
    )
    scaffold = AgentRunRequest(
        mode="spec_scaffold",
        runner="codex",
        objective="Scaffold the executable contract",
        spec_id="SPEC-DEMO-2",
        rfp_id="RFP-020",
    )
    assert requirement.requirement_id == "R2"
    assert whole.mode == "specification"
    assert scaffold.rfp_id == "RFP-020"


def test_specs_ui_exposes_actions_not_only_counts():
    root = Path(__file__).resolve().parents[2]
    app = "\n".join((root / path).read_text(encoding="utf-8") for path in [
        "frontend/src/OutsideInViews.tsx", "frontend/src/ProjectPlanView.tsx",
    ])
    api = (root / "frontend/src/api.ts").read_text(encoding="utf-8")
    for label in [
        "Work to be done",
        "Run requirement",
        "Re-check",
        "Inspect proof",
        "Review scope & tests",
    ]:
        assert label in app
    assert "inspectSpec" in api
    assert "rebindSpec" in api
