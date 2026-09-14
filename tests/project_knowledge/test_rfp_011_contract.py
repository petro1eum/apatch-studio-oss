from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def test_rfp_011_defines_the_human_knowledge_workspace() -> None:
    rfp = (
        ROOT / "docs/RFP-011-studio-project-knowledge-decisions.md"
    ).read_text(encoding="utf-8")

    acceptance = re.findall(r"\| (KNOW-\d+) \|", rfp)
    assert acceptance == [f"KNOW-{index}" for index in range(1, 11)]
    for capability in [
        "what project is open and what is it for",
        "Open plan",
        "View specification",
        "View proposal",
        "Decision basis",
        "requirement title and statement",
        "verification outcome",
        "canonical discovered IDs only",
    ]:
        assert capability in rfp
    assert "Studio persists no second document database" in rfp
    assert "It does not claim that APatch proof equals business acceptance" in rfp
