"""Studio's public APatch floor plus the capabilities its plan loop needs."""

from __future__ import annotations

import importlib
import re
from typing import Any, Callable

try:  # pragma: no cover - exercised through the real runtime
    from apatch import __version__ as apatch_version
except Exception:  # pragma: no cover - apatch missing entirely
    apatch_version = "0.0.0"

REQUIREMENTS_SCHEMA = "apatch.studio.runtime-requirements.v1"
REQUIRED_APATCH_VERSION = "0.8.45"
REQUIRED_FIXES: tuple[tuple[str, str, str, str], ...] = (
    (
        "session_binding",
        "apatch.spec_executor",
        "bind_runtime_to_active_session",
        "Plan sessions stay bound when several changes share the workspace",
    ),
    (
        "spec_bootstrap",
        "apatch.spec_ownership",
        "_bootstrap_authorization",
        "A fresh plan may create its own new specification",
    ),
)


def _version_tuple(text: str) -> tuple[int, ...]:
    parts = [int(item) for item in re.findall(r"\d+", str(text))[:3]]
    return tuple(parts + [0] * (3 - len(parts)))


def probe_runtime_requirements(
    *,
    version: str | None = None,
    importer: Callable[[str], Any] = importlib.import_module,
) -> dict[str, Any]:
    """Return whether the installed APatch carries what Studio needs, with one next step."""

    installed = str(version or apatch_version)
    fixes: list[dict[str, Any]] = []
    for fix_id, module_name, symbol, label in REQUIRED_FIXES:
        try:
            present = hasattr(importer(module_name), symbol)
        except Exception:
            present = False
        fixes.append({"id": fix_id, "label": label, "present": present})
    missing = [fix["label"] for fix in fixes if not fix["present"]]
    version_ok = _version_tuple(installed) >= _version_tuple(REQUIRED_APATCH_VERSION)
    ok = not missing
    if ok and version_ok:
        headline = f"APatch {installed} meets Studio's requirements"
        explanation = "Every fix the plan loop depends on is present."
        next_step = "Nothing to do."
    elif ok:
        headline = f"APatch {installed} carries the required fixes"
        explanation = (
            f"Studio expects {REQUIRED_APATCH_VERSION} or newer, but every fix the plan loop "
            "depends on is present, so this build works."
        )
        next_step = "Nothing to do."
    else:
        count = len(missing)
        headline = f"APatch {installed} lacks {count} required fix{'es' if count != 1 else ''}"
        explanation = "Missing: " + "; ".join(missing) + ". Preparing a plan fails until the runtime carries them."
        next_step = f"Update APatch to {REQUIRED_APATCH_VERSION} or newer, then restart Studio."
    return {
        "schema": REQUIREMENTS_SCHEMA,
        "installed_version": installed,
        "required_version": REQUIRED_APATCH_VERSION,
        "version_ok": version_ok,
        "fixes": fixes,
        "missing": missing,
        "ok": ok,
        "headline": headline,
        "explanation": explanation,
        "next_step": next_step,
    }


def runtime_banner_lines(report: dict[str, Any]) -> list[str]:
    """Lines `apatch-studio serve` prints so a mismatch is explained before the first click."""

    present = sum(1 for fix in report["fixes"] if fix["present"])
    lines = [f"APatch runtime: {report['installed_version']} · required fixes: {present}/{len(report['fixes'])}"]
    if not report["ok"]:
        lines.append(f"WARNING: {report['headline']}")
        lines.append(f"  {report['explanation']}")
        lines.append(f"  {report['next_step']}")
    return lines
