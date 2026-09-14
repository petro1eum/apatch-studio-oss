from pathlib import Path

from apatch_studio.adapter import APatchStudioAdapter
from apatch_studio.project_documents import parse_markdown_blocks


ROOT = Path(__file__).resolve().parents[2]


def test_real_project_can_be_understood_from_brief_to_decision_lineage() -> None:
    adapter = APatchStudioAdapter(ROOT, cache_ttl=0)
    overview = adapter.overview(force=True)
    catalog = adapter.document_catalog()
    proposal = adapter.document_detail("RFP-011")
    specification = adapter.document_detail("SPEC-STUDIO-PROJECT-KNOWLEDGE-1")

    assert overview["project_brief"]["title"] == "APatch Studio OSS"
    assert "contract-driven work with AI agents" in overview["project_brief"]["purpose"]
    assert overview["plans"]["count"] == catalog["count"] >= 11
    assert all(item["id"] != "SPEC-TEMPLATE" for item in catalog["items"])
    assert any(
        "Project Knowledge and Decision Workspace" in item["title"]
        for item in catalog["items"]
    )
    assert proposal["kind"] == "proposal"
    assert {section["title"] for section in proposal["sections"]}.issuperset(
        {"1. Decision", "2. User jobs", "Acceptance", "Non-goals"}
    )
    assert len(proposal["acceptance"]) == 10
    assert specification["kind"] == "specification"
    assert specification["proposal_id"] == "RFP-011"
    assert specification["traceability"]["status"] == "complete"
    assert len(specification["requirements"]) == 11
    result_basis = next(
        item for item in specification["requirements"] if item["id"] == "R6"
    )
    assert result_basis["title"] == "Result decision basis"
    assert "requirement text" in result_basis["statement"]
    assert result_basis["acceptance"]["id"] == "KNOW-6"
    assert parse_markdown_blocks("```\nplain fenced content\n```")[0] == {
        "type": "code",
        "language": None,
        "text": "plain fenced content",
    }


def test_human_journey_is_wired_into_home_plans_and_change_results() -> None:
    shell = (ROOT / "frontend/src/OutsideInApp.tsx").read_text(encoding="utf-8")
    home = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
    plan = (ROOT / "frontend/src/ProjectPlanView.tsx").read_text(encoding="utf-8")
    change = (ROOT / "frontend/src/ChangeDetailView.tsx").read_text(encoding="utf-8")

    assert "View project plans" in home
    assert "Open plan" in home
    assert "<ProjectPlanView" in shell
    assert "View proposal" in plan
    assert "View specification" in plan
    assert "Run requirement" in plan
    assert "Why this result is proven" in change
    assert "DecisionBasisSection" in change
