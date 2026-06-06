#!/usr/bin/with-contenv bashio
# Entrypoint for the AC Dashboard add-on.
# The Supervisor provides SUPERVISOR_TOKEN and proxies the Core API at
# http://supervisor/core (enabled by homeassistant_api: true in config.yaml).
set -e

export HA_URL="http://supervisor/core"
export HA_TOKEN="${SUPERVISOR_TOKEN}"

cd /opt/ac_dashboard

export SCHEDULES_PATH=/data/schedules.json

# Convert the add-on options (Configuration tab) into groups.yaml + presets.yaml.
python3 - <<'PY'
import json
import yaml

with open("/data/options.json") as f:
    options = json.load(f)
with open("groups.yaml", "w") as f:
    yaml.safe_dump({"groups": options.get("groups", [])}, f)
presets = options.get("presets", [])
for p in presets:
    t = p.get("time")
    if isinstance(t, int) and 0 <= t < 1440:
        # YAML 1.1 parses unquoted 18:00 as sexagesimal int 1080
        p["time"] = f"{t // 60:02d}:{t % 60:02d}"
with open("presets.yaml", "w") as f:
    yaml.safe_dump({"presets": presets}, f)
PY

SSL_ARGS=""
if bashio::config.true 'ssl'; then
    CERTFILE="/ssl/$(bashio::config 'certfile')"
    KEYFILE="/ssl/$(bashio::config 'keyfile')"
    if [ ! -f "${CERTFILE}" ] || [ ! -f "${KEYFILE}" ]; then
        bashio::log.fatal "ssl is enabled but ${CERTFILE} or ${KEYFILE} is missing"
        exit 1
    fi
    SSL_ARGS="--ssl-certfile ${CERTFILE} --ssl-keyfile ${KEYFILE}"
    bashio::log.info "Starting AC Dashboard on port 8088 (HTTPS)"
else
    bashio::log.info "Starting AC Dashboard on port 8088 (HTTP)"
fi

# shellcheck disable=SC2086
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8088 ${SSL_ARGS}
