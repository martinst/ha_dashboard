# Schedule Presets Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A second "Schedule" tab where the family arms config-defined presets ("heat living room at 18:00") as one-shot schedules, fired by a scheduler inside the backend.

**Architecture:** Presets load from `presets.yaml` (generated from add-on options). A `Scheduler` (asyncio loop in the FastAPI lifespan) persists armed fire-times to JSON, fires due presets through the existing `apply_command`, and exposes arm/cancel via three new endpoints. The frontend gains a client-side tab bar and a Schedule view sharing the 5 s poll. Spec: `docs/superpowers/specs/2026-06-07-schedule-presets-design.md`.

**Tech Stack:** Existing stack (FastAPI, httpx, PyYAML, pydantic, vanilla JS). New: `zoneinfo` (stdlib) for HA's timezone.

**Working directory: all commands run from `ac_dashboard/`** (the venv lives at the repo root: `../.venv/bin/pytest`). Current suite: 29 passed.

---

## File structure

| File | Change |
|---|---|
| `app/commands.py` | NEW — `SetCommand` + `apply_command` move here (breaks main↔scheduler import cycle) |
| `app/config.py` | Add `Preset` model, `load_presets()`, `Settings.schedules_path` |
| `app/ha_client.py` | Add `get_config()` |
| `app/scheduler.py` | NEW — `Scheduler`, `ArmError`, `fetch_timezone` |
| `app/main.py` | Import from commands; lifespan wires Scheduler; 3 new endpoints |
| `app/static/{index.html,app.js,style.css}` | Tab bar + Schedule view |
| `config.yaml`, `run.sh`, `DOCS.md`, `CHANGELOG.md` | Add-on v1.2.0 packaging |
| `tests/test_scheduler.py` | NEW |
| `tests/{test_config,test_ha_client,test_api}.py` | Extended |

---

### Task 1: Extract `app/commands.py` (pure refactor)

**Files:**
- Create: `app/commands.py`
- Modify: `app/main.py`

- [ ] **Step 1: Create `app/commands.py`**

```python
from pydantic import BaseModel, model_validator

from app.ha_client import HAClient


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
```

- [ ] **Step 2: Update `app/main.py`**

Delete the `SetCommand` class and `apply_command` function from `app/main.py`. Delete the now-unused `from pydantic import BaseModel, model_validator` import. Add:

```python
from app.commands import SetCommand, apply_command
```

- [ ] **Step 3: Run the full suite (behavior must be unchanged)**

Run: `../.venv/bin/pytest`
Expected: 29 passed, no warnings.

- [ ] **Step 4: Commit**

```bash
git add app/commands.py app/main.py
git commit -m "refactor: extract SetCommand/apply_command to app/commands.py"
```

---

### Task 2: Preset config

**Files:**
- Modify: `app/config.py`
- Test: `tests/test_config.py` (append)

- [ ] **Step 1: Append the failing tests to `tests/test_config.py`**

```python
from app.config import Preset, load_presets


def test_load_presets_parses_yaml(tmp_path):
    f = tmp_path / "presets.yaml"
    f.write_text(
        "presets:\n"
        "  - name: Evening warmth\n"
        "    entities: [climate.living_left, climate.living_right]\n"
        "    mode: heat\n"
        "    temperature: 23\n"
        "    time: '18:00'\n"
    )
    (p,) = load_presets(f)
    assert p.id == "evening_warmth"
    assert p.entities == ["climate.living_left", "climate.living_right"]
    assert p.mode == "heat"
    assert p.temperature == 23.0
    assert p.time == "18:00"


def test_load_presets_missing_file_returns_empty(tmp_path):
    assert load_presets(tmp_path / "nope.yaml") == []


def test_preset_invalid_time_raises(tmp_path):
    f = tmp_path / "presets.yaml"
    f.write_text(
        "presets:\n"
        "  - name: Bad\n"
        "    entities: [climate.x]\n"
        "    mode: heat\n"
        "    time: '25:99'\n"
    )
    with pytest.raises(ValueError, match="Invalid presets.yaml"):
        load_presets(f)


def test_preset_requires_mode_or_temperature():
    with pytest.raises(ValueError, match="mode and/or temperature"):
        Preset(name="X", entities=["climate.x"], time="18:00")


def test_preset_requires_entities():
    with pytest.raises(ValueError, match="entities"):
        Preset(name="X", entities=[], mode="heat", time="18:00")


def test_duplicate_preset_names_raise(tmp_path):
    f = tmp_path / "presets.yaml"
    f.write_text(
        "presets:\n"
        "  - {name: Same Name, entities: [climate.a], mode: heat, time: '18:00'}\n"
        "  - {name: same name, entities: [climate.b], mode: cool, time: '19:00'}\n"
    )
    with pytest.raises(ValueError, match="Duplicate preset"):
        load_presets(f)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `../.venv/bin/pytest tests/test_config.py -v`
Expected: the 6 new tests FAIL — `ImportError: cannot import name 'Preset'`. The 5 old tests still pass.

- [ ] **Step 3: Implement in `app/config.py`**

Add `re` to the imports and `model_validator` to the pydantic import:

```python
import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
```

Add `schedules_path` to `Settings`:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ha_url: str = "http://localhost:8123"
    ha_token: str = ""
    schedules_path: str = "schedules.json"
```

