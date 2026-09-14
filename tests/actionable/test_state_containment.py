"""SEC-2: actual service operations must not read/write through state aliases."""

import json
import os
from types import SimpleNamespace

import pytest

from apatch_studio.action_facade import FixedPurposeRequest, StudioWorkflowError, StudioWorkflowFacade
from apatch_studio.policy_workflow import PolicyActionRequest


def workspace(tmp_path):
    root, outside = tmp_path / "workspace", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    return root, outside


def action(facade, operation, *, context=None):
    return facade._complete(FixedPurposeRequest(request_id="apsreq_containment_0001"),
                            "policy_preview", context or {}, operation)


@pytest.mark.parametrize("target", [".apatch", ".apatch/studio", ".apatch/studio/action_receipts.json"])
def test_receipt_link_refused_before_operation(tmp_path, target):
    root, outside = workspace(tmp_path)
    sentinel = outside / "action_receipts.json"
    sentinel.write_text('{"sentinel":{}}')
    link = root / target
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(sentinel if target.endswith(".json") else outside,
                    target_is_directory=not target.endswith(".json"))
    calls = []
    with pytest.raises(StudioWorkflowError):
        action(StudioWorkflowFacade(root), lambda: calls.append(1) or {"ok": True})
    assert not calls
    assert sentinel.read_text() == '{"sentinel":{}}'
    assert sorted(p.name for p in outside.iterdir()) == ["action_receipts.json"]


def test_receipt_temporary_link_is_untouched_and_retries_survive_restart(tmp_path):
    root, outside = workspace(tmp_path)
    sentinel = outside / "sentinel.json"
    sentinel.write_text("unchanged")
    store = root / ".apatch/studio"
    store.mkdir(parents=True)
    old_temp = store / "action_receipts.tmp"
    old_temp.symlink_to(sentinel)
    calls = []
    operation = lambda: calls.append(1) or {"ok": True}
    receipt = action(StudioWorkflowFacade(root), operation)
    assert action(StudioWorkflowFacade(root), operation) == receipt
    assert calls == [1]
    with pytest.raises(StudioWorkflowError, match="different action"):
        action(StudioWorkflowFacade(root), operation, context={"changed": True})
    assert sentinel.read_text() == "unchanged"
    assert old_temp.is_symlink()
    assert not (store / "action_receipts.json").is_symlink()


def test_receipt_hardlink_is_not_read_as_local_history(tmp_path):
    root, outside = workspace(tmp_path)
    sentinel = outside / "sentinel.json"
    sentinel.write_text("{}")
    store = root / ".apatch/studio"
    store.mkdir(parents=True)
    os.link(sentinel, store / "action_receipts.json")
    with pytest.raises(StudioWorkflowError):
        action(StudioWorkflowFacade(root), lambda: pytest.fail("operation dispatched"))
    assert sentinel.read_text() == "{}"


def test_callback_os_errors_keep_their_original_meaning(tmp_path):
    facade = StudioWorkflowFacade(tmp_path)
    failure = OSError("provider-specific failure")
    with pytest.raises(OSError) as caught:
        action(facade, lambda: (_ for _ in ()).throw(failure))
    assert caught.value is failure
    assert not facade._load()


def policy(root, action_name="apply", suffix="0001", **fields):
    return StudioWorkflowFacade(root).policy_action(PolicyActionRequest(
        request_id=f"apsreq_policy_containment_{suffix}", action=action_name,
        confirmed=action_name in {"apply", "restore", "sign"}, **fields,
    ))


@pytest.mark.parametrize("name", ["sandbox.json", "enforcement.json", "studio/policy_history.json"])
def test_policy_final_link_is_refused_before_any_policy_write(tmp_path, name):
    root, outside = workspace(tmp_path)
    sentinel = outside / "sentinel.json"
    sentinel.write_text('{"sentinel":true}')
    path = root / ".apatch" / name
    path.parent.mkdir(parents=True)
    path.symlink_to(sentinel)
    with pytest.raises(StudioWorkflowError):
        policy(root, mode="enforce")
    assert sentinel.read_text() == '{"sentinel":true}'
    for relative in ("sandbox.json", "enforcement.json", "studio/policy_history.json"):
        if relative != name:
            assert not (root / ".apatch" / relative).exists()


