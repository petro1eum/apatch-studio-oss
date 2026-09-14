from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_rfp_traceability():
    rfp = (ROOT / "docs/RFP-003-studio-run-ledger-review.md").read_text(encoding="utf-8")
    spec = (ROOT / "docs/specs/SPEC-STUDIO-RUN-LEDGER-1.md").read_text(encoding="utf-8")
    acceptance = re.findall(r"\| (RL-\d+) \|", rfp)
    traced = re.findall(r"\| (RL-\d+) \| R\d+ \| covered \|", spec)
    expected = {f"RL-{index}" for index in range(1, 10)}
    assert len(acceptance) == len(set(acceptance)) == 9
    assert len(traced) == len(set(traced)) == 9
    assert set(acceptance) == set(traced) == expected


def test_privacy_and_authority_boundary_is_explicit():
    text = (ROOT / "docs/RFP-003-studio-run-ledger-review.md").read_text(encoding="utf-8").lower()
    for required in [
        "operating-system user state directory",
        "raw stdout/jsonl",
        "session tokens",
        "not proof of attribution",
        "never executed",
    ]:
        assert required in text
