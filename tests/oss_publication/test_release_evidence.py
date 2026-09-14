from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path


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

    assert evidence["schema"] == "apatch.studio.oss-publication.v1"
    assert evidence["version"] == "0.1.0"
    assert HEX_40.fullmatch(str(evidence["source_commit"]))
    assert HEX_40.fullmatch(str(evidence["public_candidate_commit"]))

    serialized = json.dumps(evidence, sort_keys=True).lower()
    for placeholder in FORBIDDEN_PLACEHOLDERS:
        assert not re.search(rf'[:\s\"/]({placeholder})(?:[\s\"/,}}]|$)', serialized)

    candidate = str(evidence["public_candidate_commit"])
    assert _git("cat-file", "-e", f"{candidate}^{{commit}}").returncode == 0
    assert _git("merge-base", "--is-ancestor", candidate, "HEAD").returncode == 0

    artifacts = evidence["artifacts"]
    assert isinstance(artifacts, list)
    assert [item["filename"] for item in artifacts] == [
        "apatch_studio-0.1.0-py3-none-any.whl",
        "apatch_studio-0.1.0.tar.gz",
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
