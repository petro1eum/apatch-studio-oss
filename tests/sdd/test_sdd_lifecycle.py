from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


def _api():
    return importlib.import_module("apatch_studio.sdd_workflow")


class _CoreFacts:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def preview_assignment(self, request: dict) -> dict:
        self.calls.append(("preview_assignment", request))
        return {
            "brief": {
                "schema": "apatch.sdd.brief.v1",
                "brief_id": "brief_11111111111111111111111111111111",
                "revision": 1,
                "author": request["author"],
                "source": request["source"],
                "created_at": "2026-09-01T12:00:00.000000Z",
                "content_hash": "sha256:" + "1" * 64,
                "parent_hash": None,
                "objective": request["objective"],
            },
            "coverage": {"complete": True, "missing": [], "ambiguous": []},
        }

    def freeze_contract(self, request: dict) -> dict:
        self.calls.append(("freeze_contract", request))
        return {
            "schema": "apatch.sdd.contract-freeze.v1",
            "freeze_id": "sddfrz_" + "2" * 32,
            "status": "frozen",
            "frozen_at": "2026-09-01T12:01:00.000000Z",
            "implementation_allowed": True,
            "source_mutation_count_at_freeze": 0,
            "authority": {"actor_id": request["authority"]["actor_id"], "role": "owner"},
            "contract_hash": "sha256:" + "2" * 64,
            "envelope_hash": "sha256:" + "3" * 64,
            "judge_assets": request["judge_assets"],
        }

    def project_change(self, change_id: str) -> dict:
        self.calls.append(("project_change", {"change_id": change_id}))
        return {
            "change_id": change_id,
            "objective": "Prevent unauthorized changes",
            "authority": {"label": "Approved by project owner"},
            "scope": {
                "containment": "mediated_only",
                "allowed": ["Application source requested by R4"],
                "forbidden": ["Approved tests and contract", "Unlisted network and service effects"],
                "budgets": {"files": 4, "seconds": 900},
                "violations": [{"effect": "write", "status": "blocked", "count": 1}],
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
            },
            "timeline": [
                {"kind": "request", "label": "You asked", "reason": "Prevent unauthorized changes"},
                {"kind": "decision", "label": "Owner approved the exact contract", "reason": "Scope and checks were reviewed"},
                {"kind": "execution", "label": "The agent changed only approved source", "reason": "R4 implementation"},
                {"kind": "verification", "label": "The checks detected a seeded defect and then passed", "reason": "Independent verification"},
                {"kind": "attestation", "label": "The result was recorded", "reason": "Exact hashes were bound"},
            ],
            "effort": {
                "derivation": "signed_event_op_spacing",
                "draft_hours": 1.5,
                "quality": "estimated",
                "accepted_time": False,
            },
        }

    def propose_amendment(self, request: dict) -> dict:
        self.calls.append(("propose_amendment", request))
        return {
            "schema": "apatch.sdd.contract-amendment.v1",
            "status": "proposed",
            "reason": request["reason"],
            "supersedes_hash": request["contract_hash"],
            "changed_hashes": ["sha256:" + "4" * 64],
            "invalidated_requirement_ids": ["R4"],
            "preserved_requirement_ids": ["R1", "R2", "R3"],
            "approval_required": True,
            "implementation_actor_may_approve": False,
        }


@pytest.fixture()
def facade(tmp_path: Path):
    module = _api()
    backend = _CoreFacts()
    return module.SddWorkflowFacade(tmp_path, backend=backend), backend


def _assignment() -> dict:
    return {
        "author": "owner:local",
        "source": "typed",
        "objective": "Keep the agent inside the exact requested task",
        "outcomes": ["Unauthorized effects are denied"],
        "constraints": ["No test mutation"],
        "non_goals": ["No generic remote shell"],
    }


