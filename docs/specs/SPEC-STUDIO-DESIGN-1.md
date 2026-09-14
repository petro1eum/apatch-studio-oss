# SPEC-STUDIO-DESIGN-1 — APatch Studio TrustChain design language (RFP-017)

> **apatch artifact:** `spec:SPEC-STUDIO-DESIGN-1`
> **Anchors:** RFP-017
> **Status:** Frozen for implementation · **Owner:** APatch Studio
> Tokens are ported from TrustChain Platform SPEC-UI-THEME-1 R2; the reference surface is the organization command center.

## R0 RFP traceability gate (meta)

| RFP id | SPEC Rk | Disposition |
|--------|---------|-------------|
| DS-1 | R1 | covered |
| DS-2 | R2 | covered |
| DS-3 | R3 | covered |
| DS-4 | R4 | covered |

(verify: python3 -m pytest tests/design/test_trustchain_theme.py -q -k traceability)

## R1 TrustChain token layer

`frontend/src/trustchain-theme.css` defines the TrustChain light and dark primitives, re-points every Studio semantic token to them (including the previously undefined success pair), keeps the system/light/dark control, paints the dot-grid canvas, and is imported after `outside-in.css`. `frontend/index.html` no longer locks the colour scheme to light and applies the stored theme before hydration. No external font, stylesheet or network resource is referenced.

(verify: python3 -m pytest tests/design/test_trustchain_theme.py -q -k tokens)

## R2 Command-center shell

`frontend/src/OutsideInApp.tsx` renders the navy sidebar with the gradient brand mark, edition label, section label, inset-accent active navigation, count chips, the existing theme control and a runtime status card, and a sticky top bar with workspace context, project state pill and refresh. The shell geometry floor (188px sidebar) is unchanged.

(verify: python3 -m pytest tests/design/test_trustchain_theme.py -q -k shell)

## R3 Home command center

`HomeView` in `frontend/src/OutsideInViews.tsx` renders the identity card, four cockpit cards (verified work, left to verify, uncommitted files, protection), the project brief card, the unchanged change composer, recent results and a module grid to Plans, Library and Admin. The cockpit and module grid collapse to one column at the mobile breakpoint and expose no raw runtime fields.

(verify: python3 -m pytest tests/design/test_trustchain_theme.py -q -k home)

## R4 Design floor and release gate

The combined stylesheet keeps every persistent text size at 11px or more, the design-floor, vocabulary, navigation and Home hierarchy tests stay green, the production frontend build succeeds, and `docs/release-qualification.json` pins this contract as a live-ledger requirement source.

(verify: python3 -m pytest tests/design tests/outside_in/test_design_floor.py tests/outside_in/test_vocabulary_contract.py tests/outside_in/test_navigation_contract.py tests/project_home -q && npm --prefix frontend run build)

## Non-goals

This SPEC does not change navigation targets, product vocabulary, any API or persisted schema, load web fonts or remote stylesheets, or restyle the legacy `App.tsx` surfaces that the active shell does not render.
