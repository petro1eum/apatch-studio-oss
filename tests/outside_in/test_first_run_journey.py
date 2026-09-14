from pathlib import Path

from fastapi.testclient import TestClient

from apatch_studio.app import create_app


ROOT = Path(__file__).resolve().parents[2]


class _Adapter:
    def overview(self, *, force=False):
        return {"schema": "test.overview.v1", "force": force}


class _Runs:
    def __init__(self):
        self.items = []

    def runners(self):
        return [{"id": "codex", "label": "Codex", "available": True}]

    def start(self, request, *, retry_of=None):
        item = {
            "schema": "apatch.studio.agent-run.v1",
            "run_id": "apr_" + "1" * 32,
            "runner": request.runner,
            "mode": request.mode,
            "objective": request.objective,
            "status": "succeeded",
            "phase": "complete",
            "message": "Agent completed protected work",
            "created_at": "2026-09-01T00:00:00Z",
            "started_at": "2026-09-01T00:00:01Z",
            "ended_at": "2026-09-01T00:00:02Z",
            "outcome": "complete",
            "thread_id": None,
            "retry_of": retry_of,
            "event_count": 3,
            "review": None,
            "timeline": [],
            "reviewer_note": None,
            "contribution": None,
            "scope": {
                "schema": "apatch.studio.scope-outcome.v1",
                "status": "clean",
                "audit_observed": True,
                "planned_file_count": 1,
                "logical_areas": ["tests"],
                "blocked_out_of_scope": 0,
                "reverted_out_of_scope": 0,
                "unresolved_out_of_scope": 0,
            },
            "work_ref": {
                "spec_id": None,
                "requirement_id": None,
                "governed_session_id": None,
            },
            "available_actions": ["open_review"],
            "persisted": True,
            "can_cancel": False,
            "can_retry": False,
        }
        self.items.append(item)
        return item

    def list(self):
        return list(reversed(self.items))

    def journal(self):
        return {
            "schema": "apatch.studio.run-journal-status.v1",
            "persistent": True,
            "status": "ready",
            "warning": None,
            "record_count": len(self.items),
            "retention": 200,
            "interrupted_on_start": 0,
        }

    def close(self):
        pass


def test_disposable_first_run_reaches_a_proven_change_without_setup_modes(tmp_path):
    runs = _Runs()
    app = create_app(
        str(tmp_path),
        adapter=_Adapter(),
        run_manager=runs,
        frontend_root=tmp_path,
    )
    headers = {
        "x-apatch-studio-session": app.state.studio_guard.token,
        "origin": "http://127.0.0.1:8765",
    }
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        empty = client.get("/api/v1/runs", headers=headers)
        assert empty.status_code == 200
        assert empty.json()["items"] == []

        started = client.post(
            "/api/v1/runs",
            headers=headers,
            json={
                "mode": "new_change",
                "runner": "codex",
                "objective": "Make the requested behavior true",
                "acceptance_criteria": ["The requested outcome is verified"],
            },
        )
        assert started.status_code == 202
        assert started.json()["status"] == "succeeded"
        assert started.json()["scope"]["status"] == "clean"

        listed = client.get("/api/v1/runs", headers=headers)
        assert listed.json()["items"][0]["objective"] == "Make the requested behavior true"


def test_empty_home_presents_one_primary_start_action() -> None:
    source = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")
    first_run = source.split("export function HomeView", 1)[1].split(
        "function ChangeCard",
        1,
    )[0]
    assert "changes.length === 0" in first_run
    assert "Start your first change" in first_run
    assert first_run.count("oi-start-button") == 1
    assert "What do you want to change?" in first_run
