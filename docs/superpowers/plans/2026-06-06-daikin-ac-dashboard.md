# Daikin AC Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A FastAPI app on the Pi serving a single plain-JS page that controls Daikin AC units (mode, temperature) via Home Assistant's REST API, with custom groups and group controls.

**Architecture:** The backend holds a long-lived HA token and proxies everything: `GET /api/state` merges auto-discovered `climate.*` entities with `groups.yaml`; POST endpoints map to HA `climate.*` service calls; group commands fan out in parallel. The page polls every 5 s with optimistic updates. Spec: `docs/superpowers/specs/2026-06-06-daikin-ac-dashboard-design.md`.

**Tech Stack:** Python 3.11+, FastAPI, httpx, PyYAML, pydantic-settings, uvicorn; pytest + pytest-asyncio (httpx `MockTransport` for the HA client, dependency overrides + `TestClient` for endpoints); vanilla JS/CSS frontend.

---

## File structure

| File | Responsibility |
|---|---|
| `app/config.py` | `Settings` (HA_URL/HA_TOKEN from `.env`) and `load_groups()` from `groups.yaml` |
| `app/ha_client.py` | `HAClient` — async HA REST calls; raises `HAError` on any failure |
| `app/state.py` | Pure functions: HA states + groups → the `/api/state` response shape |
| `app/main.py` | FastAPI app, dependencies, endpoints, `HAError`→502 handler, static mount |
| `app/static/{index.html,app.js,style.css}` | The frontend |
| `tests/conftest.py` | `FakeHAClient`, `ha_state()` sample builder, app client fixture |
| `tests/test_{config,ha_client,state,api}.py` | One test module per unit |

---

### Task 1: Project scaffolding

**Files:**
- Create: `requirements.txt`, `pyproject.toml`, `app/__init__.py`, `tests/__init__.py`

- [ ] **Step 1: Create `requirements.txt`**

```
fastapi>=0.115
uvicorn[standard]>=0.32
httpx>=0.27
pyyaml>=6.0
pydantic-settings>=2.6
pytest>=8.3
pytest-asyncio>=0.24
```

- [ ] **Step 2: Create `pyproject.toml`** (pytest config only — async tests run without per-test markers)

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

- [ ] **Step 3: Create empty packages**

Create `app/__init__.py` and `tests/__init__.py`, both empty.

- [ ] **Step 4: Create venv and install**

Run: `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`
Expected: installs without errors. Check `python3 --version` is ≥ 3.11 first.

- [ ] **Step 5: Verify pytest runs**

Run: `.venv/bin/pytest`
Expected: `no tests ran` (exit code 5 is fine).

- [ ] **Step 6: Commit**

```bash
git add requirements.txt pyproject.toml app/__init__.py tests/__init__.py
git commit -m "chore: scaffold project"
```

---

### Task 2: Config loading

**Files:**
- Create: `app/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_config.py
from app.config import Settings, load_groups


def test_load_groups_parses_yaml(tmp_path):
    f = tmp_path / "groups.yaml"
    f.write_text(
        "groups:\n"
        "  - name: Upstairs\n"
        "    entities: [climate.bedroom, climate.office]\n"
        "  - name: Downstairs\n"
        "    entities: [climate.living_room]\n"
    )
    groups = load_groups(f)
    assert [g.name for g in groups] == ["Upstairs", "Downstairs"]
    assert groups[0].entities == ["climate.bedroom", "climate.office"]


def test_load_groups_missing_file_returns_empty(tmp_path):
    assert load_groups(tmp_path / "nope.yaml") == []


def test_load_groups_empty_file_returns_empty(tmp_path):
    f = tmp_path / "groups.yaml"
    f.write_text("")
    assert load_groups(f) == []


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.ha_url == "http://localhost:8123"
    assert s.ha_token == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.config'`

- [ ] **Step 3: Implement `app/config.py`**

```python
from pathlib import Path

import yaml
from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class Group(BaseModel):
    name: str
    entities: list[str]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ha_url: str = "http://localhost:8123"
    ha_token: str = ""


def load_groups(path: str | Path = "groups.yaml") -> list[Group]:
    path = Path(path)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    return [Group(**g) for g in data.get("groups", [])]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: config loading (.env settings + groups.yaml)"
```

---

### Task 3: HA client

**Files:**
- Create: `app/ha_client.py`
- Test: `tests/test_ha_client.py`

- [ ] **Step 1: Write the failing tests**

