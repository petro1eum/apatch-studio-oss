import pytest

from apatch_studio.projection import UnsafeProjectionError, assert_projection_safe


def test_projection_rejects_forbidden_fields():
    for key in (
        "session_token",
        "private_key_pem",
        "prompt_text",
        "source_code",
        "workspace_path",
        "api_secret",
        "full_diff",
    ):
        with pytest.raises(UnsafeProjectionError):
            assert_projection_safe({"nested": [{key: "redacted"}]})


def test_projection_rejects_binary_and_unbounded_values():
    with pytest.raises(UnsafeProjectionError, match="binary"):
        assert_projection_safe({"value": b"source bytes"})
    with pytest.raises(UnsafeProjectionError, match="sequence limit"):
        assert_projection_safe({"items": list(range(513))})


def test_projection_rejects_excessive_nesting():
    value = "leaf"
    for _ in range(18):
        value = {"nested": value}
    with pytest.raises(UnsafeProjectionError, match="nesting limit"):
        assert_projection_safe(value)


def test_projection_accepts_local_product_metadata():
    assert_projection_safe(
        {
            "workspace": {"name": "apatch", "branch": "main"},
            "session": {"intent": "Fix verification", "phase": "verify"},
            "specifications": [{"id": "SPEC-X", "stale": 1}],
        }
    )
