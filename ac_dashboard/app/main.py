import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.commands import SetCommand, apply_command
from app.config import Settings, load_groups, load_presets
from app.ha_client import HAClient, HAError
from app.scheduler import Scheduler, fetch_timezone
from app.state import build_groups


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    app.state.ha_client = HAClient(settings.ha_url, settings.ha_token)
    app.state.groups = load_groups()
    tz = await fetch_timezone(app.state.ha_client)
    app.state.scheduler = Scheduler(
        load_presets(), app.state.ha_client, settings.schedules_path, tz
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


def get_scheduler(request: Request) -> Scheduler:
    return request.app.state.scheduler


@app.exception_handler(HAError)
async def ha_error_handler(request: Request, exc: HAError) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": str(exc)})


@app.post("/api/units/{entity_id}/set")
async def set_unit(
    entity_id: str,
    cmd: SetCommand,
    ha: HAClient = Depends(get_ha_client),
):
    await apply_command(ha, entity_id, cmd)
    return {"ok": True}


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
    results = await asyncio.gather(
        *(apply_command(ha, entity_id, cmd) for entity_id in group.entities),
        return_exceptions=True,
    )
    failed = [
        entity_id
        for entity_id, result in zip(group.entities, results)
        if isinstance(result, Exception)
    ]
    return {
        "total": len(group.entities),
        "succeeded": len(group.entities) - len(failed),
        "failed": failed,
    }


@app.get("/api/state")
async def get_state(
    ha: HAClient = Depends(get_ha_client),
    groups: list = Depends(get_groups),
):
    states = await ha.get_climate_states()
    return {"groups": build_groups(states, groups)}


class ArmRequest(BaseModel):
    date: str
    time: str


def serialize_schedule(scheduler: Scheduler) -> dict:
    return {
        "presets": [
            {
                "id": p.id,
                "name": p.name,
                "entities": p.entities,
                "mode": p.mode,
                "temperature": p.temperature,
                "time": p.time,
                "armed": (
                    scheduler.armed[p.id].to_json()
                    if p.id in scheduler.armed
                    else None
                ),
            }
            for p in scheduler.presets.values()
        ]
    }


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


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
