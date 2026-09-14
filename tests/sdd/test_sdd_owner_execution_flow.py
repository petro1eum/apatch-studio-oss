from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


SPEC_ID = "SPEC-DEMO-1"
REQUIREMENT_ID = "R1"
SECOND_REQUIREMENT_ID = "R2"

# The judge has to be a real file with a real hash: freezing pins the exact test
# that will later be re-read and re-hashed before any verdict is trusted.
_JUDGE_PATH = "tests/test_feature.py"
_JUDGE_SOURCE = "def test_feature() -> None:\n    assert True\n"
_JUDGE_SHA256 = "sha256:" + hashlib.sha256(_JUDGE_SOURCE.encode("utf-8")).hexdigest()


def _prepared_package() -> dict:
    from apatch.sdd_integrity import canonical_hash

    command = ["python3", "-m", "pytest", "tests/test_feature.py::test_feature", "-q"]
    contract_request = {
        "brief_hash": "sha256:" + "1" * 64,
        "rfp_hash": "sha256:" + "2" * 64,
        "spec_hash": "sha256:" + "3" * 64,
        "plan_hash": "sha256:" + "4" * 64,
        "baseline_hash": "sha256:" + "5" * 64,
        "coverage": {
            "complete": True,
            "missing": [],
            "ambiguous": [],
            "waivers": [],
        },
        "obligations": [
            {
                "acceptance_id": "AC-1",
                "test_id": "tests/test_feature.py::test_feature",
                "oracle": "The requested behavior is observable through the public API",
                "perspectives": ["positive", "negative", "boundary", "regression"],
                "asset_hashes": [_JUDGE_SHA256],
                "command": command,
                "command_hash": canonical_hash(command),
                "baseline": {
                    "kind": "observed_red",
                    "result_hash": "sha256:" + "7" * 64,
                },
                "falsification": {
                    "kind": "reversible_seed",
                    "expected": "red",
                    "target_hash": "sha256:" + "8" * 64,
                },
                "approver": "owner:pending",
                "material": True,
            }
        ],
    }
    envelope = {
        "schema": "apatch.sdd.task-envelope.v1",
        "requirement": f"{SPEC_ID}#{REQUIREMENT_ID}",
        "baseline_hash": contract_request["baseline_hash"],
        "allowed_reads": ["src/**", "tests/**"],
        "allowed_writes": ["src/feature.py"],
        "allowed_symbols": ["feature.apply"],
        "forbidden_paths": [
            "docs/RFP-*.md",
            "docs/specs/**",
            "docs/contracts/**",
            "tests/**",
            "schemas/**",
        ],
        "tools": ["apatch_session_start", "apatch_execute_next", "apatch_verify_run"],
        "commands": [command],
        "network": [],
        "remote": [],
        "services": [],
        "budgets": {
            "files": 1,
            "insertions": 80,
            "deletions": 20,
            "seconds": 900,
        },
        "checks": ["AC-1"],
        "rollback_owner": "session:self",
        "containment": "mediated_only",
    }
    return {
        "schema": "apatch.studio.sdd-preparation.v1",
        "spec_id": SPEC_ID,
        "objective": "Make the reviewed feature behavior true",
        "prepared_at": "2026-09-01T14:20:00+00:00",
        "source_mutation_count": 0,
        "contract_request": contract_request,
        "task_envelopes": {
            REQUIREMENT_ID: envelope,
            SECOND_REQUIREMENT_ID: {
                **envelope,
                "requirement": f"{SPEC_ID}#{SECOND_REQUIREMENT_ID}",
            },
        },
    }


def _write_prepared(root: Path) -> Path:
    judge = root / _JUDGE_PATH
    judge.parent.mkdir(parents=True, exist_ok=True)
    judge.write_text(_JUDGE_SOURCE, encoding="utf-8")
    path = root / ".apatch" / "sdd" / "prepared" / f"{SPEC_ID}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_prepared_package(), ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    return path




