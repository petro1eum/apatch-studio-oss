import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
VOCABULARY = json.loads(
    (ROOT / "frontend/src/vocabulary.contract.json").read_text(encoding="utf-8")
)
NAVIGATION = json.loads(
    (ROOT / "frontend/src/navigation.contract.json").read_text(encoding="utf-8")
)


def _visible_text(source: str) -> str:
    candidates = re.findall(r">([^<>]+)<", source)
    text_nodes = [
        value.strip()
        for value in candidates
        if value.strip()
        and "=>" not in value
        and "{" not in value
        and "}" not in value
    ]
    placeholders = re.findall(r'placeholder="([^"]+)"', source)
    titles = re.findall(r'title="([^"]+)"', source)
    return "\n".join([*text_nodes, *placeholders, *titles]).lower()


def test_vocabulary_contract_maps_every_required_protocol_term() -> None:
    assert VOCABULARY["schema"] == "apatch.studio.product-vocabulary.v1"
    assert VOCABULARY["expert_surface"] == "Proof"
    mapping = {item["protocol"]: item["product"] for item in VOCABULARY["terms"]}
    assert mapping == {
        "attest": "verify",
        "attested": "Verified",
        "notarize": "record",
        "notarized": "Recorded",
        "ratify": "re-check policy gate",
        "inclusion proof": "independent log check",
        "rebind": "re-check",
        "stale": "Needs re-check",
        "governed session": "protected run",
        "execution intent": "signed task",
        "WorkAsset": "proven method",
        "artifact reference": "backlog item",
        "doctor": "runtime check",
        "hygiene": "storage health",
    }


def test_primary_navigation_and_visible_copy_are_free_of_protocol_jargon() -> None:
    navigation_copy = "\n".join(
        item["label"] + "\n" + item["primary_action"]
        for item in NAVIGATION["targets"]
    ).lower()
    primary_sources = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in [
            "frontend/src/OutsideInApp.tsx",
            "frontend/src/OutsideInViews.tsx",
            "frontend/src/OutsideInAdmin.tsx",
        ]
    )
    visible = navigation_copy + "\n" + _visible_text(primary_sources)
    for term in VOCABULARY["forbidden_primary_terms"]:
        assert re.search(r"\b" + re.escape(term) + r"\b", visible, re.IGNORECASE) is None, term


def test_exact_protocol_fidelity_is_confined_to_labelled_proof_surface() -> None:
    proof = (ROOT / "frontend/src/ProofDetails.tsx").read_text(encoding="utf-8")
    primary = (ROOT / "frontend/src/OutsideInViews.tsx").read_text(encoding="utf-8")

    assert "<details" in proof
    assert "<summary><ShieldCheck" in proof
    assert ">Proof</summary>" in proof
    assert "governed_session_id" in proof
    assert "<ProofDetails" in primary
