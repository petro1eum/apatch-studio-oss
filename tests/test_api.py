from pathlib import Path

from fastapi.testclient import TestClient

from apatch_studio.agent_runs import AgentRunManager
from apatch_studio.app import create_app

ROOT = Path(__file__).resolve().parents[1]


class FakeAdapter:
    def overview(self, *, force=False):
        return {
            "schema": "apatch.studio.workspace-overview.v1",
            "workspace": {"name": "demo", "clean": True},
            "force": force,
        }



def test_missing_or_incomplete_frontend_is_not_ready(tmp_path):
    import shutil

    frontend = tmp_path / "frontend"
    shutil.copytree(ROOT / "frontend" / "dist", frontend)
    app = create_app(str(tmp_path), adapter=FakeAdapter(), frontend_root=frontend)
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        ready = client.get("/api/v1/health")
        assert ready.status_code == 200 and ready.json()["frontend_ready"]
        script = next((frontend / "assets").glob("*.js"))
        script.unlink()
        unavailable = client.get("/api/v1/health")
        assert unavailable.status_code == 503
        assert unavailable.json()["ok"] is False
        assert unavailable.json()["frontend_ready"] is False


def _distribution_stage(tmp_path):
    import shutil

    stage = tmp_path / "source"
    stage.mkdir()
    for name in ("pyproject.toml", "README.md", "LICENSE", "MANIFEST.in"):
        shutil.copy2(ROOT / name, stage / name)
    shutil.copytree(ROOT / "apatch_studio", stage / "apatch_studio",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "_web"))
    frontend = stage / "frontend"
    frontend.mkdir()
    for directory in ("src", "public", "dist"):
        shutil.copytree(ROOT / "frontend" / directory, frontend / directory)
    for pattern in ("*.json", "*.ts", "index.html"):
        for path in (ROOT / "frontend").glob(pattern):
            shutil.copy2(path, frontend / path.name)
    return stage


def _build_distribution(stage, output, operation, *, expect_success=True):
    import os
    import subprocess
    import sys

    output.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([sys.executable, "-E", "-P", "-c",
        "from setuptools import build_meta; import sys; "
        "print(getattr(build_meta, sys.argv[1])(sys.argv[2]))",
        operation, str(output)], cwd=stage, capture_output=True, text=True,
        timeout=90, env={**os.environ, "PATH": str(stage / "no-node-on-path")})
    if expect_success:
        assert result.returncode == 0, result.stdout + result.stderr
        return output / result.stdout.strip().splitlines()[-1]
    assert result.returncode != 0, result.stdout
    assert "Frontend build missing or incomplete" in result.stdout + result.stderr


def test_wheel_and_sdist_ship_the_actual_ui_without_checkout_or_node(tmp_path):
    import json
    import os
    import subprocess
    import sys
    import tarfile
    import zipfile

    stage = _distribution_stage(tmp_path)
    wheel = _build_distribution(stage, tmp_path / "wheel", "build_wheel")
    sdist = _build_distribution(stage, tmp_path / "sdist", "build_sdist")
    with tarfile.open(sdist) as archive:
        names = archive.getnames()
        assert any(name.endswith("/frontend/src/OutsideInApp.tsx") for name in names)
        assert any(name.endswith("/frontend/package-lock.json") for name in names)
        assert any(name.endswith("/frontend/dist/index.html") for name in names)
        assert not any("/node_modules/" in name or "/.apatch/" in name for name in names)
        archive.extractall(tmp_path / "unpacked-sdist", filter="data")
    unpacked_source = next((tmp_path / "unpacked-sdist").iterdir())
    rebuilt = _build_distribution(unpacked_source, tmp_path / "rebuilt-wheel", "build_wheel")
    probe = """
import json, re, sys
from pathlib import Path
installed, work = map(Path, sys.argv[1:])
sys.path.insert(0, str(installed))
import apatch_studio.app as implementation
from apatch_studio.agent_runs import AgentRunManager
from fastapi.testclient import TestClient
assert Path(implementation.__file__).resolve().is_relative_to(installed.resolve())
assert implementation._frontend_root() == installed / "apatch_studio" / "_web"
class Adapter:
    def overview(self, *, force=False):
        return {"schema": "test"}
app = implementation.create_app(str(work), adapter=Adapter(),
    identity_root=work.parent / "identity",
    run_manager=AgentRunManager(work, state_root=work.parent / "runs"))
with TestClient(app, base_url="http://127.0.0.1:8765") as client:
    assert client.get("/api/v1/health").status_code == 200
    response = client.get("/")
    assert response.status_code == 200
    assert "__APATCH_STUDIO_SESSION__" not in response.text
    assert app.state.studio_guard.token in response.text
    assets = re.findall(r'(?:src|href)\\s*=\\s*["\\']([^"\\']+)["\\']', response.text)
    assert "/theme-init.js" in assets and any(path.endswith(".js") for path in assets)
    for path in assets:
        asset = client.get(path)
        assert asset.status_code == 200 and asset.content, path
    assert client.get("/theme-init.js").headers["content-type"].startswith("application/javascript")
    assert client.get("/api/v1/health").json()["frontend_ready"] is True
print(json.dumps({"ready": True, "assets": len(assets)}))
"""
    for number, artifact in enumerate((wheel, rebuilt)):
        install = tmp_path / f"installed-{number}"
        with zipfile.ZipFile(artifact) as archive:
            assert "apatch_studio/_web/index.html" in archive.namelist()
            assert "apatch_studio/_web/theme-init.js" in archive.namelist()
            archive.extractall(install)
        work = tmp_path / f"consumer-{number}"
        work.mkdir()
        result = subprocess.run([sys.executable, "-E", "-P", "-c", probe, str(install), str(work)],
            cwd=work, capture_output=True, text=True, timeout=45,
            env={**os.environ, "PATH": str(work / "no-node-on-path")})
        assert result.returncode == 0, result.stdout + result.stderr
        assert json.loads(result.stdout.strip().splitlines()[-1])["ready"] is True


