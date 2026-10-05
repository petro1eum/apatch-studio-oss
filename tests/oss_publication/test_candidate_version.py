from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "release" / "candidate.json"
PUBLICATION = ROOT / "release" / "publication.json"
_REQUIREMENTS = {
    "0.1.2": "SPEC-STUDIO-COWORK-RESULT-DELIVERY-1#R6",
    "0.1.3": "SPEC-STUDIO-INTERACTIVE-CHANGE-1#R2",
    "0.1.4": "SPEC-STUDIO-READ-INDEX-1#R1",
}
_UI_FILES = ("frontend/src/ChangeDetailView.tsx", "frontend/src/outside-in.css")
_READ_MODEL_FILES = (
    "apatch_studio/adapter.py",
    "apatch_studio/app.py",
    "apatch_studio/read_index.py",
    "frontend/src/OutsideInAdmin.tsx",
    "frontend/src/OutsideInApp.tsx",
    "frontend/src/OutsideInViews.tsx",
    "frontend/src/readModelVisibility.ts",
    "frontend/src/types.ts",
)


def _version(value: str) -> tuple[int, int, int]:
    assert re.fullmatch(r"0\.[0-9]+\.[0-9]+", value)
    return tuple(int(part) for part in value.split("."))


def _git(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")[:300]
    return result.stdout


def _assert_candidate_binding(root: Path) -> None:
    candidate = json.loads((root / "release/candidate.json").read_text(encoding="utf-8"))
    publication = json.loads((root / "release/publication.json").read_text(encoding="utf-8"))
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    assert set(candidate) == {
        "schema", "version", "previous_published_version", "source_commit",
        "source_file", "source_file_sha256", "requirement",
    }
    assert candidate["schema"] == "apatch.studio.oss-candidate.v1"
    assert candidate["version"] == project["version"]
    assert _version(candidate["version"]) > _version(candidate["previous_published_version"])
    assert publication["version"] in {
        candidate["previous_published_version"], candidate["version"],
    }
    assert candidate["version"] in _REQUIREMENTS
    assert candidate["requirement"] == _REQUIREMENTS[candidate["version"]]
    commit = candidate["source_commit"]
    assert re.fullmatch(r"[0-9a-f]{40}", commit)
    assert _git(root, "rev-parse", commit).decode().strip() == commit
    _git(root, "merge-base", "--is-ancestor", commit, "HEAD")
    source_file = candidate["source_file"]
    expected_file = (
        "apatch_studio/read_index.py" if candidate["version"] == "0.1.4"
        else _UI_FILES[0] if candidate["version"] == "0.1.3"
        else "apatch_studio/result_delivery.py"
    )
    assert source_file == expected_file
    source = _git(root, "show", f"{commit}:{source_file}")
    assert hashlib.sha256(source).hexdigest() == candidate["source_file_sha256"]
    assert (root / source_file).read_bytes() == source
    if candidate["version"] == "0.1.3":
        assert candidate["previous_published_version"] == "0.1.2"
        binding = json.loads((root / "release/ui-source-binding.json").read_text(encoding="utf-8"))
        assert set(binding) == {"schema", "version", "requirement", "source_commit", "files"}
        assert binding["schema"] == "apatch.studio.ui-source-binding.v1"
        for field in ("version", "requirement", "source_commit"):
            assert binding[field] == candidate[field]
        assert [entry["path"] for entry in binding["files"]] == list(_UI_FILES)
        for entry in binding["files"]:
            assert set(entry) == {"path", "sha256"}
            assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
            recorded = _git(root, "show", f"{commit}:{entry['path']}")
            assert hashlib.sha256(recorded).hexdigest() == entry["sha256"]
            assert (root / entry["path"]).read_bytes() == recorded
        assert binding["files"][0]["sha256"] == candidate["source_file_sha256"]
    if candidate["version"] == "0.1.4":
        _assert_incremental_binding(root, candidate)


def test_governed_candidate_version_is_exact_and_advances() -> None:
    _assert_candidate_binding(ROOT)


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


@pytest.fixture
def ui_candidate(tmp_path: Path) -> Path:
    """Unsigned disposable Git fixture; no release, owner or attestation evidence."""
    root = tmp_path / "fixture"
    root.mkdir()
    _git(root, "init", "-q")
    for source_file in (*_UI_FILES, "apatch_studio/result_delivery.py"):
        path = root / source_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Exact synthetic fixture bytes: " + source_file + "\n")
    (root / "pyproject.toml").write_text('[project]\nversion = "0.1.3"\n')
    _git(root, "add", "--all")
    _git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test", "-c", "commit.gpgsign=false", "commit", "--no-verify", "-qm", "Synthetic candidate binding fixture")
    commit = _git(root, "rev-parse", "HEAD").decode().strip()
    files = [{"path": p, "sha256": hashlib.sha256((root / p).read_bytes()).hexdigest()} for p in _UI_FILES]
    _write_json(root / "release/publication.json", {"version": "0.1.2"})
    _write_json(root / "release/candidate.json", {
        "schema": "apatch.studio.oss-candidate.v1", "version": "0.1.3",
        "previous_published_version": "0.1.2", "source_commit": commit,
        "source_file": _UI_FILES[0], "source_file_sha256": files[0]["sha256"],
        "requirement": _REQUIREMENTS["0.1.3"],
    })
    _write_json(root / "release/ui-source-binding.json", {
        "schema": "apatch.studio.ui-source-binding.v1", "version": "0.1.3",
        "requirement": _REQUIREMENTS["0.1.3"], "source_commit": commit, "files": files,
    })
    return root


def test_exact_readability_candidate_binds_both_ui_files(ui_candidate: Path) -> None:
    _assert_candidate_binding(ui_candidate)


def test_historical_published_candidate_retains_its_exact_binding(ui_candidate: Path) -> None:
    (ui_candidate / "pyproject.toml").write_text('[project]\nversion = "0.1.2"\n')
    path = ui_candidate / "release/candidate.json"
    candidate = json.loads(path.read_text())
    candidate.update({
        "version": "0.1.2", "previous_published_version": "0.1.1",
        "source_file": "apatch_studio/result_delivery.py",
        "source_file_sha256": hashlib.sha256((ui_candidate / "apatch_studio/result_delivery.py").read_bytes()).hexdigest(),
        "requirement": _REQUIREMENTS["0.1.2"],
    })
    _write_json(path, candidate)
    (ui_candidate / "release/ui-source-binding.json").unlink()
    _assert_candidate_binding(ui_candidate)


@pytest.mark.parametrize("failure", [
    "stale_requirement", "wrong_primary_file", "wrong_primary_hash",
    "primary_drift", "css_drift", "malformed_commit", "nonexistent_commit",
    "version_mismatch", "wrong_previous_version", "unrelated_publication",
    "extra_candidate_field", "binding_requirement", "binding_commit",
    "binding_version", "extra_binding_field", "missing_css", "reversed_files",
    "forged_css_hash", "extra_file_field", "missing_binding",
])
def test_candidate_rejects_inexact_ui_binding(ui_candidate: Path, failure: str) -> None:
    path = ui_candidate / "release/candidate.json"
    candidate = json.loads(path.read_text())
    binding_path = ui_candidate / "release/ui-source-binding.json"
    binding = json.loads(binding_path.read_text())
    fields = {
        "wrong_primary_file": ("source_file", _UI_FILES[1]),
        "wrong_primary_hash": ("source_file_sha256", "0" * 64),
        "malformed_commit": ("source_commit", "HEAD"),
        "nonexistent_commit": ("source_commit", "0" * 40),
        "version_mismatch": ("version", "0.1.4"),
        "wrong_previous_version": ("previous_published_version", "0.1.1"),
        "extra_candidate_field": ("caller_identity", "not-accepted"),
    }
    if failure in fields:
        key, value = fields[failure]
        candidate[key] = value
    elif failure == "stale_requirement":
        candidate.update({
            "requirement": _REQUIREMENTS["0.1.2"],
            "source_file": "apatch_studio/result_delivery.py",
            "source_file_sha256": hashlib.sha256((ui_candidate / "apatch_studio/result_delivery.py").read_bytes()).hexdigest(),
        })
    elif failure in {"primary_drift", "css_drift"}:
        (ui_candidate / _UI_FILES[failure == "css_drift"]).write_text("Changed after the exact source commit\n")
    elif failure == "unrelated_publication":
        _write_json(ui_candidate / "release/publication.json", {"version": "0.1.1"})
    elif failure in {"binding_requirement", "binding_commit", "binding_version"}:
        key = {"binding_requirement": "requirement", "binding_commit": "source_commit", "binding_version": "version"}[failure]
        binding[key] = "0" * 40 if key == "source_commit" else "inexact"
    elif failure == "extra_binding_field":
        binding["owner_identity"] = "not-accepted"
    elif failure == "missing_css":
        binding["files"].pop()
    elif failure == "reversed_files":
        binding["files"].reverse()
    elif failure == "forged_css_hash":
        binding["files"][1]["sha256"] = "0" * 64
    elif failure == "extra_file_field":
        binding["files"][0]["unexpected"] = True
    elif failure == "missing_binding":
        binding_path.unlink()
    _write_json(path, candidate)
    if failure != "missing_binding":
        _write_json(binding_path, binding)
    with pytest.raises((AssertionError, FileNotFoundError)):
        _assert_candidate_binding(ui_candidate)


def _assert_incremental_binding(root: Path, candidate: dict[str, object]) -> None:
    assert candidate["previous_published_version"] == "0.1.3"
    binding = json.loads(
        (root / "release/read-model-source-binding.json").read_text(encoding="utf-8")
    )
    assert set(binding) == {"schema", "version", "requirement", "source_commit", "files"}
    assert binding["schema"] == "apatch.studio.read-model-source-binding.v1"
    for field in ("version", "requirement", "source_commit"):
        assert binding[field] == candidate[field]
    assert [entry["path"] for entry in binding["files"]] == list(_READ_MODEL_FILES)
    for entry in binding["files"]:
        assert set(entry) == {"path", "sha256"}
        assert re.fullmatch(r"[0-9a-f]{64}", entry["sha256"])
        recorded = _git(root, "show", f"{candidate['source_commit']}:{entry['path']}")
        assert hashlib.sha256(recorded).hexdigest() == entry["sha256"]
        assert (root / entry["path"]).read_bytes() == recorded
    primary = next(entry for entry in binding["files"] if entry["path"] == candidate["source_file"])
    assert primary["sha256"] == candidate["source_file_sha256"]


@pytest.fixture
def incremental_candidate(ui_candidate: Path) -> Path:
    """Synthetic version fixture, not owner consent or release qualification."""
    root = ui_candidate
    for source_file in _READ_MODEL_FILES:
        path = root / source_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("Exact synthetic read model bytes: " + source_file + "\n")
    _git(root, "add", "--all")
    _git(root, "-c", "user.name=Fixture", "-c", "user.email=fixture@example.test",
         "-c", "commit.gpgsign=false", "commit", "--no-verify", "-qm",
         "Synthetic incremental source binding fixture")
    commit = _git(root, "rev-parse", "HEAD").decode().strip()
    files = [
        {"path": path, "sha256": hashlib.sha256((root / path).read_bytes()).hexdigest()}
        for path in _READ_MODEL_FILES
    ]
    primary = next(entry for entry in files if entry["path"] == "apatch_studio/read_index.py")
    _write_json(root / "release/candidate.json", {
        "schema": "apatch.studio.oss-candidate.v1", "version": "0.1.4",
        "previous_published_version": "0.1.3", "source_commit": commit,
        "source_file": primary["path"], "source_file_sha256": primary["sha256"],
        "requirement": _REQUIREMENTS["0.1.4"],
    })
    _write_json(root / "release/read-model-source-binding.json", {
        "schema": "apatch.studio.read-model-source-binding.v1", "version": "0.1.4",
        "requirement": _REQUIREMENTS["0.1.4"], "source_commit": commit, "files": files,
    })
    _write_json(root / "release/publication.json", {"version": "0.1.3"})
    (root / "pyproject.toml").write_text('[project]\nversion = "0.1.4"\n')
    return root


def test_exact_incremental_candidate_binds_every_runtime_and_ui_file(
    incremental_candidate: Path,
) -> None:
    _assert_candidate_binding(incremental_candidate)


@pytest.mark.parametrize("source_file", _READ_MODEL_FILES)
def test_incremental_candidate_rejects_each_source_file_drift(
    incremental_candidate: Path, source_file: str,
) -> None:
    (incremental_candidate / source_file).write_text("Changed after source binding\n")
    with pytest.raises(AssertionError):
        _assert_candidate_binding(incremental_candidate)


@pytest.mark.parametrize("failure", [
    "schema", "version", "requirement", "commit", "extra_binding_field",
    "missing_file", "extra_file", "duplicate_file", "reversed_files",
    "bad_hash", "forged_hash", "extra_file_field", "missing_binding",
    "wrong_previous_version", "wrong_primary_file", "wrong_primary_hash",
    "candidate_extra_field", "publication_mismatch",
])
def test_incremental_candidate_rejects_inexact_binding(
    incremental_candidate: Path, failure: str,
) -> None:
    root = incremental_candidate
    candidate_path = root / "release/candidate.json"
    candidate = json.loads(candidate_path.read_text())
    binding_path = root / "release/read-model-source-binding.json"
    binding = json.loads(binding_path.read_text())
    if failure in {"schema", "version", "requirement", "commit"}:
        key = "source_commit" if failure == "commit" else failure
        binding[key] = "0" * 40 if failure == "commit" else "inexact"
    elif failure == "extra_binding_field":
        binding["extra"] = True
    elif failure == "missing_file":
        binding["files"].pop()
    elif failure == "extra_file":
        binding["files"].append({"path": "unexpected.py", "sha256": "0" * 64})
    elif failure == "duplicate_file":
        binding["files"][1] = dict(binding["files"][0])
    elif failure == "reversed_files":
        binding["files"].reverse()
    elif failure in {"bad_hash", "forged_hash"}:
        binding["files"][0]["sha256"] = "not-a-hash" if failure == "bad_hash" else "0" * 64
    elif failure == "extra_file_field":
        binding["files"][0]["extra"] = True
    elif failure == "missing_binding":
        binding_path.unlink()
    elif failure == "wrong_previous_version":
        candidate["previous_published_version"] = "0.1.1"
    elif failure == "wrong_primary_file":
        candidate["source_file"] = _UI_FILES[0]
    elif failure == "wrong_primary_hash":
        candidate["source_file_sha256"] = "0" * 64
    elif failure == "candidate_extra_field":
        candidate["extra"] = True
    elif failure == "publication_mismatch":
        _write_json(root / "release/publication.json", {"version": "0.1.1"})
    _write_json(candidate_path, candidate)
    if failure != "missing_binding":
        _write_json(binding_path, binding)
    with pytest.raises((AssertionError, FileNotFoundError)):
        _assert_candidate_binding(root)
