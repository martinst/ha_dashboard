import asyncio
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from pydantic import BaseModel, model_validator
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles

from app.auth import (
    SESSION_COOKIE,
    STATE_COOKIE,
    STATE_MAX_AGE,
    Auth,
    SessionSigner,
    load_or_create_secret,
    safe_next_path,
)
from app.commands import (
    CommandError,
    CoverCommand,
    LockCommand,
    SetCommand,
    apply_command,
)
from app.config import (
    SensorConfig,
    Settings,
    load_cover_presets,
    load_groups,
    load_presets,
)
from app.doors import OPEN_PAYLOAD, DoorTopics
from app.ha_client import HAClient, HAError
from app.history import RANGES, build_history
from app.scheduler import Scheduler, fetch_timezone
from app.state import (
    build_cover_groups,
    build_groups,
    build_lock_groups,
    build_temperatures,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    app.state.ha_client = HAClient(
        settings.ha_url, settings.ha_token, ws_url=settings.ha_ws_url or None
    )
    app.state.history_cache = {}
    app.state.groups = load_groups()
    app.state.cover_groups = load_groups("window_groups.yaml")
    app.state.door_groups = load_groups("door_groups.yaml")
    app.state.door_topics = DoorTopics()
    app.state.sensor_config = settings.sensor_config()
    app.state.auth = None
    if settings.google_client_id:
        app.state.auth = Auth(
            settings.google_client_id,
            settings.google_client_secret,
            settings.allowed_emails.split(","),
            SessionSigner(load_or_create_secret(settings.session_secret_path)),
            session_days=settings.session_days,
        )
    tz = await fetch_timezone(app.state.ha_client)
    app.state.scheduler = Scheduler(
        load_presets() + load_cover_presets(),
        app.state.ha_client,
        settings.schedules_path,
        tz,
    )
    app.state.scheduler.start()
    yield
    await app.state.scheduler.stop()
    await app.state.ha_client.aclose()
    if app.state.auth:
        await app.state.auth.aclose()


app = FastAPI(lifespan=lifespan)
STATIC_DIR = Path(__file__).parent / "static"


def get_ha_client(request: Request) -> HAClient:
    return request.app.state.ha_client


def get_groups(request: Request) -> list:
    return request.app.state.groups


def get_cover_groups(request: Request) -> list:
    return request.app.state.cover_groups


def get_door_groups(request: Request) -> list:
    return request.app.state.door_groups


def get_door_topics(request: Request) -> DoorTopics:
    return request.app.state.door_topics


def get_auth(request: Request) -> Auth | None:
    return request.app.state.auth


def current_user(request: Request, auth: Auth | None = Depends(get_auth)) -> str | None:
    if auth is None:
        return None
    return auth.session_email(request.cookies.get(SESSION_COOKIE))


def require_user(user: str | None = Depends(current_user)) -> str:
    if user is None:
        raise HTTPException(status_code=401, detail="Sign in required")
    return user


def get_sensor_config(request: Request) -> SensorConfig:
    return request.app.state.sensor_config


def get_history_cache(request: Request) -> dict:
    return request.app.state.history_cache


def get_scheduler(request: Request) -> Scheduler:
    return request.app.state.scheduler


@app.exception_handler(HAError)
async def ha_error_handler(request: Request, exc: HAError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.exception_handler(CommandError)
async def command_error_handler(request: Request, exc: CommandError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.post("/api/units/{entity_id}/set")
async def set_unit(
    entity_id: str,
    cmd: SetCommand,
    ha: HAClient = Depends(get_ha_client),
):
    await apply_command(ha, entity_id, cmd)
    return {"ok": True}


async def _fan_out(ha: HAClient, entities: list[str], cmd) -> dict:
    results = await asyncio.gather(
        *(apply_command(ha, entity_id, cmd) for entity_id in entities),
        return_exceptions=True,
    )
    failed = [
        entity_id
        for entity_id, result in zip(entities, results)
        if isinstance(result, Exception)
    ]
    return {
        "total": len(entities),
        "succeeded": len(entities) - len(failed),
        "failed": failed,
    }


@app.post("/api/groups/{name}/set")
async def set_group(
    name: str,
    cmd: SetCommand,
    ha: HAClient = Depends(get_ha_client),
    groups: list = Depends(get_groups),
):
    group = next((g for g in groups if g.name == name), None)
    if group is None:
        raise HTTPException(status_code=404, detail=f"Unknown group: {name}")
    return await _fan_out(ha, group.entities, cmd)


@app.post("/api/covers/{entity_id}/set")
async def set_cover(
    entity_id: str,
    cmd: CoverCommand,
    ha: HAClient = Depends(get_ha_client),
):
    await apply_command(ha, entity_id, cmd)
    return {"ok": True}


@app.post("/api/cover-groups/{name}/set")
async def set_cover_group(
    name: str,
    cmd: CoverCommand,
    ha: HAClient = Depends(get_ha_client),
    groups: list = Depends(get_cover_groups),
):
    group = next((g for g in groups if g.name == name), None)
    if group is None:
        raise HTTPException(status_code=404, detail=f"Unknown group: {name}")
    return await _fan_out(ha, group.entities, cmd)


@app.get("/api/state")
async def get_state(
    ha: HAClient = Depends(get_ha_client),
    groups: list = Depends(get_groups),
    cover_groups: list = Depends(get_cover_groups),
    sensors: SensorConfig = Depends(get_sensor_config),
):
    states = await ha.get_states()
    climate = [s for s in states if s["entity_id"].startswith("climate.")]
    covers = [s for s in states if s["entity_id"].startswith("cover.")]
    sensor_states = [s for s in states if s["entity_id"].startswith("sensor.")]
    return {
        "groups": build_groups(climate, groups),
        "cover_groups": build_cover_groups(covers, cover_groups),
        "temperatures": build_temperatures(
            sensor_states, sensors.outdoor, sensors.indoor
        ),
    }


HISTORY_CACHE_SECONDS = 60


@app.get("/api/temperatures/{slot}/history")
async def get_temperature_history(
    slot: str,
    range: Literal["24h", "7d", "30d"] = Query("24h"),
    ha: HAClient = Depends(get_ha_client),
    sensors: SensorConfig = Depends(get_sensor_config),
    cache: dict = Depends(get_history_cache),
):
    if slot not in ("outdoor", "indoor"):
        raise HTTPException(status_code=404, detail=f"Unknown slot: {slot}")
    cached = cache.get((slot, range))
    if cached and cached[0] > time.monotonic():
        return cached[1]

    states = await ha.get_states()
    sensor_states = [s for s in states if s["entity_id"].startswith("sensor.")]
    sensor = build_temperatures(sensor_states, sensors.outdoor, sensors.indoor)[slot]
    if sensor is None:
        raise HTTPException(status_code=404, detail=f"No {slot} temperature sensor")

    lookback, period = RANGES[range]
    start = datetime.now(timezone.utc) - lookback
    rows = await ha.get_statistics([sensor["entity_id"]], start, period)
    body = build_history(range, sensor["unit"], rows.get(sensor["entity_id"], []))
    body["entity_id"] = sensor["entity_id"]
    body["name"] = sensor["name"]
    cache[(slot, range)] = (time.monotonic() + HISTORY_CACHE_SECONDS, body)
    return body


class ArmRequest(BaseModel):
    date: str | None = None
    time: str
    repeat: list[int] | None = None

    @model_validator(mode="after")
    def exactly_one_mode(self):
        if (self.date is None) == (self.repeat is None):
            raise ValueError("provide exactly one of date or repeat")
        return self


def serialize_schedule(scheduler: Scheduler) -> dict:
    presets = []
    for p in scheduler.presets.values():
        entry = {
            "id": p.id,
            "name": p.name,
            "entities": p.entities,
            "domain": p.domain,
            "time": p.time,
            "armed": (
                scheduler.armed[p.id].to_json() if p.id in scheduler.armed else None
            ),
        }
        if p.domain == "climate":
            entry["mode"] = p.mode
            entry["temperature"] = p.temperature
        else:
            entry["action"] = p.action
            entry["position"] = p.position
        presets.append(entry)
    return {"presets": presets}


@app.get("/api/schedule")
async def get_schedule(scheduler: Scheduler = Depends(get_scheduler)):
    return serialize_schedule(scheduler)


@app.post("/api/schedule/{preset_id}/arm")
async def arm_preset(
    preset_id: str,
    req: ArmRequest,
    scheduler: Scheduler = Depends(get_scheduler),
):
    try:
        if req.repeat is not None:
            arm = scheduler.arm_weekly(preset_id, req.repeat, req.time)
        else:
            arm = scheduler.arm(preset_id, req.date, req.time)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown preset: {preset_id}")
    except ValueError as exc:  # ArmError or unparsable date/time
        raise HTTPException(status_code=400, detail=str(exc))
    return arm.to_json()


@app.post("/api/schedule/{preset_id}/cancel")
async def cancel_preset(
    preset_id: str, scheduler: Scheduler = Depends(get_scheduler)
):
    try:
        scheduler.cancel(preset_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown preset: {preset_id}")
    return {"ok": True}


# ---- Google sign-in -------------------------------------------------------

NOT_CONFIGURED_HTML = """<!doctype html><meta charset="utf-8">
<title>Doors — not configured</title>
<body style="font-family:-apple-system,sans-serif;padding:24px;max-width:560px">
<h2>Doors page is not configured</h2>
<p>Set <code>google_client_id</code>, <code>google_client_secret</code> and
<code>allowed_emails</code> in the add-on configuration and restart.</p>
<p><a href="/">Back</a></p></body>"""


def _secure(request: Request) -> bool:
    return request.url.scheme == "https"


def _callback_uri(request: Request) -> str:
    return str(request.url_for("auth_callback"))


@app.get("/auth/login")
async def auth_login(request: Request, next: str | None = None,
                     auth: Auth | None = Depends(get_auth)):
    if auth is None:
        return HTMLResponse(NOT_CONFIGURED_HTML, status_code=503)
    state = auth.new_state()
    resp = RedirectResponse(auth.auth_url(_callback_uri(request), state), status_code=302)
    resp.set_cookie(
        STATE_COOKIE, auth.state_token(state, safe_next_path(next)),
        max_age=STATE_MAX_AGE, httponly=True, samesite="lax", secure=_secure(request),
    )
    return resp


@app.get("/auth/callback", name="auth_callback")
async def auth_callback(request: Request, code: str | None = None,
                        state: str | None = None, error: str | None = None,
                        auth: Auth | None = Depends(get_auth)):
    if auth is None:
        return HTMLResponse(NOT_CONFIGURED_HTML, status_code=503)
    if error:
        raise HTTPException(status_code=400, detail=f"Google sign-in error: {error}")
    expected = auth.signer.verify(request.cookies.get(STATE_COOKIE))
    if not code or not state or not expected or expected.get("state") != state:
        raise HTTPException(status_code=400, detail="Sign-in state mismatch; try again")
    try:
        email = await auth.fetch_email(code, _callback_uri(request))
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    if not auth.is_allowed(email):
        body = f"""<!doctype html><meta charset="utf-8"><title>Not allowed</title>
<body style="font-family:-apple-system,sans-serif;padding:24px;max-width:560px">
<h2>Not allowed</h2><p><b>{email}</b> is not on the list of allowed accounts.</p>
<p><a href="/auth/login?next={expected.get('next', '/')}">Try another account</a>
 · <a href="/">Back</a></p></body>"""
        resp = HTMLResponse(body, status_code=403)
        resp.delete_cookie(STATE_COOKIE)
        return resp
    resp = RedirectResponse(safe_next_path(expected.get("next")), status_code=302)
    resp.set_cookie(
        SESSION_COOKIE, auth.session_token(email),
        max_age=auth.session_max_age, httponly=True, samesite="lax",
        secure=_secure(request),
    )
    resp.delete_cookie(STATE_COOKIE)
    return resp


@app.get("/auth/logout")
async def auth_logout():
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie(SESSION_COOKIE)
    return resp


@app.get("/auth/me")
async def auth_me(user: str = Depends(require_user)):
    return {"email": user}


@app.get("/doors.html")
async def doors_page(request: Request, auth: Auth | None = Depends(get_auth),
                     user: str | None = Depends(current_user)):
    if auth is None:
        return HTMLResponse(NOT_CONFIGURED_HTML, status_code=503)
    if user is None:
        return RedirectResponse("/auth/login?next=%2Fdoors.html", status_code=302)
    return FileResponse(STATIC_DIR / "doors.html", headers={"Cache-Control": "no-cache"})


# ---- Doors (locks) — every endpoint needs a signed-in user ----------------

@app.get("/api/doors")
async def get_doors(
    user: str = Depends(require_user),
    ha: HAClient = Depends(get_ha_client),
    groups: list = Depends(get_door_groups),
    topics: DoorTopics = Depends(get_door_topics),
):
    states = await ha.get_states()
    locks = [s for s in states if s["entity_id"].startswith("lock.")]
    openable = await topics.names(ha)
    result = build_lock_groups(locks, groups)
    for group in result:
        for unit in group["units"]:
            unit["supports_open"] = unit["name"] in openable
    return {"user": user, "groups": result}


@app.post("/api/doors/{entity_id}/set")
async def set_door(
    entity_id: str,
    cmd: LockCommand,
    user: str = Depends(require_user),
    ha: HAClient = Depends(get_ha_client),
    topics: DoorTopics = Depends(get_door_topics),
):
    if cmd.action != "open":
        await apply_command(ha, entity_id, cmd)
        return {"ok": True}
    if not entity_id.startswith("lock."):
        raise HTTPException(status_code=400, detail=f"{entity_id} is not a lock")
    state = next((s for s in await ha.get_states() if s["entity_id"] == entity_id), None)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Unknown door: {entity_id}")
    name = state.get("attributes", {}).get("friendly_name", entity_id)
    topic = await topics.command_topic(ha, name)
    if topic is None:
        raise HTTPException(status_code=409, detail="Open is not available for this door")
    await ha.mqtt_publish(topic, OPEN_PAYLOAD)
    return {"ok": True}


@app.post("/api/door-groups/{name}/set")
async def set_door_group(
    name: str,
    cmd: LockCommand,
    user: str = Depends(require_user),
    ha: HAClient = Depends(get_ha_client),
    groups: list = Depends(get_door_groups),
):
    if cmd.action != "lock":
        raise HTTPException(status_code=400, detail="Door groups can only be locked")
    group = next((g for g in groups if g.name == name), None)
    if group is None:
        raise HTTPException(status_code=404, detail=f"Unknown group: {name}")
    return await _fan_out(ha, group.entities, cmd)


class NoCacheStaticFiles(StaticFiles):
    """Static files with forced revalidation.

    Phone browsers cache assets aggressively; without no-cache a release can
    pair fresh HTML with stale scripts. no-cache still allows ETag 304s.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", NoCacheStaticFiles(directory=STATIC_DIR, html=True), name="static")
