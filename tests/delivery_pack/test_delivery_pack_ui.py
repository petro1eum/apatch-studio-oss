from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_change_detail_exposes_complete_delivery_workflow() -> None:
    source = (ROOT / "frontend/src/ChangeDetailView.tsx").read_text(encoding="utf-8")
    api = (ROOT / "frontend/src/api.ts").read_text(encoding="utf-8")
    types = (ROOT / "frontend/src/types.ts").read_text(encoding="utf-8")

    for component in (
        "DeliveryPackSection",
        "TestProtocolPanel",
        "AcceptanceActPanel",
        "TimeDecisionPanel",
    ):
        assert component in source
    for label in (
        "Tests",
        "Result acceptance",
        "Time report",
        "Delivery record",
        "Accept result",
        "Request changes",
        "Accept time",
        "Download record",
    ):
        assert label in source
    for action in (
        "loadDeliveryPack",
        "recordAcceptanceAct",
        "recordTimeDecision",
        "downloadDeliveryPack",
    ):
        assert action in api or action in source
    assert "interface DeliveryPack" in types


def test_protocol_jargon_is_progressively_disclosed() -> None:
    source = (ROOT / "frontend/src/ChangeDetailView.tsx").read_text(encoding="utf-8")

    assert "Technical delivery audit" in source
    assert "<details" in source
    assert "test protocol" not in source.split("Technical delivery audit")[0].lower()


def test_legacy_effort_projection_fails_closed_without_blank_screen() -> None:
    source = (ROOT / "frontend/src/ChangeDetailView.tsx").read_text(encoding="utf-8")

    assert "effort.verification ??" in source
    assert 'status: "not_recorded"' in source
    assert "verification.ok && verification.status === \"verified\"" in source
    assert "disabled={!effortAvailable}" in source
