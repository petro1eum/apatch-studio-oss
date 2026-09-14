import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CSS = (ROOT / "frontend/src/outside-in.css").read_text(encoding="utf-8")
SHELL = (ROOT / "frontend/src/OutsideInApp.tsx").read_text(encoding="utf-8")


def test_system_light_and_dark_themes_are_real_controls() -> None:
    assert ':root[data-theme="dark"]' in CSS
    assert '@media (prefers-color-scheme: dark)' in CSS
    assert ':root[data-theme="system"]' in CSS
    assert 'type Theme = "system" | "light" | "dark"' in SHELL
    for title in ["System theme", "Light theme", "Dark theme"]:
        assert title in SHELL


def test_active_surface_has_no_persistent_text_below_eleven_pixels() -> None:
    sizes = [int(value) for value in re.findall(r"font-size:\s*(\d+)px", CSS)]
    assert sizes
    assert min(sizes) >= 11


def test_destructive_actions_use_an_in_product_dialog() -> None:
    active_sources = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in [
            "frontend/src/OutsideInApp.tsx",
            "frontend/src/OutsideInViews.tsx",
            "frontend/src/OutsideInAdmin.tsx",
        ]
    )
    assert "window.confirm" not in active_sources
    assert 'role="alertdialog"' in SHELL
    assert 'aria-modal="true"' in SHELL
    assert "requestConfirm" in active_sources


def test_focus_motion_icons_and_stable_geometry_meet_the_floor() -> None:
    assert ":focus-visible" in CSS
    assert "@media (prefers-reduced-motion: reduce)" in CSS
    assert "grid-template-columns: 188px minmax(0, 1fr)" in CSS
    assert "min-height: 40px" in CSS
    assert "lucide-react" in SHELL
    for selector, radius in [
        (".oi-change-card", 7),
        (".oi-method-card", 6),
        (".oi-panel", 6),
        (".oi-dialog", 7),
    ]:
        rule = re.search(re.escape(selector) + r"\s*\{([^}]+)\}", CSS)
        assert rule is not None
        assert f"border-radius: {radius}px" in rule.group(1)
        assert radius <= 8
