# Schedule Presets (Second Tab) — Design Spec

**Date:** 2026-06-07
**Status:** Approved
**Builds on:** 2026-06-06-daikin-ac-dashboard-design.md (v1.1.0 shipped)

## Purpose

Let the family schedule one-shot AC actions from the dashboard — e.g. "start
the living-room units tomorrow at 18:00". Admin defines *presets* (which
units, what action, default time) in the add-on configuration; anyone arms or
cancels them from a new **Schedule** tab in the UI, optionally adjusting day
and time when arming.

## Scope

- Presets defined in config; armed/cancelled from the UI (adjustable day +
  time at arm time).
- One-shot semantics: a fired preset returns to unarmed. One armed instance
  per preset — re-arming replaces the previous arm.
- Armed state survives add-on restarts.

Out of scope: recurring schedules, ad-hoc scheduling without a preset, fire
history/notifications, per-user permissions.

## Configuration

New optional top-level `presets:` list in the add-on options (next to
`groups:`); for local dev a `presets.yaml` file next to `groups.yaml`:

```yaml
presets:
  - name: Evening warmth          # required, unique across presets
    entities:                     # required, non-empty
      - climate.living_left
      - climate.living_right
    mode: heat                    # optional; any HA mode, or "on"/"off"
    temperature: 23               # optional; at least one of mode/temperature
    time: "18:00"                 # required, HH:MM — default fire time
```

- Preset **id** = name lowercased with spaces → `_` (e.g. `evening_warmth`).
  Duplicate ids → startup error (same clear-failure style as groups.yaml).
- Validation at load: non-empty entities, HH:MM time, mode-or-temperature
  present. Invalid presets fail startup with a clear message.
- The add-on's `run.sh` converts the `presets` option into `presets.yaml`
  (same pattern as groups). Add-on schema gains the matching structure
  (`mode: str?`, `temperature: float?`).

## Backend

### New module `app/scheduler.py`

`Scheduler` class owning armed state and the firing loop:

- `armed: dict[preset_id, datetime]` — fire times as timezone-aware datetimes.
- **Persistence:** JSON file (add-on: `/data/schedules.json`; local dev:
  `./schedules.json`; path from new `Settings.schedules_path`). Written
  atomically (temp file + rename) on every arm/cancel/fire. Loaded at
  startup; entries referencing unknown preset ids are dropped with a log
  warning.
- **Timezone:** fetched once at startup from HA `GET /api/config`
  (`time_zone`, via a new `HAClient.get_config()`); falls back to system
  local time with a warning if unavailable.
- **Loop:** asyncio task (started/stopped in the FastAPI lifespan) that wakes
  every 10 seconds and fires any armed entry whose time has arrived.
- **Missed fires:** if `now - fires_at ≤ 1 hour` (add-on was briefly down or
  loop delayed), fire anyway; if later than that, discard with a log warning.
- **Firing:** per entity, reuse `apply_command` (same semantics as the group
  endpoint: `mode "on"` → `climate.turn_on`, etc.), `asyncio.gather` with
  `return_exceptions=True`, log partial failures. The preset disarms
  regardless of outcome.
- To avoid a circular import (`main` imports `scheduler`), `SetCommand` and
  `apply_command` move from `app/main.py` to a new `app/commands.py`; both
  `main` and `scheduler` import from there.

### New endpoints (in `app/main.py`)

| Endpoint | Behaviour |
|---|---|
| `GET /api/schedule` | `{presets: [{id, name, entities, mode, temperature, time, armed: {fires_at} \| null}]}` |
| `POST /api/schedule/{preset_id}/arm` | Body `{date: "YYYY-MM-DD", time: "HH:MM"}`. Replaces any existing arm. 400 if in the past or more than 7 days ahead; 404 unknown preset. Returns `{fires_at}` (ISO 8601 with offset). |
| `POST /api/schedule/{preset_id}/cancel` | Disarms; idempotent. 404 unknown preset. |

## Frontend

- Header gains a two-tab bar: **Control** (existing page) and **Schedule**.
  Pure client-side toggle (show/hide two `<main>` sections); no routing.
- The 5-second poll fetches `/api/state` and `/api/schedule` together; both
  tabs stay current on all phones.
- **Schedule tab:** one card per preset:
  - Name + action summary derived from mode/temperature, e.g.
    "Heat 23° — Living (left), Living (right)".
  - **Unarmed:** day selector (Today / Tomorrow), `<input type="time">`
    pre-filled with the preset's default time, and an **Arm** button. If the
    default time has already passed today, the day selector defaults to
    Tomorrow.
  - **Armed:** "Fires today at 18:00" / "Fires tomorrow at 18:00" (or the
    date if further out) + **Cancel** button.
  - Arm/cancel use optimistic UI like the rest of the app; the poll
    reconciles.
- No presets configured → the Schedule tab shows a short hint pointing at the
  add-on configuration.

## Error handling

- Arm/cancel failures (network) → existing connectivity banner.
- Fire-time HA failures are logged server-side; the family sees the result
  (or its absence) on the Control tab. No retry.
- Corrupt `schedules.json` → start with empty armed state, log warning.

## Testing

- `tests/test_scheduler.py`: arm/replace/cancel, persistence round-trip,
  fire-at-time (injectable `now` function), missed-fire grace (≤1 h fires,
  >1 h discarded), unknown-preset entries dropped at load, partial HA failure
  logged + disarm.
- `tests/test_api.py`: the three endpoints — happy paths, past-time 400,
  >7-days 400, unknown preset 404, arm replaces.
- `tests/test_config.py`: preset parsing/validation errors.
- Frontend remains manually verified.

## Versioning

Add-on `1.2.0`; CHANGELOG entry; DOCS.md section with a presets example.
