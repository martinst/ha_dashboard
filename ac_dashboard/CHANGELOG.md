# Changelog

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