def test_review_token_is_bound_to_the_selected_requirement(tmp_path):
    path = _write_prepared(tmp_path)
    package = json.loads(path.read_text())
    package["task_envelopes"]["R2"]["budgets"]["files"] = 999
    path.write_text(json.dumps(package))
    client, headers, _runs = _client(tmp_path)
    r1 = f"/api/v1/specs/{SPEC_ID}/requirements/R1/execution-contract"
    r2 = f"/api/v1/specs/{SPEC_ID}/requirements/R2/execution-contract"
    with client:
        first = client.get(r1, headers=headers).json()
        second = client.get(r2, headers=headers).json()
        assert first["approval_snapshot"] != second["approval_snapshot"]
        rejected = client.post(r2 + "/freeze", headers=headers, json={
            "request_id": "apsreq_cross_requirement_snapshot_1", "confirmed": True,
            "snapshot": first["approval_snapshot"],
        })
        assert rejected.status_code == 409, rejected.text
        assert rejected.json()["error_code"] == "sdd_approval_drift"
        _assert_no_frozen_output(tmp_path)
        approved = client.post(r2 + "/freeze", headers=headers, json={
            "request_id": "apsreq_own_requirement_snapshot_1", "confirmed": True,
            "snapshot": second["approval_snapshot"],
        })
        assert approved.status_code == 200, approved.text
        assert approved.json()["budgets"]["files"] == 999


@pytest.mark.parametrize("changed", ["budget", "scope", "contract"])
def test_prepared_drift_cannot_masquerade_as_an_existing_sealed_boundary(tmp_path, changed):
    from apatch_studio.sdd_workflow import SddWorkflowError, SddWorkflowFacade

    path = _write_prepared(tmp_path)
    facade = SddWorkflowFacade(tmp_path)
    original = facade.freeze_requirement(SPEC_ID, REQUIREMENT_ID,
        owner_actor_id="owner:local", confirmed=True)
    package = json.loads(path.read_text())
    if changed == "budget":
        package["task_envelopes"]["R1"]["budgets"]["files"] = 999
    elif changed == "scope":
        package["task_envelopes"]["R1"]["allowed_writes"].append("src/another.py")
    else:
        package["contract_request"]["plan_hash"] = "sha256:" + "a" * 64
    path.write_text(json.dumps(package))
    token = facade.approval_snapshot(SPEC_ID, REQUIREMENT_ID)
    with pytest.raises(SddWorkflowError) as review_error:
        facade.contract_review(SPEC_ID, REQUIREMENT_ID, with_snapshot=True)
    assert review_error.value.code == "sdd_approval_drift"
    with pytest.raises(SddWorkflowError) as freeze_error:
        facade.freeze_requirement(SPEC_ID, REQUIREMENT_ID,
            owner_actor_id="owner:local", confirmed=True, expected_snapshot=token)
    assert freeze_error.value.code == "sdd_approval_drift"
    binding = facade.execution_binding(SPEC_ID, REQUIREMENT_ID, actor_id="agent:control")
    assert binding["envelope_hash"] == original["envelope_hash"]
    assert binding["contract_hash"] == original["contract_hash"]


def test_repeated_reviews_and_separate_requirements_preserve_seals_after_source_edits(tmp_path):
    from apatch_studio.sdd_workflow import SddWorkflowFacade

    _write_prepared(tmp_path)
    source = tmp_path / "src" / "feature.py"
    source.parent.mkdir()
    source.write_text("before = True\n")
    facade = SddWorkflowFacade(tmp_path)
    initial = facade.contract_review(SPEC_ID, "R1", with_snapshot=True)
    first = facade.freeze_requirement(SPEC_ID, "R1", owner_actor_id="owner:local",
        confirmed=True, expected_snapshot=initial["approval_snapshot"])
    source.write_text("after = True\n")
    repeated = facade.contract_review(SPEC_ID, "R1", with_snapshot=True)
    assert repeated["status"] == "frozen"
    assert repeated["envelope_hash"] == first["envelope_hash"]
    again = facade.freeze_requirement(SPEC_ID, "R1", owner_actor_id="owner:local",
        confirmed=True, expected_snapshot=repeated["approval_snapshot"])
    assert again["envelope_hash"] == first["envelope_hash"]
    r2 = facade.contract_review(SPEC_ID, "R2", with_snapshot=True)
    second = facade.freeze_requirement(SPEC_ID, "R2", owner_actor_id="owner:local",
        confirmed=True, expected_snapshot=r2["approval_snapshot"])
    assert second["contract_hash"] == first["contract_hash"]
    assert second["envelope_hash"] != first["envelope_hash"]