`httpx.MockTransport` lets us assert exactly what hits the wire — no network, no mock library.

```python
# tests/test_ha_client.py
import json

import httpx
import pytest

from app.ha_client import HAClient, HAError

STATES = [
    {"entity_id": "climate.bedroom", "state": "cool", "attributes": {}},
    {"entity_id": "light.kitchen", "state": "on", "attributes": {}},
]


def make_ha_client(handler):
    return HAClient("http://ha.test", "secret-token", transport=httpx.MockTransport(handler))


async def test_get_climate_states_filters_and_authenticates():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["Authorization"]
        seen["path"] = request.url.path
        return httpx.Response(200, json=STATES)

    client = make_ha_client(handler)
    states = await client.get_climate_states()
    assert seen == {"auth": "Bearer secret-token", "path": "/api/states"}
    assert [s["entity_id"] for s in states] == ["climate.bedroom"]


async def test_set_hvac_mode_posts_service_call():
    calls = []

    def handler(request):
        calls.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json=[])

    await make_ha_client(handler).set_hvac_mode("climate.bedroom", "cool")
    assert calls == [
        ("/api/services/climate/set_hvac_mode",
         {"entity_id": "climate.bedroom", "hvac_mode": "cool"})
    ]


async def test_set_temperature_posts_service_call():
    calls = []

    def handler(request):
        calls.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json=[])

    await make_ha_client(handler).set_temperature("climate.bedroom", 21.5)
    assert calls == [
        ("/api/services/climate/set_temperature",
         {"entity_id": "climate.bedroom", "temperature": 21.5})
    ]


async def test_turn_on_posts_service_call():
    calls = []

    def handler(request):
        calls.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json=[])

    await make_ha_client(handler).turn_on("climate.bedroom")
    assert calls == [
        ("/api/services/climate/turn_on", {"entity_id": "climate.bedroom"})
    ]


async def test_http_error_status_raises_haerror():
    def handler(request):
        return httpx.Response(500)

    with pytest.raises(HAError):
        await make_ha_client(handler).get_climate_states()


async def test_connection_error_raises_haerror():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(HAError):
        await make_ha_client(handler).get_climate_states()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_ha_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.ha_client'`

- [ ] **Step 3: Implement `app/ha_client.py`**

```python
import httpx


class HAError(Exception):
    """Raised when Home Assistant can't be reached or returns an error."""


class HAClient:
    """Thin async client for Home Assistant's REST API."""

    def __init__(
        self,
        base_url: str,
        token: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_climate_states(self) -> list[dict]:
        data = await self._request("GET", "/api/states")
        return [s for s in data if s["entity_id"].startswith("climate.")]

    async def set_hvac_mode(self, entity_id: str, mode: str) -> None:
        await self._request(
            "POST",
            "/api/services/climate/set_hvac_mode",
            json={"entity_id": entity_id, "hvac_mode": mode},
        )

    async def set_temperature(self, entity_id: str, temperature: float) -> None:
        await self._request(
            "POST",
            "/api/services/climate/set_temperature",
            json={"entity_id": entity_id, "temperature": temperature},
        )

    async def turn_on(self, entity_id: str) -> None:
        """climate.turn_on restores the unit's previous HVAC mode."""
        await self._request(
            "POST",
            "/api/services/climate/turn_on",
            json={"entity_id": entity_id},
        )

    async def _request(self, method: str, path: str, json: dict | None = None):
        try:
            resp = await self._client.request(method, path, json=json)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise HAError(f"Home Assistant request failed: {exc}") from exc
        return resp.json()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_ha_client.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add app/ha_client.py tests/test_ha_client.py
git commit -m "feat: async HA REST client with HAError wrapping"
```

---

### Task 4: State building

**Files:**
- Create: `app/state.py`
- Modify: `tests/conftest.py` (create it — `ha_state()` helper used here and in Task 5)
- Test: `tests/test_state.py`

- [ ] **Step 1: Create `tests/conftest.py` with the sample-state builder**

