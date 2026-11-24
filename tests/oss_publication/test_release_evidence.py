from __future__ import annotations

import hashlib
import json
import re
import runpy
import subprocess
import tomllib
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "release" / "publication.json"
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
FORBIDDEN_PLACEHOLDERS = {"head", "latest", "main", "master", "pending", "todo", "tbd", "unknown"}


def _load() -> dict[str, object]:
    return json.loads(EVIDENCE.read_text(encoding="utf-8"))


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_release_evidence_is_complete_and_immutable() -> None:
    evidence = _load()
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = str(project["version"])

    assert evidence["schema"] == "apatch.studio.oss-publication.v1"
    assert evidence["version"] == version
    assert HEX_40.fullmatch(str(evidence["source_commit"]))
    assert HEX_40.fullmatch(str(evidence["public_candidate_commit"]))

    serialized = json.dumps(evidence, sort_keys=True).lower()
    for placeholder in FORBIDDEN_PLACEHOLDERS:
        assert not re.search(rf'[:\s\"/]({placeholder})(?:[\s\"/,}}]|$)', serialized)

    candidate = str(evidence["public_candidate_commit"])
    if version == "0.1.7":
        source = json.loads((ROOT / "release/candidate.json").read_text())["source_commit"]
        assert candidate == evidence["source_commit"] == source
    assert _git("cat-file", "-e", f"{candidate}^{{commit}}").returncode == 0
    assert _git("merge-base", "--is-ancestor", candidate, "HEAD").returncode == 0

    artifacts = evidence["artifacts"]
    assert isinstance(artifacts, list)
    assert [item["filename"] for item in artifacts] == [
        f"apatch_studio-{version}-py3-none-any.whl",
        f"apatch_studio-{version}.tar.gz",
    ]
    assert all(HEX_64.fullmatch(item["sha256"]) for item in artifacts)

    verification = evidence["verification"]
    assert isinstance(verification, list) and len(verification) == 5
    assert all(item["command"].strip() for item in verification)
    assert all(item["result"].startswith("passed") for item in verification)


def test_local_release_artifacts_match_recorded_hashes_when_present() -> None:
    evidence = _load()

    for item in evidence["artifacts"]:
        artifact = ROOT / "dist" / item["filename"]
        if artifact.exists():
            assert hashlib.sha256(artifact.read_bytes()).hexdigest() == item["sha256"]


@pytest.mark.parametrize("fault", ["none", "wrong_tag", "changed_wheel", "extra", "missing_sdist", "symlink"])
def test_upload_uses_only_the_reviewed_release_bytes(tmp_path, fault):
    verify = runpy.run_path(str(ROOT / "tools/verify_release_archives.py"))["verify_archives"]
    (tmp_path / "pyproject.toml").write_text('[project]\nversion="0.1.7"\n')
    dist = tmp_path / "dist"
    dist.mkdir()
    rows = []
    for name in ("apatch_studio-0.1.7-py3-none-any.whl", "apatch_studio-0.1.7.tar.gz"):
        data = name.encode()
        (dist / name).write_bytes(data)
        rows.append({"filename": name, "sha256": hashlib.sha256(data).hexdigest()})
    (tmp_path / "release").mkdir()
    (tmp_path / "release/publication.json").write_text(json.dumps({"version": "0.1.7", "artifacts": rows}))
    tag = "v0.1.7"
    wheel = dist / rows[0]["filename"]
    if fault == "none":
        assert verify(tmp_path, dist, tag) == wheel
        return
    if fault == "wrong_tag":
        tag = "v0.1.6"
    elif fault == "changed_wheel":
        wheel.write_bytes(b"other build")
    elif fault == "extra":
        (dist / "unreviewed.whl").touch()
    elif fault == "missing_sdist":
        (dist / rows[1]["filename"]).unlink()
    elif fault == "symlink":
        other = tmp_path / "outside"
        wheel.rename(other)
        wheel.symlink_to(other)
    with pytest.raises(ValueError):
        verify(tmp_path, dist, tag)
