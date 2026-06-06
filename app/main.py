from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

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


@app.get("/api/state")
async def get_state(
    ha: HAClient = Depends(get_ha_client),
    groups: list = Depends(get_groups),
):
    states = await ha.get_climate_states()
    return {"groups": build_groups(states, groups)}
