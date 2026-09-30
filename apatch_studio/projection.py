"""Content-safe projection helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

FORBIDDEN_KEY_PARTS = {
    "access_token", "argv", "branch_name", "command_line", "cookie", "credential",
    "diff", "environment", "filesystem_path", "full_diff", "generated_code", "jsonl",
    "needle", "patch", "private_key", "process_list", "prompt", "reasoning",
    "remote_url", "repository_path", "secret", "session_capability", "session_token",
    "source_code", "stderr", "stdout", "token", "transcript", "workspace_path",
}
MAX_PROJECTION_DEPTH = 16
MAX_COLLECTION_ITEMS = 512
MAX_PROJECTION_KEY_LENGTH = 96
MAX_PROJECTION_STRING_LENGTH = 4096


def private_sdd_projection(value: Mapping[str, Any]) -> dict[str, Any]:
    """Validate a private binding without exposing its hash-pinned SPEC archives.

    This view is only for the internal binding/journal guards, never an API
    response. The exact sealed documents remain unchanged for Core execution.
    Public projections still use assert_projection_safe without exceptions.
    """
    import copy
    import hashlib

    view = copy.deepcopy(dict(value))
    contract = view.get("contract")
    if not isinstance(contract, Mapping):
        return view
    amendment = contract.get("judge_amendment")
    bootstrap = amendment.get("bootstrap") if isinstance(amendment, Mapping) else None
    if not isinstance(bootstrap, Mapping) or bootstrap.get("kind") != "pytest_explicit_conftest_bootstrap":
        return view
    try:
        from apatch.sdd_integrity import issue_capability
        issue_capability(
            contract, view["task_envelope"],
            actor_id=view["actor_id"], role="implementation",
        )
    except (ImportError, KeyError, RuntimeError, ValueError) as exc:
        raise UnsafeProjectionError("invalid private SDD archive binding") from exc
    for field, pin in (
        ("old_spec_text", "old_spec_hash"),
        ("replacement_spec_text", "new_spec_hash"),
    ):
        text = bootstrap.get(field)
        if not isinstance(text, str) or len(text) > 1_048_576:
            raise UnsafeProjectionError("invalid private SPEC archive size")
        digest = "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()
        if bootstrap.get(pin) != digest:
            raise UnsafeProjectionError("private SPEC archive hash mismatch")
        bootstrap[field] = {"hash": digest, "characters": len(text)}
    return view


class UnsafeProjectionError(ValueError):
    pass


def _forbidden_key(normalized: str) -> bool:
    return any(
        normalized == part
        or normalized.startswith(part + "_")
        or normalized.endswith("_" + part)
        or f"_{part}_" in normalized
        for part in FORBIDDEN_KEY_PARTS
    )


def assert_projection_safe(value: Any, path: str = "$", *, _depth: int = 0) -> None:
    if _depth > MAX_PROJECTION_DEPTH:
        raise UnsafeProjectionError(f"projection nesting limit exceeded at {path}")
    if isinstance(value, (bytes, bytearray, memoryview)):
        raise UnsafeProjectionError(f"binary projection value at {path}")
    if isinstance(value, str):
        if len(value) > MAX_PROJECTION_STRING_LENGTH:
            raise UnsafeProjectionError(f"projection string limit exceeded at {path}")
        return
    if isinstance(value, Mapping):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise UnsafeProjectionError(f"projection mapping limit exceeded at {path}")
        for key, child in value.items():
            if not isinstance(key, str) or not key or len(key) > MAX_PROJECTION_KEY_LENGTH:
                raise UnsafeProjectionError(f"invalid projection key at {path}")
            normalized = key.strip().lower()
            if _forbidden_key(normalized):
                raise UnsafeProjectionError(f"forbidden projection key at {path}.{key}")
            assert_projection_safe(child, f"{path}.{key}", _depth=_depth + 1)
        return
    if isinstance(value, Sequence) and not isinstance(value, str):
        if len(value) > MAX_COLLECTION_ITEMS:
            raise UnsafeProjectionError(f"projection sequence limit exceeded at {path}")
        for index, child in enumerate(value):
            assert_projection_safe(child, f"{path}[{index}]", _depth=_depth + 1)
