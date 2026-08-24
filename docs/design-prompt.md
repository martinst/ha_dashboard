# Design brief: Home Dashboard restyle

## What this is

A self-hosted Home Assistant add-on serving three small web pages used by one
family on their phones: **AC** (climate control), **Windows** (motorized
covers), **Doors** (locks, behind Google sign-in). Functional, but visually
plain — I want a modern, sleek, beautiful redesign of the *styling only*.

## Current design

- Mobile-first, single column, `max-width: 640px`, light theme only.
- Look: flat light-grey background (`#f2f4f7`), white cards with 14px radius
  and a **6px colored left border** encoding state (blue=cool, orange=heat,
  green=auto/locked, grey=off, etc.), soft shadows, system font stack.
- Header: pill nav (AC | Windows | Doors) + a tiny connection dot (green/red).
- Below header: two **temperature tiles** (Outdoor / Indoor), tappable —
  they open a **bottom sheet** with an SVG history chart (mean line +
  shaded min–max band, axis labels, gridlines) and a 24h/7d/30d toggle.
- AC page: Control/Schedule tabs; group headers (uppercase muted) with
  All Off / All On and a compact ± stepper; unit cards with name, current
  temp, big ± stepper (round 44px buttons), and mode-button row where the
  active mode is filled with its accent color.
- Windows page: cards with Open/Stop/Close button row and a range slider.
- Doors page: signed-in line with Sign out link; cards with state label
  (Locked/Unlocked…), a Lock / Open / Unlock button row (a pressed Open or
  Unlock turns into an orange "Tap again to …" confirm state), and a small
  hint line. Schedule tab cards: preset info, Once/Repeat toggle, round
  day-of-week chips, native `<input type="time">` and `<select>`, Arm/Cancel.
- Red full-width banner when Home Assistant is unreachable.

Current design tokens (all colors live in `:root` custom properties):
`--bg #f2f4f7, --card #fff, --text #1c2330, --muted #6b7585,
--accent-off #9aa3b2, --accent-cool #2e86de, --accent-heat #e67e22,
--accent-dry #16a085, --accent-fan #8e44ad, --accent-auto #27ae60`

## What I want

A cohesive, contemporary look — calm, premium, "smart-home app" quality.
You choose the direction (e.g. softer neutrals, better type hierarchy and
spacing rhythm, refined state-color system, nicer segmented controls,
elevated bottom sheet, dark mode). Must stay glanceable and dense enough
that 6–12 cards fit comfortably; big touch targets are non-negotiable.
Design one artboard per page (AC control, AC schedule, Windows, Doors) plus
the history bottom sheet, at 390×844 (iPhone-ish).

## Hard constraints (please respect these)

1. **CSS-only restyle.** The DOM is built by vanilla JS; class names and
   structure must stay. Style ONLY these existing classes/selectors:
   `body, header, .pages, .page-link(.active), .dot(.ok), .banner, .tabs,
   .tab(.active), .temps, .temp-tile(.outdoor/.indoor/.unavailable),
   .temp-label, .temp-value, .user-line, main, .group, .group-header (h2),
   .group-controls, .group-msg, .card(.unavailable)[data-mode|data-state],
   .card-top, .unit-name, .current-temp, .cover-state, .lock-state,
   .stepper, .step, .target, .modes, .mode-btn(.active)[data-mode],
   .cover-btns, .cover-btn, .lock-btns, .lock-btn(.open/.unlock/.confirm),
   .lock-hint, .preset, .preset-summary, .arm-row (select, input[type=time]),
   .arm, .cancel, .fires, .mode-toggle, .mode-opt(.active), .day-chips,
   .day-chip(.active), .hint, .hint-inline, .sheet(.hidden), .sheet-backdrop,
   .sheet-panel, .sheet-head, .sheet-close, .range-toggle, .range-opt(.active),
   .chart-summary, .stat, .stat-label, .stat-value, .chart, .chart-svg
   (svg children: .grid, .axis-label, .band, .mean, .mean-dot), .hidden`.
   Generic element styling (`button`, inputs) is fine. No new wrapper divs.
2. **No external resources.** No CDN fonts/icons/frameworks — the app must
   work offline on a LAN. System font stack (or CSS-only effects). No
   images; if decoration is needed, use CSS gradients/borders only.
   Icon fonts and SVG icon sets can't be added (JS renders text labels).
3. **Full re-render every 5 s.** JS replaces all cards on each poll, so
   avoid entry animations/keyframes on cards (they'd replay constantly).
   Transitions on `:active`/hover and on the bottom sheet are fine.
4. Plain CSS (no preprocessor, no build step), one file, modern CSS is fine
   (nesting OK to avoid: keep flat selectors; custom properties encouraged).
5. Keep semantic state colors distinguishable: modes off/cool/heat/dry/
   fan/auto; cover open/closing; lock locked/unlocked/jammed; the confirm
   ("Tap again") state must be visually loud.
6. Dark mode: optional but welcome via `@media (prefers-color-scheme: dark)`
   using the same custom-property tokens.
7. Accessibility: ≥44px touch targets, WCAG AA text contrast, visible
   focus states.

## Required output format

So I can incorporate it directly:

1. **A complete replacement `style.css`** in one code block — the whole
   file, not fragments — organized: tokens (`:root`), base/reset, header,
   temps, tabs, groups/cards, steppers/modes, covers, doors, schedule,
   sheet/chart, dark mode. Comment each section.
2. A short **"design decisions"** list (type scale, spacing scale, color
   system) so future changes stay consistent.
3. If (and only if) something truly can't be done within constraint 1, an
   explicit list titled **"Requested HTML changes"** describing each change
   as: file, current element, proposed element — nothing else may assume
   HTML edits.

Do not output HTML mockups of the pages as the deliverable — the CSS file is
the deliverable; artboards are for judging the design.
