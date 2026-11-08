"""Real Core seals; private setup references never weaken public projections."""
import copy

import pytest
from apatch import sdd_integrity as S
from apatch_studio.projection import (
    UnsafeProjectionError, assert_projection_safe, private_sdd_projection,
)
from test_exact_scheme_revision import world, seal


def bound(world):
    contract = copy.deepcopy(world.native)
    setup = {"path": "acceptance/verifier.json", "sha256": "sha256:" + "a" * 64}
    contract["obligations"][0]["judge_assets"].append(setup)
    contract["obligations"][0]["asset_hashes"].append(setup["sha256"])
    contract = seal(contract)
    envelope = seal(dict(world.envelope, contract_hash=contract["document_hash"],
                         verifier_environment=setup))
    return {"contract": contract, "task_envelope": envelope, "actor_id": "performer"}


def test_private_reference_is_hashed_without_changing_sealed_execution_documents(world):
    value = bound(world)
    original = copy.deepcopy(value)
    view = private_sdd_projection(value)
    assert view["task_envelope"]["verifier_setup_hash"] == S.canonical_hash(
        value["task_envelope"]["verifier_environment"])
    assert "verifier_environment" not in view["task_envelope"]
    assert value == original
    assert_projection_safe(view)
    with pytest.raises(UnsafeProjectionError):
        assert_projection_safe(value)
    with pytest.raises(UnsafeProjectionError):
        assert_projection_safe({"verifier_environment": value["task_envelope"]["verifier_environment"]})


@pytest.mark.parametrize("change", [
    "unsealed", "draft", "unfrozen_asset", "unselected_check", "extra_field",
    "absolute", "traversal", "backslash", "noncanonical", "bad_pin",
])
def test_invalid_or_unadmitted_reference_is_rejected_even_in_private_projection(world, change):
    value = bound(world)
    setup = value["task_envelope"]["verifier_environment"]
    if change == "unsealed":
        setup["sha256"] = "sha256:" + "b" * 64
    elif change == "draft":
        value["contract"]["status"] = "draft"
    elif change == "unfrozen_asset":
        value["contract"]["obligations"][0]["judge_assets"].pop()
    elif change == "unselected_check":
        value["task_envelope"]["checks"] = ["I"]
    elif change == "extra_field":
        setup["secret"] = "must-never-enter-a-projection"
    elif change == "bad_pin":
        setup["sha256"] = "not-a-hash"
    else:
        setup["path"] = {"absolute": "/acceptance/verifier.json", "traversal": "../verifier.json",
                         "backslash": "acceptance\\verifier.json",
                         "noncanonical": "acceptance/./verifier.json"}[change]
    if change != "unsealed":
        value["contract"] = seal(value["contract"])
        value["task_envelope"] = seal(dict(value["task_envelope"],
                                          contract_hash=value["contract"]["document_hash"]))
    with pytest.raises(UnsafeProjectionError):
        private_sdd_projection(value)
