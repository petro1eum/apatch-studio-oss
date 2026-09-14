import json
from pathlib import Path

from fastapi.testclient import TestClient

from apatch_studio.app import create_app


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads(
    (ROOT / "frontend/src/navigation.contract.json").read_text(encoding="utf-8")
)


def test_every_visible_tab_has_an_executable_interaction_contract():
    targets = CONTRACT["targets"]
    assert len(targets) == 5
    for target in targets:
        assert target["primary_action"].strip()
        assert len(target["terminal_states"]) >= 2
        assert target["recovery_actions"]
        assert len(set(target["terminal_states"])) == len(target["terminal_states"])
        assert len(set(target["recovery_actions"])) == len(target["recovery_actions"])


def test_primary_actions_are_real_controls_with_progress_and_failure_states():
    sources = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in [
            "frontend/src/OutsideInApp.tsx",
            "frontend/src/OutsideInViews.tsx",
            "frontend/src/OutsideInAdmin.tsx",
            "frontend/src/ProjectPlanView.tsx",
        ]
    )
    for target in CONTRACT["targets"]:
        assert target["primary_action"] in sources
    for interaction_state in [
        "oi-progress",
        "oi-alert",
        "requestConfirm",
        "disabled={acting !== null}",
    ]:
        assert interaction_state in sources
    for recovery in [
        "retryRun",
        "recover",
        "rollback_preview",
        "rebindSpec",
        "restore",
        "rollback",
    ]:
        assert recovery in sources


def test_read_only_counts_do_not_define_tab_completion():
    serialized = json.dumps(CONTRACT, sort_keys=True)
    assert "primary_action" in serialized
    assert "terminal_states" in serialized
    assert "recovery_actions" in serialized
    assert all(target["primary_action"] != "Refresh" for target in CONTRACT["targets"])


def test_refresh_preserves_the_complete_product_projection(tmp_path):
    class Adapter:
        def overview(self, *, force=False):
            return {"schema": "apatch.studio.workspace-overview.v1", "force": force}

    class Runs:
        def close(self):
            pass

    app = create_app(
        str(tmp_path),
        adapter=Adapter(),
        run_manager=Runs(),
        frontend_root=tmp_path,
        edition="oss",
        intent_state_root=tmp_path.parent / "intent-state-functional-tabs",
    )
    headers = {
        "x-apatch-studio-session": app.state.studio_guard.token,
        "origin": "http://127.0.0.1:8765",
    }
    with TestClient(app, base_url="http://127.0.0.1:8765") as client:
        opened = client.get("/api/v1/overview", headers=headers)
        refreshed = client.post("/api/v1/refresh", headers=headers)

    assert opened.status_code == refreshed.status_code == 200
    assert opened.json()["force"] is False
    assert refreshed.json()["force"] is True
    for key in ["product", "execution_intents"]:
        assert refreshed.json()[key] == opened.json()[key]
