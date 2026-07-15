# Windows Dashboard — Design

**Date:** 2026-07-15
**Status:** Approved pending user review
**Version target:** 1.4.0

## Goal

Add a UI for controlling the Somfy TaHoma motorized windows (HA `cover.*`
entities via the Overkiz integration) with full parity to the AC section:
per-window controls, groups, and scheduled presets. The add-on generalizes
from "AC Dashboard" into a multi-domain **Home Dashboard**.

## Decisions made

- **One add-on, generalized.** Not a second add-on; not a page bolted onto
  the AC UI. The add-on becomes a general home dashboard with a section per
  domain (climate, covers).
- **Slug stays `ac_dashboard`** so the Pi updates in place and keeps its
  config. Display name changes to **Home Dashboard**. The repo directory
  stays `ac_dashboard/`.
- **Full parity for windows:** open/close/stop buttons, position slider
  where supported, groups, and scheduled presets (once + weekly repeat)
  reusing the existing scheduler.
- **Approach: parallel domain models, shared plumbing.** Cover twins of the
  climate models where the shapes genuinely differ; the scheduler, HA
  client, group-building, and API patterns are shared. The working climate
  path is not rewritten.

## Config & identity

`config.yaml`: display name → "Home Dashboard", description updated,
version → 1.4.0. Slug unchanged.

New add-on options, mirrored to yaml files by `run.sh` like the existing
`groups`/`presets`:

```yaml
window_groups:
  - name: Living room
    entities: [cover.living_left, cover.living_right]
window_presets:
  - name: Night close
    entities: [cover.living_left, cover.living_right]
    action: close        # open | close, or omit if position given
    position: 20         # optional 0–100
    time: "22:00"
```

- `window_groups` reuse the existing `Group` model.
- `window_presets` load into a new `CoverPreset` model mirroring `Preset`'s
  validation: non-empty entities, HH:MM time, at least one of
  action/position, position in 0–100, `action` in {open, close} when given.
- **Preset ID namespacing:** cover preset IDs are `cover:<slug>` so an AC
  preset and a window preset can share a display name without colliding in
  the scheduler or `schedules.json`. Existing climate preset IDs are
  unchanged (no migration).
- Ungrouped `cover.*` entities appear in an "Ungrouped" section, same as
  ungrouped climate units, so the UI works before any window config exists.
- Existing `groups`/`presets` options are untouched — zero migration for
  current AC config.

## Backend

### `ha_client.py`
- New methods: `open_cover`, `close_cover`, `stop_cover`,
  `set_cover_position` — thin wrappers over `/api/services/cover/...`.
- `get_climate_states` generalizes to a single `get_states()` fetch that
  both domains filter from (one HA round-trip per poll).

### `commands.py`
- New `CoverCommand(action: str | None, position: int | None)` with
  "at least one field" validation.
- `apply_command` dispatches on entity prefix: `climate.*` requires
  `SetCommand`, `cover.*` requires `CoverCommand`; a mismatch is a
  validation error (HTTP 400 at the API layer).
- Cover dispatch order: `stop` wins over position; otherwise position (if
  set) via `set_cover_position`; else open/close service.

### `state.py`
- `cover_from_ha_state` → `{entity_id, name, state, position,
  supports_position, available}` (state is open/closed/opening/closing;
  `supports_position` derived from the `supported_features` SET_POSITION
  flag, bit value 4, with `current_position` presence as fallback).
- `missing_cover` placeholder mirroring `missing_unit`.
- Group building shared with climate (domain parameter or thin sibling
  `build_cover_groups`); ungrouped logic reused.

### `scheduler.py`
- Unchanged except `_fire`: each preset model gains a `.command()` method
  returning its own command type; `_fire` calls `preset.command()` instead
  of constructing `SetCommand` directly.
- One scheduler instance holds both domains' presets (IDs namespaced), one
  `schedules.json`, arm/cancel/weekly logic untouched.

### `main.py`
- `POST /api/covers/{entity_id}/set` (body: `CoverCommand`).
- `POST /api/cover-groups/{name}/set` with the same partial-failure report
  (`{total, succeeded, failed}`) as climate groups.
- `/api/state` returns `{"groups": [...], "cover_groups": [...]}`.
- Schedule endpoints already work for any preset ID; `serialize_schedule`
  adds a `domain` field per preset so each page filters its own.

## Frontend

- Second static page `windows.html` + `windows.js` alongside `index.html` +
  `app.js`; shared `style.css`; a small fixed nav header with two tab links
  (**AC** / **Windows**) on both pages — no SPA router. PWA manifest keeps
  `/` as the start URL.
- Windows page, card-per-group like the AC page:
  - Per window: friendly name; state line ("Open · 40%", "Closed",
    "Opening…"); big **▲ Open / ■ Stop / ▼ Close** buttons.
  - Full-width 0–100% position slider for windows with
    `supports_position`, sent on release (not on drag).
  - Group headers: **Open all / Close all**.
  - **Schedules** section mirroring the AC one (Once/Repeat arm modes,
    weekday chips), filtered to `domain: cover` presets; the AC page
    filters to climate presets.
  - Same polling model: `/api/state` every few seconds, optimistic UI on
    press; Stop stays prominent while a window reports opening/closing.
  - Unavailable windows greyed out, controls disabled (matches AC).

## Error handling

Existing patterns throughout: `HAError` → 502; unknown group/preset → 404;
invalid command (bad action, position out of range, wrong command type for
the entity domain) → 400 via Pydantic; group ops report partial failures;
bad `window_presets` config fails at startup with a clear message.

## Testing

Mirrors the existing suite:
- `test_config.py`: `CoverPreset` validation, `window_groups` loading,
  cross-domain ID collision allowed via namespacing.
- `test_ha_client.py`: four cover service calls via mock transport.
- `test_commands.py` (or existing home): dispatch rules — stop beats
  position, wrong-domain command rejected.
- `test_state.py`: `cover_from_ha_state` incl. a position-less cover;
  `missing_cover`; ungrouped covers.
- `test_api.py`: new endpoints, partial-failure report, 400/404 paths.
- `test_scheduler.py`: a cover preset fires through `preset.command()`.

Frontend remains untested (as today).

## Rollout

Single release: bump to 1.4.0, CHANGELOG entry, DOCS.md documents
`window_groups`/`window_presets` and the rename. On the Pi it arrives as a
normal add-on update (HA/Supervisor restart needed for the update to
appear); user then adds window config in the Configuration tab and restarts
the add-on. Existing AC config, schedules, and armed state carry over
untouched.
