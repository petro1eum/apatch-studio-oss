import json
from pathlib import Path

from apatch_studio.action_facade import (
    FixedPurposeRequest,
    StudioWorkflowFacade,
    present_action,
)


ROOT = Path(__file__).resolve().parents[2]


def test_runtime_and_proof_results_have_human_first_presentations() -> None:
    runtime = present_action(
        "system_doctor",
        {
            "ok": True,
            "action": "doctor",
            "version": "0.8.40",
            "profile": "full",
            "tool_count": 123,
            "concurrent_writers": True,
        },
    )
    proof = present_action(
        "evidence_verify",
        {
            "ok": False,
            "action": "verify",
            "checked": 4,
            "violation_count": 2,
        },
    )

    assert runtime["title"] == "Runtime is ready"
    assert runtime["summary"] == "The local APatch runtime can govern agent work."
    assert {"label": "Agent tools", "value": "123"} in runtime["facts"]
    assert proof["title"] == "Proof needs attention"
    assert proof["tone"] == "attention"
    assert "2 files need proof" in proof["summary"]


def test_receipt_keeps_technical_result_behind_a_safe_presentation(tmp_path: Path) -> None:
    facade = StudioWorkflowFacade(tmp_path)
    receipt = facade._complete(
        FixedPurposeRequest(request_id="apsreq_first_user_result"),
        "system_gc_preview",
        {},
        lambda: {
            "ok": True,
            "action": "gc_preview",
            "dry_run": True,
            "counts": {"orphan_count": 3},
            "action_required": True,
        },
    )

    assert receipt["presentation"]["title"] == "Cleanup preview is ready"
    assert receipt["presentation"]["next_action"] == "Review the candidates before cleaning up."
    assert receipt["result"]["counts"]["orphan_count"] == 3
    assert "source" not in json.dumps(receipt["presentation"]).lower()


def test_outside_in_surfaces_render_product_result_before_technical_json() -> None:
    views = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
    admin = (ROOT / "frontend/src/OutsideInAdmin.tsx").read_text(encoding="utf-8")

    assert "Technical details" in views
    assert "receipt.presentation" in views
    assert admin.count("<ActionResultView") >= 2
    assert "<ActionResultView" in views
    assert "JSON.stringify(receipt.result" not in admin
    assert views.count("JSON.stringify(receipt.result") == 1