def _freeze_request() -> dict:
    return {
        "rfp": {"id": "RFP-012", "hash": "sha256:" + "a" * 64},
        "spec": {"id": "SPEC-X", "hash": "sha256:" + "b" * 64},
        "plan_hash": "sha256:" + "c" * 64,
        "baseline_hash": "sha256:" + "d" * 64,
        "judge_assets": [
            {
                "acceptance_id": "AC-1",
                "test_id": "tests/test_scope.py::test_denied",
                "oracle": "The denied operation performs no external effect",
                "perspectives": ["positive", "negative", "boundary", "regression"],
                "asset_hashes": ["sha256:" + "e" * 64],
                "command_hash": "sha256:" + "f" * 64,
                "falsification": {"kind": "reversible_seed", "expected": "red"},
            }
        ],
        "authority": {"actor_id": "owner:local", "role": "owner"},
        "source_mutation_count": 0,
    }


def test_existing_apatch_remains_canonical(facade) -> None:
    view, _ = facade
    assert view.ownership()["execution_runtime"] == "apatch"
    assert view.ownership()["studio_role"] == "human_projection_and_commands"
    assert view.ownership()["duplicate_state_forbidden"] is True


def test_brief_is_versioned_and_hashed(facade) -> None:
    view, backend = facade
    result = view.preview_assignment(_assignment())
    assert result["brief"]["revision"] == 1
    assert result["brief"]["content_hash"].startswith("sha256:")
    assert result["brief"]["author"] == "owner:local"
    assert backend.calls[0][0] == "preview_assignment"


def test_acceptance_to_requirement_coverage_is_complete(facade) -> None:
    view, _ = facade
    assert view.preview_assignment(_assignment())["coverage"] == {
        "complete": True,
        "missing": [],
        "ambiguous": [],
    }


def test_verification_contract_is_frozen_before_mutation(facade) -> None:
    view, _ = facade
    frozen = view.freeze_contract(_freeze_request())
    assert frozen["status"] == "frozen"
    assert frozen["source_mutation_count_at_freeze"] == 0
    assert frozen["implementation_allowed"] is True
    assert frozen["judge_assets"][0]["test_id"].endswith("::test_denied")


def test_behavioral_contract_requires_multiple_perspectives(facade) -> None:
    view, _ = facade
    invalid = _freeze_request()
    invalid["judge_assets"][0]["perspectives"] = ["positive"]
    with pytest.raises(ValueError, match="perspectives"):
        view.freeze_contract(invalid)


def test_falsification_must_observe_red_before_ratification(facade) -> None:
    view, _ = facade
    change = view.change("chg_" + "1" * 32)
    assert change["verification"]["falsification"] == {
        "observed_red": True,
        "restored_green": True,
    }


def test_implementation_actor_cannot_change_frozen_judge(facade) -> None:
    view, _ = facade
    assert "Approved tests and contract" in view.change("chg_" + "1" * 32)["scope"]["forbidden"]


def test_task_envelope_is_complete_and_human_readable(facade) -> None:
    view, _ = facade
    scope = view.change("chg_" + "1" * 32)["scope"]
    assert scope["allowed"] and scope["forbidden"] and scope["budgets"]
    assert scope["containment"] == "mediated_only"


def test_supported_effect_surfaces_share_one_admission_result(facade) -> None:
    module = _api()
    decisions = {
        module.project_admission({"effect": effect, "allowed": False})["decision"]
        for effect in ("mutation", "mcp_tool", "local_runner", "sandbox", "network", "remote", "service")
    }
    assert decisions == {"denied"}


def test_denied_effect_is_visible_and_blocks_proof(facade) -> None:
    view, _ = facade
    change = view.change("chg_" + "1" * 32)
    assert change["scope"]["violations"][0] == {"effect": "write", "status": "blocked", "count": 1}
    serialized = json.dumps(change)
    assert "/Users/" not in serialized and "source_code" not in serialized


