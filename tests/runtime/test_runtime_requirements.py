"""Studio pins its APatch runtime and explains a mismatch (RFP-018)."""

from __future__ import annotations

import builtins
import json
import subprocess
import sys
import tomllib
import types
from pathlib import Path

import pytest

from apatch_studio.runtime_requirements import (
    REQUIRED_APATCH_VERSION,
    REQUIRED_FIXES,
    REQUIREMENTS_SCHEMA,
    probe_runtime_requirements,
    runtime_banner_lines,
)

ROOT = Path(__file__).resolve().parents[2]
TYPES = (ROOT / "frontend/src/types.ts").read_text(encoding="utf-8")
SHELL = (ROOT / "frontend/src/OutsideInApp.tsx").read_text(encoding="utf-8")
OUTSIDE_ADMIN = (ROOT / "frontend/src/OutsideInAdmin.tsx").read_text(encoding="utf-8")
CLI = (ROOT / "apatch_studio/cli.py").read_text(encoding="utf-8")
VOCABULARY = json.loads((ROOT / "frontend/src/vocabulary.contract.json").read_text(encoding="utf-8"))
ALL_FIXES = {"bind_runtime_to_active_session", "_bootstrap_authorization", "ExistingSignerBinding"}


def _importer(present: set[str]):
    def load(module_name: str):
        module = types.SimpleNamespace()
        for _fix_id, name, symbol, _label in REQUIRED_FIXES:
            if name == module_name and symbol in present:
                setattr(module, symbol, lambda *a, **k: None)
        return module

    return load


def test_runtime_with_every_fix_is_accepted() -> None:
    report = probe_runtime_requirements(version=REQUIRED_APATCH_VERSION, importer=_importer(ALL_FIXES))
    assert report["schema"] == REQUIREMENTS_SCHEMA
    assert report["ok"] is True and report["version_ok"] is True
    assert report["missing"] == []
    assert report["next_step"] == "Nothing to do."


def test_runtime_missing_a_fix_is_explained_with_one_next_step() -> None:
    report = probe_runtime_requirements(version="0.8.45", importer=_importer(ALL_FIXES - {"_bootstrap_authorization"}))
    assert report["ok"] is False
    assert report["missing"] == ["A fresh plan may create its own new specification"]
    assert "lacks 1 required fix" in report["headline"]
    assert report["missing"][0] in report["explanation"]
    assert report["next_step"].startswith("Update APatch to " + REQUIRED_APATCH_VERSION)


def test_older_version_with_the_fixes_still_works_and_says_so() -> None:
    report = probe_runtime_requirements(version="0.8.28", importer=_importer(ALL_FIXES))
    assert report["ok"] is True and report["version_ok"] is False
    assert "carries the required fixes" in report["headline"]


def test_missing_module_counts_as_missing_fix() -> None:
    def broken(_name: str):
        raise ImportError("no apatch")

    report = probe_runtime_requirements(version="0.0.0", importer=broken)
    assert report["ok"] is False and len(report["missing"]) == len(REQUIRED_FIXES)


def test_requirement_copy_uses_product_language_only() -> None:
    for present in (ALL_FIXES, {"bind_runtime_to_active_session"}, set()):
        report = probe_runtime_requirements(version="0.8.45", importer=_importer(present))
        for text in (report["headline"], report["explanation"], report["next_step"], *report["missing"]):
            lowered = text.lower()
            for term in VOCABULARY["forbidden_primary_terms"]:
                assert term not in lowered, (term, text)


def test_serve_prints_the_runtime_banner_and_the_mismatch() -> None:
    report = probe_runtime_requirements(version="0.8.45", importer=_importer({"bind_runtime_to_active_session"}))
    lines = runtime_banner_lines(report)
    assert lines[0] == "APatch runtime: 0.8.45 · required fixes: 1/3"
    assert lines[1].startswith("WARNING: APatch 0.8.45 lacks 2 required fixes")
    assert "runtime_banner_lines(probe_runtime_requirements())" in CLI
    ok_lines = runtime_banner_lines(probe_runtime_requirements(version="0.8.45", importer=_importer(ALL_FIXES)))
    assert ok_lines == ["APatch runtime: 0.8.45 · required fixes: 3/3"]


def test_report_floor_matches_the_install_requirement() -> None:
    with (ROOT / "pyproject.toml").open("rb") as project:
        requirements = tomllib.load(project)["project"]["dependencies"]
    assert f"apatch[mcp]>={REQUIRED_APATCH_VERSION}" in requirements


def test_missing_core_api_keeps_help_and_explains_start_failure(tmp_path) -> None:
    # Exercise a fresh interpreter: pre-imported routers would hide this defect.
    launcher = (
        "import runpy, sys; "
        "sys.modules['apatch.strict_existing_signer'] = None; "
        "runpy.run_module('apatch_studio.cli', run_name='__main__')"
    )

    def run(*args):
        return subprocess.run(
            [sys.executable, "-c", launcher, *args], cwd=tmp_path,
            capture_output=True, text=True, timeout=20, check=False,
        )

    help_result = run("--help")
    assert help_result.returncode == 0 and "serve" in help_result.stdout
    result = run("serve", "--no-open", "--workspace", str(tmp_path))
    assert result.returncode != 0 and "Traceback" not in result.stderr
    assert "apatch.strict_existing_signer" in result.stderr
    assert "requirements/source.txt" in result.stderr
    assert not (tmp_path / ".apatch").exists()


def test_unrelated_import_error_is_not_reported_as_a_core_mismatch(monkeypatch, tmp_path):
    from apatch_studio.cli import _parser, serve

    real_import = builtins.__import__

    def unavailable(name, *args, **kwargs):
        if name == "apatch_studio.app":
            raise ModuleNotFoundError("unrelated dependency", name="unrelated_dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", unavailable)
    with pytest.raises(ModuleNotFoundError, match="unrelated dependency"):
        serve(_parser().parse_args(["serve", "--no-open", "--workspace", str(tmp_path)]))


def test_admin_and_runtime_card_surface_the_requirement_state() -> None:
    assert "requirements: RuntimeRequirements;" in TYPES
    assert "export interface RuntimeRequirements" in TYPES
    assert "data.runtime.requirements.ok" in SHELL
    assert "<dt>Required fixes</dt>" in OUTSIDE_ADMIN
    assert "data.runtime.requirements.headline" in OUTSIDE_ADMIN
    assert "data.runtime.requirements.next_step" in OUTSIDE_ADMIN