```python
# tests/conftest.py
def ha_state(entity_id, state="cool", **attrs):
    """Build an HA climate state dict like GET /api/states returns."""
    base = {
        "friendly_name": entity_id.split(".")[1].replace("_", " ").title(),
        "current_temperature": 24.0,
        "temperature": 22.0,
        "hvac_modes": ["off", "cool", "heat", "dry", "fan_only", "auto"],
        "min_temp": 16,
        "max_temp": 30,
    }
    base.update(attrs)
    return {"entity_id": entity_id, "state": state, "attributes": base}
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_state.py
from app.config import Group
from app.state import build_groups

from tests.conftest import ha_state


def test_groups_units_in_configured_order():
    states = [ha_state("climate.office"), ha_state("climate.bedroom")]
    groups = [Group(name="Upstairs", entities=["climate.bedroom", "climate.office"])]
    result = build_groups(states, groups)
    assert len(result) == 1
    assert result[0]["name"] == "Upstairs"
    assert [u["entity_id"] for u in result[0]["units"]] == [
        "climate.bedroom", "climate.office"
    ]


def test_unit_fields_mapped_from_ha_state():
    states = [ha_state("climate.bedroom", state="heat", current_temperature=19.5,
                       temperature=23.0)]
    result = build_groups(states, [Group(name="G", entities=["climate.bedroom"])])
    unit = result[0]["units"][0]
    assert unit == {
        "entity_id": "climate.bedroom",
        "name": "Bedroom",
        "current_temp": 19.5,
        "target_temp": 23.0,
        "mode": "heat",
        "available_modes": ["off", "cool", "heat", "dry", "fan_only", "auto"],
        "min_temp": 16,
        "max_temp": 30,
        "available": True,
    }


def test_unavailable_state_maps_to_unavailable_unit():
    states = [ha_state("climate.bedroom", state="unavailable")]
    result = build_groups(states, [Group(name="G", entities=["climate.bedroom"])])
    assert result[0]["units"][0]["available"] is False


def test_configured_entity_missing_from_ha_shows_as_unavailable():
    result = build_groups([], [Group(name="G", entities=["climate.gone"])])
    unit = result[0]["units"][0]
    assert unit["entity_id"] == "climate.gone"
    assert unit["available"] is False
    assert unit["name"] == "Gone"


def test_unlisted_entities_land_in_ungrouped_sorted_by_name():
    states = [ha_state("climate.zeta"), ha_state("climate.alpha"),
              ha_state("climate.bedroom")]
    groups = [Group(name="G", entities=["climate.bedroom"])]
    result = build_groups(states, groups)
    assert [g["name"] for g in result] == ["G", "Ungrouped"]
    assert [u["name"] for u in result[1]["units"]] == ["Alpha", "Zeta"]


def test_no_ungrouped_section_when_everything_grouped():
    states = [ha_state("climate.bedroom")]
    groups = [Group(name="G", entities=["climate.bedroom"])]
    assert [g["name"] for g in build_groups(states, groups)] == ["G"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.state'`

- [ ] **Step 4: Implement `app/state.py`**

```python
from app.config import Group

UNGROUPED = "Ungrouped"


def unit_from_ha_state(state: dict) -> dict:
    attrs = state.get("attributes", {})
    return {
        "entity_id": state["entity_id"],
        "name": attrs.get("friendly_name", state["entity_id"]),
        "current_temp": attrs.get("current_temperature"),
        "target_temp": attrs.get("temperature"),
        "mode": state.get("state"),
        "available_modes": attrs.get("hvac_modes", []),
        "min_temp": attrs.get("min_temp"),
        "max_temp": attrs.get("max_temp"),
        "available": state.get("state") not in ("unavailable", "unknown"),
    }


def missing_unit(entity_id: str) -> dict:
    """Placeholder for a groups.yaml entity that HA doesn't know about."""
    return {
        "entity_id": entity_id,
        "name": entity_id.removeprefix("climate.").replace("_", " ").title(),
        "current_temp": None,
        "target_temp": None,
        "mode": None,
        "available_modes": [],
        "min_temp": None,
        "max_temp": None,
        "available": False,
    }


def build_groups(climate_states: list[dict], groups: list[Group]) -> list[dict]:
    by_id = {s["entity_id"]: s for s in climate_states}
    grouped_ids: set[str] = set()
    result = []
    for group in groups:
        units = []
        for entity_id in group.entities:
            grouped_ids.add(entity_id)
            state = by_id.get(entity_id)
            units.append(unit_from_ha_state(state) if state else missing_unit(entity_id))
        result.append({"name": group.name, "units": units})

    ungrouped = sorted(
        (unit_from_ha_state(s) for eid, s in by_id.items() if eid not in grouped_ids),
        key=lambda u: u["name"],
    )
    if ungrouped:
        result.append({"name": UNGROUPED, "units": ungrouped})
    return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_state.py -v`
Expected: 6 PASS

- [ ] **Step 6: Commit**

