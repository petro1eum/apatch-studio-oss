"""New-lineage drafting beside an existing frozen contract uses real Core."""
import importlib.util
import json
from pathlib import Path
import pytest

_spec = importlib.util.spec_from_file_location("initial_draft_fixture", Path(__file__).with_name("test_draft_workflow.py"))
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
setup = _module.setup
RUN, SPEC, REL, URL = _module.RUN, _module.SPEC, _module.REL, _module.URL


def initial(setup, root):
    from apatch.sdd_integrity import freeze_contract, canonical_hash
    client, headers, records, package, original = setup
    request = _module._fixture_module._prepared_package()["contract_request"]
    request["authority"] = {"actor_id": "studio-laptop", "role": "authority"}
    request["source_mutation_count"] = 0
    obligation = request["obligations"][0]
    obligation["falsification"]["target_path"] = "src/feature.py"
    judge = root / "tests/test_feature.py"
    judge.parent.mkdir(exist_ok=True)
    judge.write_text(_module._fixture_module._JUDGE_SOURCE)
    obligation["judge_assets"] = [{"path": "tests/test_feature.py", "sha256": _module._fixture_module._JUDGE_SHA256}]
    frozen = freeze_contract(request)
    profile = root / ".apatch/sdd_verification_contract.json"
    profile.write_text(json.dumps(frozen))
    (root / REL).unlink()
    package["files"] += [
        {"path": "docs/RFP-STUDIO-ABCDEF123456.md", "content": "# RFP-STUDIO-ABCDEF123456\n"},
        {"path": f".apatch/sdd/prepared/{SPEC}.json", "content": json.dumps({"spec_id": SPEC, "source_mutation_count": 0})}
    ]
    return client, headers, package, profile.read_bytes()


def test_initial_draft_uses_existing_owner_boundary_without_replacing_contract(setup, tmp_path):
    client, headers, package, before = initial(setup, tmp_path)
    review = _module.proposal(client, headers, package)
    assert review["review"]["initial"] is True
    assert not (tmp_path / REL).exists()
    response = client.post(URL + "/approve", headers=headers, json=_module.approval(review["snapshot"]))
    assert response.status_code == 200, response.text
    assert response.json()["functional_acceptance"] is False
    assert (tmp_path / ".apatch/sdd_verification_contract.json").read_bytes() == before
    assert (tmp_path / REL).is_file()
    assert (tmp_path / "tests/test_feature.py").read_text() == _module._fixture_module._JUDGE_SOURCE
    assert client.get(URL, headers=headers).json()["status"] == "completed"


def test_initial_draft_does_not_accept_client_selected_owner(setup, tmp_path):
    client, headers, package, before = initial(setup, tmp_path)
    review = _module.proposal(client, headers, package)
    payload = {**_module.approval(review["snapshot"]), "owner": {"id": "forged"}}
    assert client.post(URL + "/approve", headers=headers, json=payload).status_code == 422
    assert not (tmp_path / REL).exists()
    assert (tmp_path / ".apatch/sdd_verification_contract.json").read_bytes() == before


def test_initial_draft_prompt_uses_proposal_instead_of_bootstrap(tmp_path):
    from apatch_studio.agent_runs import build_planning_context, build_governed_prompt
    from apatch_studio.operations import AgentRunRequest
    profile = tmp_path / ".apatch/sdd_verification_contract.json"
    profile.parent.mkdir()
    profile.write_text("{}")
    capsule = build_planning_context(tmp_path, RUN)
    assert "Existing frozen contract" in capsule
    prompt = build_governed_prompt(AgentRunRequest.model_validate({
        "mode": "new_change", "runner": "codex", "objective": "Prepare a resource contract",
        "acceptance_criteria": ["Owner reviews the complete contract"]
    }), studio_run_id=RUN, planning_context=capsule)
    assert "the following write steps do not apply" in prompt
    assert "do not open a legacy bootstrap session" in prompt
