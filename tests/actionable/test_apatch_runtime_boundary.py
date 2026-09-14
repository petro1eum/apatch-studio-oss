import json
import os
import subprocess
import sysconfig
from pathlib import Path

import pytest

from apatch_studio.action_facade import StudioWorkflowFacade
from apatch_studio.agent_runs import RunnerCatalog
from apatch_studio.capabilities import apatch_python_command

from apatch_studio.capabilities import (
    APATCH_CAPABILITY_FAMILIES,
    APATCH_TRUTH_DOMAINS,
    build_runtime_capability_contract,
)


ROOT = Path(__file__).resolve().parents[2]


def test_apatch_owns_every_governed_truth_domain() -> None:
    assert set(APATCH_TRUTH_DOMAINS) == {
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
    }
    assert set(APATCH_CAPABILITY_FAMILIES) == {
        "change_and_spec",
        "governed_session",
        "mutation_and_lease",
        "verification_and_recovery",
        "evidence",
        "work_assets",
        "remote_execution",
        "policy",
    }


def test_runtime_contract_preserves_discovered_full_agent_catalog() -> None:
    contract = build_runtime_capability_contract(
        version="0.8.36",
        profile="full",
        tool_count=122,
        concurrent_writers=True,
    )

    assert contract["runtime_owner"] == "apatch"
    assert contract["studio_role"] == "fixed_purpose_facade"
    assert contract["catalog"] == {
        "version": "0.8.36",
        "profile": "full",
        "tool_count": 122,
        "discovery": "runtime",
        "full_professional_api": True,
    }
    assert contract["invariants"] == {
        "studio_reimplements_runtime": False,
        "studio_reduces_agent_catalog": False,
        "read_only_refresh_takes_writer_lease": False,
        "path_scoped_concurrency": True,
    }
    assert all(item["runtime_owner"] == "apatch" for item in contract["families"])


def test_studio_composes_installed_apatch_instead_of_forking_runtime() -> None:
    adapter = (ROOT / "apatch_studio" / "adapter.py").read_text(encoding="utf-8")
    runner = (ROOT / "apatch_studio" / "agent_runs.py").read_text(encoding="utf-8")
    modules = {path.stem for path in (ROOT / "apatch_studio").glob("*.py")}

    for imported_owner in [
        "from apatch.doctor import run_doctor",
        "from apatch.spec import _ledger_entries, _load_spec",
        "from apatch.spec_coverage import spec_coverage_from_entries",
        "from apatch.runtime.session import build_session_view",
        "from apatch.work_assets import list_work_assets",
    ]:
        assert imported_owner in adapter

    assert "installed full APatch MCP/CLI" in runner
    assert "All source mutations must belong to an exact governed APatch session" in runner
    assert not {
        "ledger",
        "path_leases",
        "spec_runtime",
        "work_assets",
    }.intersection(modules)


@pytest.mark.parametrize("surface", ["cli", "mcp_import"])
@pytest.mark.parametrize("shadow", [
    "workspace_package", "workspace_module", "pythonpath_package",
    "relative_pythonpath_package", "empty_pythonpath_sitecustomize",
    "pythonpath_sitecustomize", "relative_pythonuserbase", "invalid_pythonhome",
])
def test_workspace_cannot_supply_apatch_or_startup_code(tmp_path, monkeypatch, surface, shadow):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    external = tmp_path / "external"
    external.mkdir()
    marker = tmp_path / "untrusted-startup-executed"
    payload = (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n"
        "print('{\"forged_runtime\": true}')\n"
        "raise SystemExit(0)\n"
    )
    if shadow.startswith("workspace") or shadow == "empty_pythonpath_sitecustomize":
        location = workspace
    elif shadow == "relative_pythonpath_package":
        location = workspace / "relative"
        location.mkdir()
    else:
        location = external
    if shadow == "relative_pythonuserbase":
        location = Path(sysconfig.get_path("purelib", scheme=sysconfig.get_preferred_scheme("user"),
            vars={"userbase": str(workspace / "relative-userbase")}))
        location.mkdir(parents=True)
    if "sitecustomize" in shadow or shadow == "relative_pythonuserbase":
        (location / "sitecustomize.py").write_text(payload, encoding="utf-8")
    elif shadow == "workspace_module":
        (location / "apatch.py").write_text(payload, encoding="utf-8")
    else:
        package = location / "apatch"
        package.mkdir()
        (package / "__init__.py").write_text(payload, encoding="utf-8")
    monkeypatch.setenv("PYTHONPATH", (
        "relative" if shadow == "relative_pythonpath_package"
        else "" if shadow == "empty_pythonpath_sitecustomize"
        else str(location)
    ))
    # Do not let an invalid PYTHONHOME hide an unsafe nested diagnostic child.
    monkeypatch.delenv("PYTHONHOME", raising=False)
    monkeypatch.delenv("PYTHONUSERBASE", raising=False)
    if shadow == "invalid_pythonhome":
        monkeypatch.setenv("PYTHONHOME", str(tmp_path / "untrusted-python-home"))
    if shadow == "relative_pythonuserbase":
        monkeypatch.setenv("PYTHONUSERBASE", "relative-userbase")
    monkeypatch.setenv("APATCH_LANE", "security-startup-control")
    if surface == "cli":
        result = StudioWorkflowFacade(workspace)._cli(
            ["doctor", "--target-dir", str(workspace)], timeout=60,
        )
        assert "version" in result
        assert not result.get("forged_runtime")
    else:
        server = RunnerCatalog.apatch_mcp_server()
        # Exercise the exact interpreter startup used by MCP without starting or
        # restarting the user's MCP server. Import the same target module.
        assert server["args"][-2:] == ["-m", "apatch.mcp.launcher"]
        probe = (
            "import json, os, sys; import apatch.mcp.launcher as launcher; "
            "print(json.dumps({'module': launcher.__file__, 'utf8': sys.flags.utf8_mode,"
            "'user_site_disabled': sys.flags.no_user_site,"
            "'lane': os.environ.get('APATCH_LANE'),"
            "'profile': os.environ.get('APATCH_MCP_PROFILE')}))"
        )
        completed = subprocess.run(
            [server["command"], *server["args"][:-2], "-c", probe],
            cwd=workspace, env={**os.environ, **server["env"]},
            capture_output=True, text=True, timeout=60, check=True,
        )
        result = json.loads(completed.stdout)
        assert not Path(result["module"]).is_relative_to(tmp_path)
        assert result["utf8"] == 1
        assert result["user_site_disabled"] == 0
        assert result["lane"] == "security-startup-control"
        assert result["profile"] == "full"
    assert not marker.exists()


def test_ordinary_installed_runtime_still_returns_a_structured_result(tmp_path):
    result = StudioWorkflowFacade(tmp_path)._cli(
        ["doctor", "--target-dir", str(tmp_path)], timeout=60,
    )
    assert isinstance(result["version"], str)


def test_no_caller_can_choose_another_python_module():
    with pytest.raises(ValueError, match="code-owned"):
        apatch_python_command("workspace.untrusted")