Add below `load_groups`:

```python
class Preset(BaseModel):
    name: str
    entities: list[str]
    mode: str | None = None
    temperature: float | None = None
    time: str

    @model_validator(mode="after")
    def validate_preset(self):
        if not self.entities:
            raise ValueError("entities must be non-empty")
        if self.mode is None and self.temperature is None:
            raise ValueError("provide mode and/or temperature")
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", self.time):
            raise ValueError(f"time must be HH:MM, got {self.time!r}")
        return self

    @property
    def id(self) -> str:
        return self.name.lower().replace(" ", "_")


def load_presets(path: str | Path = "presets.yaml") -> list[Preset]:
    path = Path(path)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    try:
        presets = [Preset(**p) for p in data.get("presets", [])]
    except (TypeError, ValidationError) as exc:
        raise ValueError(f"Invalid presets.yaml ({path}): {exc}") from exc
    ids = [p.id for p in presets]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"Duplicate preset ids in {path}: {duplicates}")
    return presets
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `../.venv/bin/pytest tests/test_config.py -v`
Expected: 11 PASS. Full suite: `../.venv/bin/pytest` → 35 passed.

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: preset model and presets.yaml loading"
```

---

### Task 3: `HAClient.get_config`

**Files:**
- Modify: `app/ha_client.py`
- Test: `tests/test_ha_client.py` (append)

- [ ] **Step 1: Append the failing test to `tests/test_ha_client.py`**

```python
async def test_get_config_fetches_api_config():
    def handler(request):
        assert request.url.path == "/api/config"
        return httpx.Response(200, json={"time_zone": "Europe/Stockholm"})

    config = await make_ha_client(handler).get_config()
    assert config["time_zone"] == "Europe/Stockholm"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `../.venv/bin/pytest tests/test_ha_client.py -v`
Expected: new test FAILS — `AttributeError: 'HAClient' object has no attribute 'get_config'`. 7 old tests pass.

- [ ] **Step 3: Implement in `app/ha_client.py`** (below `get_climate_states`)

```python
    async def get_config(self) -> dict:
        return await self._request("GET", "/api/config")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `../.venv/bin/pytest tests/test_ha_client.py -v` → 8 PASS. Full suite → 36 passed.

- [ ] **Step 5: Commit**

```bash
git add app/ha_client.py tests/test_ha_client.py
git commit -m "feat: HAClient.get_config for timezone discovery"
```

---

### Task 4: Scheduler core

