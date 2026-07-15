import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel, model_validator
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.commands import CommandError, CoverCommand, SetCommand, apply_command
from app.config import Settings, load_cover_presets, load_groups, load_presets
from app.ha_client import HAClient, HAError
from app.scheduler import Scheduler, fetch_timezone
from app.state import build_cover_groups, build_groups


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    app.state.ha_client = HAClient(settings.ha_url, settings.ha_token)
    app.state.groups = load_groups()
    app.state.cover_groups = load_groups("window_groups.yaml")
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


app = FastAPI(lifespan=lifespan)


def get_ha_client(request: Request) -> HAClient:
    return request.app.state.ha_client


def get_groups(request: Request) -> list:
    return request.app.state.groups


def get_cover_groups(request: Request) -> list:
    return request.app.state.cover_groups


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
):
    states = await ha.get_states()
    climate = [s for s in states if s["entity_id"].startswith("climate.")]
    covers = [s for s in states if s["entity_id"].startswith("cover.")]
    return {
        "groups": build_groups(climate, groups),
        "cover_groups": build_cover_groups(covers, cover_groups),
    }


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


class NoCacheStaticFiles(StaticFiles):
    """Static files with forced revalidation.

    Phone browsers cache assets aggressively; without no-cache a release can
    pair fresh HTML with stale scripts. no-cache still allows ETag 304s.
    """

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/", NoCacheStaticFiles(directory=STATIC_DIR, html=True), name="static")
