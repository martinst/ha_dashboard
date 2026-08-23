#!/usr/bin/with-contenv bashio
# Entrypoint for the Home Dashboard add-on.
# The Supervisor provides SUPERVISOR_TOKEN and proxies the Core API at
# http://supervisor/core (enabled by homeassistant_api: true in config.yaml).
set -e

export HA_URL="http://supervisor/core"
export HA_TOKEN="${SUPERVISOR_TOKEN}"
export HA_WS_URL="ws://supervisor/core/websocket"

cd /opt/ac_dashboard

export SCHEDULES_PATH=/data/schedules.json

# Outdoor/indoor temperature sensors (empty = auto-detect Ecowitt-style names).
export OUTDOOR_SENSOR="$(bashio::config 'outdoor_sensor' '')"
export INDOOR_SENSOR="$(bashio::config 'indoor_sensor' '')"

# Convert the add-on options (Configuration tab) into the yaml config files.
python3 - <<'PY'
import json
import yaml

with open("/data/options.json") as f:
    options = json.load(f)


def fix_times(presets):
    for p in presets:
        t = p.get("time")
        if isinstance(t, int) and 0 <= t < 1440:
            # YAML 1.1 parses unquoted 18:00 as sexagesimal int 1080
            p["time"] = f"{t // 60:02d}:{t % 60:02d}"
    return presets


with open("groups.yaml", "w") as f:
    yaml.safe_dump({"groups": options.get("groups", [])}, f)
with open("presets.yaml", "w") as f:
    yaml.safe_dump({"presets": fix_times(options.get("presets", []))}, f)
with open("window_groups.yaml", "w") as f:
    yaml.safe_dump({"groups": options.get("window_groups", [])}, f)
with open("window_presets.yaml", "w") as f:
    yaml.safe_dump({"presets": fix_times(options.get("window_presets", []))}, f)
with open("door_groups.yaml", "w") as f:
    yaml.safe_dump({"groups": options.get("door_groups", [])}, f)
PY

# Google sign-in for the Doors page (session key persists in /data so
# people stay signed in across restarts and updates).
export SESSION_SECRET_PATH=/data/session_secret
eval "$(python3 - <<'PYENV'
import json, shlex
o = json.load(open("/data/options.json"))
print("export GOOGLE_CLIENT_ID=" + shlex.quote(o.get("google_client_id") or ""))
print("export GOOGLE_CLIENT_SECRET=" + shlex.quote(o.get("google_client_secret") or ""))
print("export ALLOWED_EMAILS=" + shlex.quote(",".join(o.get("allowed_emails") or [])))
PYENV
)"

SSL_ARGS=""
if bashio::config.true 'ssl'; then
    CERTFILE="/ssl/$(bashio::config 'certfile')"
    KEYFILE="/ssl/$(bashio::config 'keyfile')"
    if [ ! -f "${CERTFILE}" ] || [ ! -f "${KEYFILE}" ]; then
        bashio::log.fatal "ssl is enabled but ${CERTFILE} or ${KEYFILE} is missing"
        exit 1
    fi
    SSL_ARGS="--ssl-certfile ${CERTFILE} --ssl-keyfile ${KEYFILE}"
    bashio::log.info "Starting Home Dashboard on port 8088 (HTTPS)"
else
    bashio::log.info "Starting Home Dashboard on port 8088 (HTTP)"
fi

# shellcheck disable=SC2086
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8088 ${SSL_ARGS}
