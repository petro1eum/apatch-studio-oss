"""Studio must show an exact Core scope and resolve the real approver."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from apatch_studio import authoring_workflow as workflow

ROOT = Path(__file__).resolve().parents[2]
fixture_spec = importlib.util.spec_from_file_location("authoring_owner_fixtures", ROOT / "tests/sdd/test_sdd_owner_execution_flow.py")
fixtures = importlib.util.module_from_spec(fixture_spec)
fixture_spec.loader.exec_module(fixtures)
URL = "/api/v1/specs/SPEC-DEMO-1/requirements/R1/authoring"


def seal(value):
    return {**value, "document_hash": "sha256:" + hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()}


@pytest.fixture
def boundary(monkeypatch):
    calls = []
    def prepare(root, **request):
        calls.append(("prepare", request))
        if "bad" in request["files"]:
            raise ValueError("Rejected exact scope")
        return seal({**request, "functional_acceptance": False, "contract_hash": "sha256:" + "a" * 64})
    def approve(root, scope, **decision):
        calls.append(("approve", decision))
        assert decision["expected_snapshot"] == scope["document_hash"]
        return seal({"scope": scope, "approved_by": decision["authority_id"], "functional_acceptance": False})
    monkeypatch.setattr(workflow, "authoring_core", lambda: SimpleNamespace(prepare_scope=prepare, approve_scope=approve))
    return calls


def proposal(client, headers, files=None):
    return client.post(URL, headers=headers, json={"request_id": "apsreq_authoring_proposal", "actor_id": "implementation-agent", "files": files or ["tests/test_new.py"]})


def approval(client, headers, snapshot, **extra):
    return client.post(URL + "/approve", headers=headers, json={"request_id": "apsreq_authoring_approval", "confirmed": True, "snapshot": snapshot, **extra})


def test_exact_scope_requires_distinct_owner_action(tmp_path, boundary):
    client, headers, _ = fixtures._client(tmp_path)
    with client:
        response = proposal(client, headers)
        assert response.status_code == 200, response.text
        scope = response.json()
        assert scope["status"] == "awaiting_approval"
        assert not list(tmp_path.glob(".apatch/sdd/authoring/*.json"))
        assert client.get(URL, headers=headers).json() == scope
        accepted = approval(client, headers, scope["snapshot"])
        assert accepted.status_code == 200, accepted.text
        assert boundary[-1][1]["authority_id"] == "studio-laptop"
        grant = json.loads(next(tmp_path.glob(".apatch/sdd/authoring/*.json")).read_text())
        assert grant["scope"] == scope["scope"]
        assert grant["functional_acceptance"] is False
        assert approval(client, headers, scope["snapshot"]).status_code == 409
        assert proposal(client, headers).status_code == 409


def test_old_snapshot_cannot_approve_revised_proposal(tmp_path, boundary):
    client, headers, _ = fixtures._client(tmp_path)
    with client:
        old = proposal(client, headers).json()
        proposal(client, headers, ["tests/test_second.py"])
        assert approval(client, headers, old["snapshot"]).status_code == 409
        assert not any(call[0] == "approve" for call in boundary)


@pytest.mark.parametrize("extra", [{"authority_id": "forged-owner"}, {"scope": {}}, {"role": "owner"}])
def test_approval_cannot_select_authority_or_scope(tmp_path, boundary, extra):
    client, headers, _ = fixtures._client(tmp_path)
    with client:
        scope = proposal(client, headers).json()
        assert approval(client, headers, scope["snapshot"], **extra).status_code == 422
        assert not any(call[0] == "approve" for call in boundary)


def test_core_rejection_does_not_store_proposal(tmp_path, boundary):
    client, headers, _ = fixtures._client(tmp_path)
    with client:
        assert proposal(client, headers, ["bad"]).status_code == 409
        assert client.get(URL, headers=headers).json()["status"] == "not_prepared"


def test_old_core_is_explicitly_unavailable(tmp_path, monkeypatch):
    def unavailable():
        raise workflow.SddWorkflowError("Installed Core cannot authorize preparation", code="sdd_authoring_unavailable", status_code=503)
    monkeypatch.setattr(workflow, "authoring_core", unavailable)
    client, headers, _ = fixtures._client(tmp_path)
    with client:
        result = proposal(client, headers)
        assert result.status_code == 503
        assert result.json()["error_code"] == "sdd_authoring_unavailable"
        assert not list(tmp_path.glob(".apatch/sdd/authoring/*.json"))


def test_no_session_token_cannot_propose_or_approve(tmp_path, boundary):
    client, headers, _ = fixtures._client(tmp_path)
    with client:
        assert proposal(client, {}).status_code == 401
        assert approval(client, {}, "sha256:" + "a" * 64).status_code == 401
        assert boundary == []


def test_proposal_cannot_be_copied_between_requirements(tmp_path, boundary):
    client, headers, _ = fixtures._client(tmp_path)
    with client:
        scope = proposal(client, headers).json()
        folder = tmp_path / ".apatch/sdd/authoring-proposals/SPEC-DEMO-1"
        (folder / "R2.json").write_text((folder / "R1.json").read_text())
        result = client.post(URL.replace("/R1/", "/R2/") + "/approve", headers=headers, json={"request_id": "apsreq_cross_requirement", "confirmed": True, "snapshot": scope["snapshot"]})
        assert result.status_code == 409
        assert not any(call[0] == "approve" for call in boundary)


def test_proposal_store_symlink_is_rejected(tmp_path, boundary):
    outside = tmp_path / "outside"
    outside.mkdir()
    client, headers, _ = fixtures._client(tmp_path)
    state = tmp_path / ".apatch/sdd"
    state.mkdir(parents=True, exist_ok=True)
    (state / "authoring-proposals").symlink_to(outside, target_is_directory=True)
    with client:
        assert proposal(client, headers).status_code == 409
        assert not list(outside.iterdir())


def test_browser_requires_review_and_displays_full_scope():
    source = (ROOT / "frontend/src/AuthoringScopeReview.tsx").read_text()
    for field in ("scope.files", "scope.effects", "scope.max_bytes", "scope.commands", "scope.judge_assets", "scope.contract_hash", "scope.release_hash"):
        assert field in source
    assert 'review?.status === "awaiting_approval"' in source
    assert "This approval does not accept a feature or authorize implementation" in source
    api = (ROOT / "frontend/src/api.ts").read_text().split("export const approveAuthoringScope", 1)[1]
    assert "confirmed: true, snapshot" in api
    assert "authority_id" not in api


def test_revision_keeps_approved_history_and_reviews_before_hashes(tmp_path, boundary, monkeypatch):
    original = workflow.authoring_core()
    completed = False
    def prepare(root, *, spec_id, requirement_id, actor_id, files, previous_grant_hash=None):
        if not previous_grant_hash:
            return original.prepare_scope(root, spec_id=spec_id, requirement_id=requirement_id, actor_id=actor_id, files=files)
        if not completed:
            raise ValueError("Previous preparation is not complete")
        return seal({"spec_id": spec_id, "requirement_id": requirement_id,
                     "actor_id": actor_id, "files": files,
                     "previous_grant_hash": previous_grant_hash,
                     "before_hashes": {path: "sha256:" + "e" * 64 for path in files},
                     "effects": ["replace"], "functional_acceptance": False})
    monkeypatch.setattr(workflow, "authoring_core", lambda: SimpleNamespace(prepare_scope=prepare, approve_scope=original.approve_scope))
    client, headers, _ = fixtures._client(tmp_path)
    with client:
        first = proposal(client, headers).json()
        accepted = approval(client, headers, first["snapshot"]).json()
        request = {"request_id": "apsreq_revision_proposal", "actor_id": "implementation-agent", "files": ["tests/test_new.py"], "previous_grant_hash": accepted["grant_hash"]}
        assert client.post(URL, headers=headers, json=request).status_code == 409
        assert client.get(URL, headers=headers).json() == accepted
        completed = True
        revised = client.post(URL, headers=headers, json=request)
        assert revised.status_code == 200, revised.text
        assert revised.json()["scope"]["before_hashes"]["tests/test_new.py"] == "sha256:" + "e" * 64
        assert approval(client, headers, first["snapshot"]).status_code == 409
        history = list(tmp_path.glob(".apatch/sdd/authoring-proposals/SPEC-DEMO-1/R1/history/*-approved.json"))
        assert len(history) == 1
        assert json.loads(history[0].read_text()) == accepted
        assert approval(client, headers, revised.json()["snapshot"]).status_code == 200
        assert json.loads(history[0].read_text()) == accepted


def test_owner_refrozen_canonical_base_allows_new_create_only_wave(tmp_path, boundary):
    client, headers, _ = fixtures._client(tmp_path)
    with client:
        first = proposal(client, headers).json()
        accepted = approval(client, headers, first["snapshot"]).json()
        from apatch.sdd_integrity import canonical_hash

        pins = {
            "baseline_hash": "sha256:" + "1" * 64,
            "brief_hash": "sha256:" + "2" * 64,
            "rfp_hash": "sha256:" + "2" * 64,
            "spec_hash": "sha256:" + "3" * 64,
        }
        contract = {
            "schema": "apatch.sdd.verification-contract.v1",
            "status": "frozen",
            "implementation_allowed": True,
            "authority": {"actor_id": "studio-laptop", "role": "authority"},
            "candidate_path": None,
            **pins,
        }
        contract["document_hash"] = canonical_hash(contract)
        active = tmp_path / ".apatch/sdd_verification_contract.json"
        active.write_text(json.dumps(contract))
        archive = tmp_path / ".apatch/sdd/frozen" / (contract["document_hash"][7:] + ".json")
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_text(json.dumps(contract))
        package = {
            "schema": "apatch.studio.sdd-preparation.v1",
            "spec_id": "SPEC-DEMO-1",
            "contract_request": dict(pins),
            "task_envelopes": {},
        }
        prepared = tmp_path / ".apatch/sdd/prepared/SPEC-DEMO-1.json"
        prepared.parent.mkdir(parents=True, exist_ok=True)
        prepared.write_text(json.dumps(package))

        next_wave = proposal(client, headers, ["tests/test_after_refreeze.py"])
        assert next_wave.status_code == 200, next_wave.text
        assert next_wave.json()["scope"]["files"] == ["tests/test_after_refreeze.py"]
        history = list(tmp_path.glob(
            ".apatch/sdd/authoring-proposals/SPEC-DEMO-1/R1/history/*-approved.json"
        ))
        assert len(history) == 1
        assert json.loads(history[0].read_text()) == accepted


@pytest.mark.parametrize("corruption", ["candidate", "grant", "archive", "owner", "package"])
def test_owner_refreeze_recovery_fails_closed_on_drift(tmp_path, boundary, corruption):
    client, headers, _ = fixtures._client(tmp_path)
    with client:
        first = proposal(client, headers).json()
        accepted = approval(client, headers, first["snapshot"]).json()
        from apatch.sdd_integrity import canonical_hash

        pins = {
            "baseline_hash": "sha256:" + "1" * 64,
            "brief_hash": "sha256:" + "2" * 64,
            "rfp_hash": "sha256:" + "2" * 64,
            "spec_hash": "sha256:" + "3" * 64,
        }
        contract = {
            "schema": "apatch.sdd.verification-contract.v1",
            "status": "frozen",
            "implementation_allowed": True,
            "authority": {
                "actor_id": "another-owner" if corruption == "owner" else "studio-laptop",
                "role": "authority",
            },
            "candidate_path": ".apatch/sdd/prepared/other.json" if corruption == "candidate" else None,
            **({"authoring_grant_hash": accepted["grant_hash"]} if corruption == "grant" else {}),
            **pins,
        }
        contract["document_hash"] = canonical_hash(contract)
        (tmp_path / ".apatch/sdd_verification_contract.json").write_text(json.dumps(contract))
        archive = tmp_path / ".apatch/sdd/frozen" / (contract["document_hash"][7:] + ".json")
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_text(json.dumps({} if corruption == "archive" else contract))
        package = {
            "schema": "apatch.studio.sdd-preparation.v1",
            "spec_id": "SPEC-DEMO-1",
            "contract_request": {**pins, **(
                {"spec_hash": "sha256:" + "4" * 64} if corruption == "package" else {}
            )},
            "task_envelopes": {},
        }
        prepared = tmp_path / ".apatch/sdd/prepared/SPEC-DEMO-1.json"
        prepared.parent.mkdir(parents=True, exist_ok=True)
        prepared.write_text(json.dumps(package))

        assert proposal(client, headers, ["tests/test_after_refreeze.py"]).status_code == 409
        assert client.get(URL, headers=headers).json() == accepted


def test_completed_unactivated_preparation_allows_new_create_wave(tmp_path, boundary, monkeypatch):
    client, headers, _ = fixtures._client(tmp_path)
    with client:
        first = proposal(client, headers).json()
        accepted = approval(client, headers, first["snapshot"]).json()
        import apatch.sdd_integrity as integrity
        monkeypatch.setattr(integrity, "load_profile_contract", lambda root: {
            "document_hash": "sha256:" + "a" * 64,
            "authority": {"actor_id": "studio-laptop", "role": "authority"},
        })
        prepared = tmp_path / "tests/test_new.py"
        prepared.parent.mkdir(parents=True, exist_ok=True)
        prepared.write_text("prepared\\n")
        digest = "sha256:" + hashlib.sha256(prepared.read_bytes()).hexdigest()
        import apatch.sdd_authoring as core_authoring
        monkeypatch.setattr(core_authoring, "completed_preparation", lambda root, grant_hash: {
            "grant": {"approved_by": "studio-laptop", "scope": {
                **first["scope"], "effects": ["create"], "previous_grant_hash": None,
            }},
            "files": {"tests/test_new.py": digest},
        })
        next_wave = proposal(client, headers, ["tests/test_after_complete.py"])
        assert next_wave.status_code == 200, next_wave.text
        assert next_wave.json()["scope"]["files"] == ["tests/test_after_complete.py"]
        history = list(tmp_path.glob(
            ".apatch/sdd/authoring-proposals/SPEC-DEMO-1/R1/history/*-approved.json"
        ))
        assert len(history) == 1
        assert json.loads(history[0].read_text()) == accepted


@pytest.mark.parametrize("corruption", ["owner", "contract", "files", "digest"])
def test_completed_unactivated_preparation_fails_closed_on_drift(
    tmp_path, boundary, monkeypatch, corruption
):
    client, headers, _ = fixtures._client(tmp_path)
    with client:
        first = proposal(client, headers).json()
        accepted = approval(client, headers, first["snapshot"]).json()
        import apatch.sdd_integrity as integrity
        monkeypatch.setattr(integrity, "load_profile_contract", lambda root: {
            "document_hash": "sha256:" + "a" * 64,
            "authority": {"actor_id": "studio-laptop", "role": "authority"},
        })
        prepared = tmp_path / "tests/test_new.py"
        prepared.parent.mkdir(parents=True, exist_ok=True)
        prepared.write_text("prepared\\n")
        digest = "sha256:" + hashlib.sha256(prepared.read_bytes()).hexdigest()
        import apatch.sdd_authoring as core_authoring
        scope = {**first["scope"], "effects": ["create"], "previous_grant_hash": None}
        if corruption == "contract":
            scope["contract_hash"] = "sha256:" + "f" * 64
        files = {"tests/test_new.py": digest}
        if corruption == "files":
            files = {"tests/another.py": digest}
        if corruption == "digest":
            files["tests/test_new.py"] = "sha256:" + "f" * 64
        monkeypatch.setattr(core_authoring, "completed_preparation", lambda root, grant_hash: {
            "grant": {
                "approved_by": "another-owner" if corruption == "owner" else "studio-laptop",
                "scope": scope,
            },
            "files": files,
        })
        assert proposal(client, headers, ["tests/test_after_complete.py"]).status_code == 409
        assert client.get(URL, headers=headers).json() == accepted


@pytest.mark.parametrize("corruption", ["unrelated_grant", "wrong_parent", "bad_seal", "archive_drift"])
def test_next_wave_requires_exact_activated_preparation(tmp_path, boundary, corruption):
    client, headers, _ = fixtures._client(tmp_path)
    with client:
        first = proposal(client, headers).json()
        accepted = approval(client, headers, first["snapshot"]).json()
        from apatch.sdd_integrity import canonical_hash
        contract = {"schema": "apatch.sdd.verification-contract.v1", "status": "frozen", "implementation_allowed": True,
                    "authoring_grant_hash": accepted["grant_hash"], "supersedes_hash": first["scope"]["contract_hash"]}
        if corruption == "unrelated_grant":
            contract["authoring_grant_hash"] = "sha256:" + "d" * 64
        if corruption == "wrong_parent":
            contract["supersedes_hash"] = "sha256:" + "e" * 64
        contract["document_hash"] = canonical_hash(contract)
        if corruption == "bad_seal":
            contract["status"] = "changed"
        active = tmp_path / ".apatch/sdd_verification_contract.json"
        active.write_text(json.dumps(contract))
        archive = tmp_path / ".apatch/sdd/frozen" / (contract["document_hash"][7:] + ".json")
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.write_text(json.dumps({} if corruption == "archive_drift" else contract))
        assert proposal(client, headers, ["tests/test_next.py"]).status_code == 409
        assert client.get(URL, headers=headers).json() == accepted
