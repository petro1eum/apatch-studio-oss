from __future__ import annotations

import re
from pathlib import Path

import tomllib


ROOT = Path(__file__).resolve().parents[2]
TRUSTCHAIN_LICENSE = """MIT License

Copyright (c) 2026 Ed Cherednik

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
PROHIBITED_PATHS = {
    "apatch_studio/pro",
    "apatch_studio/fleet_workflow.py",
    "apatch_studio/local_team.py",
    "apatch_studio/local_team_workflow.py",
    "apatch_studio/release_qualification.py",
    "frontend/src/ProAccessView.tsx",
    "frontend/src/ProViews.tsx",
    "frontend/src/LocalTeamView.tsx",
    "tests/pro",
    "tests/local_team",
    "docs/STUDIO-PRO-SERVER.md",
}


def tracked_files() -> list[Path]:
    return [
        path for path in ROOT.rglob("*")
        if path.is_file()
        and ".git" not in path.parts
        and ".venv" not in path.parts
        and "node_modules" not in path.parts
        and "__pycache__" not in path.parts
        and "dist" not in path.parts
    ]


def test_clean_public_source_boundary() -> None:
    assert (ROOT / "LICENSE").read_text(encoding="utf-8") == TRUSTCHAIN_LICENSE
    metadata = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    project = metadata["project"]
    assert project["license"] == "MIT"
    assert project["name"] == "apatch-studio"
    assert "private" not in project["description"].lower()
    for relative in PROHIBITED_PATHS:
        assert not (ROOT / relative).exists(), f"private implementation leaked: {relative}"
    cli = (ROOT / "apatch_studio/cli.py").read_text(encoding="utf-8")
    for forbidden in ("pro-init", "pro-serve", "--pro-origin", "--pro-tenant-id"):
        assert forbidden not in cli


def test_publication_hygiene_fails_closed() -> None:
    patterns = {
        "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |)PRIVATE KEY-----"),
        "GitHub token": re.compile(r"github_pat_[A-Za-z0-9_]{20,}"),
        "PyPI token": re.compile(r"pypi-[A-Za-z0-9_-]{20,}"),
        "machine path": re.compile(
            r"/Users/(?!person(?:/|\b)|private(?:/|\b)|example(?:/|\b))[^/\s]+/|[A-Z]:\\Users\\"
        ),
        "private repository": re.compile(r"github\.com/petro1eum/APatch_Studio(?:\.git)?"),
    }
    violations: list[str] = []
    for path in tracked_files():
        if path == Path(__file__).resolve():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(ROOT)
        for label, pattern in patterns.items():
            if pattern.search(text):
                violations.append(f"{relative}: {label}")
    assert violations == []
    assert not (ROOT / ".git/shallow").exists(), "public history must not be copied"
    assert not (ROOT / ".trustchain").exists(), "private signing ledger must not be copied"


def test_readme_describes_the_real_product_and_uses_public_links() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    required = [
        "contract-driven work with AI agents",
        "useful without an account, subscription or network connection",
        "TrustChain Cowork",
        "explicit local acceptance",
        "Source code, diffs, prompts, credentials and private keys stay",
        "organization control plane",
    ]
    for phrase in required:
        assert phrase in readme
    links = re.findall(r"\[[^]]+\]\(([^)]+)\)", readme)
    assert links
    assert all(link.startswith("https://") for link in links)
    assert all("APatch_Studio" not in link for link in links)
