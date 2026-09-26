from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CANDIDATE = ROOT / "release" / "candidate.json"
PUBLICATION = ROOT / "release" / "publication.json"


def _version(value: str) -> tuple[int, int, int]:
    assert re.fullmatch(r"0\.[0-9]+\.[0-9]+", value)
    return tuple(int(part) for part in value.split("."))


def _git(*args: str) -> bytes:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, check=False,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")[:300]
    return result.stdout


def test_governed_candidate_version_is_exact_and_advances() -> None:
    candidate = json.loads(CANDIDATE.read_text(encoding="utf-8"))
    publication = json.loads(PUBLICATION.read_text(encoding="utf-8"))
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]
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
    assert candidate["requirement"] == "SPEC-STUDIO-COWORK-RESULT-DELIVERY-1#R6"
    commit = candidate["source_commit"]
    assert re.fullmatch(r"[0-9a-f]{40}", commit)
    assert _git("rev-parse", commit).decode().strip() == commit
    _git("merge-base", "--is-ancestor", commit, "HEAD")
    source_file = candidate["source_file"]
    assert source_file == "apatch_studio/result_delivery.py"
    source = _git("show", f"{commit}:{source_file}")
    assert hashlib.sha256(source).hexdigest() == candidate["source_file_sha256"]
    assert (ROOT / source_file).read_bytes() == source