def test_owner_freeze_persists_exact_contract_and_requirement_envelope(tmp_path: Path) -> None:
    from apatch_studio.sdd_workflow import SddWorkflowFacade

    _write_prepared(tmp_path)
    facade = SddWorkflowFacade(
        tmp_path,
        clock=lambda: "2026-09-01T14:30:00+00:00",
    )

    review = facade.contract_review(SPEC_ID, REQUIREMENT_ID)
    assert review["status"] == "ready_for_owner"
    assert review["objective"] == "Make the reviewed feature behavior true"
    assert review["scope"]["allowed_writes"] == ["src/feature.py"]
    assert review["scope"]["forbidden_paths"] == _prepared_package()[
        "task_envelopes"
    ][REQUIREMENT_ID]["forbidden_paths"]
    assert review["checks"][0]["perspectives"] == [
        "positive",
        "negative",
        "boundary",
        "regression",
    ]
    assert review["checks"][0]["observed_red"] is True
    assert review["checks"][0]["falsification_expected"] == "red"

    frozen = facade.freeze_requirement(
        SPEC_ID,
        REQUIREMENT_ID,
        owner_actor_id="owner:local",
        confirmed=True,
    )
    assert frozen["status"] == "frozen"
    assert frozen["owner_actor_id"] == "owner:local"
    assert frozen["frozen_at"] == "2026-09-01T14:30:00+00:00"

    manifest = json.loads(
        (tmp_path / ".apatch" / "sdd_verification_contract.json").read_text(
            encoding="utf-8"
        )
    )
    envelope = json.loads(
        (
            tmp_path
            / ".apatch"
            / "sdd"
            / "envelopes"
            / SPEC_ID
            / f"{REQUIREMENT_ID}.json"
        ).read_text(encoding="utf-8")
    )
    assert manifest["schema"] == "apatch.sdd.verification-contract.v1"
    assert manifest["status"] == "frozen"
    assert manifest["authority"] == {
        "actor_id": "owner:local",
        "role": "authority",
    }
    assert envelope["contract_hash"] == manifest["document_hash"]

    binding = facade.execution_binding(
        SPEC_ID,
        REQUIREMENT_ID,
        actor_id="agent:codex",
    )
    assert binding["contract_hash"] == manifest["document_hash"]
    assert binding["envelope_hash"] == envelope["document_hash"]
    assert binding["actor_id"] == "agent:codex"
    assert "role" not in binding


def test_every_requirement_binds_to_one_frozen_contract(tmp_path: Path) -> None:
    """One SPEC, one contract. Freezing a second requirement must not mint another.

    Each call stamped its own freeze time, so every requirement produced a
    different contract hash and the workspace ended up holding several documents
    that each claimed to be the frozen one, with envelopes bound to different
    ones. Nothing downstream could then execute more than one requirement.
    """

    from apatch_studio.sdd_workflow import SddWorkflowFacade

    _write_prepared(tmp_path)
    facade = SddWorkflowFacade(tmp_path)

    first = facade.freeze_requirement(
        SPEC_ID, REQUIREMENT_ID, owner_actor_id="owner:local", confirmed=True
    )
    second = facade.freeze_requirement(
        SPEC_ID, SECOND_REQUIREMENT_ID, owner_actor_id="owner:local", confirmed=True
    )

    assert second["contract_hash"] == first["contract_hash"]
    assert second["envelope_hash"] != first["envelope_hash"]

    frozen = list((tmp_path / ".apatch" / "sdd" / "frozen").glob("*.json"))
    assert len(frozen) == 1

    manifest = json.loads(
        (tmp_path / ".apatch" / "sdd_verification_contract.json").read_text(
            encoding="utf-8"
        )
    )
    for requirement in (REQUIREMENT_ID, SECOND_REQUIREMENT_ID):
        envelope = json.loads(
            (
                tmp_path / ".apatch" / "sdd" / "envelopes" / SPEC_ID / f"{requirement}.json"
            ).read_text(encoding="utf-8")
        )
        assert envelope["contract_hash"] == manifest["document_hash"]


