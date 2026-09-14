from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RFP = ROOT / "docs/RFP-010-studio-interactive-project-change.md"
SPEC = ROOT / "docs/specs/SPEC-STUDIO-INTERACTIVE-CHANGE-1.md"
ACCEPTANCE_IDS = [f"CHANGE-{index}" for index in range(1, 10)]


def test_rfp_010_acceptance_maps_one_to_one_to_executable_requirements() -> None:
    rfp = RFP.read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")

    assert "**Executable contract:** docs/specs/SPEC-STUDIO-INTERACTIVE-CHANGE-1.md" in rfp
    assert "> **apatch artifact:** `spec:SPEC-STUDIO-INTERACTIVE-CHANGE-1`" in spec
    for index, acceptance_id in enumerate(ACCEPTANCE_IDS, start=1):
        assert f"| {acceptance_id} |" in rfp
        assert f"| {acceptance_id} | R{index} | covered |" in spec
        assert f"## R{index} " in spec
    assert "TODO" not in spec
