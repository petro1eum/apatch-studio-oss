from __future__ import annotations

import email
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import venv
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[2]
PROHIBITED_MEMBERS = (
    "/pro/",
    "fleet_workflow.py",
    "local_team.py",
    "local_team_workflow.py",
    "release_qualification.py",
)


@pytest.fixture(scope="session")
def built_artifacts(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    output = tmp_path_factory.mktemp("studio-oss-artifacts")
    subprocess.run(
        [sys.executable, "-m", "build", "--outdir", str(output)],
        cwd=ROOT,
        check=True,
        env={**os.environ, "PYTHONNOUSERSITE": "1"},
    )
    wheels = list(output.glob("*.whl"))
    sdists = list(output.glob("*.tar.gz"))
    assert len(wheels) == len(sdists) == 1
    return wheels[0], sdists[0]


def _license_member(names: list[str]) -> str:
    matches = [name for name in names if name.endswith(".dist-info/licenses/LICENSE")]
    assert len(matches) == 1
    return matches[0]


def test_built_artifacts_enforce_the_oss_boundary(
    built_artifacts: tuple[Path, Path],
) -> None:
    wheel, sdist = built_artifacts
    expected_license = (ROOT / "LICENSE").read_bytes()

    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert archive.read(_license_member(names)) == expected_license
        assert any(name.startswith("apatch_studio/_web/assets/") and name.endswith(".js") for name in names)
        assert "apatch_studio/_web/index.html" in names
        metadata_name = next(name for name in names if name.endswith(".dist-info/METADATA"))
        metadata = email.message_from_bytes(archive.read(metadata_name))
        assert metadata["License-Expression"] == "MIT"
        requirements = metadata.get_all("Requires-Dist", [])
        assert requirements
        assert all("git+" not in requirement and " @ " not in requirement for requirement in requirements)
        assert not [name for name in names if any(marker in "/" + name for marker in PROHIBITED_MEMBERS)]

    with tarfile.open(sdist, "r:gz") as archive:
        names = archive.getnames()
        license_name = next(name for name in names if name.endswith("/LICENSE"))
        extracted = archive.extractfile(license_name)
        assert extracted is not None and extracted.read() == expected_license
        assert any("/frontend/dist/assets/" in name and name.endswith(".js") for name in names)
        assert not [name for name in names if any(marker in "/" + name for marker in PROHIBITED_MEMBERS)]


def test_isolated_wheel_serves_the_bundled_client(
    built_artifacts: tuple[Path, Path], tmp_path: Path,
) -> None:
    wheel, _sdist = built_artifacts
    environment = tmp_path / "venv"
    venv.EnvBuilder(with_pip=True).create(environment)
    python = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    subprocess.run(
        [str(python), "-m", "pip", "install", str(wheel)],
        cwd=tmp_path,
        check=True,
        env={**os.environ, "PYTHONNOUSERSITE": "1"},
        stdout=subprocess.DEVNULL,
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    subprocess.run(["git", "init", "-q", str(workspace)], check=True)
    script = r'''
import json
import sys
from fastapi.testclient import TestClient
from apatch_studio.app import create_app
from apatch_studio.cli import _parser

workspace = sys.argv[1]
app = create_app(workspace)
with TestClient(app, base_url="http://127.0.0.1:8765") as client:
    health = client.get("/api/v1/health")
    root = client.get("/")
    asset_path = next(route.path for route in app.routes if route.path == "/assets")
assert health.status_code == 200
assert root.status_code == 200
assert "__APATCH_STUDIO_SESSION__" not in root.text
assert asset_path == "/assets"
commands = set(_parser()._subparsers._group_actions[0].choices)
assert commands == {"serve", "name-this-machine", "enroll"}
print(json.dumps({"health": health.json(), "commands": sorted(commands)}))
'''
    completed = subprocess.run(
        [str(python), "-I", "-c", script, str(workspace)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONNOUSERSITE": "1"},
    )
    assert '"serve"' in completed.stdout
