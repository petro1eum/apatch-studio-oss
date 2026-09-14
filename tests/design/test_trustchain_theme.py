"""Frozen verification contract for SPEC-STUDIO-DESIGN-1 (RFP-017)."""

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_rfp_017_traceability_and_verification_contract_are_complete() -> None:
    rfp = _read("docs/RFP-017-studio-trustchain-design.md")
    spec = _read("docs/specs/SPEC-STUDIO-DESIGN-1.md")

    for acceptance_id in [f"DS-{index}" for index in range(1, 5)]:
        assert f"| {acceptance_id} |" in rfp
        assert f"| {acceptance_id} | R" in spec
    assert "clients.trust-chain.ai/org/command" in rfp
    assert "SPEC-UI-THEME-1" in rfp
    assert "(verify: TODO" not in spec
    verify_lines = [line for line in spec.splitlines() if line.startswith("(verify:")]
    assert len(verify_lines) == 5


def test_tokens_port_the_trustchain_palette_into_every_studio_semantic() -> None:
    theme = _read("frontend/src/trustchain-theme.css")
    main = _read("frontend/src/main.tsx")
    index = _read("frontend/index.html")
    theme_init = _read("frontend/public/theme-init.js")

    for token in [
        "--tc-brand-gradient: linear-gradient(135deg, #f97316 0%, #e11d48 100%)",
        "--tc-shell-sidebar-bg: #0f172a",
        "--tc-bg-primary: #0b1120",
        "--tc-bg-card: #1b2438",
        "--tc-bg-primary: #eef3f8",
        "--tc-accent: #e11d48",
        "--tc-accent: #ef4444",
        "--tc-trust: #2563eb",
        "--tc-trust: #60a5fa",
    ]:
        assert token in theme, token
    for semantic in [
        "--oi-bg",
        "--oi-surface",
        "--oi-surface-2",
        "--oi-border",
        "--oi-text",
        "--oi-muted",
        "--oi-strong",
        "--oi-accent",
        "--oi-accent-strong",
        "--oi-accent-soft",
        "--oi-info",
        "--oi-info-soft",
        "--oi-success",
        "--oi-success-soft",
        "--oi-warning",
        "--oi-warning-soft",
        "--oi-danger",
        "--oi-danger-soft",
        "--oi-shadow",
    ]:
        assert re.search(r"^\s*" + re.escape(semantic) + r":", theme, flags=re.MULTILINE), semantic
    assert ':root[data-theme="dark"]' in theme
    assert "@media (prefers-color-scheme: dark)" in theme
    assert ':root[data-theme="system"]' in theme
    assert "radial-gradient(circle, var(--tc-grid-dot) 1px, transparent 1px)" in theme
    assert ".tone-success { color: var(--oi-success); background: var(--oi-success-soft); }" in theme

    assert "@import" not in theme
    assert "url(" not in theme
    assert "http" not in theme
    assert "fonts.googleapis" not in index
    assert "<link" not in index

    assert main.index('import "./outside-in.css";') < main.index('import "./trustchain-theme.css";')
    assert 'content="light"' not in index
    assert '<script src="/theme-init.js"></script>' in index
    assert "<script>" not in index
    assert "apatch-studio-theme" in theme_init
    assert 'data-theme' in theme_init

    sizes = [int(value) for value in re.findall(r"font-size:\s*(\d+)px", theme)]
    assert sizes and min(sizes) >= 11


def test_shell_reproduces_the_command_center_chrome() -> None:
    shell = _read("frontend/src/OutsideInApp.tsx")
    theme = _read("frontend/src/trustchain-theme.css")
    floor = _read("frontend/src/outside-in.css")

    assert '<span className="oi-brand-mark"><ShieldCheck size={18} /></span>' in shell
    assert 'className="oi-brand-edition"' in shell
    assert '<p className="oi-nav-section">Workspace</p>' in shell
    assert 'className="oi-nav-count"' in shell
    assert '<div className="oi-workspace">' in shell
    assert '<header className="oi-topbar">' in shell
    assert 'className="oi-topbar-context"' in shell
    assert 'className={"oi-topbar-state tone-" + home.state.tone}' in shell
    assert 'title="Refresh workspace"' in shell
    assert 'className={"oi-runtime-card' in shell
    assert "Local runtime" in shell
    for title in ["System theme", "Light theme", "Dark theme"]:
        assert title in shell

    assert ".oi-sidebar { background: var(--tc-shell-sidebar-bg);" in theme
    assert "box-shadow: inset 3px 0 0 var(--tc-accent)" in theme
    assert "background: var(--tc-brand-gradient); box-shadow: 0 8px 24px rgba(225, 29, 72, 0.22)" in theme
    assert ".oi-topbar { position: sticky; top: 0;" in theme
    assert ".oi-runtime-card.is-attention" in theme
    assert "grid-template-columns: 188px minmax(0, 1fr)" in floor


def test_home_is_a_command_center_over_the_existing_composer() -> None:
    views = _read("frontend/src/OutsideInViews.tsx")
    theme = _read("frontend/src/trustchain-theme.css")
    home = views[views.index("export function HomeView(") : views.index("export function ChangeCard(")]

    assert '<header className="oi-project-header">' in home
    assert '<span className="oi-command-glyph"><LayoutDashboard size={20} /></span>' in home
    assert '<section className="oi-project-summary" aria-label="Project status">' in home
    assert home.count('className={"oi-cockpit-card ') == 4
    for label in ["Verified work", "Left to verify", "Uncommitted files", "Protection"]:
        assert f"<span>{label}</span>" in home, label
    assert '<section className="oi-project-brief"' in home
    assert "What do you want to change?" in home
    assert 'className="oi-composer-row"' in home
    assert '<section className="oi-modules" aria-label="Workspace areas">' in home
    assert home.count('className="oi-module"') == 3
    for module in [
        "<span><BookOpenCheck size={16} />Plans</span>",
        "<span><Library size={16} />Library</span>",
        "<span><Settings2 size={16} />Admin</span>",
    ]:
        assert module in home, module
    assert "onOpenLibrary" in home and "onOpenAdmin" in home
    for forbidden in ["hygiene_issues", "tool_count", "trust_anchor", "writer_protocol", "capability_contract"]:
        assert forbidden not in home, forbidden

    assert ".oi-project-summary { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));" in theme
    assert ".oi-modules { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));" in theme
    mobile = theme[theme.index("@media (max-width: 640px)") :]
    assert ".oi-project-summary, .oi-modules { grid-template-columns: 1fr; }" in mobile


def test_floor_and_release_gate_hold_with_the_theme_layer() -> None:
    combined = _read("frontend/src/outside-in.css") + _read("frontend/src/trustchain-theme.css")
    sizes = [int(value) for value in re.findall(r"font-size:\s*(\d+)px", combined)]
    assert sizes and min(sizes) >= 11
    assert "@media (prefers-reduced-motion: reduce)" in combined
    assert ":focus-visible" in combined

    spec = _read("docs/specs/SPEC-STUDIO-DESIGN-1.md")
    headings = re.findall(r"^## (R\d+) ", spec, flags=re.MULTILINE)
    assert headings == ["R0", "R1", "R2", "R3", "R4"]