```bash
git add app/state.py tests/test_state.py tests/conftest.py
git commit -m "feat: merge discovered climate entities with configured groups"
```

---

### Task 5: API — GET /api/state (+ HAError → 502)

**Files:**
- Create: `app/main.py`
- Modify: `tests/conftest.py` (add `FakeHAClient` + app client fixture)
- Test: `tests/test_api.py`

- [ ] **Step 1: Add `FakeHAClient` and fixture to `tests/conftest.py`**

Append below `ha_state`:

```python
import pytest
from fastapi.testclient import TestClient

from app.ha_client import HAError


class FakeHAClient:
    """In-memory stand-in for HAClient; records service calls."""

    def __init__(self, states=None, fail_entities=(), fail_states=False):
        self.states = states or []
        self.fail_entities = set(fail_entities)
        self.fail_states = fail_states
        self.calls = []

    async def get_climate_states(self):
        if self.fail_states:
            raise HAError("HA unreachable")
        return self.states

    async def set_hvac_mode(self, entity_id, mode):
        self._record(("set_hvac_mode", entity_id, mode), entity_id)

    async def set_temperature(self, entity_id, temperature):
        self._record(("set_temperature", entity_id, temperature), entity_id)

    async def turn_on(self, entity_id):
        self._record(("turn_on", entity_id), entity_id)

    def _record(self, call, entity_id):
        if entity_id in self.fail_entities:
            raise HAError("HA unreachable")
        self.calls.append(call)


@pytest.fixture
def make_client():
    """Returns a factory: make_client(fake_ha, groups) -> TestClient."""
    from app.main import app, get_groups, get_ha_client

    def _make(fake_ha, groups=()):
        app.dependency_overrides[get_ha_client] = lambda: fake_ha
        app.dependency_overrides[get_groups] = lambda: list(groups)
        return TestClient(app)

    yield _make
    from app.main import app as _app
    _app.dependency_overrides.clear()
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_api.py
from app.config import Group

from tests.conftest import FakeHAClient, ha_state


def test_get_state_returns_groups(make_client):
    fake = FakeHAClient(states=[ha_state("climate.bedroom")])
    client = make_client(fake, [Group(name="Upstairs", entities=["climate.bedroom"])])
    resp = client.get("/api/state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["groups"][0]["name"] == "Upstairs"
    assert body["groups"][0]["units"][0]["entity_id"] == "climate.bedroom"


def test_get_state_returns_502_when_ha_unreachable(make_client):
    client = make_client(FakeHAClient(fail_states=True))
    resp = client.get("/api/state")
    assert resp.status_code == 502
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.main'`

- [ ] **Step 4: Implement `app/main.py`**

```python
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_api.py -v`
Expected: 2 PASS

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_api.py tests/conftest.py
git commit -m "feat: GET /api/state endpoint with 502 on HA failure"
```

---

### Task 6: API — POST /api/units/{entity_id}/set

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_api.py` (append)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_api.py`)

```python
def test_set_unit_mode_calls_set_hvac_mode(make_client):
    fake = FakeHAClient()
    client = make_client(fake)
    resp = client.post("/api/units/climate.bedroom/set", json={"mode": "cool"})
    assert resp.status_code == 200
    assert fake.calls == [("set_hvac_mode", "climate.bedroom", "cool")]


def test_set_unit_mode_on_calls_turn_on(make_client):
    fake = FakeHAClient()
    client = make_client(fake)
    client.post("/api/units/climate.bedroom/set", json={"mode": "on"})
    assert fake.calls == [("turn_on", "climate.bedroom")]


def test_set_unit_temperature(make_client):
    fake = FakeHAClient()
    client = make_client(fake)
    client.post("/api/units/climate.bedroom/set", json={"temperature": 21.5})
    assert fake.calls == [("set_temperature", "climate.bedroom", 21.5)]


def test_set_unit_mode_and_temperature_together(make_client):
    fake = FakeHAClient()
    client = make_client(fake)
    client.post("/api/units/climate.bedroom/set",
                json={"mode": "heat", "temperature": 23.0})
    assert fake.calls == [
        ("set_hvac_mode", "climate.bedroom", "heat"),
        ("set_temperature", "climate.bedroom", 23.0),
    ]


def test_set_unit_empty_body_is_422(make_client):
    client = make_client(FakeHAClient())
    resp = client.post("/api/units/climate.bedroom/set", json={})
    assert resp.status_code == 422


