# Theme Inventory (Phase 0)

This file captures the semantic color system baseline for the theme refactor.

## Token Domains

- `scale`:
  - `brand` (`50..950`)
  - `info` (`50..950`)
  - `success` (`50..950`)
  - `warning` (`50..950`)
  - `danger` (`50..950`)
- `surface`:
  - `app`
  - `nav`
  - `nav_active`
  - `card`
  - `card_muted`
  - `table`
  - `table_header`
  - `input`
  - `overlay`
- `text`:
  - `primary`
  - `secondary`
  - `muted`
  - `inverse`
  - `link`
- `border`:
  - `default`
  - `strong`
  - `subtle`
  - `interactive`
- `focus`:
  - `ring`
  - `ring_offset`
- `action` variants (`primary`, `secondary`, `ghost`, `danger`):
  - `bg`
  - `border`
  - `text`
  - `hover_bg`
  - `hover_border`
  - `hover_text`
- `state` variants (`info`, `success`, `warning`, `danger`):
  - `bg`
  - `border`
  - `text`

## Theme Sources

Theme presets are dynamically loaded from `frontend/src/theme/presets/*.{json,js}`.

Current preset files:

- `frontend/src/theme/presets/parchment.js`
- `frontend/src/theme/presets/lilac.js`
- `frontend/src/theme/presets/dune.js`
- `frontend/src/theme/presets/oatmeal.js`
- `frontend/src/theme/presets/scholarly.json`
- `frontend/src/theme/presets/graphite.json`
- `frontend/src/theme/presets/tide.json`

Each preset contains both `light` and `dark` mode token definitions.

## Adoption Status (Phase 0-3 complete baseline)

Tokenized foundation components:

- `AppButton`
- `AppCard`
- `AppCheckbox`
- `AppEmptyState`
- `AppHelpHint`
- `AppInput`
- `AppSelect`
- `AppTable`
- `AppModal`
- `AppHeader`
- `AppNav`
- `AppAlert`
- `AppBadge`
- `RunStatusBadge`
- `QueueHealthBadge`

Hardening in place:

- Frontend token policy check script: `frontend/scripts/check_theme_tokens.mjs`
- CI enforcement step in `frontend-quality` workflow
- Theme preset integrity tests in `frontend/src/theme/presets.test.ts`
