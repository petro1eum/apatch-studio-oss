from pathlib import Path

from apatch_studio.adapter import APatchStudioAdapter


def test_adapter_reads_real_apatch_workspace(monkeypatch):
    calls = []
    original = APatchStudioAdapter._canonical_status_snapshot

    def snapshot(adapter, *, include_hygiene=True):
        calls.append(include_hygiene)
        return original(adapter, include_hygiene=include_hygiene)

    monkeypatch.setattr(APatchStudioAdapter, "_canonical_status_snapshot", snapshot)
    root = Path(__file__).resolve().parents[1]
    projection = APatchStudioAdapter(root, cache_ttl=60).overview()

    assert projection["schema"] == "apatch.studio.workspace-overview.v1"
    assert projection["workspace"]["name"] == root.name
    assert projection["runtime"]["apatch_version"] >= "0.8.36"
    assert projection["runtime"]["mcp_profile"] == "full"
    assert isinstance(projection["specifications"], list)
    assert "session_token" not in repr(projection)
    assert calls == [False]


def test_adapter_cache_returns_same_projection(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    adapter = APatchStudioAdapter(tmp_path, cache_ttl=60)
    projection = {"schema": "cached"}
    monkeypatch.setattr(adapter, "_build", lambda: projection)
    assert adapter.overview() is adapter.overview()


def test_cache_ttl_starts_after_a_slow_snapshot_finishes(tmp_path, monkeypatch):
    (tmp_path / ".git").mkdir()
    adapter = APatchStudioAdapter(tmp_path, cache_ttl=2)
    projection = {"schema": "slow-snapshot"}
    builds = []
    moments = iter([100.0, 104.0, 104.1])
    monkeypatch.setattr("apatch_studio.adapter.time.monotonic", lambda: next(moments))
    monkeypatch.setattr(adapter, "_build", lambda: builds.append(True) or projection)

    assert adapter.overview() is projection
    assert adapter.overview() is projection
    assert builds == [True]


def test_session_without_exact_id_is_idle():
    view = APatchStudioAdapter._session(
        {
            "session": {
                "session_id": None,
                "lifecycle": "verifying",
                "phase": "verify",
                "next_action": "stale diagnostic action",
            }
        }
    )
    assert view == {
        "active": False,
        "id": None,
        "intent": None,
        "lifecycle": "idle",
        "phase": "idle",
        "checkpoint": None,
        "risk": "low",
        "next_action": None,
        "started_at": None,
        "ended_at": None,
        "failure": None,
    }


def test_mcp_profile_prefers_connected_runtime_fingerprint():
    doctor = {
        "mcp_profile": "compact",
        "mcp_health": {"stored_mcp_fingerprint": {"mcp_profile": "full"}},
    }
    assert APatchStudioAdapter._mcp_profile(doctor) == "full"
