# RFP-017 -- APatch Studio TrustChain Design Language

> **Status:** Approved for implementation
> **Owner:** APatch Studio
> **Date:** 2026-09-03
> **Depends on:** RFP-007, RFP-009, RFP-016
> **Design reference:** TrustChain Platform organization command center (`clients.trust-chain.ai/org/command`)
> **Executable contract:** docs/specs/SPEC-STUDIO-DESIGN-1.md

## 1. Decision

APatch Studio adopts the TrustChain Platform design language as its visual system. The reference surface is the TrustChain organization command center: a navy shell with a gradient brand mark, a dot-grid canvas, rounded cards, cockpit stat tiles, pill badges, gradient primary actions and a light/dark palette driven by semantic tokens. Studio keeps its own product vocabulary, navigation contract, accessibility floor and information architecture. Only presentation changes.

The primitive tokens are ported from TrustChain Platform `frontend/src/app/globals.css` (SPEC-UI-THEME-1 R2), the same source OLang Studio already uses. Studio does not load external fonts, stylesheets or scripts: the local-first boundary stays intact.

## 2. Reproduced gap

Studio, TrustChain Platform and OLang Studio are shown to the same owners, pilots and design partners. Studio shipped with a neutral green theme, a flat sidebar and a text-only project header that do not read as part of the same product family. The Home page listed three numbers in a border band instead of the cockpit the other surfaces use, and the sidebar carried no runtime posture. The success tone was mapped to the accent colour, so a future accent change would silently recolour every verified state, and two semantic tokens used by SDD views (`--oi-success`, `--oi-success-soft`) were never defined.

## 3. Design system port

- **Tokens.** A dedicated theme layer defines the TrustChain primitives (`--tc-*`) for light and dark and re-points every Studio semantic token (`--oi-*`) to them, adds the missing success pair, and keeps the existing system/light/dark control. Success is emerald, information is trust blue, the crimson accent is reserved for brand and primary actions.
- **Shell.** The sidebar is the TrustChain navy chrome in both themes: gradient brand mark, product name, edition label, a section label, navigation with an inset accent bar for the active destination, count chips, the theme control and a runtime status card. A sticky top bar shows the workspace name, branch, project state pill and refresh.
- **Home command center.** An identity card with a glyph, project name and byline; four cockpit cards (verified work, left to verify, uncommitted files, protection); the project brief card; the unchanged change composer; recent results; and a module grid to Plans, Library and Admin.
- **Components.** Outer cards use a 16px radius and inner tiles 12px, list rows keep their existing geometry; primary actions use the brand gradient, secondary actions the ghost surface; badges are pills with tone borders; identifiers use a monospace stack; inputs get the crimson focus ring.

## 4. Boundaries

- No new runtime behaviour, API, persisted data or network access. The theme is CSS plus presentational markup.
- The vocabulary contract, navigation contract v2 and design floor (system/light/dark themes, 11px minimum text, focus-visible, reduced motion, in-product confirmation dialogs, stable shell geometry) remain enforced, and the new CSS is subject to the same floor.
- `outside-in.css` remains the structural floor. The theme file layers colour, surfaces and shell presentation on top of it and is loaded after it.
- Raw runtime fields, protocol identifiers and paths do not appear in the cockpit; it shows only the existing Home summary and the existing runtime projection in product language.

## 5. Verification contract

Frozen tests under `tests/design/` cover the token layer, the shell chrome, the Home command center and the floor/regression gate before implementation begins. Release requires the design tests, the existing design-floor, vocabulary, navigation and Home hierarchy tests, the complete Python suite, the production frontend build and a browser pass in light, dark and mobile layouts.

## Acceptance

| Id | Requirement | Level |
|---|---|---|
| DS-1 | Studio ships a TrustChain token layer: the light and dark palettes, brand gradient, navy shell and dot-grid canvas from SPEC-UI-THEME-1 resolve every Studio semantic token in system, light and dark modes, the theme is no longer locked to light before hydration, and no external font, stylesheet or network resource is loaded | MUST |
| DS-2 | The shell reproduces the TrustChain command-center chrome: navy sidebar with gradient brand mark, edition label, section label, inset-accent active navigation, count chips, theme control and runtime status card, plus a sticky top bar with workspace context, project state and refresh | MUST |
| DS-3 | Home is a command center: identity card, four cockpit cards for verified work, remaining work, uncommitted files and protection, the project brief card, the unchanged change composer, recent results and a module grid to Plans, Library and Admin, collapsing to one column on narrow screens | MUST |
| DS-4 | The design floor, vocabulary contract, navigation contract, existing Home hierarchy tests, complete Python suite and production frontend build stay green, and the release qualification pins this contract | MUST |

## Non-goals

This RFP does not change the navigation contract, product vocabulary, APatch governance, any API or persisted schema, load web fonts or remote stylesheets, add analytics, or restyle the legacy `App.tsx` surfaces that the active shell no longer renders.