**Files:**
- Create: `app/scheduler.py`
- Test: `tests/test_scheduler.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_scheduler.py
import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.config import Preset
from app.scheduler import ArmError, Scheduler

from tests.conftest import FakeHAClient

TZ = ZoneInfo("Europe/Stockholm")
START = datetime(2026, 6, 7, 12, 0, tzinfo=TZ)

PRESET = Preset(
    name="Evening warmth",
    entities=["climate.a", "climate.b"],
    mode="heat",
    temperature=23.0,
    time="18:00",
)


class Clock:
    def __init__(self, now=START):
        self.now = now

    def __call__(self):
        return self.now


def make_scheduler(tmp_path, clock, presets=(PRESET,), ha=None):
    return Scheduler(
        list(presets),
        ha or FakeHAClient(),
        tmp_path / "schedules.json",
        TZ,
        now=clock,
    )


def test_arm_returns_aware_datetime_and_persists(tmp_path):
    s = make_scheduler(tmp_path, Clock())
    fires = s.arm("evening_warmth", "2026-06-08", "18:00")
    assert fires.isoformat().startswith("2026-06-08T18:00")
    assert fires.tzinfo is not None
    saved = json.loads((tmp_path / "schedules.json").read_text())
    assert saved == {"evening_warmth": fires.isoformat()}


def test_arm_past_raises(tmp_path):
    s = make_scheduler(tmp_path, Clock())
    with pytest.raises(ArmError, match="past"):
        s.arm("evening_warmth", "2026-06-07", "11:00")


def test_arm_too_far_ahead_raises(tmp_path):
    s = make_scheduler(tmp_path, Clock())
    with pytest.raises(ArmError, match="7 days"):
        s.arm("evening_warmth", "2026-06-20", "18:00")


def test_arm_unknown_preset_raises(tmp_path):
    s = make_scheduler(tmp_path, Clock())
    with pytest.raises(KeyError):
        s.arm("ghost", "2026-06-08", "18:00")


def test_rearm_replaces(tmp_path):
    s = make_scheduler(tmp_path, Clock())
    s.arm("evening_warmth", "2026-06-08", "18:00")
    fires = s.arm("evening_warmth", "2026-06-08", "19:30")
    assert s.armed["evening_warmth"] == fires
    assert len(s.armed) == 1


def test_cancel_disarms_and_is_idempotent(tmp_path):
    s = make_scheduler(tmp_path, Clock())
    s.arm("evening_warmth", "2026-06-08", "18:00")
    s.cancel("evening_warmth")
    assert s.armed == {}
    s.cancel("evening_warmth")  # no error
    assert json.loads((tmp_path / "schedules.json").read_text()) == {}


def test_cancel_unknown_preset_raises(tmp_path):
    s = make_scheduler(tmp_path, Clock())
    with pytest.raises(KeyError):
        s.cancel("ghost")


def test_persistence_round_trip(tmp_path):
    clock = Clock()
    s1 = make_scheduler(tmp_path, clock)
    fires = s1.arm("evening_warmth", "2026-06-08", "18:00")
    s2 = make_scheduler(tmp_path, clock)
    assert s2.armed == {"evening_warmth": fires}


def test_unknown_preset_in_file_dropped(tmp_path):
    (tmp_path / "schedules.json").write_text(
        json.dumps({"ghost": "2026-06-08T18:00:00+02:00"})
    )
    s = make_scheduler(tmp_path, Clock())
    assert s.armed == {}


def test_corrupt_file_ignored(tmp_path):
    (tmp_path / "schedules.json").write_text("not json{")
    s = make_scheduler(tmp_path, Clock())
    assert s.armed == {}


async def test_check_due_fires_and_disarms(tmp_path):
    clock = Clock()
    ha = FakeHAClient()
    s = make_scheduler(tmp_path, clock, ha=ha)
    s.arm("evening_warmth", "2026-06-07", "14:00")
    clock.now = datetime(2026, 6, 7, 14, 0, 30, tzinfo=TZ)
    await s.check_due()
    assert s.armed == {}
    assert ("set_hvac_mode", "climate.a", "heat") in ha.calls
    assert ("set_temperature", "climate.a", 23.0) in ha.calls
    assert ("set_hvac_mode", "climate.b", "heat") in ha.calls
    assert ("set_temperature", "climate.b", 23.0) in ha.calls
    assert json.loads((tmp_path / "schedules.json").read_text()) == {}


async def test_check_due_not_yet_due_does_nothing(tmp_path):
    clock = Clock()
    ha = FakeHAClient()
    s = make_scheduler(tmp_path, clock, ha=ha)
    s.arm("evening_warmth", "2026-06-07", "14:00")
    clock.now = datetime(2026, 6, 7, 13, 59, tzinfo=TZ)
    await s.check_due()
    assert ha.calls == []
    assert "evening_warmth" in s.armed


async def test_check_due_within_grace_fires(tmp_path):
    clock = Clock()
    ha = FakeHAClient()
    s = make_scheduler(tmp_path, clock, ha=ha)
    s.arm("evening_warmth", "2026-06-07", "14:00")
    clock.now = datetime(2026, 6, 7, 14, 50, tzinfo=TZ)
    await s.check_due()
    assert ha.calls != []
    assert s.armed == {}


async def test_check_due_past_grace_discards(tmp_path):
    clock = Clock()
    ha = FakeHAClient()
    s = make_scheduler(tmp_path, clock, ha=ha)
    s.arm("evening_warmth", "2026-06-07", "14:00")
    clock.now = datetime(2026, 6, 7, 15, 30, tzinfo=TZ)
    await s.check_due()
    assert ha.calls == []
    assert s.armed == {}


async def test_fire_partial_failure_still_disarms(tmp_path):
    clock = Clock()
    ha = FakeHAClient(fail_entities=["climate.a"])
    s = make_scheduler(tmp_path, clock, ha=ha)
    s.arm("evening_warmth", "2026-06-07", "14:00")
    clock.now = datetime(2026, 6, 7, 14, 1, tzinfo=TZ)
    await s.check_due()  # must not raise
    assert s.armed == {}
    assert ("set_hvac_mode", "climate.b", "heat") in ha.calls
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `../.venv/bin/pytest tests/test_scheduler.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.scheduler'`

