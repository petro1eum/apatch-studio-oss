import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads(
    (ROOT / "frontend/src/navigation.contract.json").read_text(encoding="utf-8")
)


def _canonical(path: str) -> tuple[str, str | None]:
    parts = [part for part in path.strip("#/").split("/") if part]
    matches = sorted(
        CONTRACT["legacy_routes"],
        key=lambda item: len(item.split("/")),
        reverse=True,
    )
    for source in matches:
        prefix = source.split("/")
        if parts[: len(prefix)] == prefix:
            parts = CONTRACT["legacy_routes"][source].split("/") + parts[len(prefix) :]
            break
    target = next(
        (item for item in CONTRACT["targets"] if item["id"] == (parts[0] if parts else CONTRACT["default_route"])),
        next(item for item in CONTRACT["targets"] if item["id"] == "home"),
    )
    offset = 1
    if len(parts) > 1 and parts[1] in target["sections"]:
        offset = 2
    return target["id"], "/".join(parts[offset:]) or None


def test_oss_has_four_primary_destinations_and_adds_inbox_when_configured() -> None:
    assert CONTRACT["schema"] == "apatch.studio.navigation.v2"
    assert CONTRACT["default_route"] == "home"
    assert [item["id"] for item in CONTRACT["targets"] if item["availability"] == "all"] == [
        "home",
        "backlog",
        "library",
        "admin",
    ]
    assert [item["id"] for item in CONTRACT["targets"] if item["availability"] == "configured"] == ["inbox"]
    assert len(CONTRACT["targets"]) == 5


def test_every_old_capability_has_a_deterministic_outside_in_home() -> None:
    expected = {
        "work/runs": ("home", None),
        "work/runs/apr_123": ("home", "apr_123"),
        "review/apr_123": ("home", "apr_123"),
        "specs/SPEC-X": ("backlog", "SPEC-X"),
        "evidence/event-7": ("library", "event-7"),
        "assets/wa-2": ("library", "wa-2"),
        "policies": ("admin", None),
        "settings": ("admin", None),
    }
    assert {source: _canonical(source) for source in expected} == expected


def test_active_shell_uses_longest_prefix_redirect_and_preserves_identifiers() -> None:
    navigation = (ROOT / "frontend/src/outsideInNavigation.ts").read_text(encoding="utf-8")
    shell = (ROOT / "frontend/src/OutsideInApp.tsx").read_text(encoding="utf-8")
    main = (ROOT / "frontend/src/main.tsx").read_text(encoding="utf-8")

    assert 'right.split("/").length - left.split("/").length' in navigation
    assert "parts.slice(prefix.length)" in navigation
    assert "encodeURIComponent(route.resourceId)" in navigation
    assert "canonicalOutsideInHash" in shell
    assert "outsideInNavigationTargets.filter" in shell
    assert "<OutsideInApp />" in main
