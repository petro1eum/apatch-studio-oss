from pathlib import Path

import apatch_studio.adapter as adapter_module
from apatch_studio.adapter import APatchStudioAdapter, _repository_slug


def test_repository_slug_removes_transport_and_credentials() -> None:
    assert (
        _repository_slug("https://token-value@github.com/example/private-product.git")
        == "example/private-product"
    )
    assert (
        _repository_slug("git@github.com:example/acme-app.git")
        == "example/acme-app"
    )
    assert _repository_slug("/Users/private/acme-app") is None
    assert _repository_slug("C:\\Users\\private\\acme-app") is None


def test_workspace_projection_has_safe_project_context(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "acme-app"
    (root / ".git").mkdir(parents=True)
    responses = {
        ("status", "--porcelain=v1"): "?? local-note.txt",
        ("branch", "--show-current"): "feature/governed-change",
        ("rev-parse", "--short=12", "HEAD"): "b1aee3ced2d7",
        ("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"):
            "origin/feature/governed-change",
        ("remote", "get-url", "origin"):
            "https://private-token@github.com/example/private-product.git",
        ("config", "user.name"): "EdCher",
    }

    monkeypatch.setattr(
        adapter_module,
        "_git",
        lambda _root, *args: responses.get(args, ""),
    )

    workspace = APatchStudioAdapter(root)._workspace()

    assert workspace == {
        "name": "acme-app",
        "identity": workspace["identity"],
        "repository": "example/private-product",
        "branch": "feature/governed-change",
        "upstream": "origin/feature/governed-change",
        "head": "b1aee3ced2d7",
        "operator": "EdCher",
        "dirty_files": 1,
        "clean": False,
    }
    serialized = repr(workspace)
    assert "private-token" not in serialized
    assert str(root) not in serialized
    assert "@" not in serialized