- [ ] **Step 3: Implement `app/scheduler.py`**

```python
import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.commands import SetCommand, apply_command
from app.config import Preset
from app.ha_client import HAClient

log = logging.getLogger(__name__)

GRACE = timedelta(hours=1)
MAX_AHEAD = timedelta(days=7)
TICK_SECONDS = 10


class ArmError(ValueError):
    """Raised when an arm request is invalid (past time, too far ahead)."""


async def fetch_timezone(ha: HAClient):
    """HA's configured timezone, falling back to system local time."""
    try:
        config = await ha.get_config()
        return ZoneInfo(config["time_zone"])
    except Exception as exc:
        log.warning("Could not get HA timezone (%s); using system local time", exc)
        return datetime.now().astimezone().tzinfo


class Scheduler:
    """One-shot preset schedules: armed state, persistence, firing loop."""

    def __init__(self, presets: list[Preset], ha: HAClient, path, tz, now=None):
        self.presets = {p.id: p for p in presets}
        self._ha = ha
        self._path = Path(path)
        self._tz = tz
        self._now = now or (lambda: datetime.now(self._tz))
        self.armed: dict[str, datetime] = {}
        self._task: asyncio.Task | None = None
        self._load()

    # -- persistence --

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
        except (OSError, ValueError) as exc:
            log.warning("Ignoring corrupt %s: %s", self._path, exc)
            return
        for preset_id, iso in raw.items():
            if preset_id not in self.presets:
                log.warning("Dropping armed schedule for unknown preset %r", preset_id)
                continue
            self.armed[preset_id] = datetime.fromisoformat(iso)

    def _save(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({pid: dt.isoformat() for pid, dt in self.armed.items()})
        )
        os.replace(tmp, self._path)

    # -- arm / cancel --

    def arm(self, preset_id: str, date_str: str, time_str: str) -> datetime:
        if preset_id not in self.presets:
            raise KeyError(preset_id)
        fires_at = datetime.fromisoformat(f"{date_str}T{time_str}").replace(
            tzinfo=self._tz
        )
        now = self._now()
        if fires_at <= now:
            raise ArmError("fire time is in the past")
        if fires_at - now > MAX_AHEAD:
            raise ArmError("fire time is more than 7 days ahead")
        self.armed[preset_id] = fires_at
        self._save()
        return fires_at

    def cancel(self, preset_id: str) -> None:
        if preset_id not in self.presets:
            raise KeyError(preset_id)
        if self.armed.pop(preset_id, None) is not None:
            self._save()

    # -- firing loop --

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while True:
            try:
                await self.check_due()
            except Exception:
                log.exception("Scheduler tick failed")
            await asyncio.sleep(TICK_SECONDS)

    async def check_due(self) -> None:
        now = self._now()
        for preset_id, fires_at in list(self.armed.items()):
            if fires_at > now:
                continue
            del self.armed[preset_id]
            self._save()
            if now - fires_at > GRACE:
                log.warning(
                    "Discarding %r: fire time %s is too far in the past",
                    preset_id,
                    fires_at,
                )
                continue
            await self._fire(self.presets[preset_id])

    async def _fire(self, preset: Preset) -> None:
        cmd = SetCommand(mode=preset.mode, temperature=preset.temperature)
        results = await asyncio.gather(
            *(apply_command(self._ha, entity_id, cmd) for entity_id in preset.entities),
            return_exceptions=True,
        )
        failed = [
            entity_id
            for entity_id, result in zip(preset.entities, results)
            if isinstance(result, Exception)
        ]
        if failed:
            log.warning("Preset %r fired with failures: %s", preset.id, failed)
        else:
            log.info("Preset %r fired for %d unit(s)", preset.id, len(preset.entities))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `../.venv/bin/pytest tests/test_scheduler.py -v` → 15 PASS. Full suite → 51 passed, no warnings.

- [ ] **Step 5: Commit**

```bash
git add app/scheduler.py tests/test_scheduler.py
git commit -m "feat: one-shot preset scheduler with persistence and grace window"
```

---

### Task 5: Schedule API endpoints

**Files:**
- Modify: `app/main.py`, `tests/conftest.py`
- Test: `tests/test_api.py` (append)

- [ ] **Step 1: Extend the `make_client` fixture in `tests/conftest.py`**

Replace the `_make` inner function so it accepts an optional scheduler override (`get_scheduler` is added to `app/main.py` in Step 4):

```python
@pytest.fixture
def make_client():
    """Returns a factory: make_client(fake_ha, groups, scheduler) -> TestClient."""
    from app.main import app, get_groups, get_ha_client, get_scheduler

    def _make(fake_ha, groups=(), scheduler=None):
        app.dependency_overrides[get_ha_client] = lambda: fake_ha
        app.dependency_overrides[get_groups] = lambda: list(groups)
        if scheduler is not None:
            app.dependency_overrides[get_scheduler] = lambda: scheduler
        return TestClient(app)

    yield _make
    from app.main import app as _app
    _app.dependency_overrides.clear()
