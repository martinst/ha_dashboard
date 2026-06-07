# Recurring Schedules ("Repeat until cancelled") — Design Spec

**Date:** 2026-06-07
**Status:** Approved
**Builds on:** 2026-06-07-schedule-presets-design.md (v1.2.0 shipped)

## Purpose

Let the family arm a preset to repeat on chosen weekdays at a chosen time,
staying armed until cancelled — alongside the existing one-shot arming.

## Scope

- New "Repeat" arm mode: pick weekdays (Mon–Sun) + time; fires on each
  selected day until cancelled.
- One armed entry per preset still holds: re-arming (either mode) replaces.
- Presets remain defined in config exactly as in v1.2.0 — no config changes.

Out of scope: multiple armed entries per preset, end dates, per-occurrence
skip, fire history.

## Data model & persistence

`Scheduler.armed` values become typed records instead of bare datetimes:

- **Once:** `{"type": "once", "fires_at": <aware datetime>}` — fires, then
  disarms (v1.2.0 behavior).
- **Weekly:** `{"type": "weekly", "days": <set of int>, "time": "HH:MM",
  "next_fire": <aware datetime>}` — days use Python's weekday numbering
  (Mon=0 … Sun=6). After firing — or after skipping a missed occurrence
  older than the 1-hour grace window (logged) — `next_fire` advances to the
  next selected weekday at `time` and the entry **stays armed**.

`schedules.json` stores the same shape with ISO datetimes and `days` as a
sorted list. Entries in the v1.2.0 format (plain ISO string values) load as
`once` records, so armed schedules survive the upgrade. Unknown/corrupt
entries are dropped with a warning, as before.

Internally the scheduler represents records as small dataclasses
(`OnceArm(fires_at)`, `WeeklyArm(days, time, next_fire)`) with a shared
`due_at` accessor, so `check_due` stays a single loop over "what fires next".

### Next-occurrence rule

Given now, selected `days`, and `time`: the next fire is today at `time` if
today's weekday is selected and `time` is still ahead; otherwise the next
selected weekday (searching forward up to 7 days) at `time`. Advancing after
a fire uses the same rule starting from one minute after the fire time.

## API

- `POST /api/schedule/{preset_id}/arm` accepts either body:
  - `{date: "YYYY-MM-DD", time: "HH:MM"}` → once (unchanged semantics).
    Now returns the typed record `{type: "once", fires_at}` (v1.2.0
    returned bare `{fires_at}`; the only consumer is this app's own JS,
    which is updated in the same release).
  - `{repeat: [0,1,2,3,4], time: "HH:MM"}` → weekly. 400 if `repeat` is
    empty, has values outside 0–6, or `time` is malformed. Returns
    `{type: "weekly", days, time, next_fire}`.
  - Bodies with both `date` and `repeat`, or neither → 422/400.
- `GET /api/schedule`: `armed` is now the full typed record:
  `{type: "once", fires_at}` or `{type: "weekly", days, time, next_fire}`,
  or `null`.
- `POST /api/schedule/{preset_id}/cancel`: unchanged (cancels either type).

## Scheduler changes

- `arm(preset_id, date_str, time_str)` keeps its signature (once).
- New `arm_weekly(preset_id, days, time_str)` — validates inputs
  (`ArmError`), computes `next_fire`, persists, returns the record.
- `check_due`: an entry whose due time has arrived is handled by type:
  - once → remove, save, fire (grace rule unchanged)
  - weekly → advance `next_fire`, save, then fire only if within grace
- Firing itself (`_fire`, `apply_command`, partial-failure logging) is
  unchanged.

## UI (Schedule tab)

The unarmed card's arm row gains a two-option mode toggle, **Once | Repeat**
(per-preset, kept in the existing `armForm` map; default Once):

- **Once:** current controls (Today/Tomorrow + time + Arm).
- **Repeat:** seven weekday chips labeled M T W T F S S (all selected by
  default; tapping toggles; Arm disabled while none selected) + time + Arm.

Armed cards:

- once → "Fires today/tomorrow/date at HH:MM" (unchanged)
- weekly → "Repeats <days> at HH:MM · next <today/tomorrow/date>" where
  `<days>` renders compact ranges ("Mon–Fri", "Mon, Wed, Fri", "every day")
- Both show **Cancel**. Optimistic updates and poll reconciliation work as
  in v1.2.0 (the pending window now protects the whole armed record).

Weekday numbering seam: the API uses Mon=0…Sun=6; JavaScript's
`Date.getDay()` is Sun=0 — the frontend converts explicitly when computing
"next" labels. Day labels are computed client-side from `next_fire` exactly
as `firesLabel` does today.

## Error handling

- Invalid repeat input → 400 with message; UI reverts optimistic state
  (existing pattern).
- Restart while weekly-armed: `next_fire` reloads from disk; if it's in the
  past beyond grace at the first tick, the occurrence is skipped, the entry
  advances, and it stays armed.

## Testing

- Scheduler: arm_weekly validation (empty days, bad day numbers, bad time);
  next-occurrence math (today-ahead, today-passed, week wrap, exactly-now);
  fire advances and stays armed; missed-beyond-grace advances without
  firing; persistence round-trip for both types; legacy v1.2.0 string
  entries load as once; re-arm replaces across types.
- API: weekly arm happy path + validation 400s; GET shape for both types;
  cancel of a weekly arm; once arming unchanged (regression).
- Frontend: manual on-device (Task verification step), `node --check`.

## Versioning

Add-on `1.3.0`; CHANGELOG entry; DOCS.md "Schedule presets" section gains a
sentence about Repeat mode. No config schema changes.
