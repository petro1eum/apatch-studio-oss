import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CONTRACT = json.loads(
    (ROOT / "frontend" / "src" / "navigation.contract.json").read_text(encoding="utf-8")
)


def test_navigation_has_exact_product_targets() -> None:
    targets = CONTRACT["targets"]
    assert [item["id"] for item in targets] == [
        "home",
        "backlog",
        "library",
        "admin",
        "inbox",
    ]
    assert len({item["id"] for item in targets}) == 5
    assert {item["id"] for item in targets if item["availability"] == "configured"} == {"inbox"}


def test_every_legacy_top_level_route_has_a_deterministic_target() -> None:
    assert CONTRACT["legacy_routes"] == {
        "work/runs": "home",
        "work/start": "home",
        "work": "home",
        "start": "home",
        "runs": "home",
        "overview": "home",
        "changes": "home",
        "review": "home",
        "specs": "backlog",
        "specifications": "backlog",
        "evidence": "library/proof",
        "assets": "library/methods",
        "policies": "admin/rules",
        "settings": "admin/runtime",
        "requests": "inbox",
    }


def test_frontend_canonicalizes_hash_routes_and_preserves_resource_ids() -> None:
    navigation = (ROOT / "frontend" / "src" / "outsideInNavigation.ts").read_text(encoding="utf-8")
    app = (ROOT / "frontend" / "src" / "OutsideInApp.tsx").read_text(encoding="utf-8")

    assert "legacyRoutes[key]" in navigation
    assert "parts.slice(prefix.length)" in navigation
    assert "encodeURIComponent(route.resourceId)" in navigation
    assert 'window.addEventListener("hashchange", sync)' in app
    assert 'window.history.replaceState(null, "", canonical)' in app
    assert "outsideInNavigationTargets" in app
    assert "canonicalOutsideInHash" in app


def canonical_navigation_imported(app: str) -> bool:
    return all(
        symbol in app
        for symbol in [
            "navigationTargets",
            "parseStudioHash",
            "studioRouteHash",
            "canonicalStudioHash",
        ]
    )
