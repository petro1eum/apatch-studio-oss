from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from apatch_studio.agent_runs import build_governed_prompt
from apatch_studio.app import create_app
from apatch_studio.operations import AgentRunRequest


CHANGE_ID = "apchg_" + "1" * 32
ROOT = Path(__file__).resolve().parents[2]


class _Adapter:
    def overview(self, *, force: bool = False):
        return {"schema": "test.overview.v1", "changes": []}

    def change_detail(self, change_id: str):
        return {
            "schema": "apatch.studio.imported-change-detail.v1",
            "change_id": change_id,
            "available_actions": [],
        }


class _Runs:
    def runners(self):
        return []

    def list(self):
        return []

    def journal(self):
        return {"schema": "test.journal.v1"}

    def close(self):
        pass


class _Sdd:
    def __init__(self, *, legacy: bool = False):
        self.legacy = legacy

    def change(self, change_id: str):
        if self.legacy:
            raise LookupError("change has no SDD evidence")
        return {
            "schema": "apatch.studio.sdd-change.v1",
            "change_id": change_id,
            "scope": {
                "containment": "mediated_only",
                "allowed": ["Change the requested application source"],
                "forbidden": ["Do not change approved tests and contract"],
                "budgets": {"files": 4, "seconds": 900},
                "violations": [],
                "amendment": {"status": "not_requested"},
            },
            "verification": {
                "capability": "non_mutating",
                "collected": 12,
                "executed": 12,
                "passed": 12,
                "failed": 0,
                "skipped": 0,
                "perspectives": ["positive", "negative", "boundary", "regression"],
                "falsification": {"observed_red": True, "restored_green": True},
                "gate_quality": "meaningful",
                "accepted": True,
                "reasons": [],
            },
            "proof": {
                "status": "proven",
                "contract_hash": "sha256:" + "2" * 64,
                "envelope_hash": "sha256:" + "3" * 64,
                "actor": "agent:codex",
                "mutation_count": 3,
                "adherence": "compliant",
                "checkpoint_refs": ["checkpoint:1"],
                "ledger_refs": ["op:1"],
                "evidence_hash": "sha256:" + "4" * 64,
            },
            "timeline": [
                {
                    "kind": "request",
                    "label": "You asked",
                    "reason": "Prevent unauthorized changes",
                    "at": "2026-09-01T12:00:00Z",
                }
            ],
            "effort": {
                "derivation": "signed_event_op_spacing",
                "draft_hours": 1.5,
                "quality": "estimated",
                "accepted_time": False,
                "method_note": "Estimate from signed APatch event spacing, not a stopwatch",
            },
        }


def _client(tmp_path: Path, sdd: _Sdd):
    app = create_app(
        str(tmp_path),
        adapter=_Adapter(),
        run_manager=_Runs(),
        sdd_facade=sdd,
        frontend_root=tmp_path,
    )
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    headers = {"x-apatch-studio-session": app.state.studio_guard.token}
    return app, client, headers


def test_change_api_composes_canonical_sdd_facts_without_a_new_route(tmp_path: Path) -> None:
    app, client, headers = _client(tmp_path, _Sdd())
    response = client.get(f"/api/v1/changes/{CHANGE_ID}", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["sdd"]["available"] is True
    assert payload["sdd"]["scope"]["containment"] == "mediated_only"
    assert payload["sdd"]["verification"]["collected"] == 12
    assert payload["sdd"]["proof"]["contract_hash"].startswith("sha256:")
    assert payload["sdd"]["effort"]["accepted_time"] is False
    assert app.state.studio_sdd is not None
    assert not {
        route.path
        for route in app.routes
        if route.path.startswith("/api/v1/sdd")
    }


def test_legacy_change_is_explicit_and_never_receives_fabricated_proof(tmp_path: Path) -> None:
    _app, client, headers = _client(tmp_path, _Sdd(legacy=True))
    payload = client.get(f"/api/v1/changes/{CHANGE_ID}", headers=headers).json()

    assert payload["sdd"] == {
        "schema": "apatch.studio.sdd-change-status.v1",
        "available": False,
        "reason": "legacy_change_without_frozen_contract",
        "message": "This change predates the frozen execution contract.",
    }


def test_new_change_prompt_forbids_source_work_before_owner_freeze() -> None:
    prompt = build_governed_prompt(
        AgentRunRequest(
            mode="new_change",
            runner="codex",
            objective="Keep the agent inside the reviewed task",
            acceptance_criteria=["Out-of-scope effects are denied"],
        )
    )

    assert "Source implementation is forbidden until" in prompt
    assert "frozen verification contract" in prompt
    assert "positive, negative, boundary and regression" in prompt
    assert "reversible falsification" in prompt
    assert "Do not approve the contract or amendment as the implementation actor" in prompt


def test_change_screen_renders_the_human_sdd_lifecycle() -> None:
    source = (ROOT / "frontend/src/ChangeDetailView.tsx").read_text(encoding="utf-8")
    types = (ROOT / "frontend/src/types.ts").read_text(encoding="utf-8")

    for component in (
        "ExecutionContractSection",
        "VerificationSection",
        "CausalReplaySection",
        "EffortSection",
    ):
        assert component in source
    for label in (
        "What the agent was allowed to do",
        "What the agent could not do",
        "How this was checked",
        "Why this change happened",
        "Estimated governed effort",
        "not accepted time",
    ):
        assert label in source
    assert "detail.sdd?.available" in source
    assert "interface SddChangeProjection" in types
    assert "sdd: SddChangeProjection" in types
