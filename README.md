# AC Dashboard — Home Assistant App

A simple web page for controlling AC units configured in Home Assistant.
Stripped-down controls with big touch targets, no HA login — made for family
use on phones, reachable over your LAN or VPN (e.g. the Tailscale app).

This repository is a Home Assistant **app repository** (add-on repository)
containing one app: [`ac_dashboard`](ac_dashboard/).

## Install (Home Assistant OS / Supervised)

1. In Home Assistant: **Settings → Apps** (called Add-ons in older HA versions)
2. Top-right **⋮ menu → Repositories**, add:
   `https://github.com/martinst/ha_dashboard`
3. Refresh the store, open **AC Dashboard**, click **Install**
   (the image builds on the device — takes a few minutes on a Pi)
4. In the app's **Configuration** tab, define your groups
   (see [DOCS](ac_dashboard/DOCS.md) for the format)
5. **Start** the app, then open `http://<your-ha-host>:8088`
   (or click **Open Web UI**)

No access token setup is needed — the app talks to Home Assistant through
the Supervisor.

## Security

The dashboard has **no authentication** — it relies on being reachable only
via your LAN/VPN. Do not port-forward port 8088 to the internet.

## Local development

```bash
cd ac_dashboard
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
cp .env.example .env       # point at your HA + a long-lived access token
cp groups.yaml.example groups.yaml
.venv/bin/pytest           # run the test suite
.venv/bin/uvicorn app.main:app --port 8088
```

Design spec and implementation plan live under `docs/superpowers/`.