```

- [ ] **Step 2: Append the failing tests to `tests/test_api.py`**

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Preset
from app.scheduler import Scheduler

TZ = ZoneInfo("Europe/Stockholm")

SCHED_PRESET = Preset(
    name="Evening warmth",
    entities=["climate.bedroom"],
    mode="heat",
    temperature=23.0,
    time="18:00",
)


def make_sched(tmp_path, fake_ha):
    return Scheduler(
        [SCHED_PRESET],
        fake_ha,
        tmp_path / "schedules.json",
        TZ,
        now=lambda: datetime(2026, 6, 7, 12, 0, tzinfo=TZ),
    )


def test_get_schedule_lists_presets(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    resp = client.get("/api/schedule")
    assert resp.status_code == 200
    (p,) = resp.json()["presets"]
    assert p["id"] == "evening_warmth"
    assert p["name"] == "Evening warmth"
    assert p["time"] == "18:00"
    assert p["armed"] is None


def test_arm_endpoint_arms_preset(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    resp = client.post(
        "/api/schedule/evening_warmth/arm",
        json={"date": "2026-06-08", "time": "18:00"},
    )
    assert resp.status_code == 200
    assert resp.json()["fires_at"].startswith("2026-06-08T18:00")
    armed = client.get("/api/schedule").json()["presets"][0]["armed"]
    assert armed["fires_at"].startswith("2026-06-08T18:00")


def test_arm_past_time_is_400(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    resp = client.post(
        "/api/schedule/evening_warmth/arm",
        json={"date": "2026-06-07", "time": "11:00"},
    )
    assert resp.status_code == 400


def test_arm_bad_date_is_400(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    resp = client.post(
        "/api/schedule/evening_warmth/arm",
        json={"date": "not-a-date", "time": "18:00"},
    )
    assert resp.status_code == 400


def test_arm_unknown_preset_is_404(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    resp = client.post(
        "/api/schedule/ghost/arm", json={"date": "2026-06-08", "time": "18:00"}
    )
    assert resp.status_code == 404


def test_cancel_endpoint_disarms(make_client, tmp_path):
    fake = FakeHAClient()
    sched = make_sched(tmp_path, fake)
    client = make_client(fake, scheduler=sched)
    client.post(
        "/api/schedule/evening_warmth/arm",
        json={"date": "2026-06-08", "time": "18:00"},
    )
    resp = client.post("/api/schedule/evening_warmth/cancel")
    assert resp.status_code == 200
    assert client.get("/api/schedule").json()["presets"][0]["armed"] is None
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `../.venv/bin/pytest tests/test_api.py -v`
Expected: the 6 new tests FAIL (404 — routes don't exist; the unknown-preset test may accidentally pass). The 11 old api tests still pass.

- [ ] **Step 4: Implement in `app/main.py`**

Update imports: add to the existing `app.config` import line and add the scheduler import; add `BaseModel` back for `ArmRequest`:

```python
from pydantic import BaseModel

