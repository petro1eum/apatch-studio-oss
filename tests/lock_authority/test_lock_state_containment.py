import pytest

from apatch_studio.lock_authority import LockAuthority, LockAuthorityError
from test_solo_release import SPEC, _enrol


@pytest.mark.parametrize("relative", [".apatch", ".apatch/locks", f".apatch/locks/{SPEC}",
                                      ".apatch/locks/journal.jsonl"])
def test_lock_state_alias_cannot_write_outside_workspace(tmp_path, relative):
    workspace, outside, identity = (tmp_path / name for name in ("workspace", "outside", "identity"))
    for folder in (workspace, outside, identity):
        folder.mkdir()
    _enrol(identity)
    sentinel = outside / "sentinel.jsonl"
    sentinel.write_text("unchanged\n")
    link = workspace / relative
    link.parent.mkdir(parents=True, exist_ok=True)
    is_file = relative.endswith(".jsonl")
    link.symlink_to(sentinel if is_file else outside, target_is_directory=not is_file)
    authority = LockAuthority(workspace / ".apatch", identity_root=identity)
    with pytest.raises(LockAuthorityError):
        authority.lock_solo(SPEC, "R1")
    assert sentinel.read_text() == "unchanged\n"
    assert sorted(path.name for path in outside.iterdir()) == ["sentinel.jsonl"]
    assert not (workspace / ".apatch" / "locks" / SPEC / "R1.json").is_file()


def test_lock_and_release_journal_survive_restart(tmp_path):
    identity = tmp_path / "identity"
    identity.mkdir()
    _enrol(identity)
    root = tmp_path / "workspace" / ".apatch"
    authority = LockAuthority(root, identity_root=identity)
    authority.lock_solo(SPEC, "R1")
    authority.request_release(SPEC, "R1", reason="the agreed scope needs an amendment")
    authority = LockAuthority(root, identity_root=identity)
    assert authority.read(SPEC, "R1")["release"]["state"] == "awaiting_answer"
    record = authority.answer_release(SPEC, "R1", decision="grant", reason="reviewed and agreed to the amendment")
    assert record["release"]["state"] == "granted"
    assert len(authority._journal_for(SPEC, "R1")) == 3


def test_explicit_workspace_alias_keeps_the_same_lock_authority(tmp_path):
    workspace, identity = tmp_path / "workspace", tmp_path / "identity"
    workspace.mkdir()
    identity.mkdir()
    _enrol(identity)
    alias = tmp_path / "selected-workspace"
    alias.symlink_to(workspace, target_is_directory=True)
    authority = LockAuthority(alias / ".apatch", identity_root=identity)
    authority.lock_solo(SPEC, "R1")
    assert LockAuthority(workspace / ".apatch", identity_root=identity).is_locked(SPEC, "R1")