def test_set_unit_returns_502_when_ha_unreachable(make_client):
    client = make_client(FakeHAClient(fail_entities=["climate.bedroom"]))
    resp = client.post("/api/units/climate.bedroom/set", json={"mode": "cool"})
    assert resp.status_code == 502
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_api.py -v`
Expected: the 6 new tests FAIL with 404 (route doesn't exist); the 2 earlier tests still PASS.

- [ ] **Step 3: Implement in `app/main.py`**

Add imports at the top:

```python
from pydantic import BaseModel, model_validator
```

Add below `ha_error_handler`:

```python
class SetCommand(BaseModel):
    mode: str | None = None
    temperature: float | None = None

    @model_validator(mode="after")
    def at_least_one_field(self):
        if self.mode is None and self.temperature is None:
            raise ValueError("provide mode and/or temperature")
        return self


async def apply_command(ha: HAClient, entity_id: str, cmd: SetCommand) -> None:
    if cmd.mode == "on":
        await ha.turn_on(entity_id)
    elif cmd.mode is not None:
        await ha.set_hvac_mode(entity_id, cmd.mode)
    if cmd.temperature is not None:
        await ha.set_temperature(entity_id, cmd.temperature)


@app.post("/api/units/{entity_id}/set")
async def set_unit(
    entity_id: str,
    cmd: SetCommand,
    ha: HAClient = Depends(get_ha_client),
):
    await apply_command(ha, entity_id, cmd)
    return {"ok": True}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_api.py -v`
Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_api.py
git commit -m "feat: POST /api/units/{entity_id}/set"
```

---

### Task 7: API — POST /api/groups/{name}/set

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_api.py` (append)

- [ ] **Step 1: Write the failing tests** (append to `tests/test_api.py`)

```python
GROUPS = [Group(name="Upstairs", entities=["climate.bedroom", "climate.office"])]


def test_set_group_fans_out_to_all_units(make_client):
    fake = FakeHAClient()
    client = make_client(fake, GROUPS)
    resp = client.post("/api/groups/Upstairs/set", json={"mode": "off"})
    assert resp.status_code == 200
    assert resp.json() == {"total": 2, "succeeded": 2, "failed": []}
    assert sorted(fake.calls) == [
        ("set_hvac_mode", "climate.bedroom", "off"),
        ("set_hvac_mode", "climate.office", "off"),
    ]


def test_set_group_reports_partial_failure(make_client):
    fake = FakeHAClient(fail_entities=["climate.office"])
    client = make_client(fake, GROUPS)
    resp = client.post("/api/groups/Upstairs/set", json={"temperature": 22.0})
    assert resp.status_code == 200
    assert resp.json() == {"total": 2, "succeeded": 1, "failed": ["climate.office"]}


def test_set_group_unknown_group_is_404(make_client):
    client = make_client(FakeHAClient(), GROUPS)
    resp = client.post("/api/groups/Basement/set", json={"mode": "off"})
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_api.py -v`
Expected: the 3 new tests FAIL with 404-related assertion errors (route doesn't exist, so even the 404 test fails on the response detail — confirm the failures are from the new tests only).

Note: the unknown-group test may accidentally "pass" before implementation (404 either way). That's fine — the other two prove the route is missing.

- [ ] **Step 3: Implement in `app/main.py`**

Add imports at the top:

```python
import asyncio

from fastapi import HTTPException
```

(Merge with the existing `fastapi` import line: `from fastapi import Depends, FastAPI, HTTPException, Request`.)

Add below `set_unit`:

```python
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
```

- [ ] **Step 4: Run the full suite**

Run: `.venv/bin/pytest -v`
Expected: all tests PASS (config 4, ha_client 6, state 6, api 11)

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_api.py
git commit -m "feat: POST /api/groups/{name}/set with partial-failure reporting"
```

---

### Task 8: Frontend

**Files:**
- Create: `app/static/index.html`, `app/static/style.css`, `app/static/app.js`
- Modify: `app/main.py` (mount static)

No JS test harness (per spec) — backend tests must still pass, plus a manual smoke check.

- [ ] **Step 1: Create `app/static/index.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AC Control</title>
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <header>
    <h1>AC Control</h1>
    <span id="status-dot" class="dot" title="Connection to Home Assistant"></span>
  </header>
  <div id="banner" class="banner hidden">Can't reach Home Assistant</div>
  <main id="groups"></main>
  <script src="/app.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create `app/static/app.js`**

```javascript
const POLL_MS = 5000;
const PENDING_MS = 4000; // ignore poll data for a unit this long after a local change
const DEBOUNCE_MS = 600; // wait for temp-stepper taps to settle before sending
const UNGROUPED = "Ungrouped";

