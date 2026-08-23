# Changelog

## 1.9.0

- Doors: `door_names` option to give doors friendlier names on the page
  (Home Assistant's names from inception-mqtt can't be edited in HA)

## 1.8.2

- Fix: the 1.8.1 log configuration raised a "Logging error" on every request
  (access-log fields need uvicorn's own formatter); logs are clean and
  timestamped again

## 1.8.1

- Doors: the MQTT discovery read for Open now runs in a background task
  (at start and every 10 minutes) instead of during page polls, and a failed
  read keeps the previous mapping
- Doors page polls a single endpoint (`/api/doors` now includes the
  temperatures), halving its Home Assistant requests
- Log lines are timestamped, and every Home Assistant failure that the page
  sees as 502 is logged with its path and cause

## 1.8.0

- Doors: new **Open** button — Inception's momentary open (the door re-locks
  by itself after its unlock time), next to Lock and the latched Unlock.
  Works for doors bridged by the inception-mqtt add-on; sent via MQTT
  because Home Assistant's lock entity has no "open" there.
- Doors: card hint corrected — Unlock stays unlocked until you Lock.

## 1.7.0

- New **Doors** page: lock / unlock `lock.*` entities (e.g. Inner Range
  Inception doors via the inception-mqtt add-on), with `door_groups` and a
  "Lock all" per group. Unlock needs a second confirming tap.
- The Doors page is behind **Google sign-in**: only the accounts listed in
  `allowed_emails` get in (`google_client_id` / `google_client_secret`
  options). Sign-in is remembered for a year, across restarts and updates.
- AC and Windows pages are unchanged and still need no sign-in.

## 1.6.0

- Tap the Outdoor / Indoor tile to open a temperature history chart with a
  24h / 7 days / 30 days toggle (mean line with min–max band)
- History is read from Home Assistant's long-term statistics over the
  websocket API, so it goes back further than the recorder's raw history

## 1.5.0

- **Outdoor / Indoor temperature** strip at the top of both pages, read from
  an Ecowitt weather console (or any HA temperature sensors)
- Sensors are auto-detected (`sensor.*_outdoor_temperature` /
  `sensor.*_indoor_temperature`); override with the new `outdoor_sensor` /
  `indoor_sensor` options

## 1.4.3

- Fix: version-stamped asset URLs (`style.css?v=…`, scripts) so browsers that
  cached files from an older version can never mix them with new pages — no
  manual cache clearing needed on phones after updates

## 1.4.2

- Fix: serve all pages/scripts/styles with `Cache-Control: no-cache` so
  browsers revalidate after updates — stale cached scripts from an older
  version could leave the AC page blank and the page navigation unstyled

## 1.4.1

- Fix: windows whose state HA reports as "unknown" (stateless covers such as
  Somfy RTS, no position feedback) were shown as unavailable with controls
  disabled; they are now controllable and show "–" as their state

## 1.4.0

- Renamed to **Home Dashboard** — now controls motorized windows as well as AC
- New **Windows** page: open/stop/close, position slider, window groups
  (`window_groups` option)
- Window schedule presets (`window_presets` option) with Once/Repeat arming,
  sharing the scheduler with AC presets
- Existing AC configuration and armed schedules carry over unchanged

## 1.3.0

- Repeat mode: arm a preset to fire on chosen weekdays at a chosen time
  until cancelled. One-shot arming unchanged. Armed schedules from 1.2.0
  carry over.

## 1.2.0

- New Schedule tab: arm one-shot schedules from config-defined presets
  (adjustable day/time), cancel from any phone, armed state survives
  restarts. Times follow Home Assistant's timezone.

## 1.1.0

- HTTPS support: new `ssl`, `certfile`, `keyfile` options using certificates
  from Home Assistant's `/ssl` folder (e.g. from the Let's Encrypt app).
- Add-to-home-screen support: web app manifest, icons, and standalone
  display mode on phones.
- Add-on store icon.

## 1.0.0

- Initial release: auto-discovered climate entities, custom groups with
  group controls (All Off / All On / group temperature), per-unit mode and
  temperature control, mobile-first UI with 5-second polling and optimistic
  updates.
