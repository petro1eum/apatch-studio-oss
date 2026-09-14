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
