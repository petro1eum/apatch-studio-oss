from pathlib import Path
import re

from apatch_studio.app import create_app


ROOT = Path(__file__).resolve().parents[2]


def test_interactive_change_release_journey_is_wired_end_to_end(tmp_path) -> None:
    shell = (ROOT / "frontend/src/OutsideInApp.tsx").read_text(encoding="utf-8")
    detail = (ROOT / "frontend/src/ChangeDetailView.tsx").read_text(encoding="utf-8")
    views = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
    api = (ROOT / "frontend/src/api.ts").read_text(encoding="utf-8")

    assert "route.resourceId ? (" in shell
    assert "changes.find((item) => item.id === route.resourceId)" in shell
    assert "loadChangeDetail(resourceId)" in detail
    assert "openChangeLocalReview(resourceId)" in detail
    assert "open_recorded_patch" in detail
    assert "detail.decision_basis" in detail
    assert "onOpenDocument" in detail
    assert "<ProjectPlanView" in shell
    assert "resourceId={route.resourceId}" in shell
    assert "data.plans.items.map" in views
    assert '"/api/v1/changes/" + encodeURIComponent(changeId)' in api

    class Adapter:
        def overview(self, *, force=False):
            return {"schema": "test.overview.v1", "changes": []}

        def change_detail(self, change_id):
            return {"change_id": change_id}

    app = create_app(str(tmp_path), adapter=Adapter(), frontend_root=tmp_path)
    routes = {
        (route.path, method)
        for route in app.routes
        for method in getattr(route, "methods", set())
    }
    assert ("/api/v1/changes/{change_id}", "GET") in routes
    assert ("/api/v1/changes/{change_id}/local-review", "POST") in routes


def test_interactive_change_release_keeps_the_design_and_security_floor() -> None:
    css = (ROOT / "frontend/src/outside-in.css").read_text(encoding="utf-8")
    shell = (ROOT / "frontend/src/OutsideInApp.tsx").read_text(encoding="utf-8")
    detail = (ROOT / "frontend/src/ChangeDetailView.tsx").read_text(encoding="utf-8")
    sizes = [int(value) for value in re.findall(r"font-size:\s*(\d+)px", css)]

    assert sizes and min(sizes) >= 11
    assert "window.confirm" not in shell + detail
    assert "repository_path" not in detail
    assert "workspace_path" not in detail
    assert "source_code" not in detail
    assert "No files were changed" in detail
    assert "Studio runner" in detail
    assert "Local operator" in detail
    assert "Recorded by" in detail
