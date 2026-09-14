from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RFP = ROOT / "docs/RFP-009-studio-comprehensible-project-home.md"
SPEC = ROOT / "docs/specs/SPEC-STUDIO-PROJECT-HOME-1.md"
ACCEPTANCE_IDS = [f"HOME-{index}" for index in range(1, 9)]


def test_rfp_009_acceptance_maps_one_to_one_to_executable_requirements() -> None:
    rfp = RFP.read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")

    assert "**Status:** Implemented and release-qualified" in rfp
    assert "**Executable contract:** docs/specs/SPEC-STUDIO-PROJECT-HOME-1.md" in rfp
    assert "> **apatch artifact:** `spec:SPEC-STUDIO-PROJECT-HOME-1`" in spec
    for index, acceptance_id in enumerate(ACCEPTANCE_IDS, start=1):
        assert f"| {acceptance_id} |" in rfp
        assert f"| {acceptance_id} | R{index} | covered |" in spec
        assert f"## R{index} " in spec
    assert "TODO" not in spec