def test_distribution_build_refuses_an_absent_frontend(tmp_path):
    import shutil

    stage = _distribution_stage(tmp_path)
    shutil.rmtree(stage / "frontend" / "dist")
    _build_distribution(stage, tmp_path / "wheel", "build_wheel", expect_success=False)


def test_authenticated_overview_and_refresh(tmp_path):
    app = create_app(str(tmp_path), adapter=FakeAdapter(), frontend_root=tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    token = app.state.studio_guard.token
    auth = {"x-apatch-studio-session": token}

    response = client.get("/api/v1/overview", headers=auth)
    assert response.status_code == 200
    assert response.json()["workspace"]["name"] == "demo"

    response = client.post(
        "/api/v1/refresh",
        headers={**auth, "origin": "http://127.0.0.1:8765"},
    )
    assert response.status_code == 200
    assert response.json()["force"] is True


def test_missing_frontend_is_explicit(tmp_path):
    app = create_app(str(tmp_path), adapter=FakeAdapter(), frontend_root=tmp_path)
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    response = client.get("/")
    assert response.status_code == 503
    assert response.json()["error"] == "frontend build missing"


def test_index_injects_process_token_without_cookie_or_url(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text(
        '<meta name="apatch-studio-session" '
        'content="__APATCH_STUDIO_SESSION__">',
        encoding="utf-8",
    )
    app = create_app(str(tmp_path), adapter=FakeAdapter(), frontend_root=frontend)
    client = TestClient(app, base_url="http://127.0.0.1:8765")

    response = client.get("/")

    token = app.state.studio_guard.token
    assert response.status_code == 200
    assert token in response.text
    assert "__APATCH_STUDIO_SESSION__" not in response.text
    assert token not in str(response.request.url)
    assert "set-cookie" not in response.headers
    assert response.headers["cache-control"] == "no-store"


def test_theme_initializer_is_served_as_javascript(tmp_path):
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "index.html").write_text("<main>Studio shell</main>", encoding="utf-8")
    (frontend / "theme-init.js").write_text("document.documentElement.dataset.theme = 'system';\n", encoding="utf-8")
    app = create_app(str(tmp_path), adapter=FakeAdapter(), frontend_root=frontend)
    client = TestClient(app, base_url="http://127.0.0.1:8765")

    response = client.get("/theme-init.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert response.text == "document.documentElement.dataset.theme = 'system';\n"
    assert "Studio shell" not in response.text


def test_authenticated_real_workspace_smoke(tmp_path):
    run_manager = AgentRunManager(ROOT, state_root=tmp_path / "state")
    app = create_app(
        str(ROOT),
        run_manager=run_manager,
        frontend_root=ROOT / "frontend" / "dist",
    )
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = client.get(
            "/api/v1/overview",
            headers={"x-apatch-studio-session": app.state.studio_guard.token},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema"] == "apatch.studio.workspace-overview.v1"
    assert payload["workspace"]["name"] == ROOT.name
    assert payload["runtime"]["apatch_version"] == payload["runtime"]["requirements"]["installed_version"]
    assert payload["runtime"]["mcp_profile"] == "full"
    assert payload["runtime"]["tool_count"] >= 120
    assert payload["runtime"]["requirements"]["schema"] == "apatch.studio.runtime-requirements.v1"
    assert isinstance(payload["runtime"]["requirements"]["ok"], bool)
    assert isinstance(payload["specifications"], list)
