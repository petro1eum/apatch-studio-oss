"""Optional-reader control flow; no real authority/activation is created."""
import copy
import hashlib
from pathlib import Path

import pytest

from apatch.sdd_integrity import _seal
from apatch_studio.authoring_workflow import AuthoringWorkflow
from apatch_studio.state_io import write_json

ROOT = Path(__file__).resolve().parents[2]
GRANT = "sha256:" + "1" * 64
PARENT = "sha256:" + "2" * 64


def context(tmp_path, *, direct=True, grant=GRANT):
    root = tmp_path / "generated-lineage-input"
    root.mkdir()
    proposal = {"grant_hash": GRANT, "scope": {"contract_hash": PARENT}}
    parent = PARENT if direct else "sha256:" + "3" * 64
    fields = {"schema": "apatch.sdd.verification-contract.v1", "status": "frozen",
              "implementation_allowed": True, "authoring_grant_hash": grant, "supersedes_hash": parent}
    if not direct:
        fields["judge_amendment"] = {"supersedes_hash": parent}
    contract = _seal(fields)
    write_json(root / ".apatch/sdd/frozen" / (contract["document_hash"][7:] + ".json"), contract)
    return AuthoringWorkflow(root), proposal, contract


def test_empty_profile_does_not_require_optional_signed_reader(tmp_path):
    root = tmp_path / "empty"; root.mkdir()
    before = list(root.rglob("*"))
    assert AuthoringWorkflow(root)._activated_successor_of({"grant_hash": GRANT, "scope": {"contract_hash": PARENT}}) is False
    assert list(root.rglob("*")) == before


def test_direct_exact_parent_is_available_without_optional_reader(tmp_path):
    workflow, proposal, contract = context(tmp_path)
    assert workflow._activated_successor_of(proposal, contract=contract) is True


def test_unrelated_grant_never_becomes_activation(tmp_path):
    workflow, proposal, contract = context(tmp_path, grant="sha256:" + "9" * 64)
    assert workflow._activated_successor_of(proposal, contract=contract) is False


def test_bad_active_seal_still_fails_before_lineage_read(tmp_path):
    workflow, proposal, contract = context(tmp_path)
    contract = {**contract, "implementation_allowed": False}
    with pytest.raises(ValueError, match="Invalid active contract seal"):
        workflow._activated_successor_of(proposal, contract=contract, signed_rows=[])


def test_different_immutable_archive_is_rejected(tmp_path):
    workflow, proposal, contract = context(tmp_path)
    archived = copy.deepcopy(contract); archived["status"] = "not-frozen"
    write_json(workflow.root / ".apatch/sdd/frozen" / (contract["document_hash"][7:] + ".json"), archived)
    with pytest.raises(ValueError, match="immutable archive"):
        workflow._activated_successor_of(proposal, contract=contract, signed_rows=[])


def test_supplied_empty_verified_rows_do_not_require_reader_or_prove_activation(tmp_path):
    workflow, proposal, contract = context(tmp_path, direct=False)
    with pytest.raises(ValueError, match="unambiguous signed activation"):
        workflow._activated_successor_of(proposal, contract=contract, signed_rows=[])


def test_needed_but_unavailable_reader_gives_explicit_fail_closed_error(tmp_path):
    workflow, proposal, contract = context(tmp_path, direct=False)
    with pytest.raises(ValueError, match="(?i)signed lineage reader.*unavailable"):
        workflow._activated_successor_of(proposal, contract=contract)


@pytest.mark.parametrize("relative,expected", [
    ("tests/authoring/test_studio_authoring.py", "407bc309f2b6203c67c6a64156c8258ac43509364b68a8a28508e47e636f71ca"),
    ("tests/authoring/test_contract_intake_api.py", "7b743686c620fbb215956c73d31ee57f07c624cf75e5b825d90989e9dcc45a30"),
    ("tests/authoring/contract_intake_fixture.py", "1a29ab298d55313b4564d1c638f8650572fead79b1f32b1967d30673391f5ab4"),
])
def test_existing_authoring_and_intake_judges_remain_byte_identical(relative, expected):
    assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected
