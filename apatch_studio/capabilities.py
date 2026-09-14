"""Declarative Studio-to-APatch capability boundary.

This module describes composition only. APatch remains the canonical runtime and
the full discovered agent catalog remains available outside the bounded human UI.
"""

from __future__ import annotations

import os
import sys
from typing import Any, Final, Literal

APatchModule = Literal["apatch.cli", "apatch.mcp.launcher"]


def apatch_python_command(module: APatchModule) -> list[str]:
    """Use the installed runtime without cwd/PYTHONPATH/PYTHONHOME injection.

    Python >=3.11 is required by Studio. -E ignores Python startup environment
    overrides; -P excludes unsafe cwd/script-directory insertion before imports.
    Unlike -I this preserves legitimate user-site installations. Editable installs
    registered with the interpreter remain supported; PYTHONPATH-only installs do
    not. Explicit UTF-8 replaces the Python environment settings ignored by -E.
    Non-Python environment (runner credentials, APATCH_LANE/profile) is preserved.
    """
    if module not in {"apatch.cli", "apatch.mcp.launcher"}:
        raise ValueError("Only the code-owned APatch entrypoints may be launched")
    return [sys.executable, "-E", "-P", "-X", "utf8", "-m", module]


def apatch_python_startup_env() -> dict[str, str]:
    """Clear inherited Python overrides and protect runtime-spawned interpreters.

    MCP configuration can override but cannot delete inherited environment keys.
    Empty values neutralize startup overrides; safe-path and UTF-8 propagate to
    APatch's own diagnostic subprocesses, whose argv Studio does not construct.
    Ordinary user-site installs and non-Python runner credentials remain intact.
    """
    cleared = {
        name: "" for name in os.environ
        if name.startswith("PYTHON") and name.isascii() and name.isidentifier()
    }
    return {
        **cleared, "PYTHONPATH": "", "PYTHONHOME": "", "PYTHONUSERBASE": "",
        "PYTHONSAFEPATH": "1", "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8",
    }


APATCH_RUNTIME_OWNER: Final = "apatch"
STUDIO_RUNTIME_ROLE: Final = "fixed_purpose_facade"

APATCH_CAPABILITY_FAMILIES: Final = {
    "change_and_spec": (
        "apatch_rfp_lint",
        "apatch_spec_lint",
        "apatch_spec_status",
        "apatch_spec_run",
        "apatch_spec_run_multi",
        "apatch_execute_next",
        "apatch_rebind_stale",
    ),
    "governed_session": (
        "apatch_session_start",
        "apatch_session_state",
        "apatch_recover",
        "apatch_resume_session",
        "apatch_session_end",
    ),
    "mutation_and_lease": (
        "apatch_generate_batch",
        "apatch_apply_session",
        "apatch_path_lease_acquire",
        "apatch_path_lease_release",
    ),
    "verification_and_recovery": (
        "apatch_verify_run",
        "apatch_verify_status",
        "apatch_attest",
        "apatch_rollback",
    ),
    "evidence": (
        "apatch_events_tail",
        "apatch_attestation_show",
        "apatch_attestation_export",
        "apatch_trustchain_coverage",
        "apatch_verify_notarization",
    ),
    "work_assets": (
        "apatch_work_assets",
        "apatch_work_asset_search",
        "apatch_work_asset_show",
        "apatch_work_asset_suggest",
        "apatch_work_asset_recall",
        "apatch_work_asset_use",
        "apatch_work_asset_export",
    ),
    "remote_execution": (
        "apatch_remote_task_run",
        "apatch_remote_service_action",
        "apatch_remote_source_handoff",
    ),
    "policy": (
        "apatch_policy_sign",
        "apatch_policy_verify",
        "apatch_sandbox_status",
        "apatch_sandbox_audit",
        "apatch_arch_check",
        "apatch_db_safety",
    ),
}

APATCH_TRUTH_DOMAINS: Final = (
    "change",
    "specification",
    "requirement",
    "governed_session",
    "path_lease",
    "mutation",
    "verification",
    "attestation",
    "rollback",
    "evidence",
    "work_asset",
    "remote_execution",
    "policy",
)


def build_runtime_capability_contract(
    *,
    version: str,
    profile: str,
    tool_count: int,
    concurrent_writers: bool,
) -> dict[str, Any]:
    """Return a content-safe declaration of the runtime boundary."""

    return {
        "schema": "apatch.studio.runtime-capability-contract.v1",
        "runtime_owner": APATCH_RUNTIME_OWNER,
        "studio_role": STUDIO_RUNTIME_ROLE,
        "catalog": {
            "version": version,
            "profile": profile,
            "tool_count": tool_count,
            "discovery": "runtime",
            "full_professional_api": profile == "full",
        },
        "truth_domains": list(APATCH_TRUTH_DOMAINS),
        "families": [
            {
                "id": family_id,
                "runtime_owner": APATCH_RUNTIME_OWNER,
                "studio_access": "fixed_purpose_or_allowlisted_runner",
                "entrypoint_count": len(entrypoints),
            }
            for family_id, entrypoints in APATCH_CAPABILITY_FAMILIES.items()
        ],
        "invariants": {
            "studio_reimplements_runtime": False,
            "studio_reduces_agent_catalog": False,
            "read_only_refresh_takes_writer_lease": False,
            "path_scoped_concurrency": concurrent_writers,
        },
    }