const MODE_LABELS = {
  off: "Off",
  cool: "Cool",
  heat: "Heat",
  dry: "Dry",
  fan_only: "Fan",
  auto: "Auto",
  heat_cool: "Auto",
};

let state = { groups: [] };
const pendingUntil = {}; // entity_id -> ms timestamp
const timers = {};       // debounce timers, keyed by entity_id or "group:<name>"
const groupTemps = {};   // group name -> locally chosen group target temp

// ---- polling ----

async function poll() {
  try {
    const resp = await fetch("/api/state");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    mergeState(await resp.json());
    setConnected(true);
  } catch {
    setConnected(false);
  }
  render();
}

// Keep locally-changed units as-is until their pending window expires,
// so optimistic updates aren't reverted by an in-flight poll.
function mergeState(fresh) {
  const now = Date.now();
  const oldUnits = {};
  for (const g of state.groups) for (const u of g.units) oldUnits[u.entity_id] = u;
  for (const g of fresh.groups) {
    g.units = g.units.map((u) =>
      (pendingUntil[u.entity_id] || 0) > now && oldUnits[u.entity_id]
        ? oldUnits[u.entity_id]
        : u
    );
  }
  state = fresh;
}

function setConnected(ok) {
  document.getElementById("status-dot").classList.toggle("ok", ok);
  document.getElementById("banner").classList.toggle("hidden", ok);
}

// ---- commands ----

function markPending(entityId) {
  pendingUntil[entityId] = Date.now() + PENDING_MS;
}

async function post(url, body) {
  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    setConnected(true);
  } catch {
    setConnected(false);
  }
}

function setUnitMode(unit, mode) {
  unit.mode = mode;
  markPending(unit.entity_id);
  render();
  post(`/api/units/${unit.entity_id}/set`, { mode });
}

function stepUnitTemp(unit, delta) {
  const lo = unit.min_temp ?? 16;
  const hi = unit.max_temp ?? 30;
  unit.target_temp = clamp((unit.target_temp ?? 22) + delta, lo, hi);
  markPending(unit.entity_id);
  render();
  debounce(unit.entity_id, () =>
    post(`/api/units/${unit.entity_id}/set`, { temperature: unit.target_temp })
  );
}

function groupAllOff(group) {
  for (const u of group.units) {
    u.mode = "off";
    markPending(u.entity_id);
  }
  render();
  post(`/api/groups/${encodeURIComponent(group.name)}/set`, { mode: "off" });
}

function groupAllOn(group) {
  // climate.turn_on restores each unit's previous mode — we can't predict it,
  // so no optimistic update; the next poll (≤5 s) shows the result.
  post(`/api/groups/${encodeURIComponent(group.name)}/set`, { mode: "on" });
}

function stepGroupTemp(group, delta) {
  const current = groupTemps[group.name] ?? avgTarget(group.units) ?? 22;
  const next = clamp(current + delta, 16, 30);
  groupTemps[group.name] = next;
  for (const u of group.units) {
    u.target_temp = next;
    markPending(u.entity_id);
  }
  render();
  debounce(`group:${group.name}`, () =>
    post(`/api/groups/${encodeURIComponent(group.name)}/set`, { temperature: next })
  );
}

// ---- rendering ----

function render() {
  const main = document.getElementById("groups");
  main.replaceChildren(...state.groups.map(renderGroup));
}

function renderGroup(group) {
  const section = el("section", "group");
  const header = el("div", "group-header");
  header.append(el("h2", "", group.name));
  if (group.name !== UNGROUPED) {
    const controls = el("div", "group-controls");
    controls.append(
      btn("All Off", "ctl", () => groupAllOff(group)),
      btn("All On", "ctl", () => groupAllOn(group)),
      stepperEl(groupTemps[group.name] ?? avgTarget(group.units), (d) =>
        stepGroupTemp(group, d)
      )
    );
    header.append(controls);
  }
  section.append(header, ...group.units.map(renderUnit));
  return section;
}

