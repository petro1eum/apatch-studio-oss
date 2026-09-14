import json
from pathlib import Path
import re
import tomllib

from apatch_studio.app import create_app

ROOT = Path(__file__).resolve().parents[1]


def test_product_boundary():
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = metadata["project"]
    readme = (ROOT / "README.md").read_text(encoding="utf-8").lower()
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8").lower()
    rfp = (ROOT / "docs/RFP-023-studio-oss-publication.md").read_text(encoding="utf-8")
    sandbox = json.loads((ROOT / ".apatch/sandbox.json").read_text(encoding="utf-8"))

    assert project["license"] == "MIT"
    assert project["description"] == "Local contract-driven workspace for governing AI-agent work with APatch and TrustChain Cowork"
    assert any(dep.startswith("apatch[mcp]>=0.8.45") for dep in project["dependencies"])
    assert "apatch studio oss" in readme
    assert "organization control plane" in readme
    assert "trustchain cowork" in readme
    assert "source code, diffs, prompts, credentials and private keys stay" in readme
    assert readme.index("npm --prefix frontend run build") < readme.index('.venv/bin/pip install -e ".[dev]"')
    guide = (ROOT / "docs/GETTING-STARTED.md").read_text(encoding="utf-8")
    assert "APatch Studio OSS" in guide
    assert "clean, independently installable OSS client" in rfp
    assert "mit license" in license_text
    assert not (ROOT / "apatch").exists()
    assert not (ROOT / "frontend/tsconfig.app.tsbuildinfo").exists()
    assert {"apatch_studio/**", "frontend/src/**", "tests/**", "docs/**"}.issubset(
        set(sandbox["protected_globs"])
    )
    assert not {"tests/**", "docs/*.md", "*.md"}.intersection(sandbox["allow_globs"])


def test_rfp_traceability():
    rfp = (ROOT / "docs/RFP-001-studio-foundation.md").read_text(encoding="utf-8")
    spec = (ROOT / "docs/specs/SPEC-STUDIO-FOUNDATION-1.md").read_text(encoding="utf-8")
    acceptance_rows = re.findall(r"\| (ST-\d+) \|", rfp)
    traced_rows = re.findall(r"\| (ST-\d+) \| R\d+ \| covered \|", spec)
    assert len(acceptance_rows) == len(set(acceptance_rows)) == 8
    assert len(traced_rows) == len(set(traced_rows)) == 8
    assert set(acceptance_rows) == set(traced_rows) == {f"ST-{index}" for index in range(1, 9)}


def test_api_is_fixed_purpose_without_shell_or_mcp_relay(tmp_path):
    class FakeAdapter:
        def overview(self, *, force=False):
            return {"ok": True}

    app = create_app(str(tmp_path), adapter=FakeAdapter(), frontend_root=tmp_path)
    routes = {
        (route.path, method)
        for route in app.routes
        for method in getattr(route, "methods", set())
        if route.path.startswith("/api/")
    }
    assert routes == {
        ("/api/v1/health", "GET"),
        ("/api/v1/overview", "GET"),
        ("/api/v1/refresh", "POST"),
        ("/api/v1/documents", "GET"),
        ("/api/v1/documents/{document_id}", "GET"),
        (
            "/api/v1/specs/{spec_id}/requirements/{requirement_id}/execution-contract",
            "GET",
        ),
        ("/api/v1/specs/{spec_id}/requirements/{requirement_id}/lock", "GET"),
        (
            "/api/v1/specs/{spec_id}/requirements/{requirement_id}/lock/release-request",
            "POST",
        ),
        (
            "/api/v1/specs/{spec_id}/requirements/{requirement_id}/lock/release-answer",
            "POST",
        ),
        (
            "/api/v1/specs/{spec_id}/requirements/{requirement_id}/execution-contract/freeze",
            "POST",
        ),
        ("/api/v1/specs/{spec_id}/inspect", "POST"),
        ("/api/v1/specs/{spec_id}/rebind", "POST"),
        ("/api/v1/evidence/actions", "POST"),
        ("/api/v1/assets/search", "POST"),
        ("/api/v1/assets/suggest", "POST"),
        ("/api/v1/assets/{asset_id}/actions", "POST"),
        ("/api/v1/system/actions", "POST"),
        ("/api/v1/policies/actions", "POST"),
        ("/api/v1/workspaces/actions", "POST"),
        ("/api/v1/runners", "GET"),
        ("/api/v1/runs", "GET"),
        ("/api/v1/changes", "GET"),
        ("/api/v1/changes/{change_id}", "GET"),
        ("/api/v1/changes/{change_id}/delivery-pack", "GET"),
        ("/api/v1/changes/{change_id}/acceptance", "POST"),
        ("/api/v1/changes/{change_id}/time-decision", "POST"),
        ("/api/v1/changes/{change_id}/local-review", "POST"),
        ("/api/v1/runs", "POST"),
        ("/api/v1/runs/{run_id}", "GET"),
        ("/api/v1/runs/{run_id}/cancel", "POST"),
        ("/api/v1/runs/{run_id}/retry", "POST"),
        ("/api/v1/runs/{run_id}/review-note", "POST"),
        ("/api/v1/runs/{run_id}/local-review", "POST"),
        ("/api/v1/delivery", "GET"),
        ("/api/v1/delivery/actions", "POST"),
        ("/api/v1/timesheet/actions", "POST"),
        ("/api/v1/contributions/health", "GET"),
    }
    assert not {method for _path, method in routes}.intersection({"PUT", "PATCH", "DELETE"})
    forbidden_terms = {
        "apply",
        "capability",
        "command",
        "execute",
        "mcp",
        "rollback",
        "shell",
        "tool",
    }
    assert not {
        term
        for path, _method in routes
        for term in forbidden_terms
        if term in path.lower()
    }
    assert app.openapi_url is None
    assert app.docs_url is None
    assert app.redoc_url is None