class _Adapter:
    def overview(self, *, force: bool = False):
        return {"schema": "test.overview.v1", "changes": []}


class _Runs:
    def __init__(self) -> None:
        self.bindings: list[dict] = []

    def runners(self):
        return [{"id": "codex", "label": "Codex", "available": True}]

    def start(self, request, *, retry_of=None, execution_context=None, sdd_execution=None):
        self.bindings.append(sdd_execution)
        return {
            "schema": "apatch.studio.agent-run.v1",
            "run_id": "apr_" + "1" * 32,
            "runner": request.runner,
            "mode": request.mode,
            "objective": request.objective,
            "status": "queued",
            "phase": "queued",
            "message": "Waiting for a local runner slot",
            "created_at": "2026-09-01T14:31:00+00:00",
            "started_at": None,
            "ended_at": None,
            "outcome": None,
            "thread_id": None,
            "retry_of": retry_of,
            "execution_context": None,
            "execution_contract": None,
            "event_count": 0,
            "review": None,
            "timeline": [],
            "reviewer_note": None,
            "contribution": None,
            "scope": {
                "schema": "apatch.studio.scope-outcome.v1",
                "status": "pending",
                "audit_observed": False,
                "planned_file_count": 0,
                "logical_areas": [],
                "blocked_out_of_scope": 0,
                "reverted_out_of_scope": 0,
                "unresolved_out_of_scope": 0,
            },
            "work_ref": {
                "spec_id": request.spec_id,
                "requirement_id": request.requirement_id,
                "governed_session_id": None,
            },
            "available_actions": ["cancel"],
            "persisted": True,
            "can_cancel": True,
            "can_retry": False,
        }

    def list(self):
        return []

    def journal(self):
        return {"schema": "test.journal.v1"}

    def close(self):
        pass


def _enrol(root: Path, name: str = "studio-laptop") -> None:
    """Give the workspace somebody it can name as approving.

    Without this the freeze is refused on identity, which is the point of the
    approval path: the name is resolved here, not sent by whoever calls.
    """

    state = root / ".apatch"
    state.mkdir(parents=True, exist_ok=True)
    (state / "machine-identity.json").write_text(
        json.dumps(
            {
                "schema": "apatch.studio.machine-identity.v1",
                "machine_name": name,
                "key_path": str(state / "agent.key"),
                "certificate_path": str(state / "agent.crt"),
            }
        ),
        encoding="utf-8",
    )


def _client(tmp_path: Path):
    from apatch_studio.app import create_app
    from apatch_studio.sdd_workflow import SddWorkflowFacade

    _enrol(tmp_path)
    runs = _Runs()
    facade = SddWorkflowFacade(
        tmp_path,
        clock=lambda: "2026-09-01T14:30:00+00:00",
    )
    app = create_app(
        str(tmp_path),
        adapter=_Adapter(),
        run_manager=runs,
        sdd_facade=facade,
        frontend_root=tmp_path,
        identity_root=tmp_path / ".apatch",
    )
    client = TestClient(app, base_url="http://127.0.0.1:8765")
    headers = {
        "x-apatch-studio-session": app.state.studio_guard.token,
        "origin": "http://127.0.0.1:8765",
    }
    return client, headers, runs


def _run_payload() -> dict:
    return {
        "mode": "requirement",
        "runner": "codex",
        "objective": "Make the reviewed feature behavior true",
        "spec_id": SPEC_ID,
        "requirement_id": REQUIREMENT_ID,
    }


