from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_rfp_014_traceability_and_verification_contract_are_complete():
    rfp = (ROOT / "docs/RFP-014-studio-first-user-operability.md").read_text(encoding="utf-8")
    spec = (ROOT / "docs/specs/SPEC-STUDIO-FIRST-USER-1.md").read_text(encoding="utf-8")

    acceptance_ids = {f"FJ-{index}" for index in range(1, 9)}
    for acceptance_id in acceptance_ids:
        assert f"| {acceptance_id} |" in rfp
        assert f"| {acceptance_id} | R" in spec
    assert "REC-ea73c3c7a55c" in rfp
    assert "(verify: TODO" not in spec
    verify_lines = [line for line in spec.splitlines() if line.startswith("(verify:")]
    assert len(verify_lines) == 9
