# Daikin AC Dashboard

A simple web page for controlling Daikin AC units configured in Home
Assistant. Runs next to HA on the Pi; reach it over your Tailscale/VPN —
no HA login needed.

## Setup

1. **HA token**: in Home Assistant, go to your profile → Security →
   Long-lived access tokens → Create token.
2. Copy `.env.example` to `.env` and fill in `HA_URL` and `HA_TOKEN`.
3. Copy `groups.yaml.example` to `groups.yaml` and list your units
   (entity IDs are under Settings → Devices & Services → Entities in HA,
   filter on "climate"). Units not listed appear under "Ungrouped".
4. Install and run:

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8088
   ```

5. Open `http://<pi-address>:8088`.

## Run on boot (systemd)

Adjust paths/user in `deploy/ha-dashboard.service` if yours differ, then:

```bash
sudo cp deploy/ha-dashboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ha-dashboard
```

## Tests

```bash
.venv/bin/pytest
```

## Security note

The app has no authentication — it relies on being reachable only via
your LAN/Tailscale network. Do not port-forward it to the internet.
