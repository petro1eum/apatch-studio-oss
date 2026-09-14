"""Runners must get the exact full-profile apatch MCP server (REC-db629a7ee98f)."""

import json
import sys
from pathlib import Path

from apatch_studio.agent_runs import RunnerCatalog


def _catalog() -> RunnerCatalog:
    return RunnerCatalog(which={"codex": "/fixed/codex", "claude": "/fixed/claude"}.get)


def test_codex_argv_pins_the_full_profile_apatch_server_before_stdin() -> None:
    argv = _catalog().command("codex", Path("/fixed/workspace"))
    joined = " ".join(argv)
    assert argv[-1] == "-"
    assert f'mcp_servers.apatch.command="{sys.executable}"' in argv
    assert 'mcp_servers.apatch.args=["-E", "-P", "-X", "utf8", "-m", "apatch.mcp.launcher"]' in argv
    assert 'APATCH_MCP_PROFILE="full"' in joined
    assert "mcp_servers.apatch.enabled=true" in argv
    assert "--approve-for-me" in argv
    assert "--sandbox" not in argv


def test_planning_argv_keeps_the_fast_profile_and_the_mcp_server() -> None:
    planning = _catalog().planning_command("codex", Path("/fixed/workspace"))
    assert planning[-1] == "-"
    assert planning[planning.index("--model") + 1] == "gpt-5.6-luna"
    assert any(item.startswith("mcp_servers.apatch.env={") for item in planning)


def test_claude_argv_uses_only_the_explicit_apatch_server() -> None:
    argv = _catalog().command("claude", Path("/fixed/workspace"))
    assert "--strict-mcp-config" in argv
    config = json.loads(argv[argv.index("--mcp-config") + 1])
    server = config["mcpServers"]["apatch"]
    assert server["command"] == sys.executable
    assert server["args"] == ["-E", "-P", "-X", "utf8", "-m", "apatch.mcp.launcher"]
    assert server["env"]["APATCH_MCP_PROFILE"] == "full"
    assert list(config["mcpServers"]) == ["apatch"]


def test_server_definition_has_no_workspace_paths_or_secrets(monkeypatch) -> None:
    monkeypatch.setenv("PYTHONPATH", "/untrusted/workspace/python")
    server = RunnerCatalog.apatch_mcp_server()
    assert server["env"]["PYTHONPATH"] == ""
    assert server["env"]["PYTHONHOME"] == ""
    assert server["env"]["PYTHONUSERBASE"] == ""
    assert server["env"]["PYTHONSAFEPATH"] == "1"
    rendered = json.dumps(server)
    for forbidden in ("APATCH_AGENT_KEY", "APATCH_PLATFORM_URL", "/Users/"):
        if forbidden == "/Users/" and rendered.count("/Users/") == rendered.count(sys.executable):
            continue
        assert forbidden not in rendered.replace(sys.executable, ""), forbidden
