import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.commands import SetCommand, apply_command
from app.config import Settings, load_groups
from app.ha_client import HAClient, HAError
from app.state import build_groups


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = Settings()
    app.state.ha_client = HAClient(settings.ha_url, settings.ha_token)
    app.state.groups = load_groups()
    yield
    await app.state.ha_client.aclose()


app = FastAPI(lifespan=lifespan)


def get_ha_client(request: Request) -> HAClient:
    return request.app.state.ha_client


def get_groups(request: Request) -> list:
    return request.app.state.groups


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


STATIC_DIR = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
