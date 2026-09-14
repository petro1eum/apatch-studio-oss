import json
from pathlib import Path

from apatch_studio.agent_runs import AgentRunManager, RunnerCatalog
from apatch_studio.operations import AgentRunRequest


def _request() -> AgentRunRequest:
    return AgentRunRequest.model_validate(
        {
            "mode": "specification",
            "runner": "codex",
            "objective": "Execute a bounded first-user specification",
            "spec_id": "SPEC-FIRST-USER-1",
        }
    )


def _fake_codex(tmp_path: Path, body: str) -> Path:
    executable = tmp_path / "codex"
    executable.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        + body
        + "\n",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable


def _catalog(executable: Path) -> RunnerCatalog:
    return RunnerCatalog(
        which=lambda name: str(executable) if name == "codex" else None
    )


def test_codex_argv_uses_automatic_review_without_conflicting_or_bypass_flags(
    tmp_path: Path,
) -> None:
    executable = _fake_codex(tmp_path, "sys.exit(0)")
    argv = _catalog(executable).command("codex", tmp_path)

    assert "--approve-for-me" in argv
    assert "--sandbox" not in argv
    assert "workspace-write" not in argv
    assert "dangerously-bypass" not in " ".join(argv)


def test_process_level_codex_contract_progresses_beyond_launch(tmp_path: Path) -> None:
    executable = _fake_codex(
        tmp_path,
        """
args = sys.argv[1:]
if "--sandbox" in args and "--approve-for-me" in args:
    print("error: the argument '--sandbox <SANDBOX_MODE>' cannot be used with '--approve-for-me'")
    raise SystemExit(2)
sys.stdin.read()
print(json.dumps({"type": "thread.started", "thread_id": "first-user"}))
print(json.dumps({"type": "turn.completed"}))
""".strip(),
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = AgentRunManager(
        workspace,
        catalog=_catalog(executable),
        state_root=tmp_path / "state",
    )
    try:
        completed = manager.wait(manager.start(_request())["run_id"], timeout=3)
    finally:
        manager.close()

    assert completed["status"] == "succeeded"
    assert completed["thread_id"] == "first-user"
    assert completed["outcome"] == "complete"


def test_known_runner_diagnostic_is_actionable_and_content_safe(tmp_path: Path) -> None:
    executable = _fake_codex(
        tmp_path,
        """
sys.stdin.read()
print("error: the argument '--sandbox <SANDBOX_MODE>' cannot be used with '--approve-for-me'")
raise SystemExit(2)
""".strip(),
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manager = AgentRunManager(
        workspace,
        catalog=_catalog(executable),
        state_root=tmp_path / "state",
    )
    try:
        completed = manager.wait(manager.start(_request())["run_id"], timeout=3)
    finally:
        manager.close()

    assert completed["status"] == "failed"
    assert completed["outcome"] == "runner_options_incompatible"
    assert completed["message"] == (
        "Codex runner options are incompatible. Update APatch Studio and retry."
    )
    assert "--sandbox" not in json.dumps(completed)


def test_unknown_runner_output_privacy_never_leaks_into_projection_or_journal(
    tmp_path: Path,
) -> None:
    executable = _fake_codex(
        tmp_path,
        """
sys.stdin.read()
print("TOKEN=super-secret /Users/person/private.py prompt=steal-me")
raise SystemExit(9)
""".strip(),
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    state_root = tmp_path / "state"
    manager = AgentRunManager(
        workspace,
        catalog=_catalog(executable),
        state_root=state_root,
    )
    try:
        completed = manager.wait(manager.start(_request())["run_id"], timeout=3)
    finally:
        manager.close()

    projection = json.dumps(completed)
    journal_files = list(state_root.rglob("*.json"))
    assert journal_files
    journal = "\n".join(
        path.read_text(encoding="utf-8") for path in journal_files
    )
    assert completed["outcome"] == "runner_exit"
    assert completed["message"] == "The agent stopped before it finished"
    assert completed["failure"]["headline"] == "The agent stopped early"
    for forbidden in ("super-secret", "/Users/person/private.py", "steal-me"):
        assert forbidden not in projection
        assert forbidden not in journal