function renderUnit(unit) {
  const card = el("div", "card");
  card.dataset.mode = unit.available ? unit.mode : "unavailable";
  if (!unit.available) card.classList.add("unavailable");

  const top = el("div", "card-top");
  top.append(
    el("span", "unit-name", unit.name),
    el("span", "current-temp",
       unit.current_temp != null ? `${unit.current_temp}°` : "–")
  );

  const temp = stepperEl(unit.target_temp, (d) => stepUnitTemp(unit, d),
                         !unit.available);

  const modes = el("div", "modes");
  for (const mode of unit.available_modes) {
    const b = btn(MODE_LABELS[mode] ?? mode, "mode-btn", () =>
      setUnitMode(unit, mode)
    );
    b.dataset.mode = mode;
    if (mode === unit.mode) b.classList.add("active");
    b.disabled = !unit.available;
    modes.append(b);
  }

  card.append(top, temp, modes);
  return card;
}

function stepperEl(value, onStep, disabled = false) {
  const wrap = el("div", "stepper");
  const minus = btn("−", "step", () => onStep(-0.5));
  const plus = btn("+", "step", () => onStep(0.5));
  minus.disabled = plus.disabled = disabled;
  wrap.append(minus, el("span", "target", value != null ? `${value}°` : "–"), plus);
  return wrap;
}

// ---- helpers ----

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

function btn(label, cls, onClick) {
  const b = el("button", cls, label);
  b.addEventListener("click", onClick);
  return b;
}

function clamp(value, lo, hi) {
  return Math.min(hi, Math.max(lo, Math.round(value * 2) / 2));
}

function avgTarget(units) {
  const temps = units.map((u) => u.target_temp).filter((t) => t != null);
  if (!temps.length) return null;
  return Math.round((temps.reduce((a, b) => a + b, 0) / temps.length) * 2) / 2;
}

function debounce(key, fn) {
  clearTimeout(timers[key]);
  timers[key] = setTimeout(fn, DEBOUNCE_MS);
}

poll();
setInterval(poll, POLL_MS);
```

- [ ] **Step 3: Create `app/static/style.css`**

```css
:root {
  --bg: #f2f4f7;
  --card: #ffffff;
  --text: #1c2330;
  --muted: #6b7585;
  --accent-off: #9aa3b2;
  --accent-cool: #2e86de;
  --accent-heat: #e67e22;
  --accent-dry: #16a085;
  --accent-fan: #8e44ad;
  --accent-auto: #27ae60;
}

* { box-sizing: border-box; }

body {
  margin: 0;
  font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
  background: var(--bg);
  color: var(--text);
}

header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  max-width: 640px;
  margin: 0 auto;
}