from app.config import Settings, load_groups, load_presets
from app.scheduler import Scheduler, fetch_timezone
```

Replace `lifespan` with:

```python
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
```

Add below `get_groups`:

```python
def get_scheduler(request: Request) -> Scheduler:
    return request.app.state.scheduler
```

Add below the `set_group` endpoint (and above the static mount):

```python
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
                    {"fires_at": scheduler.armed[p.id].isoformat()}
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
        fires_at = scheduler.arm(preset_id, req.date, req.time)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown preset: {preset_id}")
    except ValueError as exc:  # ArmError or unparsable date/time
        raise HTTPException(status_code=400, detail=str(exc))
    return {"fires_at": fires_at.isoformat()}


@app.post("/api/schedule/{preset_id}/cancel")
async def cancel_preset(
    preset_id: str, scheduler: Scheduler = Depends(get_scheduler)
):
    try:
        scheduler.cancel(preset_id)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown preset: {preset_id}")
    return {"ok": True}
```

- [ ] **Step 5: Run the full suite**

Run: `../.venv/bin/pytest -v`
Expected: 57 passed (config 11, ha_client 8, state 6, scheduler 15, api 17), no warnings.

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/test_api.py tests/conftest.py
git commit -m "feat: schedule endpoints (list/arm/cancel) wired to scheduler"
```

---

### Task 6: Frontend — tabs and Schedule view

**Files:**
- Modify: `app/static/index.html`, `app/static/app.js`, `app/static/style.css`

- [ ] **Step 1: Update `app/static/index.html`** — add the tab bar after `</header>` and a second `<main>`:

Replace the `<body>` content with:

```html
<body>
  <header>
    <h1>AC Control</h1>
    <span id="status-dot" class="dot" title="Connection to Home Assistant"></span>
  </header>
  <nav class="tabs">
    <button id="tab-control" class="tab active">Control</button>
    <button id="tab-schedule" class="tab">Schedule</button>
  </nav>
  <div id="banner" class="banner hidden">Can't reach Home Assistant</div>
  <main id="groups"></main>
  <main id="schedule" class="hidden"></main>
  <script src="/app.js"></script>
</body>
```

- [ ] **Step 2: Update `app/static/app.js`**

(a) Add state at the top, after `groupTemps`:

```javascript
let scheduleState = { presets: [] };
const armForm = {};         // preset id -> {day, time} (survives re-renders)
const pendingSchedule = {}; // preset id -> suppress-poll-until timestamp
```

(b) Replace `poll()` and add `mergeSchedule` after `mergeState`:

```javascript
async function poll() {
  try {
    const [stateResp, schedResp] = await Promise.all([
      fetch("/api/state"),
      fetch("/api/schedule"),
    ]);
    if (!stateResp.ok || !schedResp.ok) throw new Error("poll failed");
    mergeState(await stateResp.json());
    mergeSchedule(await schedResp.json());
    setConnected(true);
  } catch {
    setConnected(false);
  }
  render();
}
```

```javascript
function mergeSchedule(fresh) {
  const now = Date.now();
  const old = {};
  for (const p of scheduleState.presets) old[p.id] = p;
  fresh.presets = fresh.presets.map((p) =>
    (pendingSchedule[p.id] || 0) > now && old[p.id] ? old[p.id] : p
  );
  scheduleState = fresh;
}
```

(c) Replace `render()` and add tab wiring at the bottom (before the `poll()` call):

```javascript
function render() {
  document
    .getElementById("groups")
    .replaceChildren(...state.groups.map(renderGroup));
  renderSchedule();
}
```

```javascript
function showTab(name) {
  document.getElementById("groups").classList.toggle("hidden", name !== "control");
  document.getElementById("schedule").classList.toggle("hidden", name !== "schedule");
  document.getElementById("tab-control").classList.toggle("active", name === "control");
  document.getElementById("tab-schedule").classList.toggle("active", name === "schedule");
}

document.getElementById("tab-control").addEventListener("click", () => showTab("control"));
document.getElementById("tab-schedule").addEventListener("click", () => showTab("schedule"));
```

(d) Add the Schedule view functions (after `stepperEl`):

