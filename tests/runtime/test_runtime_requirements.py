"""Studio pins its APatch runtime and explains a mismatch (RFP-018)."""

from __future__ import annotations

import json
import types
from pathlib import Path

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


def _importer(present: set[str]):
    def load(module_name: str):
        module = types.SimpleNamespace()
        for _fix_id, name, symbol, _label in REQUIRED_FIXES:
            if name == module_name and symbol in present:
                setattr(module, symbol, lambda *a, **k: None)
        return module

    return load


def test_runtime_with_every_fix_is_accepted() -> None:
    report = probe_runtime_requirements(version="0.8.45", importer=_importer({"bind_runtime_to_active_session", "_bootstrap_authorization"}))
    assert report["schema"] == REQUIREMENTS_SCHEMA
    assert report["ok"] is True and report["version_ok"] is True
    assert report["missing"] == []
    assert report["next_step"] == "Nothing to do."


def test_runtime_missing_a_fix_is_explained_with_one_next_step() -> None:
    report = probe_runtime_requirements(version="0.8.45", importer=_importer({"bind_runtime_to_active_session"}))
    assert report["ok"] is False
    assert report["missing"] == ["A fresh plan may create its own new specification"]
    assert "lacks 1 required fix" in report["headline"]
    assert "Preparing a plan fails" in report["explanation"]
    assert report["next_step"].startswith("Update APatch to " + REQUIRED_APATCH_VERSION)


def test_older_version_with_the_fixes_still_works_and_says_so() -> None:
    report = probe_runtime_requirements(version="0.8.28", importer=_importer({"bind_runtime_to_active_session", "_bootstrap_authorization"}))
    assert report["ok"] is True and report["version_ok"] is False
    assert "carries the required fixes" in report["headline"]


def test_missing_module_counts_as_missing_fix() -> None:
    def broken(_name: str):
        raise ImportError("no apatch")

    report = probe_runtime_requirements(version="0.0.0", importer=broken)
    assert report["ok"] is False and len(report["missing"]) == len(REQUIRED_FIXES)


def test_requirement_copy_uses_product_language_only() -> None:
    for present in ({"bind_runtime_to_active_session", "_bootstrap_authorization"}, {"bind_runtime_to_active_session"}, set()):
        report = probe_runtime_requirements(version="0.8.45", importer=_importer(present))
        for text in (report["headline"], report["explanation"], report["next_step"], *report["missing"]):
            lowered = text.lower()
            for term in VOCABULARY["forbidden_primary_terms"]:
                assert term not in lowered, (term, text)


def test_serve_prints_the_runtime_banner_and_the_mismatch() -> None:
    report = probe_runtime_requirements(version="0.8.45", importer=_importer({"bind_runtime_to_active_session"}))
    lines = runtime_banner_lines(report)
    assert lines[0] == "APatch runtime: 0.8.45 · required fixes: 1/2"
    assert lines[1].startswith("WARNING: APatch 0.8.45 lacks 1 required fix")
    assert "runtime_banner_lines(probe_runtime_requirements())" in CLI
    ok_lines = runtime_banner_lines(probe_runtime_requirements(version="0.8.45", importer=_importer({"bind_runtime_to_active_session", "_bootstrap_authorization"})))
    assert ok_lines == ["APatch runtime: 0.8.45 · required fixes: 2/2"]


def test_admin_and_runtime_card_surface_the_requirement_state() -> None:
    assert "requirements: RuntimeRequirements;" in TYPES
    assert "export interface RuntimeRequirements" in TYPES
    assert "data.runtime.requirements.ok" in SHELL
    assert "<dt>Required fixes</dt>" in OUTSIDE_ADMIN
    assert "data.runtime.requirements.headline" in OUTSIDE_ADMIN
    assert "data.runtime.requirements.next_step" in OUTSIDE_ADMIN
