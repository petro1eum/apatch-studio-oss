from __future__ import annotations

import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from apatch_studio.app import create_app
from apatch_studio.result_delivery import ResultPreviewRequest, ResultSubmitRequest


ROOT = Path(__file__).resolve().parents[2]


class Adapter:
    def overview(self, *, force=False):
        return {
            "schema": "apatch.studio.workspace-overview.v1",
            "workspace": {"name": "result-delivery", "clean": True},
            "force": force,
        }


class Runs:
    def close(self):
        pass


class Intents:
    trusted_origins = frozenset()
    workspace_id = "workspace-result-delivery"

    def __init__(self):
        self.calls = []

    def summary(self):
        return {
            "schema": "apatch.studio.execution-intent-summary.v1",
            "available": True,
            "configured": True,
            "workspace_id": self.workspace_id,
            "cowork_connected": True,
            "pending": 0,
            "attention": 0,
        }

    def preview_result(self, intent_id, request):
        assert isinstance(request, ResultPreviewRequest)
        self.calls.append(("preview", intent_id, request.model_dump()))
        return {
            "schema": "apatch.studio.cowork-result-delivery-plan.v1",
            "plan_hash": "sha256:" + "1" * 64,
            "result": {"relative_path": request.relative_path},
        }

    def submit_result(self, intent_id, request):
        assert isinstance(request, ResultSubmitRequest)
        self.calls.append(("submit", intent_id, request.model_dump()))
        return {
            "schema": "apatch.studio.cowork-result-delivery.v1",
            "intent_id": intent_id,
            "state": "submitted",
            "plan_hash": request.plan["plan_hash"],
        }


def test_result_delivery_routes_accept_only_closed_preview_and_submit_requests(tmp_path):
    intents = Intents()
    app = create_app(
        str(tmp_path),
        adapter=Adapter(),
        run_manager=Runs(),
        frontend_root=tmp_path,
        intent_manager=intents,
    )
    headers = {
        "x-apatch-studio-session": app.state.studio_guard.token,
        "origin": "http://127.0.0.1:8765",
    }
    intent_id = "tcapsei_" + "1" * 32
    base = f"/api/v1/execution-intents/{intent_id}/result"
    plan = {"plan_hash": "sha256:" + "2" * 64}
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        preview = client.post(
            base + "/preview",
            headers=headers,
            json={"relative_path": "reports/result.md"},
        )
        rejected = client.post(
            base + "/preview",
            headers=headers,
            json={"relative_path": "reports/result.md", "outcome_ref": "client-value"},
        )
        submitted = client.post(
            base + "/submit",
            headers=headers,
            json={
                "relative_path": "reports/result.md",
                "plan": plan,
                "confirmation": "submit:" + plan["plan_hash"],
            },
        )

    assert preview.status_code == 200
    assert rejected.status_code == 422
    assert submitted.status_code == 202
    assert intents.calls == [
        ("preview", intent_id, {"relative_path": "reports/result.md"}),
        (
            "submit",
            intent_id,
            {
                "relative_path": "reports/result.md",
                "plan": plan,
                "confirmation": "submit:" + plan["plan_hash"],
            },
        ),
    ]


def test_inbox_production_build_contains_the_complete_human_delivery_path():
    built = subprocess.run(
        ["npm", "--prefix", "frontend", "run", "build"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert built.returncode == 0, built.stdout + built.stderr
    javascript = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted((ROOT / "frontend" / "dist" / "assets").glob("*.js"))
    )
    for text in (
        "Result file",
        "Prepare submission",
        "Shared with Cowork",
        "Kept on this computer",
        "Exact confirmation",
        "Submit to Cowork",
        "Submitted to Cowork",
        "/result/preview",
        "/result/submit",
    ):
        assert text in javascript
    source = (ROOT / "frontend" / "src" / "OutsideInAdmin.tsx").read_text(
        encoding="utf-8"
    )
    for forbidden_input in (
        'aria-label="Outcome hash"',
        'aria-label="Evidence bundle ID"',
        'aria-label="Release ID"',
        'aria-label="Credential"',
        "Accept result",
        "Reject result",
        "Complete work item",
    ):
        assert forbidden_input not in source
