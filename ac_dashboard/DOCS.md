# Home Dashboard

Simple web pages for controlling your AC units (any `climate.*` entities in
Home Assistant) and motorized windows (any `cover.*` entities, e.g. Somfy
TaHoma via the Overkiz integration), with the outdoor and indoor temperature
from a weather station (e.g. Ecowitt) at the top — large touch targets, no HA
login, made for family use on phones. Units are auto-discovered; you choose
how to group them.

## Configuration

Set up your groups in the **Configuration** tab. Example:

```yaml
groups:
  - name: Upstairs
    entities:
      - climate.master_bedroom
      - climate.upstairs_hallway
  - name: Living room
    entities:
      - climate.living_left
      - climate.living_right
```

Entity IDs are listed in HA under **Settings → Devices & Services → Entities**
(filter on "climate"). Any climate entity not listed in a group still appears
on the page under an "Ungrouped" section.

Restart the app after changing the configuration.

## Windows

The **Windows** page (top navigation) controls `cover.*` entities: open /
stop / close buttons, and a 0–100 % position slider for windows that support
it. Configure window groups the same way as AC groups:

```yaml
window_groups:
  - name: Living room
    entities:
      - cover.living_left
      - cover.living_right
```

Any cover entity not listed still appears under "Ungrouped" on the Windows
page.

## Doors (with Google sign-in)

The **Doors** page controls `lock.*` entities — for example doors and gates
from an Inner Range Inception system exposed through the *inception-mqtt*
add-on. Each card shows the lock state and has **Lock**, **Open** and
**Unlock** buttons (Open and Unlock ask for a second tap):

- **Unlock** — Home Assistant's `lock.unlock`; with inception-mqtt this is
  Inception's latched *Unlock*: the door stays unlocked until you Lock.
- **Open** — Inception's momentary *Open*: lets someone in, then the door
  re-locks by itself after its configured unlock time. Home Assistant's lock
  entity has no such action, so the dashboard publishes `Open` to the door's
  MQTT command topic (read from the add-on's discovery messages). The button
  only appears for doors whose discovery config is visible to the add-on.

Optional groups get a **Lock all** button — groups deliberately cannot
unlock or open everything at once.

```yaml
door_groups:
  - name: Street
    entities:
      - lock.front_gate
      - lock.driveway_gates
```

Because this page can open your doors, it is protected by **Google
sign-in**, and only the Google accounts you list are accepted. People stay
signed in for a year on each device, so the Google prompt appears once.
Setting it up takes a few minutes in the Google Cloud console:

1. Go to <https://console.cloud.google.com/>, create a project (any name).
2. **APIs & Services → OAuth consent screen**: choose *External*, fill in the
   app name and your email. Under **Test users** add every email you intend
   to allow (or *Publish* the app — it only asks for the basic email scope,
   so no Google verification is needed).
3. **APIs & Services → Credentials → Create credentials → OAuth client ID**,
   type *Web application*. Under **Authorized redirect URIs** add
   `https://<your-host>:8088/auth/callback` — the exact address your family
   uses to open the dashboard, e.g.
   `https://myhome.duckdns.org:8088/auth/callback`. Google requires HTTPS
   and a real hostname here (no IP addresses, no `.local` names), so set up
   the HTTPS section below first.
4. Copy the client ID and client secret into the add-on configuration:

```yaml
google_client_id: 1234567890-abc.apps.googleusercontent.com
google_client_secret: GOCSPX-...
allowed_emails:
  - you@gmail.com
  - partner@gmail.com
```

5. Restart the add-on. Opening **Doors** now goes through Google once per
   device; **Sign out** is at the top of the page.

Until `google_client_id` is set, the Doors page shows a "not configured"
notice. The AC and Windows pages never require sign-in.

## Outdoor / indoor temperature

Both pages show an **Outdoor** and **Indoor** temperature tile at the top. By
default the app looks for Ecowitt-style sensors — the first
`sensor.*_outdoor_temperature` and `sensor.*_indoor_temperature` entities with
device class *temperature* (the Ecowitt integration creates these for a
WN1980C/GW-series console). To use other sensors, set them explicitly:

```yaml
outdoor_sensor: sensor.garden_probe_temperature
indoor_sensor: sensor.hallway_temperature
```

A tile is hidden when no sensor is configured or found, and dimmed when the
sensor is unavailable.

**Tap a tile** to open a history chart: 24 hours (5-minute resolution), 7
days or 30 days (hourly), showing the mean with a shaded min–max band. The
data comes from Home Assistant's long-term statistics, so it goes back as far
as the sensor has been recording statistics — the recorder's `purge_keep_days`
setting does not limit it. A sensor that was recently added or renamed
starts with an empty chart that fills in over time.

## Schedule presets

Optional schedules for the **Schedule** tab. You define presets here;
anyone can arm them from the page (picking day and time) and cancel them.
A fired one-shot preset disarms itself; a repeating one stays armed.

```yaml
presets:
  - name: Evening warmth
    entities:
      - climate.living_left
      - climate.living_right
    mode: heat          # any mode the units support, or "on" / "off"
    temperature: 23     # optional — at least one of mode/temperature
    time: "18:00"       # default time shown when arming
```

Armed schedules survive app restarts. If the app was stopped at the
scheduled time, the action still runs if the app comes back within an hour;
otherwise it is skipped (a log line records this).

When arming you can pick **Once** (fires once, then disarms) or **Repeat**
(pick weekdays; fires on each selected day at the chosen time until
cancelled).

Window schedules work the same way with `window_presets` (shown on the
Windows page's Schedule tab):

```yaml
window_presets:
  - name: Night close
    entities:
      - cover.living_left
      - cover.living_right
    action: close       # open | close — or omit if position is given
    position: 20        # optional 0–100; wins over action when both are set
    time: "22:00"
```

## Usage

Open `http://<your-ha-host>:8088` (or click **Open Web UI**). Each unit card
shows the current room temperature and offers mode buttons (Off / Cool / Heat /
Dry / Fan / Auto — only modes the unit supports) and a target-temperature
stepper. Each group header has **All Off** / **All On** buttons and a group
temperature stepper that applies to every unit in the group.

## HTTPS

The dashboard can serve HTTPS using a certificate from Home Assistant's
`/ssl` folder:

```yaml
ssl: true
certfile: fullchain.pem
keyfile: privkey.pem
```

To get a browser-trusted certificate without exposing anything to the
internet, the usual recipe is:

1. Create a free [DuckDNS](https://www.duckdns.org) subdomain and set its IP
   to your Home Assistant host's address (its Tailscale IP if your family
   uses Tailscale, otherwise its LAN IP).
2. Install the official **Let's Encrypt** app, configured with the
   `dns-duckdns` challenge and your DuckDNS token — it writes
   `fullchain.pem`/`privkey.pem` into `/ssl`. Restart it every couple of
   months to renew (an HA automation can do this on a schedule).
3. Enable `ssl: true` here and restart this app.
4. Use `https://<your-subdomain>.duckdns.org:8088` — the certificate is only
   valid for that hostname, not for IPs or `.local` names.

After that, phones can add the page to their home screen and it opens
standalone like an app (icon and manifest are built in).

## Security

The AC and Windows pages have **no authentication** — anyone who can reach
port 8088 can control your AC units and windows. Keep it on your LAN/VPN
(e.g. the Tailscale app). Do **not** port-forward it to the internet.

The Doors page additionally requires Google sign-in from an allowed account.
The sign-in cookie is HttpOnly and signed with a key stored in the add-on's
data folder; signing out on a device or removing an address from
`allowed_emails` takes effect on that device's next request.