h1 { font-size: 1.2rem; margin: 0; }

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #e74c3c;
  display: inline-block;
}
.dot.ok { background: #2ecc71; }

.banner {
  background: #e74c3c;
  color: #fff;
  text-align: center;
  padding: 8px;
  font-size: 0.9rem;
}
.hidden { display: none; }

main {
  padding: 0 12px 24px;
  max-width: 640px;
  margin: 0 auto;
}

.group { margin-top: 16px; }

.group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 8px;
}
.group-header h2 {
  font-size: 1rem;
  margin: 0;
  color: var(--muted);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.group-controls {
  display: flex;
  align-items: center;
  gap: 8px;
}

button {
  font: inherit;
  border: none;
  border-radius: 8px;
  background: #e3e7ee;
  color: var(--text);
  padding: 8px 12px;
  cursor: pointer;
  touch-action: manipulation;
}
button:disabled { opacity: 0.4; cursor: default; }

.card {
  background: var(--card);
  border-radius: 14px;
  padding: 14px 16px;
  margin-top: 10px;
  border-left: 6px solid var(--accent-off);
  box-shadow: 0 1px 3px rgb(0 0 0 / 8%);
}
.card[data-mode="cool"] { border-left-color: var(--accent-cool); }
.card[data-mode="heat"] { border-left-color: var(--accent-heat); }
.card[data-mode="dry"] { border-left-color: var(--accent-dry); }
.card[data-mode="fan_only"] { border-left-color: var(--accent-fan); }
.card[data-mode="auto"],
.card[data-mode="heat_cool"] { border-left-color: var(--accent-auto); }
.card.unavailable { opacity: 0.55; }

.card-top {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.unit-name { font-weight: 600; }
.current-temp { color: var(--muted); }

.stepper {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 16px;
  margin: 10px 0;
}
.stepper .step {
  width: 44px;
  height: 44px;
  font-size: 1.3rem;
  border-radius: 50%;
}
.stepper .target {
  font-size: 1.6rem;
  font-weight: 700;
  min-width: 72px;
  text-align: center;
}

.group-controls .stepper { margin: 0; gap: 6px; }
.group-controls .step { width: 34px; height: 34px; font-size: 1rem; }
.group-controls .target { font-size: 1rem; min-width: 44px; font-weight: 600; }

.modes {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.mode-btn.active { background: var(--text); color: #fff; }
.mode-btn.active[data-mode="cool"] { background: var(--accent-cool); }
.mode-btn.active[data-mode="heat"] { background: var(--accent-heat); }
.mode-btn.active[data-mode="dry"] { background: var(--accent-dry); }
.mode-btn.active[data-mode="fan_only"] { background: var(--accent-fan); }
.mode-btn.active[data-mode="auto"],
.mode-btn.active[data-mode="heat_cool"] { background: var(--accent-auto); }
```

- [ ] **Step 4: Mount static files in `app/main.py`**

Add import at the top:

```python
from pathlib import Path

from fastapi.staticfiles import StaticFiles
```

Add at the very bottom of the file (after all routes — API routes registered first take precedence):

```python
STATIC_DIR = Path(__file__).parent / "static"
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
```

- [ ] **Step 5: Verify backend tests still pass**

Run: `.venv/bin/pytest -v`
Expected: all PASS (the static mount must not break API routes)

- [ ] **Step 6: Manual smoke check (no HA needed)**

Run: `.venv/bin/uvicorn app.main:app --port 8088`
Open `http://localhost:8088` in a browser. Expected: page loads with header and status dot; since HA isn't reachable, the red "Can't reach Home Assistant" banner appears and the dot is red. Ctrl-C the server.

- [ ] **Step 7: Commit**

```bash
git add app/static app/main.py
git commit -m "feat: mobile-first frontend with polling and optimistic updates"
```

---

### Task 9: Config examples, README, deployment

**Files:**
- Create: `groups.yaml.example`, `.env.example`, `README.md`, `deploy/ha-dashboard.service`

- [ ] **Step 1: Create `groups.yaml.example`**

```yaml
# Copy to groups.yaml and edit. Entities not listed here still appear
# under an "Ungrouped" section.
groups:
  - name: Upstairs
    entities:
      - climate.bedroom
      - climate.office
  - name: Downstairs
    entities:
      - climate.living_room
```

- [ ] **Step 2: Create `.env.example`**

```
# Copy to .env and fill in. Never commit .env (it's gitignored).
HA_URL=http://localhost:8123
HA_TOKEN=your-long-lived-access-token
```

- [ ] **Step 3: Create `deploy/ha-dashboard.service`**

```ini
[Unit]
Description=Daikin AC Dashboard
After=network-online.target
Wants=network-online.target

[Service]
User=pi
WorkingDirectory=/home/pi/ha_dashboard
ExecStart=/home/pi/ha_dashboard/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8088
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

- [ ] **Step 4: Create `README.md`**

```markdown
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
sudo systemctl enable --now ha-dashboard
```

## Tests

```bash
.venv/bin/pytest
```

## Security note

The app has no authentication — it relies on being reachable only via
your LAN/Tailscale network. Do not port-forward it to the internet.
```

- [ ] **Step 5: Run the full suite one last time**

Run: `.venv/bin/pytest -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add groups.yaml.example .env.example deploy/ha-dashboard.service README.md
git commit -m "docs: setup, config examples, and systemd deployment"
```

---

### Task 10: End-to-end verification against real HA

Manual — needs your HA instance reachable from the dev machine (e.g. over Tailscale) or run directly on the Pi.

- [ ] **Step 1: Configure**: create `.env` (real `HA_URL` + token) and `groups.yaml` with your real entity IDs.
- [ ] **Step 2: Start**: `.venv/bin/uvicorn app.main:app --port 8088` and open `http://localhost:8088`.
- [ ] **Step 3: Verify**, checking the unit's physical/HA state after each:
  - All units appear in the right groups; current temps look right; status dot green.
  - Tap a mode (e.g. Cool) on one unit → unit turns on/changes mode in HA within a few seconds.
  - Step temperature ±0.5° → HA target updates after the taps settle.
  - Mode Off → unit turns off.
  - Group "All Off" → every unit in the group turns off; "All On" → they come back in their previous modes (UI catches up on next poll).
  - Group temp stepper → all group members get the new target.
  - Stop HA (or break `HA_URL`) → red banner appears; restore → banner clears.
- [ ] **Step 4: Deploy to the Pi** per the README systemd section and re-check from a phone on Tailscale.
```