def test_plan_mismatch_is_blocking(facade) -> None:
    module = _api()
    outcome = module.project_admission({"effect": "write", "allowed": True, "plan_match": False})
    assert outcome["decision"] == "denied"
    assert outcome["blocks_proof"] is True


def test_solo_freeze_precedes_implementation(facade) -> None:
    view, _ = facade
    frozen = view.freeze_contract(_freeze_request())
    assert frozen["frozen_at"] < "2026-09-01T12:02:00.000000Z"
    assert frozen["authority"]["role"] == "owner"


def test_team_authority_and_contributor_do_not_collapse(facade) -> None:
    module = _api()
    assert module.role_separation("authority:1", "contributor:2", "verifier:3")["separated"] is True
    assert module.role_separation("actor:1", "actor:1", "verifier:3")["separated"] is False


def test_studio_projects_allowed_and_forbidden_scope(facade) -> None:
    view, _ = facade
    contour = view.scope_contour("chg_" + "1" * 32)
    assert contour["title"] == "What the agent can do"
    assert contour["allowed_label"] == "Allowed for this change"
    assert contour["forbidden_label"] == "Not allowed"
    assert contour["violations_label"] == "Blocked attempts"


def test_verifier_rejects_empty_skipped_drifted_and_incomplete_gates(facade) -> None:
    module = _api()
    base = {"required_perspectives": ["positive", "negative", "boundary", "regression"]}
    cases = [
        {**base, "collected": 0, "executed": 0, "skipped": 0, "perspectives": base["required_perspectives"]},
        {**base, "collected": 4, "executed": 0, "skipped": 4, "perspectives": base["required_perspectives"]},
        {**base, "collected": 4, "executed": 4, "skipped": 0, "perspectives": base["required_perspectives"], "asset_drift": True},
        {**base, "collected": 4, "executed": 4, "skipped": 0, "perspectives": ["positive"]},
    ]
    assert all(module.project_verifier_quality(case)["accepted"] is False for case in cases)


def test_proof_binds_exact_contract_and_envelope(facade) -> None:
    view, _ = facade
    proof = view.change("chg_" + "1" * 32)["proof"]
    assert proof["contract_hash"].startswith("sha256:")
    assert proof["envelope_hash"].startswith("sha256:")
    assert proof["adherence"] == "compliant"
    assert proof["checkpoint_refs"] and proof["ledger_refs"]


def test_causal_replay_uses_human_language(facade) -> None:
    view, _ = facade
    replay = view.causal_replay("chg_" + "1" * 32)
    assert [row["kind"] for row in replay] == [
        "request", "decision", "execution", "verification", "attestation"
    ]
    assert all(row["label"] and row["reason"] for row in replay)
    assert "governed_session_id" not in json.dumps(replay)


def test_effort_is_rederived_and_not_accepted_time(facade) -> None:
    view, _ = facade
    effort = view.change("chg_" + "1" * 32)["effort"]
    assert effort["derivation"] == "signed_event_op_spacing"
    assert effort["accepted_time"] is False
    assert effort["quality"] == "estimated"


def test_amendment_invalidates_only_affected_work(facade) -> None:
    view, _ = facade
    amendment = view.propose_amendment({
        "contract_hash": "sha256:" + "2" * 64,
        "reason": "The boundary oracle omitted a required failure mode",
        "changed_acceptance_ids": ["SDD-5"],
    })
    assert amendment["status"] == "proposed"
    assert amendment["invalidated_requirement_ids"] == ["R4"]
    assert amendment["preserved_requirement_ids"] == ["R1", "R2", "R3"]
    assert amendment["implementation_actor_may_approve"] is False


def test_oss_and_cowork_share_integrity_floor(facade) -> None:
    module = _api()
    oss = module.integrity_floor("oss")
    cowork = module.integrity_floor("cowork")
    assert oss == cowork
    assert {"strict_envelope", "locked_judge", "meaningful_verification", "falsification"} <= set(oss)