@pytest.mark.parametrize("name", ["sandbox.json", "enforcement.json", "studio/policy_history.json"])
def test_policy_predictable_temporary_links_cannot_overwrite_external_file(tmp_path, name):
    root, outside = workspace(tmp_path)
    sentinel = outside / "sentinel.json"
    sentinel.write_text("unchanged")
    path = root / ".apatch" / (name + ".studio.tmp")
    path.parent.mkdir(parents=True)
    path.symlink_to(sentinel)
    assert policy(root, mode="enforce")["result"]["current"]["mode"] == "enforce"
    assert policy(root, "restore", "0002")["result"]["current"]["mode"] == "off"
    assert sentinel.read_text() == "unchanged"
    assert path.is_symlink()


def enrolled_identity(monkeypatch):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.generate()
    provider = SimpleNamespace(sign=key.sign, get_public_key=lambda: key.public_key().public_bytes_raw())
    identity = SimpleNamespace(agent_id="operator:test", key_provider=provider, cert_path=None, backend="pem")
    monkeypatch.setattr("apatch.trust_identity.load_local_identity", lambda root=None: identity)


def test_policy_sign_and_verify_preserve_exact_manifest_bytes(tmp_path, monkeypatch):
    import hashlib

    root, _outside = workspace(tmp_path)
    directory = root / ".apatch"
    directory.mkdir()
    original = b'{ "mode" : "audit" }\n'
    (directory / "sandbox.json").write_bytes(original)
    enrolled_identity(monkeypatch)
    assert policy(root, "sign")["result"]["signed"] is True
    assert policy(root, "verify", "0002")["result"]["signature_ok"] is True
    lock = json.loads((directory / "policy.lock.json").read_text())
    assert lock["manifest"]["files"][".apatch/sandbox.json"] == hashlib.sha256(original).hexdigest()
    assert (directory / "sandbox.json").read_bytes() == original


def test_native_policy_writer_cannot_escape_during_directory_swap(tmp_path, monkeypatch):
    import apatch_studio.policy_workflow as workflow

    root, outside = workspace(tmp_path)
    enrolled_identity(monkeypatch)
    original = workflow.sign_policy
    sentinel = outside / "policy.lock.json"
    sentinel.write_text("unchanged")

    def swap_before_native_write(snapshot):
        (root / ".apatch").rename(root / "old-state")
        (root / ".apatch").symlink_to(outside, target_is_directory=True)
        return original(snapshot)

    monkeypatch.setattr(workflow, "sign_policy", swap_before_native_write)
    with pytest.raises(StudioWorkflowError):
        policy(root, "sign")
    assert sentinel.read_text() == "unchanged"


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor-relative race; Windows denies the rename")
def test_open_directory_stays_bound_when_path_is_replaced(tmp_path):
    from apatch_studio.state_io import StateDirectory

    root, outside = workspace(tmp_path)
    directory = root / "state"
    directory.mkdir()
    sentinel = outside / "entry.json"
    sentinel.write_text('{"external":true}')
    with StateDirectory(directory) as store:
        directory.rename(root / "original-state")
        directory.symlink_to(outside, target_is_directory=True)
        store.write_json("entry.json", {"local": True})
        assert store.read_json("entry.json") == {"local": True}
        store.unlink("entry.json")
    assert sentinel.read_text() == '{"external":true}'


def test_final_path_is_never_chmod_after_atomic_replacement(tmp_path, monkeypatch):
    import apatch_studio.state_io as storage

    root, outside = workspace(tmp_path)
    sentinel = outside / "entry.json"
    sentinel.write_text("unchanged")
    sentinel.chmod(0o644)
    original = storage.os.replace

    def swap_after_replace(src, dst, **kwargs):
        original(src, dst, **kwargs)
        (root / "entry.json").unlink()
        (root / "entry.json").symlink_to(sentinel)

    monkeypatch.setattr(storage.os, "replace", swap_after_replace)
    storage.write_json(root / "entry.json", {"local": True})
    assert sentinel.read_text() == "unchanged"
    assert sentinel.stat().st_mode & 0o777 == 0o644
