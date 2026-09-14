from __future__ import annotations

from fastapi.testclient import TestClient

from apatch_studio.app import create_app
from apatch_studio.change_feed import build_unified_change_feed


SESSION = "apatch_sess_1000000000000000_shared"


def _run(run_id: str, at: str, session_id: str | None = None):
    return {
        "schema": "apatch.studio.agent-run.v1",
        "run_id": run_id,
        "objective": "Studio supervised change",
        "created_at": at,
        "started_at": at,
        "ended_at": at,
        "work_ref": {"governed_session_id": session_id},
    }


def _change(change_id: str, at: str, session_id: str):
    return {
        "schema": "apatch.studio.imported-change.v1",
        "change_id": change_id,
        "governed_session_id": session_id,
        "objective": "Signed APatch change",
        "created_at": at,
        "updated_at": at,
        "status": "proven",
    }


def test_feed_orders_both_sources_and_deduplicates_exact_session() -> None:
    page = build_unified_change_feed(
        [_run("apr_old", "2026-09-01T10:00:00Z"), _run("apr_new", "2026-09-01T12:00:00Z", SESSION)],
        [
            _change("apchg_duplicate", "2026-09-01T11:00:00Z", SESSION),
            _change("apchg_middle", "2026-09-01T11:30:00Z", "apatch_sess_2000000000000000_other"),
        ],
    )
    assert [(item["kind"], item["id"]) for item in page["items"]] == [
        ("studio_run", "apr_new"),
        ("imported_change", "apchg_middle"),
        ("studio_run", "apr_old"),
    ]
    assert page["count"] == 3


class _Adapter:
    def overview(self, *, force=False):
        return {
            "schema": "test.overview.v1",
            "changes": [
                _change("apchg_existing", "2026-09-01T11:30:00Z", "apatch_sess_3000000000000000_existing")
            ],
        }


class _Runs:
    def runners(self):
        return []

    def list(self):
        return [_run("apr_local", "2026-09-01T12:00:00Z")]

    def journal(self):
        return {"schema": "test.journal.v1"}

    def close(self):
        pass


def test_change_feed_api_returns_existing_apatch_and_studio_work(tmp_path) -> None:
    app = create_app(str(tmp_path), adapter=_Adapter(), run_manager=_Runs(), frontend_root=tmp_path)
    headers = {"x-apatch-studio-session": app.state.studio_guard.token}
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        response = client.get("/api/v1/changes", headers=headers)

    assert response.status_code == 200
    assert [item["kind"] for item in response.json()["items"]] == ["studio_run", "imported_change"]
