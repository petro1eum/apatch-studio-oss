"""Product runners must not let a user's global MCP cwd select another project."""

import json
import tomllib
from pathlib import Path

import pytest

from apatch_studio.agent_runs import RunnerCatalog


def _catalog() -> RunnerCatalog:
    return RunnerCatalog(which={"codex": "/fixed/codex", "claude": "/fixed/claude"}.get)


def _server(runner: str, argv: list[str]) -> dict:
    if runner == "claude":
        return json.loads(argv[argv.index("--mcp-config") + 1])["mcpServers"]["apatch"]
    overrides = [argv[index + 1] for index, value in enumerate(argv) if value == "-c"]
    return tomllib.loads("\n".join(overrides))["mcp_servers"]["apatch"]


@pytest.mark.parametrize("runner", ["codex", "claude"])
def test_runner_pins_canonical_workspace_despite_inherited_binding(
    runner: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = tmp_path / 'project "QA" \\ folder'
    workspace.mkdir()
    alias = tmp_path / "linked-project"
    alias.symlink_to(workspace, target_is_directory=True)
    monkeypatch.setenv("APATCH_MCP_BOUND", "/unrelated/home/workspace")

    server = _server(runner, _catalog().command(runner, alias))

    assert server["env"]["APATCH_MCP_BOUND"] == str(workspace.resolve())
    assert server["env"]["APATCH_MCP_PROFILE"] == "full"
    assert server["env"]["PYTHONPATH"] == ""
    if runner == "codex":
        assert server["cwd"] == str(workspace.resolve())


@pytest.mark.parametrize("runner", ["codex", "claude"])
def test_planning_runner_keeps_the_same_exact_workspace(runner: str, tmp_path: Path) -> None:
    server = _server(runner, _catalog().planning_command(runner, tmp_path))
    assert server["env"]["APATCH_MCP_BOUND"] == str(tmp_path.resolve())


def test_introspection_remains_unbound_and_does_not_inherit_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APATCH_MCP_BOUND", "/unrelated/home/workspace")
    server = RunnerCatalog.apatch_mcp_server()
    assert "APATCH_MCP_BOUND" not in server["env"]
    assert "cwd" not in server
    overrides = RunnerCatalog._codex_mcp_overrides()
    assert not any(value.startswith("mcp_servers.apatch.cwd=") for value in overrides)
