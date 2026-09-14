from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_plan_reader_uses_existing_bounded_studio_actions() -> None:
    source = (ROOT / "frontend/src/ProjectPlanView.tsx").read_text(encoding="utf-8")
    api = (ROOT / "frontend/src/api.ts").read_text(encoding="utf-8")

    assert "loadDocument(documentId)" in source
    assert 'mode: "requirement"' in source
    assert "startRun({" in source
    assert "rebindSpec(specificationId, [requirement.id], [])" in source
    assert 'inspectSpec(specificationId, "status")' in source
    assert "onOpenDocument" in source
    assert "onBack" in source
    assert "Run requirement" in source
    assert "Re-check" in source
    assert "Inspect proof" in source
    assert 'request<ProjectDocument>("/api/v1/documents/"' in api
    assert "window.confirm" not in source
