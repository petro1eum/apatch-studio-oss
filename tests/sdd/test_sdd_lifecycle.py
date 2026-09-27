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



def _assert_judge_amendment_authoring_lineage(tmp_path, monkeypatch, corruption):
    """Actual Ed25519 transition evidence, never signature-presence fixtures."""
    import copy
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PrivateFormat, NoEncryption
    from apatch.sdd_integrity import _seal
    from apatch.trustchain_helper import TrustChainHelper
    from apatch_studio.authoring_workflow import AuthoringWorkflow
    key = tmp_path / "test-key.pem"
    key.write_bytes(Ed25519PrivateKey.generate().private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    monkeypatch.setenv("APATCH_AGENT_ID", "lineage-test")
    monkeypatch.setenv("APATCH_AGENT_KEY", str(key))
    original_hash, grant = "sha256:" + "1"*64, "sha256:" + "2"*64
    parent = _seal({"schema":"apatch.sdd.verification-contract.v1", "status":"frozen",
        "implementation_allowed":True, "authority":{"actor_id":"owner","role":"authority"},
        "authoring_grant_hash":grant, "supersedes_hash":original_hash})
    details = {"supersedes_hash":parent["document_hash"], "judge_path":"tests/check.py",
               "old_judge_hash":"sha256:"+"3"*64, "new_judge_hash":"sha256:"+"4"*64}
    child = _seal({**parent, "supersedes_hash":parent["document_hash"], "judge_amendment":details})
    proposal = {"grant_hash":grant, "scope":{"contract_hash":original_hash}}
    review_data = {"schema":"apatch.sdd.judge-amendment-review.v1", "authority_id":"owner",
        "previous_contract":parent, "new_contract":child, "contract_hash":parent["document_hash"]}
    shared = isinstance(corruption, str) and corruption.startswith("shared_")
    if shared:
        review_data.update(affected_requirement_refs=["SPEC-DEMO#R1", "SPEC-DEMO#R2"],
            invalidated_acceptance_ids=["AC-1", "AC-2"],
            invalidated_checks_by_requirement={"SPEC-DEMO#R1": ["AC-1"], "SPEC-DEMO#R2": ["AC-2"]})
    review = _seal(review_data)
    result = {"contract":child, "contract_hash":child["document_hash"]}
    receipt = _seal({"review_hash":review["document_hash"], "result":result})
    root = tmp_path
    def put(relative, value):
        path = root / relative; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value)); return path
    active = put(".apatch/sdd_verification_contract.json", child)
    parent_path = put(".apatch/sdd/frozen/"+parent["document_hash"][7:]+".json", parent)
    put(".apatch/sdd/frozen/"+child["document_hash"][7:]+".json", child)
    folder = ".apatch/sdd/judge-amendments/"+review["document_hash"][7:]
    review_path = put(folder+"/review.json", review)
    receipt_path = put(folder+"/receipt.json", receipt)
    tc = TrustChainHelper(str(root), auto_init=True)
    proof = {"schema":"apatch.sdd.judge-amendment-activation.v1", "stage":"activated",
        "amendment_id":review["document_hash"], "authority_id":"owner",
        "contract_hash":child["document_hash"], "previous_contract_hash":parent["document_hash"],
        "judge_path":details["judge_path"], "old_judge_hash":details["old_judge_hash"],
        "new_judge_hash":details["new_judge_hash"]}
    if shared:
        for ref in review["affected_requirement_refs"]:
            item = {**proof, "requirement_ref": ref, "affected_requirement_refs": [ref],
                "affected_requirements": [ref.split("#")[1]],
                "invalidated_acceptance_ids": review["invalidated_checks_by_requirement"][ref],
                "invalidated_checks_by_requirement": review["invalidated_checks_by_requirement"],
                "review_invalidated_acceptance_ids": review["invalidated_acceptance_ids"],
                "review_affected_requirement_refs": review["affected_requirement_refs"],
                "functional_acceptance": False}
            if corruption == "shared_missing" and ref.endswith("R2"):
                continue
            if corruption == "shared_wrong_checks" and ref.endswith("R2"):
                item["invalidated_acceptance_ids"] = ["AC-1"]
            if corruption == "shared_wrong_owner" and ref.endswith("R2"):
                item["authority_id"] = "other"
            assert tc.commit_action("apatch_sdd_judge_amendment", item)
            if corruption == "shared_duplicate_conflict" and ref.endswith("R2"):
                assert tc.commit_action("apatch_sdd_judge_amendment", {**item, "new_judge_hash": "sha256:"+"a"*64})
    else:
        assert tc.commit_action("apatch_sdd_judge_amendment", proof)
    if corruption == "missing_receipt":
        receipt_path.unlink()
    elif corruption == "wrong_grant":
        proposal["grant_hash"] = "sha256:" + "f"*64
    elif corruption == "wrong_review":
        wrong = copy.deepcopy(review); wrong["authority_id"]="other"
        wrong.pop("document_hash"); review_path.write_text(json.dumps(_seal(wrong)))
    elif corruption == "bad_seal":
        changed=copy.deepcopy(child);changed["authority"]["actor_id"]="other"
        active.write_text(json.dumps(changed))
    elif corruption == "cycle":
        cyclic=copy.deepcopy(parent);cyclic["supersedes_hash"]=child["document_hash"]
        parent_path.write_text(json.dumps(cyclic))
    elif corruption == "missing_parent":
        parent_path.unlink()
    elif corruption == "bad_signature":
        for row in tc.iter_ledger_entries():
            if row["tool_id"] == "apatch_sdd_judge_amendment":
                path=root/".trustchain"/row["object_path"];raw=json.loads(path.read_text())
                raw["value"]["data"]["authority_id"]="forged";path.write_text(json.dumps(raw))
    if corruption in (None, "shared_valid"):
        assert AuthoringWorkflow(root)._activated_successor_of(proposal) is True
    else:
        try:
            allowed = AuthoringWorkflow(root)._activated_successor_of(proposal)
        except (ValueError, OSError):
            allowed = False
        assert allowed is False

@pytest.mark.parametrize("corruption", [None, "missing_receipt", "wrong_grant", "wrong_review", "bad_seal", "cycle", "missing_parent", "bad_signature", "shared_valid", "shared_missing", "shared_wrong_checks", "shared_wrong_owner", "shared_duplicate_conflict", "shared_roundtrip"])
def test_amendment_invalidates_only_affected_work(facade, tmp_path, monkeypatch, corruption) -> None:
    if corruption == "shared_roundtrip":
        from tests.authoring.test_shared_authoring_roundtrip import test_shared_amendment_then_next_signed_authoring_and_successor
        test_shared_amendment_then_next_signed_authoring_and_successor(tmp_path, monkeypatch)
    else:
        _assert_judge_amendment_authoring_lineage(tmp_path, monkeypatch, corruption)
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