def test_requirement_run_is_blocked_until_visible_owner_freeze(tmp_path: Path) -> None:
    _write_prepared(tmp_path)
    client, headers, runs = _client(tmp_path)

    blocked = client.post("/api/v1/runs", headers=headers, json=_run_payload())
    assert blocked.status_code == 409
    assert blocked.json()["error_code"] == "sdd_contract_not_frozen"
    assert runs.bindings == []

    review = client.get(
        f"/api/v1/specs/{SPEC_ID}/requirements/{REQUIREMENT_ID}/execution-contract",
        headers=headers,
    )
    assert review.status_code == 200
    assert review.json()["status"] == "ready_for_owner"
    assert review.json()["owner_confirmation_required"] is True

    frozen = client.post(
        f"/api/v1/specs/{SPEC_ID}/requirements/{REQUIREMENT_ID}/execution-contract/freeze",
        headers=headers,
        json={"request_id": "apsreq_freeze_" + "1" * 32, "confirmed": True,
              "snapshot": review.json()["approval_snapshot"]},
    )
    assert frozen.status_code == 200
    assert frozen.json()["status"] == "frozen"
    # The approval names the machine this workspace enrolled. It used to name
    # a literal the browser sent, identically for everyone who ever approved.
    assert frozen.json()["owner_actor_id"] == "studio-laptop"

    started = client.post("/api/v1/runs", headers=headers, json=_run_payload())
    assert started.status_code == 202
    assert runs.bindings[0]["contract_hash"] == frozen.json()["contract_hash"]
    assert runs.bindings[0]["actor_id"] == "agent:codex"
    assert "role" not in runs.bindings[0]


def test_fixed_purpose_prompt_binds_exact_contract_without_authority_role(tmp_path: Path) -> None:
    from apatch.sdd_integrity import canonical_json
    from apatch_studio.agent_runs import build_governed_prompt
    from apatch_studio.operations import AgentRunRequest, SddExecutionContext
    from apatch_studio.sdd_workflow import SddWorkflowFacade

    _write_prepared(tmp_path)
    facade = SddWorkflowFacade(
        tmp_path,
        clock=lambda: "2026-09-01T14:30:00+00:00",
    )
    facade.freeze_requirement(
        SPEC_ID,
        REQUIREMENT_ID,
        owner_actor_id="owner:local",
        confirmed=True,
    )
    binding = SddExecutionContext.model_validate(
        facade.execution_binding(SPEC_ID, REQUIREMENT_ID, actor_id="agent:codex")
    )

    prompt = build_governed_prompt(
        AgentRunRequest.model_validate(_run_payload()),
        sdd_execution=binding,
    )
    assert "apatch_session_start" in prompt
    assert canonical_json(binding.contract) in prompt
    assert canonical_json(binding.task_envelope) in prompt
    assert "actor_id=agent:codex" in prompt
    assert "The MCP fixes the capability role to implementation" in prompt
    assert "never request verifier or authority capability" in prompt


def test_tampered_frozen_envelope_fails_closed_before_runner_dispatch(tmp_path: Path) -> None:
    from apatch_studio.sdd_workflow import SddWorkflowError, SddWorkflowFacade

    _write_prepared(tmp_path)
    facade = SddWorkflowFacade(
        tmp_path,
        clock=lambda: "2026-09-01T14:30:00+00:00",
    )
    facade.freeze_requirement(
        SPEC_ID,
        REQUIREMENT_ID,
        owner_actor_id="owner:local",
        confirmed=True,
    )
    envelope_path = (
        tmp_path
        / ".apatch"
        / "sdd"
        / "envelopes"
        / SPEC_ID
        / f"{REQUIREMENT_ID}.json"
    )
    envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
    envelope["budgets"]["files"] = 999
    envelope_path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(SddWorkflowError) as exc_info:
        facade.execution_binding(SPEC_ID, REQUIREMENT_ID, actor_id="agent:codex")
    assert exc_info.value.code == "sdd_contract_tampered"


def _freeze_body(snapshot):
    return {"request_id": "apsreq_snapshot_0000000000000001", "confirmed": True, "snapshot": snapshot}


def _assert_no_frozen_output(root):
    assert not (root / ".apatch/sdd_verification_contract.json").exists()
    assert not (root / f".apatch/sdd/envelopes/{SPEC_ID}/{REQUIREMENT_ID}.json").exists()


