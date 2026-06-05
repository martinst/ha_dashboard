# Daikin AC Dashboard — Design Spec

**Date:** 2026-06-06
**Status:** Approved

## Purpose

A simple web page for controlling the household's Daikin AC units, which are
configured as climate entities in Home Assistant (HA) on a Raspberry Pi. Goals:

- **Simple for family**: stripped-down controls, no HA login or HA UI clutter.
- **Reachable from outside** via the existing Tailscale/VPN — no public exposure,
  so the app itself needs no authentication.

## Scope

Per unit: on/off, target temperature, HVAC mode (cool/heat/dry/fan/auto), and
current room temperature display. Units are auto-discovered from HA and
organized into custom groups with group-level controls.

Out of scope for v1: fan speed, swing, presets, scheduling, history/graphs,
live push updates (polling is sufficient).

## Architecture

FastAPI backend + a single plain-JS HTML page. Runs on the Pi (uvicorn,
port 8088) next to HA, reached over Tailscale. The backend holds a long-lived
HA access token and proxies all HA communication; the browser only talks to
the backend. State updates by polling every 5 seconds (Option A — chosen over
a WebSocket relay for simplicity; the UI can be upgraded later without
structural change).

### Project layout

```
ha_dashboard/
├── app/
│   ├── main.py          # FastAPI app: serves the page + API endpoints
│   ├── ha_client.py     # Thin async client for HA's REST API (httpx)
│   ├── config.py        # Loads .env + groups.yaml
│   └── static/
│       ├── index.html
│       ├── app.js
│       └── style.css
├── groups.yaml          # Custom group definitions
├── .env                 # HA_URL, HA_TOKEN (never committed)
├── requirements.txt
└── README.md            # Setup incl. running as a systemd service on the Pi
```

### Configuration

- `.env`: `HA_URL` (e.g. `http://localhost:8123`), `HA_TOKEN` (long-lived
  access token created in HA).
- `groups.yaml`:

```yaml
groups:
  - name: Upstairs
    entities: [climate.bedroom, climate.office]
  - name: Downstairs
    entities: [climate.living_room]
```

Auto-discovered climate entities not listed in any group appear under an
"Ungrouped" section, so new units are never invisible.

## API

| Endpoint | Action |
|---|---|
| `GET /` | Serves `index.html` |
| `GET /api/state` | All groups + units with current state in one call |
| `POST /api/units/{entity_id}/set` | Body: any of `{mode, temperature}` |
| `POST /api/groups/{name}/set` | Same body, fanned out to every unit in the group |

`GET /api/state` response shape:

```json
{
  "groups": [
    {
      "name": "Upstairs",
      "units": [
        {
          "entity_id": "climate.bedroom",
          "name": "Bedroom",
          "current_temp": 24.5,
          "target_temp": 22.0,
          "mode": "cool",
          "available_modes": ["off", "cool", "heat", "dry", "fan_only", "auto"],
          "min_temp": 16,
          "max_temp": 30,
          "available": true
        }
      ]
    }
  ]
}
```

### Data flow

- `GET /api/state`: backend calls HA `GET /api/states`, filters to `climate.*`
  entities, merges with `groups.yaml`, returns the combined structure.
- Set commands map to HA services: `mode` → `climate.set_hvac_mode`
  (`"off"` turns the unit off; any other mode turns it on),
  `temperature` → `climate.set_temperature`. The special value `mode: "on"`
  maps to `climate.turn_on`, which restores the unit's previous mode — used
  by the group "All On" button (per-unit turn-on is always an explicit mode
  choice in the UI).
- Group commands fan out to all member units in parallel (`asyncio.gather`)
  and report partial failures (e.g. "2 of 3 units updated").
- The page polls `/api/state` every 5 s. Control taps apply optimistically in
  the UI, send the POST, and reconcile on the next poll.

### Error handling

- HA unreachable → backend returns 502; the page shows a "Can't reach Home
  Assistant" banner and keeps polling until it recovers.
- A unit `unavailable` in HA renders greyed-out with controls disabled.

## UI

Mobile-first single page, plain CSS, large touch targets:

- **Header**: title + connection status dot.
- **One section per group**: group name heading with a compact group-control
  row — All Off / All On buttons and a temp stepper applying to the whole group.
- **Unit cards**:
  - Unit name + current room temperature
  - Large target temperature with − / + steppers (0.5° steps, clamped to the
    unit's reported min/max)
  - Mode selector: row of buttons (Off / Cool / Heat / Dry / Fan / Auto)
    showing only modes the unit supports; active mode highlighted; Off styled
    distinctly
  - Card accent tinted by mode (blue cooling, orange heating, grey off) for
    at-a-glance readability
- Optimistic updates on tap; poll reconciles.

## Testing

- `pytest` with the `httpx`/FastAPI test client; HA responses mocked.
- Coverage: state merging (discovery + groups + ungrouped), set-command →
  HA service-call mapping, group fan-out with partial failure, HA-unreachable
  handling.
- Frontend verified manually for v1 (no JS test harness).
