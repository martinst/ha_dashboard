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

## Usage

Open `http://<your-ha-host>:8088` (or click **Open Web UI**). Each unit card
shows the current room temperature and offers mode buttons (Off / Cool / Heat /
Dry / Fan / Auto — only modes the unit supports) and a target-temperature
stepper. Each group header has **All Off** / **All On** buttons and a group
temperature stepper that applies to every unit in the group.

## Security

The dashboard has **no authentication** — anyone who can reach port 8088 can
control your AC units. Keep it on your LAN/VPN (e.g. the Tailscale app).
Do **not** port-forward it to the internet.
