# Changelog

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
