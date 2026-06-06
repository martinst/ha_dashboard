#!/usr/bin/with-contenv bashio
# Entrypoint for the AC Dashboard add-on.
# The Supervisor provides SUPERVISOR_TOKEN and proxies the Core API at
# http://supervisor/core (enabled by homeassistant_api: true in config.yaml).
set -e

export HA_URL="http://supervisor/core"
export HA_TOKEN="${SUPERVISOR_TOKEN}"

cd /opt/ac_dashboard

# Convert the add-on options (Configuration tab) into groups.yaml.
python3 - <<'PY'
import json
import yaml

with open("/data/options.json") as f:
    options = json.load(f)
with open("groups.yaml", "w") as f:
    yaml.safe_dump({"groups": options.get("groups", [])}, f)
PY

bashio::log.info "Starting AC Dashboard on port 8088"
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8088