@pytest.mark.parametrize("supplied", ["missing", None, "not-a-digest"])
def test_oss_http_requires_a_reviewed_snapshot(tmp_path, supplied):
    _write_prepared(tmp_path)
    client, headers, _ = _client(tmp_path)
    endpoint = f"/api/v1/specs/{SPEC_ID}/requirements/{REQUIREMENT_ID}"
    body = _freeze_body(supplied)
    if supplied == "missing":
        body.pop("snapshot")
    with client:
        response = client.post(endpoint + "/execution-contract/freeze", headers=headers, json=body)
        assert response.status_code == 422
        assert client.get(endpoint + "/lock", headers=headers).json()["state"] == "unlocked"
    _assert_no_frozen_output(tmp_path)


@pytest.mark.parametrize("change", ["objective", "scope", "budget", "source", "new_source", "judge"])
def test_oss_http_rejects_changes_since_owner_review(tmp_path, change):
    prepared = _write_prepared(tmp_path)
    source = tmp_path / "src/feature.py"
    source.parent.mkdir()
    source.write_text("original = True\n", encoding="utf-8")
    client, headers, _ = _client(tmp_path)
    endpoint = f"/api/v1/specs/{SPEC_ID}/requirements/{REQUIREMENT_ID}"
    with client:
        review = client.get(endpoint + "/execution-contract", headers=headers).json()
        snapshot = review["approval_snapshot"]
        assert snapshot.startswith("sha256:") and len(snapshot) == 71
        package = json.loads(prepared.read_text(encoding="utf-8"))
        if change == "objective":
            package["objective"] = "A different obligation"
        elif change == "scope":
            package["task_envelopes"]["R1"]["allowed_writes"].append("src/another.py")
        elif change == "budget":
            package["task_envelopes"]["R1"]["budgets"]["files"] = 999
        elif change == "source":
            source.write_text("original = False\n", encoding="utf-8")
        elif change == "new_source":
            source.with_name("new.py").write_text("added = True\n", encoding="utf-8")
        else:
            (tmp_path / _JUDGE_PATH).write_text("def test_feature():\n    assert False\n", encoding="utf-8")
        prepared.write_text(json.dumps(package), encoding="utf-8")
        response = client.post(endpoint + "/execution-contract/freeze",
            headers=headers, json=_freeze_body(snapshot))
        assert response.status_code == 409
        assert response.json()["error_code"] == "sdd_approval_drift"
        assert client.get(endpoint + "/lock", headers=headers).json()["state"] == "unlocked"
        _assert_no_frozen_output(tmp_path)
        if change in {"objective", "budget"}:
            fresh = client.get(endpoint + "/execution-contract", headers=headers).json()
            assert fresh["approval_snapshot"] != snapshot
            accepted = client.post(endpoint + "/execution-contract/freeze",
                headers=headers, json=_freeze_body(fresh["approval_snapshot"]))
            assert accepted.status_code == 200


def test_review_never_pairs_old_content_with_a_new_preparation_snapshot(tmp_path, monkeypatch):
    from apatch_studio.sdd_workflow import SddWorkflowError, SddWorkflowFacade
    prepared = _write_prepared(tmp_path)
    facade = SddWorkflowFacade(tmp_path)
    original = facade._review_prepared
    def replace_during_projection(*args):
        result = original(*args)
        package = json.loads(prepared.read_text(encoding="utf-8"))
        package["objective"] = "Replaced during review"
        prepared.write_text(json.dumps(package), encoding="utf-8")
        return result
    monkeypatch.setattr(facade, "_review_prepared", replace_during_projection)
    with pytest.raises(SddWorkflowError, match="changed during review") as error:
        facade.contract_review(SPEC_ID, REQUIREMENT_ID, with_snapshot=True)
    assert error.value.code == "sdd_approval_drift"
    _assert_no_frozen_output(tmp_path)