```javascript
// ---- schedule tab ----

function renderSchedule() {
  const main = document.getElementById("schedule");
  if (!scheduleState.presets.length) {
    main.replaceChildren(
      el("p", "hint",
         "No presets configured. Add a presets: section in the add-on configuration.")
    );
    return;
  }
  main.replaceChildren(...scheduleState.presets.map(renderPreset));
}

function renderPreset(p) {
  const card = el("div", "card preset");
  card.append(el("div", "unit-name", p.name));
  card.append(el("div", "preset-summary", presetSummary(p)));
  const row = el("div", "arm-row");
  if (p.armed) {
    row.append(el("span", "fires", firesLabel(p.armed.fires_at)));
    row.append(btn("Cancel", "ctl cancel", () => cancelPreset(p)));
  } else {
    const form = armForm[p.id] ?? (armForm[p.id] = {
      day: timePassedToday(p.time) ? "tomorrow" : "today",
      time: p.time,
    });
    const daySel = document.createElement("select");
    for (const [value, label] of [["today", "Today"], ["tomorrow", "Tomorrow"]]) {
      const o = document.createElement("option");
      o.value = value;
      o.textContent = label;
      if (form.day === value) o.selected = true;
      daySel.append(o);
    }
    daySel.addEventListener("change", () => { form.day = daySel.value; });
    const timeInput = document.createElement("input");
    timeInput.type = "time";
    timeInput.value = form.time;
    timeInput.addEventListener("change", () => { form.time = timeInput.value; });
    row.append(daySel, timeInput, btn("Arm", "ctl arm", () => armPreset(p)));
  }
  card.append(row);
  return card;
}

function presetSummary(p) {
  const action = [
    p.mode ? (MODE_LABELS[p.mode] ?? p.mode) : null,
    p.temperature != null ? `${p.temperature}°` : null,
  ].filter(Boolean).join(" ");
  return `${action} — ${p.entities.map(unitName).join(", ")}`;
}

function unitName(entityId) {
  for (const g of state.groups)
    for (const u of g.units)
      if (u.entity_id === entityId) return u.name;
  return entityId;
}

function timePassedToday(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  const now = new Date();
  return now.getHours() > h || (now.getHours() === h && now.getMinutes() >= m);
}

function isoDate(offsetDays) {
  const d = new Date(Date.now() + offsetDays * 86400000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function firesLabel(iso) {
  const time = iso.slice(11, 16);
  const day = iso.slice(0, 10);
  if (day === isoDate(0)) return `Fires today at ${time}`;
  if (day === isoDate(1)) return `Fires tomorrow at ${time}`;
  return `Fires ${day} at ${time}`;
}

async function armPreset(p) {
  const form = armForm[p.id];
  if (!form.time) return;
  const date = isoDate(form.day === "tomorrow" ? 1 : 0);
  p.armed = { fires_at: `${date}T${form.time}:00` };
  pendingSchedule[p.id] = Date.now() + PENDING_MS;
  render();
  const body = await post(`/api/schedule/${p.id}/arm`, { date, time: form.time });
  if (!body) {
    // rejected (e.g. time just passed) or network error — revert
    p.armed = null;
    delete pendingSchedule[p.id];
    render();
  }
}

async function cancelPreset(p) {
  p.armed = null;
  pendingSchedule[p.id] = Date.now() + PENDING_MS;
  render();
  await post(`/api/schedule/${p.id}/cancel`, {});
}
```

- [ ] **Step 3: Add to `app/static/style.css`** (at the end):

```css
.tabs {
  display: flex;
  gap: 6px;
  padding: 0 12px;
  max-width: 640px;
  margin: 0 auto 4px;
}
.tab {
  flex: 1;
  background: transparent;
  color: var(--muted);
  border-bottom: 2px solid transparent;
  border-radius: 8px 8px 0 0;
}
.tab.active {
  color: var(--text);
  border-bottom-color: var(--accent-cool);
  font-weight: 600;
}

.preset-summary {
  color: var(--muted);
  font-size: 0.9rem;
  margin-top: 2px;
}

.arm-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 12px;
}
.arm-row select,
.arm-row input[type="time"] {
  font: inherit;
  padding: 8px;
  border: 1px solid #d4dae3;
  border-radius: 8px;
  background: #fff;
  color: var(--text);
}
.arm-row .arm {
  margin-left: auto;
  background: var(--accent-cool);
  color: #fff;
}
.arm-row .cancel { margin-left: auto; }
.fires { font-weight: 600; }

.hint {
  color: var(--muted);
  text-align: center;
  padding: 24px 12px;
}
```

