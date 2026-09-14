from fastapi.testclient import TestClient

from apatch_studio.app import create_app


class FakeAdapter:
    def overview(self, *, force=False):
        return {"ok": True, "force": force}


class FakeRunManager:
    def __init__(self):
        self.records = {}
        self.closed = False

    def runners(self):
        return [
            {"id": "codex", "label": "Codex", "available": True},
            {"id": "claude", "label": "Claude Code", "available": False},
        ]

    def start(self, request, *, retry_of=None):
        run_id = f"apr_{len(self.records) + 1:032x}"
        record = {
            "schema": "apatch.studio.agent-run.v1",
            "run_id": run_id,
            "runner": request.runner,
            "mode": request.mode,
            "objective": request.objective,
            "status": "queued",
            "phase": "queued",
            "message": "Waiting for a local runner slot",
            "created_at": "2026-08-31T00:00:00+00:00",
            "started_at": None,
            "ended_at": None,
            "outcome": None,
            "thread_id": None,
            "retry_of": retry_of,
            "event_count": 0,
            "review": {
                "schema": "apatch.studio.run-review.v1",
                "baseline": None,
                "result": None,
                "delta": None,
                "attribution": "workspace_observation_only",
            },
            "persisted": True,
            "can_cancel": True,
            "can_retry": False,
        }
        self.records[run_id] = record
        return record

    def list(self):
        return list(reversed(self.records.values()))

    def journal(self):
        return {
            "schema": "apatch.studio.run-journal-status.v1",
            "persistent": True,
            "status": "ready",
            "warning": None,
            "record_count": len(self.records),
            "retention": 200,
            "interrupted_on_start": 0,
        }

    def get(self, run_id):
        from apatch_studio.agent_runs import RunNotFoundError

        if run_id not in self.records:
            raise RunNotFoundError(run_id)
        return self.records[run_id]

    def cancel(self, run_id):
        record = self.get(run_id)
        record.update(
            status="cancelled",
            phase="complete",
            outcome="cancelled",
            message="Agent run cancelled",
            can_cancel=False,
            can_retry=True,
        )
        return record

    def retry(self, run_id):
        from apatch_studio.agent_runs import RunStateError

        record = self.get(run_id)
        if not record["can_retry"]:
            raise RunStateError("only failed or cancelled runs can be retried")
        from apatch_studio.operations import AgentRunRequest

        request = AgentRunRequest.model_validate(
            {
                "mode": record["mode"],
                "runner": record["runner"],
                "objective": record["objective"],
                "acceptance_criteria": ["The focused verification passes"],
            }
        )
        return self.start(request, retry_of=run_id)

    def close(self):
        self.closed = True


def make_client(tmp_path):
    manager = FakeRunManager()
    app = create_app(
        str(tmp_path),
        adapter=FakeAdapter(),
        run_manager=manager,
        frontend_root=tmp_path,
    )
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    token = app.state.studio_guard.token
    headers = {
        "x-apatch-studio-session": token,
        "origin": "http://127.0.0.1:8765",
    }
    return app, manager, client, headers


def valid_request():
    return {
        "mode": "new_change",
        "runner": "codex",
        "objective": "Implement a bounded export workflow",
        "acceptance_criteria": ["The focused verification passes"],
    }


def test_fixed_purpose_run_api(tmp_path):
    _app, manager, client, headers = make_client(tmp_path)

    runners = client.get("/api/v1/runners", headers=headers)
    assert runners.status_code == 200
    assert runners.json()["items"][0] == {
        "id": "codex",
        "label": "Codex",
        "available": True,
    }

    started = client.post("/api/v1/runs", headers=headers, json=valid_request())
    assert started.status_code == 202
    run = started.json()
    assert run["status"] == "queued"
    assert run["objective"] == "Implement a bounded export workflow"

    listed = client.get("/api/v1/runs", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["items"][0]["run_id"] == run["run_id"]

    detail = client.get(f"/api/v1/runs/{run['run_id']}", headers=headers)
    assert detail.status_code == 200

    cancelled = client.post(f"/api/v1/runs/{run['run_id']}/cancel", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"

    retried = client.post(f"/api/v1/runs/{run['run_id']}/retry", headers=headers)
    assert retried.status_code == 202
    assert retried.json()["retry_of"] == run["run_id"]
    assert len(manager.records) == 2

    missing = client.get("/api/v1/runs/apr_missing", headers=headers)
    assert missing.status_code == 404
    assert missing.json() == {"ok": False, "error": "run not found"}


def test_run_api_returns_persisted_review_metadata(tmp_path):
    _app, _manager, client, headers = make_client(tmp_path)
    started = client.post("/api/v1/runs", headers=headers, json=valid_request()).json()

    listed = client.get("/api/v1/runs", headers=headers)
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["schema"] == "apatch.studio.agent-runs.v2"
    assert payload["journal"] == {
        "schema": "apatch.studio.run-journal-status.v1",
        "persistent": True,
        "status": "ready",
        "warning": None,
        "record_count": 1,
        "retention": 200,
        "interrupted_on_start": 0,
    }
    assert payload["items"][0]["persisted"] is True
    assert payload["items"][0]["review"]["attribution"] == "workspace_observation_only"

    detail = client.get(f"/api/v1/runs/{started['run_id']}", headers=headers).json()
    assert detail["review"] == payload["items"][0]["review"]
    serialized = str(payload)
    assert "session_token" not in serialized
    assert "workspace_path" not in serialized
    assert "raw" not in serialized


def test_api_rejects_arbitrary_command_fields(tmp_path):
    _app, _manager, client, headers = make_client(tmp_path)
    for field, value in [
        ("command", "rm -rf ."),
        ("argv", ["bash", "-lc", "env"]),
        ("cwd", "/tmp"),
        ("environment", {"TOKEN": "secret"}),
        ("mcp_tool", "apatch_apply"),
        ("permission_mode", "bypassPermissions"),
    ]:
        payload = {**valid_request(), field: value}
        response = client.post("/api/v1/runs", headers=headers, json=payload)
        assert response.status_code == 422
        assert not _manager.records

    assert client.post("/api/v1/runs", json=valid_request()).status_code == 401
    attacker = {
        "x-apatch-studio-session": headers["x-apatch-studio-session"],
        "origin": "http://attacker.invalid",
    }
    assert client.post("/api/v1/runs", headers=attacker, json=valid_request()).status_code == 403
