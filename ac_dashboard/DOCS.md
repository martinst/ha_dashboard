# AC Dashboard

A simple web page for controlling your AC units (any `climate.*` entities in
Home Assistant) — large touch targets, no HA login, made for family use on
phones. Units are auto-discovered; you choose how to group them.

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

The dashboard has **no authentication** — anyone who can reach port 8088 can
control your AC units. Keep it on your LAN/VPN (e.g. the Tailscale app).
Do **not** port-forward it to the internet.