- [ ] **Step 4: Verify**

Run: `node --check app/static/app.js` → no output (syntax OK).
Run: `../.venv/bin/pytest` → 57 passed.
Create a local `presets.yaml` (copy of the example in Task 7), start `../.venv/bin/uvicorn app.main:app --port 8090`, open `http://localhost:8090`: both tabs render, the Schedule tab shows the preset; arm it for a minute ahead and confirm it fires (watch the server log and the unit in HA), confirm Cancel works, then Ctrl-C and delete `schedules.json`.

- [ ] **Step 5: Commit**

```bash
git add app/static
git commit -m "feat: Schedule tab with arm/cancel preset UI"
```

---

### Task 7: Add-on packaging v1.2.0

**Files:**
- Modify: `config.yaml`, `run.sh`, `DOCS.md`, `CHANGELOG.md`
- Create: `presets.yaml.example`

- [ ] **Step 1: Update `config.yaml`** — bump version, add presets option/schema:

`version: "1.2.0"`, and in `options:` / `schema:`:

```yaml
options:
  groups: []
  presets: []
  ssl: false
  certfile: fullchain.pem
  keyfile: privkey.pem
schema:
  groups:
    - name: str
      entities:
        - str
  presets:
    - name: str
      entities:
        - str
      mode: str?
      temperature: float?
      time: str
  ssl: bool
  certfile: str?
  keyfile: str?
```

- [ ] **Step 2: Update `run.sh`** — write presets.yaml too and export the schedules path. Replace the python conversion block with:

```sh
export SCHEDULES_PATH=/data/schedules.json

# Convert the add-on options (Configuration tab) into groups.yaml + presets.yaml.
python3 - <<'PY'
import json
import yaml

with open("/data/options.json") as f:
    options = json.load(f)
with open("groups.yaml", "w") as f:
    yaml.safe_dump({"groups": options.get("groups", [])}, f)
with open("presets.yaml", "w") as f:
    yaml.safe_dump({"presets": options.get("presets", [])}, f)
PY
```

(`Settings.schedules_path` reads the `SCHEDULES_PATH` env var via pydantic-settings.)

- [ ] **Step 3: Create `presets.yaml.example`**

```yaml
# Local development only — the add-on generates presets.yaml from its options.
presets:
  - name: Evening warmth
    entities:
      - climate.living_left
      - climate.living_right
    mode: heat
    temperature: 23
    time: "18:00"
```

- [ ] **Step 4: Update `DOCS.md`** — add after the Configuration section:

```markdown
## Schedule presets

Optional one-shot schedules for the **Schedule** tab. You define presets
here; anyone can arm them from the page (picking day and time) and cancel
them. A fired preset disarms itself.

```yaml
presets:
  - name: Evening warmth
    entities:
      - climate.living_left
      - climate.living_right
    mode: heat          # any mode the units support, or "on" / "off"
    temperature: 23     # optional — at least one of mode/temperature
    time: "18:00"       # default time shown when arming
```

Armed schedules survive app restarts. If the app was stopped at the
scheduled time, the action still runs if the app comes back within an hour;
otherwise it is skipped (a log line records this).
```

- [ ] **Step 5: Update `CHANGELOG.md`** — add at the top:

```markdown
## 1.2.0

- New Schedule tab: arm one-shot schedules from config-defined presets
  (adjustable day/time), cancel from any phone, armed state survives
  restarts. Times follow Home Assistant's timezone.
```

- [ ] **Step 6: Run the full suite, commit**

Run: `../.venv/bin/pytest` → 57 passed.

```bash
git add config.yaml run.sh DOCS.md CHANGELOG.md presets.yaml.example
git commit -m "feat: add-on v1.2.0 — presets options and schedules persistence"
```

---

### Task 8: Ship and verify on the Pi

Manual, with the user:

- [ ] **Step 1:** Push: `git push`
- [ ] **Step 2:** In HA: Settings → Apps → App Store → ⋮ → Check for updates; update AC Dashboard to 1.2.0.
- [ ] **Step 3:** Add a `presets:` section in the app's Configuration tab; restart the app.
- [ ] **Step 4:** On a phone: Schedule tab shows the presets; arm one a few minutes ahead; confirm the units turn on at the time; confirm the preset disarms afterwards; confirm Cancel works; restart the app with one armed and confirm the arm survives.