@pytest.mark.parametrize("replace_read", [1, 2])
def test_freeze_binds_consumed_preparation_even_when_disk_returns_to_original(tmp_path, monkeypatch, replace_read):
    from apatch_studio.sdd_workflow import SddWorkflowError, SddWorkflowFacade
    _write_prepared(tmp_path)
    facade = SddWorkflowFacade(tmp_path)
    snapshot = facade.approval_snapshot(SPEC_ID, REQUIREMENT_ID)
    original = facade._prepared
    reads = 0
    def transient_preparation(spec, requirement):
        nonlocal reads
        reads += 1
        package, contract, envelope = original(spec, requirement)
        if reads == replace_read:
            package["task_envelopes"][requirement]["budgets"]["files"] = 999
        return package, contract, envelope
    monkeypatch.setattr(facade, "_prepared", transient_preparation)
    try:
        frozen = facade.freeze_requirement(SPEC_ID, REQUIREMENT_ID,
            owner_actor_id="owner:local", confirmed=True, expected_snapshot=snapshot)
    except SddWorkflowError as error:
        assert error.code == "sdd_approval_drift"
        _assert_no_frozen_output(tmp_path)
    else:
        assert frozen["budgets"]["files"] == 1
        envelope = json.loads((tmp_path / f".apatch/sdd/envelopes/{SPEC_ID}/R1.json").read_text(encoding="utf-8"))
        assert envelope["budgets"]["files"] == 1


def test_drift_during_core_freeze_is_rejected_before_persistence(tmp_path, monkeypatch):
    from apatch_studio.sdd_workflow import SddWorkflowError, SddWorkflowFacade
    prepared = _write_prepared(tmp_path)
    facade = SddWorkflowFacade(tmp_path)
    snapshot = facade.approval_snapshot(SPEC_ID, REQUIREMENT_ID)
    original = facade.backend.freeze_contract
    def mutate_during_freeze(payload):
        result = original(payload)
        package = json.loads(prepared.read_text(encoding="utf-8"))
        package["task_envelopes"]["R1"]["budgets"]["files"] = 999
        prepared.write_text(json.dumps(package), encoding="utf-8")
        return result
    monkeypatch.setattr(facade.backend, "freeze_contract", mutate_during_freeze)
    with pytest.raises(SddWorkflowError) as error:
        facade.freeze_requirement(SPEC_ID, REQUIREMENT_ID, owner_actor_id="owner:local",
            confirmed=True, expected_snapshot=snapshot)
    assert error.value.code == "sdd_approval_drift"
    _assert_no_frozen_output(tmp_path)


def test_preparation_replacement_at_storage_cannot_change_the_sealed_envelope(tmp_path, monkeypatch):
    import apatch_studio.sdd_workflow as workflow
    prepared = _write_prepared(tmp_path)
    facade = workflow.SddWorkflowFacade(tmp_path)
    snapshot = facade.approval_snapshot(SPEC_ID, REQUIREMENT_ID)
    original = workflow._atomic_json
    def replace_at_storage(path, document):
        package = json.loads(prepared.read_text(encoding="utf-8"))
        package["task_envelopes"]["R1"]["budgets"]["files"] = 999
        prepared.write_text(json.dumps(package), encoding="utf-8")
        return original(path, document)
    monkeypatch.setattr(workflow, "_atomic_json", replace_at_storage)
    frozen = facade.freeze_requirement(SPEC_ID, REQUIREMENT_ID, owner_actor_id="owner:local",
        confirmed=True, expected_snapshot=snapshot)
    assert frozen["budgets"]["files"] == 1
    envelope = json.loads((tmp_path / f".apatch/sdd/envelopes/{SPEC_ID}/R1.json").read_text(encoding="utf-8"))
    assert envelope["budgets"]["files"] == 1


def test_solo_browser_confirmation_carries_the_displayed_snapshot():
    root = Path(__file__).resolve().parents[2]
    view = (root / "frontend/src/ProjectPlanView.tsx").read_text(encoding="utf-8")
    api = (root / "frontend/src/api.ts").read_text(encoding="utf-8")
    assert "const snapshot = review?.approval_snapshot;" in view
    assert "if (!snapshot)" in view
    assert "{ snapshot }" in view
    assert "agreement: { snapshot: string }" in api
