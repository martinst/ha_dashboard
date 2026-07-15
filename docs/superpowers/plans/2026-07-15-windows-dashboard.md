# Windows Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generalize the AC Dashboard add-on into a "Home Dashboard" with a second page controlling Somfy TaHoma motorized windows (HA `cover.*` entities): open/close/stop, position slider, groups, and scheduled presets.

**Architecture:** Parallel domain models with shared plumbing. Cover twins of the climate models are added where shapes genuinely differ (`CoverCommand`, `CoverPreset`, `cover_from_ha_state`); the HA client, group builder, scheduler, and API patterns are shared. The frontend gains a `windows.html` page; schedule-tab JS is extracted into a shared file both pages load. Spec: `docs/superpowers/specs/2026-07-15-windows-dashboard-design.md`.

**Tech Stack:** Python 3.11+ / FastAPI / Pydantic v2 / httpx, pytest (asyncio_mode=auto), vanilla JS frontend, HA add-on packaging (config.yaml + run.sh + Dockerfile).

## Global Constraints

- Add-on `slug` stays `ac_dashboard`; display name becomes `Home Dashboard`; version becomes `1.4.0` (all in `ac_dashboard/config.yaml`, Task 9).
- Existing `groups`/`presets` options, climate API endpoints, and climate preset IDs must keep working unchanged (no config migration).
- Cover preset IDs are namespaced `cover:<slug>`; climate preset IDs are unchanged.
- No new Python dependencies.
- All backend work happens in `ac_dashboard/`; run tests from there: `../.venv/bin/pytest` (all commands below assume `cd ac_dashboard`).
- After EVERY task the full suite must pass: `../.venv/bin/pytest -q`.
- JS files must pass `node --check <file>` (no test framework for frontend).

---

### Task 1: HA client — `get_states()` + cover service calls

**Files:**
- Modify: `ac_dashboard/app/ha_client.py`
- Modify: `ac_dashboard/app/main.py:88-94` (get_state call site)
- Modify: `ac_dashboard/tests/conftest.py` (FakeHAClient)
- Test: `ac_dashboard/tests/test_ha_client.py`

**Interfaces:**
- Consumes: existing `HAClient._request`.
- Produces: `HAClient.get_states() -> list[dict]` (ALL states, unfiltered; replaces `get_climate_states`), `open_cover(entity_id: str)`, `close_cover(entity_id: str)`, `stop_cover(entity_id: str)`, `set_cover_position(entity_id: str, position: int)` — all `async -> None`. `FakeHAClient.get_states()` and cover-call recorders `("open_cover", id)`, `("close_cover", id)`, `("stop_cover", id)`, `("set_cover_position", id, position)`.

- [ ] **Step 1: Update tests — replace `get_climate_states` tests, add cover-service tests**

In `tests/test_ha_client.py`, replace `test_get_climate_states_filters_and_authenticates` with:

```python
async def test_get_states_returns_all_states_and_authenticates():
    seen = {}

    def handler(request):
        seen["auth"] = request.headers["Authorization"]
        seen["path"] = request.url.path
        return httpx.Response(200, json=STATES)

    client = make_ha_client(handler)
    states = await client.get_states()
    assert seen == {"auth": "Bearer secret-token", "path": "/api/states"}
    assert [s["entity_id"] for s in states] == ["climate.bedroom", "light.kitchen"]
```

In the three error tests (`test_http_error_status_raises_haerror`, `test_connection_error_raises_haerror`, `test_non_json_response_raises_haerror`), change `.get_climate_states()` to `.get_states()`.

Append:

```python
async def test_cover_services_post_service_calls():
    calls = []

    def handler(request):
        calls.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json=[])

    client = make_ha_client(handler)
    await client.open_cover("cover.win")
    await client.close_cover("cover.win")
    await client.stop_cover("cover.win")
    await client.set_cover_position("cover.win", 40)
    assert calls == [
        ("/api/services/cover/open_cover", {"entity_id": "cover.win"}),
        ("/api/services/cover/close_cover", {"entity_id": "cover.win"}),
        ("/api/services/cover/stop_cover", {"entity_id": "cover.win"}),
        ("/api/services/cover/set_cover_position",
         {"entity_id": "cover.win", "position": 40}),
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `../.venv/bin/pytest tests/test_ha_client.py -v`
Expected: FAIL — `AttributeError: 'HAClient' object has no attribute 'get_states'` (and no `open_cover`).

- [ ] **Step 3: Implement in `app/ha_client.py`**

Replace `get_climate_states` with `get_states` and add the cover methods after `turn_on`:

```python
    async def get_states(self) -> list[dict]:
        return await self._request("GET", "/api/states")
```

```python
    async def open_cover(self, entity_id: str) -> None:
        await self._request(
            "POST",
            "/api/services/cover/open_cover",
            body={"entity_id": entity_id},
        )

    async def close_cover(self, entity_id: str) -> None:
        await self._request(
            "POST",
            "/api/services/cover/close_cover",
            body={"entity_id": entity_id},
        )

    async def stop_cover(self, entity_id: str) -> None:
        await self._request(
            "POST",
            "/api/services/cover/stop_cover",
            body={"entity_id": entity_id},
        )

    async def set_cover_position(self, entity_id: str, position: int) -> None:
        await self._request(
            "POST",
            "/api/services/cover/set_cover_position",
            body={"entity_id": entity_id, "position": position},
        )
```

- [ ] **Step 4: Update the two callers of `get_climate_states`**

In `app/main.py`, the `get_state` endpoint body becomes:

```python
    states = await ha.get_states()
    climate = [s for s in states if s["entity_id"].startswith("climate.")]
    return {"groups": build_groups(climate, groups)}
```

In `tests/conftest.py`, in `FakeHAClient` rename `get_climate_states` to `get_states` (same body) and add cover recorders after `turn_on`:

```python
    async def get_states(self):
        if self.fail_states:
            raise HAError("HA unreachable")
        return self.states

    async def open_cover(self, entity_id):
        self._record(("open_cover", entity_id), entity_id)

    async def close_cover(self, entity_id):
        self._record(("close_cover", entity_id), entity_id)

    async def stop_cover(self, entity_id):
        self._record(("stop_cover", entity_id), entity_id)

    async def set_cover_position(self, entity_id, position):
        self._record(("set_cover_position", entity_id, position), entity_id)
```

- [ ] **Step 5: Run the full suite**

Run: `../.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/ha_client.py app/main.py tests/conftest.py tests/test_ha_client.py
git commit -m "feat: HA client cover services and unfiltered get_states"
```

---

### Task 2: Commands — `CoverCommand` + domain dispatch

**Files:**
- Modify: `ac_dashboard/app/commands.py`
- Test: `ac_dashboard/tests/test_commands.py` (new file)

**Interfaces:**
- Consumes: `HAClient` cover methods from Task 1.
- Produces: `CoverCommand(BaseModel)` with `action: str | None` (one of `"open"|"close"|"stop"`) and `position: int | None` (0–100), at least one required. `CommandError(ValueError)`. `apply_command(ha, entity_id, cmd)` now dispatches on entity prefix and raises `CommandError` on domain/command mismatch or unknown domain. Dispatch order for covers: `stop` beats `position` beats `open`/`close`.

- [ ] **Step 1: Write failing tests — create `tests/test_commands.py`**

```python
import pytest
from pydantic import ValidationError

from app.commands import CommandError, CoverCommand, SetCommand, apply_command

from tests.conftest import FakeHAClient


def test_cover_command_requires_action_or_position():
    with pytest.raises(ValidationError, match="action and/or position"):
        CoverCommand()


def test_cover_command_rejects_unknown_action():
    with pytest.raises(ValidationError, match="open, close or stop"):
        CoverCommand(action="tilt")


def test_cover_command_rejects_position_out_of_range():
    with pytest.raises(ValidationError, match="0-100"):
        CoverCommand(position=101)


async def test_cover_open_calls_open_cover():
    fake = FakeHAClient()
    await apply_command(fake, "cover.win", CoverCommand(action="open"))
    assert fake.calls == [("open_cover", "cover.win")]


async def test_cover_close_calls_close_cover():
    fake = FakeHAClient()
    await apply_command(fake, "cover.win", CoverCommand(action="close"))
    assert fake.calls == [("close_cover", "cover.win")]


async def test_cover_stop_wins_over_position():
    fake = FakeHAClient()
    await apply_command(fake, "cover.win", CoverCommand(action="stop", position=50))
    assert fake.calls == [("stop_cover", "cover.win")]


async def test_cover_position_wins_over_open_close():
    fake = FakeHAClient()
    await apply_command(fake, "cover.win", CoverCommand(action="open", position=40))
    assert fake.calls == [("set_cover_position", "cover.win", 40)]


async def test_cover_position_only():
    fake = FakeHAClient()
    await apply_command(fake, "cover.win", CoverCommand(position=0))
    assert fake.calls == [("set_cover_position", "cover.win", 0)]


async def test_climate_command_on_cover_entity_raises():
    with pytest.raises(CommandError):
        await apply_command(FakeHAClient(), "cover.win", SetCommand(mode="off"))


async def test_cover_command_on_climate_entity_raises():
    with pytest.raises(CommandError):
        await apply_command(
            FakeHAClient(), "climate.bedroom", CoverCommand(action="open")
        )


async def test_unknown_domain_raises():
    with pytest.raises(CommandError):
        await apply_command(FakeHAClient(), "light.kitchen", SetCommand(mode="off"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `../.venv/bin/pytest tests/test_commands.py -v`
Expected: FAIL — `ImportError: cannot import name 'CommandError'`.

- [ ] **Step 3: Implement — replace `app/commands.py` with**

```python
from pydantic import BaseModel, model_validator

from app.ha_client import HAClient


class CommandError(ValueError):
    """Raised when a command doesn't match the target entity's domain."""


class SetCommand(BaseModel):
    mode: str | None = None
    temperature: float | None = None

    @model_validator(mode="after")
    def at_least_one_field(self):
        if self.mode is None and self.temperature is None:
            raise ValueError("provide mode and/or temperature")
        return self


class CoverCommand(BaseModel):
    action: str | None = None
    position: int | None = None

    @model_validator(mode="after")
    def validate_command(self):
        if self.action is None and self.position is None:
            raise ValueError("provide action and/or position")
        if self.action is not None and self.action not in ("open", "close", "stop"):
            raise ValueError(f"action must be open, close or stop, got {self.action!r}")
        if self.position is not None and not 0 <= self.position <= 100:
            raise ValueError(f"position must be 0-100, got {self.position}")
        return self


async def apply_command(
    ha: HAClient, entity_id: str, cmd: SetCommand | CoverCommand
) -> None:
    if entity_id.startswith("climate."):
        if not isinstance(cmd, SetCommand):
            raise CommandError(f"{entity_id} requires a climate command")
        if cmd.mode == "on":
            await ha.turn_on(entity_id)
        elif cmd.mode is not None:
            await ha.set_hvac_mode(entity_id, cmd.mode)
        if cmd.temperature is not None:
            await ha.set_temperature(entity_id, cmd.temperature)
    elif entity_id.startswith("cover."):
        if not isinstance(cmd, CoverCommand):
            raise CommandError(f"{entity_id} requires a cover command")
        if cmd.action == "stop":
            await ha.stop_cover(entity_id)
        elif cmd.position is not None:
            await ha.set_cover_position(entity_id, cmd.position)
        elif cmd.action == "open":
            await ha.open_cover(entity_id)
        else:
            await ha.close_cover(entity_id)
    else:
        raise CommandError(f"unsupported entity domain: {entity_id}")
```

- [ ] **Step 4: Run the full suite**

Run: `../.venv/bin/pytest -q`
Expected: all pass (existing climate paths unchanged; all existing tests use `climate.*` IDs).

- [ ] **Step 5: Commit**

```bash
git add app/commands.py tests/test_commands.py
git commit -m "feat: CoverCommand and entity-domain dispatch in apply_command"
```

---

### Task 3: Config — `CoverPreset`, `.command()`/`domain`, `load_cover_presets`

**Files:**
- Modify: `ac_dashboard/app/config.py`
- Test: `ac_dashboard/tests/test_config.py`

**Interfaces:**
- Consumes: `SetCommand`, `CoverCommand` from `app.commands`.
- Produces: `CoverPreset(name, entities, action: str | None in {"open","close"}, position: int | None 0–100, time)` with `.id -> "cover:<slug>"`, `.command() -> CoverCommand`, class attr `domain = "cover"`. `Preset` gains class attr `domain = "climate"` and `.command() -> SetCommand`. `load_cover_presets(path="window_presets.yaml") -> list[CoverPreset]` (file shape `{"presets": [...]}`, missing file → `[]`, duplicate ids raise). Window groups need no new loader — `load_groups("window_groups.yaml")` reuses the existing one (file shape `{"groups": [...]}`).

- [ ] **Step 1: Write failing tests — append to `tests/test_config.py`**

```python
from app.commands import CoverCommand, SetCommand
from app.config import CoverPreset, load_cover_presets


def test_load_cover_presets_parses_yaml(tmp_path):
    f = tmp_path / "window_presets.yaml"
    f.write_text(
        "presets:\n"
        "  - name: Night close\n"
        "    entities: [cover.living_left, cover.living_right]\n"
        "    action: close\n"
        "    time: '22:00'\n"
    )
    (p,) = load_cover_presets(f)
    assert p.id == "cover:night_close"
    assert p.entities == ["cover.living_left", "cover.living_right"]
    assert p.action == "close"
    assert p.position is None
    assert p.time == "22:00"
    assert p.domain == "cover"


def test_load_cover_presets_missing_file_returns_empty(tmp_path):
    assert load_cover_presets(tmp_path / "nope.yaml") == []


def test_cover_preset_requires_action_or_position():
    with pytest.raises(ValueError, match="action and/or position"):
        CoverPreset(name="X", entities=["cover.x"], time="18:00")


def test_cover_preset_rejects_stop_action():
    with pytest.raises(ValueError, match="open or close"):
        CoverPreset(name="X", entities=["cover.x"], action="stop", time="18:00")


def test_cover_preset_rejects_position_out_of_range():
    with pytest.raises(ValueError, match="0-100"):
        CoverPreset(name="X", entities=["cover.x"], position=101, time="18:00")


def test_cover_preset_id_namespaced_away_from_climate():
    climate = Preset(name="Night", entities=["climate.x"], mode="off", time="22:00")
    cover = CoverPreset(name="Night", entities=["cover.x"], action="close", time="22:00")
    assert climate.id == "night"
    assert cover.id == "cover:night"


def test_duplicate_cover_preset_names_raise(tmp_path):
    f = tmp_path / "window_presets.yaml"
    f.write_text(
        "presets:\n"
        "  - {name: Same, entities: [cover.a], action: open, time: '08:00'}\n"
        "  - {name: same, entities: [cover.b], action: close, time: '09:00'}\n"
    )
    with pytest.raises(ValueError, match="Duplicate preset"):
        load_cover_presets(f)


def test_preset_command_builds_domain_command():
    climate = Preset(
        name="N", entities=["climate.x"], mode="heat", temperature=23.0, time="18:00"
    )
    cover = CoverPreset(name="N", entities=["cover.x"], position=20, time="18:00")
    assert climate.domain == "climate"
    assert climate.command() == SetCommand(mode="heat", temperature=23.0)
    assert cover.command() == CoverCommand(position=20)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `../.venv/bin/pytest tests/test_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'CoverPreset'`.

- [ ] **Step 3: Implement in `app/config.py`**

Add imports at the top:

```python
from typing import ClassVar

from app.commands import CoverCommand, SetCommand
```

In `Preset`, add after the `id` property:

```python
    domain: ClassVar[str] = "climate"

    def command(self) -> SetCommand:
        return SetCommand(mode=self.mode, temperature=self.temperature)
```

Add after the `Preset` class:

```python
class CoverPreset(BaseModel):
    name: str
    entities: list[str]
    action: str | None = None
    position: int | None = None
    time: str

    domain: ClassVar[str] = "cover"

    @model_validator(mode="after")
    def validate_preset(self):
        if not self.entities:
            raise ValueError("entities must be non-empty")
        if not _slug(self.name):
            raise ValueError("name must contain at least one letter or digit")
        if self.action is None and self.position is None:
            raise ValueError("provide action and/or position")
        if self.action is not None and self.action not in ("open", "close"):
            raise ValueError(f"action must be open or close, got {self.action!r}")
        if self.position is not None and not 0 <= self.position <= 100:
            raise ValueError(f"position must be 0-100, got {self.position}")
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", self.time):
            raise ValueError(f"time must be HH:MM, got {self.time!r}")
        return self

    @property
    def id(self) -> str:
        return f"cover:{_slug(self.name)}"

    def command(self) -> CoverCommand:
        return CoverCommand(action=self.action, position=self.position)
```

Refactor the preset loaders to share the file-reading logic (replaces the body of `load_presets`):

```python
def _load_preset_file(path: Path, model, label: str) -> list:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    try:
        presets = [model(**p) for p in data.get("presets", [])]
    except (TypeError, ValidationError) as exc:
        raise ValueError(f"Invalid {label} ({path}): {exc}") from exc
    ids = [p.id for p in presets]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"Duplicate preset ids in {path}: {duplicates}")
    return presets


def load_presets(path: str | Path = "presets.yaml") -> list[Preset]:
    return _load_preset_file(Path(path), Preset, "presets.yaml")


def load_cover_presets(path: str | Path = "window_presets.yaml") -> list[CoverPreset]:
    return _load_preset_file(Path(path), CoverPreset, "window_presets.yaml")
```

- [ ] **Step 4: Run the full suite**

Run: `../.venv/bin/pytest -q`
Expected: all pass (the existing `match="Invalid presets.yaml"` test still matches the label).

- [ ] **Step 5: Commit**

```bash
git add app/config.py tests/test_config.py
git commit -m "feat: CoverPreset with namespaced ids and per-domain preset commands"
```

---

### Task 4: State — cover mapping and `build_cover_groups`

**Files:**
- Modify: `ac_dashboard/app/state.py`
- Modify: `ac_dashboard/tests/conftest.py` (add `cover_ha_state` helper)
- Test: `ac_dashboard/tests/test_state.py`

**Interfaces:**
- Consumes: `Group` from `app.config`.
- Produces: `cover_from_ha_state(state: dict) -> dict` with keys `entity_id, name, state, position, supports_position, available`; `missing_cover(entity_id) -> dict` (same keys, unavailable); `build_cover_groups(cover_states, groups) -> list[dict]` (same `{name, units}` shape as `build_groups`, incl. Ungrouped). `tests.conftest.cover_ha_state(entity_id, state="closed", **attrs)` helper. `supports_position` = `supported_features & 4` (SET_POSITION) or non-null `current_position`.

- [ ] **Step 1: Add the conftest helper — in `tests/conftest.py` after `ha_state`**

```python
def cover_ha_state(entity_id, state="closed", **attrs):
    """Build an HA cover state dict like GET /api/states returns."""
    base = {
        "friendly_name": entity_id.split(".")[1].replace("_", " ").title(),
        "current_position": 0,
        "supported_features": 15,  # OPEN(1) | CLOSE(2) | SET_POSITION(4) | STOP(8)
    }
    base.update(attrs)
    return {"entity_id": entity_id, "state": state, "attributes": base}
```

- [ ] **Step 2: Write failing tests — append to `tests/test_state.py`**

```python
from app.state import build_cover_groups

from tests.conftest import cover_ha_state


def test_cover_fields_mapped_from_ha_state():
    states = [cover_ha_state("cover.living_left", state="open", current_position=40)]
    result = build_cover_groups(
        states, [Group(name="Living", entities=["cover.living_left"])]
    )
    assert result[0]["units"][0] == {
        "entity_id": "cover.living_left",
        "name": "Living Left",
        "state": "open",
        "position": 40,
        "supports_position": True,
        "available": True,
    }


def test_cover_without_position_support():
    # 11 = OPEN | CLOSE | STOP, no SET_POSITION
    states = [
        cover_ha_state("cover.basic", supported_features=11, current_position=None)
    ]
    result = build_cover_groups(states, [Group(name="G", entities=["cover.basic"])])
    unit = result[0]["units"][0]
    assert unit["supports_position"] is False
    assert unit["position"] is None


def test_unavailable_cover_maps_to_unavailable():
    states = [cover_ha_state("cover.win", state="unavailable")]
    result = build_cover_groups(states, [Group(name="G", entities=["cover.win"])])
    assert result[0]["units"][0]["available"] is False


def test_configured_cover_missing_from_ha_shows_as_unavailable():
    result = build_cover_groups([], [Group(name="G", entities=["cover.gone"])])
    unit = result[0]["units"][0]
    assert unit["entity_id"] == "cover.gone"
    assert unit["name"] == "Gone"
    assert unit["available"] is False
    assert unit["supports_position"] is False


def test_unlisted_covers_land_in_ungrouped_sorted_by_name():
    states = [cover_ha_state("cover.zeta"), cover_ha_state("cover.alpha"),
              cover_ha_state("cover.win")]
    groups = [Group(name="G", entities=["cover.win"])]
    result = build_cover_groups(states, groups)
    assert [g["name"] for g in result] == ["G", "Ungrouped"]
    assert [u["name"] for u in result[1]["units"]] == ["Alpha", "Zeta"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `../.venv/bin/pytest tests/test_state.py -v`
Expected: FAIL — `ImportError: cannot import name 'build_cover_groups'`.

- [ ] **Step 4: Implement in `app/state.py`**

Add after `missing_unit`:

```python
SUPPORT_SET_POSITION = 4  # cover supported_features flag


def cover_from_ha_state(state: dict) -> dict:
    attrs = state.get("attributes", {})
    features = attrs.get("supported_features") or 0
    position = attrs.get("current_position")
    return {
        "entity_id": state["entity_id"],
        "name": attrs.get("friendly_name", state["entity_id"]),
        "state": state.get("state"),
        "position": position,
        "supports_position": bool(features & SUPPORT_SET_POSITION)
        or position is not None,
        "available": state.get("state") not in ("unavailable", "unknown"),
    }


def missing_cover(entity_id: str) -> dict:
    """Placeholder for a window_groups entity that HA doesn't know about."""
    return {
        "entity_id": entity_id,
        "name": entity_id.removeprefix("cover.").replace("_", " ").title(),
        "state": None,
        "position": None,
        "supports_position": False,
        "available": False,
    }
```

Replace `build_groups` with a shared builder plus two thin wrappers:

```python
def _build(states: list[dict], groups: list[Group], state_fn, missing_fn) -> list[dict]:
    by_id = {s["entity_id"]: s for s in states}
    grouped_ids: set[str] = set()
    result = []
    for group in groups:
        units = []
        for entity_id in group.entities:
            grouped_ids.add(entity_id)
            state = by_id.get(entity_id)
            units.append(state_fn(state) if state else missing_fn(entity_id))
        result.append({"name": group.name, "units": units})

    ungrouped = sorted(
        (state_fn(s) for eid, s in by_id.items() if eid not in grouped_ids),
        key=lambda u: u["name"],
    )
    if ungrouped:
        result.append({"name": UNGROUPED, "units": ungrouped})
    return result


def build_groups(climate_states: list[dict], groups: list[Group]) -> list[dict]:
    return _build(climate_states, groups, unit_from_ha_state, missing_unit)


def build_cover_groups(cover_states: list[dict], groups: list[Group]) -> list[dict]:
    return _build(cover_states, groups, cover_from_ha_state, missing_cover)
```

- [ ] **Step 5: Run the full suite**

Run: `../.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/state.py tests/conftest.py tests/test_state.py
git commit -m "feat: cover state mapping and build_cover_groups"
```

---

### Task 5: Scheduler fires per-domain preset commands

**Files:**
- Modify: `ac_dashboard/app/scheduler.py:11-12,222-223`
- Test: `ac_dashboard/tests/test_scheduler.py`

**Interfaces:**
- Consumes: `Preset.command()` / `CoverPreset.command()` from Task 3, `apply_command` dispatch from Task 2.
- Produces: `Scheduler._fire` works for any preset object exposing `.command()`, `.entities`, `.id`. No signature changes.

- [ ] **Step 1: Write failing test — append to `tests/test_scheduler.py`**

```python
from app.config import CoverPreset

COVER_PRESET = CoverPreset(
    name="Night close",
    entities=["cover.a", "cover.b"],
    action="close",
    time="22:00",
)


async def test_cover_preset_fires_cover_commands(tmp_path):
    clock = Clock()
    ha = FakeHAClient()
    s = make_scheduler(tmp_path, clock, presets=(COVER_PRESET,), ha=ha)
    s.arm("cover:night_close", "2026-06-07", "14:00")
    clock.now = datetime(2026, 6, 7, 14, 0, 30, tzinfo=TZ)
    await s.check_due()
    assert ("close_cover", "cover.a") in ha.calls
    assert ("close_cover", "cover.b") in ha.calls
    assert s.armed == {}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `../.venv/bin/pytest tests/test_scheduler.py::test_cover_preset_fires_cover_commands -v`
Expected: FAIL — `CommandError` (or `ValidationError` constructing `SetCommand` from cover fields), because `_fire` hardcodes `SetCommand(mode=preset.mode, ...)`.

- [ ] **Step 3: Implement in `app/scheduler.py`**

Change the import at the top from:

```python
from app.commands import SetCommand, apply_command
```

to:

```python
from app.commands import apply_command
```

In `_fire`, replace:

```python
        cmd = SetCommand(mode=preset.mode, temperature=preset.temperature)
```

with:

```python
        cmd = preset.command()
```

Also loosen the `_fire` annotation from `preset: Preset` to just `preset` (both preset types flow through), and the `__init__` annotation `presets: list[Preset]` to `presets: list`.

- [ ] **Step 4: Run the full suite**

Run: `../.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add app/scheduler.py tests/test_scheduler.py
git commit -m "feat: scheduler fires per-domain preset commands"
```

---

### Task 6: API — cover endpoints, cover_groups state, domain-aware schedule

**Files:**
- Modify: `ac_dashboard/app/main.py`
- Modify: `ac_dashboard/tests/conftest.py` (make_client cover_groups override)
- Test: `ac_dashboard/tests/test_api.py`

**Interfaces:**
- Consumes: everything from Tasks 1–5.
- Produces: `POST /api/covers/{entity_id}/set` (body `CoverCommand`) → `{"ok": true}`; `POST /api/cover-groups/{name}/set` → `{total, succeeded, failed}`; `GET /api/state` → `{"groups": [...], "cover_groups": [...]}`; `GET /api/schedule` presets each carry `domain` plus `mode`/`temperature` (climate) or `action`/`position` (cover); `CommandError` → HTTP 400. Dependency `get_cover_groups(request)`. `make_client(fake_ha, groups=(), scheduler=None, cover_groups=())`.

- [ ] **Step 1: Update conftest `make_client`**

In `tests/conftest.py`, update the factory:

```python
@pytest.fixture
def make_client():
    """Returns a factory: make_client(fake_ha, groups, scheduler, cover_groups)."""
    from fastapi.testclient import TestClient

    from app.main import (
        app,
        get_cover_groups,
        get_groups,
        get_ha_client,
        get_scheduler,
    )

    def _make(fake_ha, groups=(), scheduler=None, cover_groups=()):
        app.dependency_overrides[get_ha_client] = lambda: fake_ha
        app.dependency_overrides[get_groups] = lambda: list(groups)
        app.dependency_overrides[get_cover_groups] = lambda: list(cover_groups)
        if scheduler is not None:
            app.dependency_overrides[get_scheduler] = lambda: scheduler
        return TestClient(app)

    yield _make
    from app.main import app as _app
    _app.dependency_overrides.clear()
```

- [ ] **Step 2: Write failing tests — append to `tests/test_api.py`**

```python
from app.config import CoverPreset
from tests.conftest import cover_ha_state

COVER_GROUPS = [Group(name="Living", entities=["cover.left", "cover.right"])]


def test_get_state_includes_cover_groups(make_client):
    fake = FakeHAClient(states=[
        ha_state("climate.bedroom"),
        cover_ha_state("cover.left", state="open", current_position=40),
    ])
    client = make_client(
        fake,
        [Group(name="Upstairs", entities=["climate.bedroom"])],
        cover_groups=[Group(name="Living", entities=["cover.left"])],
    )
    body = client.get("/api/state").json()
    assert body["groups"][0]["units"][0]["entity_id"] == "climate.bedroom"
    assert body["cover_groups"][0]["name"] == "Living"
    assert body["cover_groups"][0]["units"][0]["position"] == 40


def test_set_cover_action(make_client):
    fake = FakeHAClient()
    client = make_client(fake)
    resp = client.post("/api/covers/cover.left/set", json={"action": "open"})
    assert resp.status_code == 200
    assert fake.calls == [("open_cover", "cover.left")]


def test_set_cover_position(make_client):
    fake = FakeHAClient()
    client = make_client(fake)
    resp = client.post("/api/covers/cover.left/set", json={"position": 40})
    assert resp.status_code == 200
    assert fake.calls == [("set_cover_position", "cover.left", 40)]


def test_set_cover_empty_body_is_422(make_client):
    resp = make_client(FakeHAClient()).post("/api/covers/cover.left/set", json={})
    assert resp.status_code == 422


def test_set_cover_on_climate_entity_is_400(make_client):
    resp = make_client(FakeHAClient()).post(
        "/api/covers/climate.bedroom/set", json={"action": "open"}
    )
    assert resp.status_code == 400


def test_set_cover_group_fans_out(make_client):
    fake = FakeHAClient()
    client = make_client(fake, cover_groups=COVER_GROUPS)
    resp = client.post("/api/cover-groups/Living/set", json={"action": "close"})
    assert resp.status_code == 200
    assert resp.json() == {"total": 2, "succeeded": 2, "failed": []}
    assert sorted(fake.calls) == [
        ("close_cover", "cover.left"),
        ("close_cover", "cover.right"),
    ]


def test_set_cover_group_partial_failure(make_client):
    fake = FakeHAClient(fail_entities=["cover.right"])
    client = make_client(fake, cover_groups=COVER_GROUPS)
    resp = client.post("/api/cover-groups/Living/set", json={"action": "open"})
    assert resp.json() == {"total": 2, "succeeded": 1, "failed": ["cover.right"]}


def test_set_cover_group_unknown_is_404(make_client):
    client = make_client(FakeHAClient(), cover_groups=COVER_GROUPS)
    resp = client.post("/api/cover-groups/Kitchen/set", json={"action": "open"})
    assert resp.status_code == 404


COVER_SCHED_PRESET = CoverPreset(
    name="Night close", entities=["cover.left"], action="close", time="22:00"
)


def make_mixed_sched(tmp_path, fake_ha):
    return Scheduler(
        [SCHED_PRESET, COVER_SCHED_PRESET],
        fake_ha,
        tmp_path / "schedules.json",
        TZ,
        now=lambda: datetime(2026, 6, 7, 12, 0, tzinfo=TZ),
    )


def test_schedule_serializes_domain_fields(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_mixed_sched(tmp_path, fake))
    presets = {p["id"]: p for p in client.get("/api/schedule").json()["presets"]}
    climate = presets["evening_warmth"]
    assert climate["domain"] == "climate"
    assert climate["mode"] == "heat"
    assert climate["temperature"] == 23.0
    cover = presets["cover:night_close"]
    assert cover["domain"] == "cover"
    assert cover["action"] == "close"
    assert cover["position"] is None
    assert "mode" not in cover


def test_arm_and_cancel_cover_preset(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_mixed_sched(tmp_path, fake))
    resp = client.post(
        "/api/schedule/cover:night_close/arm",
        json={"date": "2026-06-08", "time": "22:00"},
    )
    assert resp.status_code == 200
    assert resp.json()["fires_at"].startswith("2026-06-08T22:00")
    resp = client.post("/api/schedule/cover:night_close/cancel")
    assert resp.status_code == 200
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `../.venv/bin/pytest tests/test_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'get_cover_groups' from 'app.main'`.

- [ ] **Step 4: Implement in `app/main.py`**

Update imports:

```python
from app.commands import CommandError, CoverCommand, SetCommand, apply_command
from app.config import Settings, load_cover_presets, load_groups, load_presets
from app.state import build_cover_groups, build_groups
```

In `lifespan`, after `app.state.groups = load_groups()`:

```python
    app.state.cover_groups = load_groups("window_groups.yaml")
```

and change the Scheduler construction to load both preset kinds:

```python
    app.state.scheduler = Scheduler(
        load_presets() + load_cover_presets(),
        app.state.ha_client,
        settings.schedules_path,
        tz,
    )
```

Add a dependency after `get_groups`:

```python
def get_cover_groups(request: Request) -> list:
    return request.app.state.cover_groups
```

Add an exception handler after `ha_error_handler`:

```python
@app.exception_handler(CommandError)
async def command_error_handler(request: Request, exc: CommandError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})
```

Extract the group fan-out (used by both group endpoints). Replace the body of `set_group` and add the cover endpoints:

```python
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
```

Replace the `get_state` endpoint:

```python
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
```

Replace `serialize_schedule`:

```python
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
```

- [ ] **Step 5: Run the full suite**

Run: `../.venv/bin/pytest -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add app/main.py tests/conftest.py tests/test_api.py
git commit -m "feat: cover endpoints, cover groups in state, domain-aware schedule API"
```

---

### Task 7: Frontend — extract shared.js (pure refactor, AC page unchanged)

**Files:**
- Create: `ac_dashboard/app/static/shared.js`
- Modify: `ac_dashboard/app/static/app.js`
- Modify: `ac_dashboard/app/static/index.html`

**Interfaces:**
- Consumes: `/api/schedule` presets now carrying `domain` (Task 6).
- Produces: `shared.js` (loaded before the page script) providing: constants `POLL_MS`, `PENDING_MS`, `DEBOUNCE_MS`, `DAY_CHIP_LABELS`, `DAY_NAMES`; globals `scheduleState`, `armForm`, `pendingSchedule`, `timers`; functions `setConnected(ok)`, `post(url, body)`, `el(tag, cls, text)`, `btn(label, cls, onClick)`, `clamp(v, lo, hi)`, `debounce(key, fn)`, `mergeSchedule(fresh)`, `renderSchedule()`, `armPreset(p)`, `cancelPreset(p)`, and the date/label helpers. Each page script must define a global `const PAGE = { domain, presetsHint, presetSummary }` and a global `render()` before polling starts; `renderSchedule` filters presets by `PAGE.domain` and renders summaries via `PAGE.presetSummary(p)`.

- [ ] **Step 1: Create `app/static/shared.js`**

The schedule/date/helper functions are MOVED VERBATIM from the current `app.js` (only the two `PAGE.*` references and the domain filter are new):

```javascript
// Shared between pages. Each page script defines:
//   const PAGE = { domain, presetsHint, presetSummary };  // page identity
//   function render() { ... }                              // full re-render
// and is loaded AFTER this file.

const POLL_MS = 5000;
const PENDING_MS = 4000; // ignore poll data for a unit this long after a local change
const DEBOUNCE_MS = 600; // wait for stepper taps to settle before sending

const DAY_CHIP_LABELS = ["M", "T", "W", "T", "F", "S", "S"]; // Mon=0 .. Sun=6
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const timers = {}; // debounce timers, keyed by entity_id or "group:<name>"

let scheduleState = { presets: [] };
const armForm = {};         // preset id -> form state (survives re-renders)
const pendingSchedule = {}; // preset id -> suppress-poll-until timestamp

// ---- connection + fetch ----

function setConnected(ok) {
  document.getElementById("status-dot").classList.toggle("ok", ok);
  document.getElementById("banner").classList.toggle("hidden", ok);
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
    return await resp.json();
  } catch {
    setConnected(false);
    return null;
  }
}

// ---- DOM helpers ----

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

function debounce(key, fn) {
  clearTimeout(timers[key]);
  timers[key] = setTimeout(fn, DEBOUNCE_MS);
}

// ---- schedule tab ----

function mergeSchedule(fresh) {
  const now = Date.now();
  const old = {};
  for (const p of scheduleState.presets) old[p.id] = p;
  fresh.presets = fresh.presets.map((p) =>
    (pendingSchedule[p.id] || 0) > now && old[p.id] ? old[p.id] : p
  );
  scheduleState = fresh;
}

function renderSchedule() {
  const main = document.getElementById("schedule");
  const presets = scheduleState.presets.filter((p) => p.domain === PAGE.domain);
  if (!presets.length) {
    main.replaceChildren(el("p", "hint", PAGE.presetsHint));
    return;
  }
  main.replaceChildren(...presets.map(renderPreset));
}

function renderPreset(p) {
  const card = el("div", "card preset");
  card.append(el("div", "unit-name", p.name));
  card.append(el("div", "preset-summary", PAGE.presetSummary(p)));
  const row = el("div", "arm-row");
  if (p.armed) {
    const label =
      p.armed.type === "weekly"
        ? `Repeats ${dayRangeLabel(p.armed.days)} at ${p.armed.time} · next ${nextLabel(p.armed.next_fire)}`
        : firesLabel(p.armed.fires_at);
    row.append(el("span", "fires", label));
    row.append(btn("Cancel", "ctl cancel", () => cancelPreset(p)));
  } else {
    const form = armForm[p.id] ?? (armForm[p.id] = {
      mode: "once",
      day: timePassedToday(p.time) ? "tomorrow" : "today",
      time: p.time,
      days: [0, 1, 2, 3, 4, 5, 6],
    });
    const modeRow = el("div", "mode-toggle");
    for (const [value, label] of [["once", "Once"], ["repeat", "Repeat"]]) {
      const b = btn(label, "mode-opt", () => { form.mode = value; render(); });
      if (form.mode === value) b.classList.add("active");
      modeRow.append(b);
    }
    card.append(modeRow);
    if (form.mode === "repeat") {
      const chips = el("div", "day-chips");
      for (let d = 0; d < 7; d++) {
        const chip = btn(DAY_CHIP_LABELS[d], "day-chip", () => {
          form.days = form.days.includes(d)
            ? form.days.filter((x) => x !== d)
            : [...form.days, d];
          render();
        });
        if (form.days.includes(d)) chip.classList.add("active");
        chips.append(chip);
      }
      card.append(chips);
      const timeInput = document.createElement("input");
      timeInput.type = "time";
      timeInput.value = form.time;
      timeInput.addEventListener("change", () => { form.time = timeInput.value; });
      const armBtn = btn("Arm", "ctl arm", () => armPreset(p));
      armBtn.disabled = !form.days.length;
      row.append(timeInput, armBtn);
    } else {
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
  }
  card.append(row);
  return card;
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

function dayRangeLabel(days) {
  if (days.length === 7) return "every day";
  const sorted = [...days].sort((a, b) => a - b);
  const contiguous = sorted.every((d, i) => i === 0 || d === sorted[i - 1] + 1);
  if (contiguous && sorted.length > 2) {
    return `${DAY_NAMES[sorted[0]]}–${DAY_NAMES[sorted[sorted.length - 1]]}`;
  }
  return sorted.map((d) => DAY_NAMES[d]).join(", ");
}

function nextLabel(iso) {
  const day = iso.slice(0, 10);
  if (day === isoDate(0)) return "today";
  if (day === isoDate(1)) return "tomorrow";
  return day;
}

function nextFireIso(days, time) {
  for (let offset = 0; offset < 8; offset++) {
    const d = new Date(Date.now() + offset * 86400000);
    const apiDay = (d.getDay() + 6) % 7; // JS Sun=0 -> API Mon=0
    if (!days.includes(apiDay)) continue;
    if (offset === 0 && timePassedToday(time)) continue;
    return `${isoDate(offset)}T${time}:00`;
  }
  return `${isoDate(0)}T${time}:00`; // fallback; poll reconciles
}

async function armPreset(p) {
  const form = armForm[p.id];
  if (!form.time) return;
  let body;
  let optimistic;
  if (form.mode === "repeat") {
    if (!form.days.length) return;
    const days = [...form.days].sort((a, b) => a - b);
    body = { repeat: days, time: form.time };
    optimistic = {
      type: "weekly",
      days,
      time: form.time,
      next_fire: nextFireIso(days, form.time),
    };
  } else {
    const date = isoDate(form.day === "tomorrow" ? 1 : 0);
    body = { date, time: form.time };
    optimistic = { type: "once", fires_at: `${date}T${form.time}:00` };
  }
  p.armed = optimistic;
  pendingSchedule[p.id] = Date.now() + PENDING_MS;
  render();
  const resp = await post(`/api/schedule/${p.id}/arm`, body);
  if (!resp) {
    p.armed = null;
    delete pendingSchedule[p.id];
    render();
  }
}

async function cancelPreset(p) {
  const previous = p.armed;
  p.armed = null;
  pendingSchedule[p.id] = Date.now() + PENDING_MS;
  render();
  const body = await post(`/api/schedule/${p.id}/cancel`, {});
  if (!body) {
    p.armed = previous;
    delete pendingSchedule[p.id];
    render();
  }
}
```

- [ ] **Step 2: Rewrite `app/static/app.js` to only the AC-specific code**

Replace the whole file with (everything below already exists in the current file; only the `PAGE` const is new — nothing else may change):

```javascript
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
const groupTemps = {};   // group name -> locally chosen group target temp
const groupMsgs = {};    // group name -> {text, until} transient result message

const PAGE = {
  domain: "climate",
  presetsHint:
    "No presets configured. Add a presets: section in the add-on configuration.",
  presetSummary,
};

// ---- polling ----

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

// ---- commands ----

function markPending(entityId) {
  pendingUntil[entityId] = Date.now() + PENDING_MS;
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
  post(`/api/groups/${encodeURIComponent(group.name)}/set`, { mode: "off" })
    .then((body) => reportGroupResult(group.name, body));
}

function groupAllOn(group) {
  // climate.turn_on restores each unit's previous mode — we can't predict it,
  // so no optimistic update; the next poll (≤5 s) shows the result.
  post(`/api/groups/${encodeURIComponent(group.name)}/set`, { mode: "on" })
    .then((body) => reportGroupResult(group.name, body));
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
      .then((body) => reportGroupResult(group.name, body))
  );
}

function reportGroupResult(name, body) {
  if (!body || !body.failed || !body.failed.length) return;
  groupMsgs[name] = {
    text: `${body.succeeded} of ${body.total} units updated`,
    until: Date.now() + 6000,
  };
  render();
}

// ---- rendering ----

function render() {
  document
    .getElementById("groups")
    .replaceChildren(...state.groups.map(renderGroup));
  renderSchedule();
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
    const msg = groupMsgs[group.name];
    if (msg && msg.until > Date.now()) {
      header.append(el("span", "group-msg", msg.text));
    }
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

function avgTarget(units) {
  const temps = units.map((u) => u.target_temp).filter((t) => t != null);
  if (!temps.length) return null;
  return Math.round((temps.reduce((a, b) => a + b, 0) / temps.length) * 2) / 2;
}

function showTab(name) {
  document.getElementById("groups").classList.toggle("hidden", name !== "control");
  document.getElementById("schedule").classList.toggle("hidden", name !== "schedule");
  document.getElementById("tab-control").classList.toggle("active", name === "control");
  document.getElementById("tab-schedule").classList.toggle("active", name === "schedule");
}

document.getElementById("tab-control").addEventListener("click", () => showTab("control"));
document.getElementById("tab-schedule").addEventListener("click", () => showTab("schedule"));

poll();
setInterval(poll, POLL_MS);
```

- [ ] **Step 3: Load shared.js in `index.html`**

Replace `<script src="/app.js"></script>` with:

```html
  <script src="/shared.js"></script>
  <script src="/app.js"></script>
```

- [ ] **Step 4: Verify**

Run: `node --check app/static/shared.js && node --check app/static/app.js && ../.venv/bin/pytest -q`
Expected: no syntax errors; all tests pass.

Optional manual check (needs reachable HA in `.env`): `../.venv/bin/uvicorn app.main:app --port 8088`, open `http://localhost:8088` — AC page must look and behave exactly as before (control tab, schedule tab, arming).

- [ ] **Step 5: Commit**

```bash
git add app/static/shared.js app/static/app.js app/static/index.html
git commit -m "refactor: extract shared frontend helpers and schedule tab into shared.js"
```

---

### Task 8: Frontend — Windows page and page navigation

**Files:**
- Create: `ac_dashboard/app/static/windows.html`
- Create: `ac_dashboard/app/static/windows.js`
- Modify: `ac_dashboard/app/static/index.html` (page nav, title)
- Modify: `ac_dashboard/app/static/style.css` (append page-nav + cover styles)

**Interfaces:**
- Consumes: `shared.js` contract from Task 7; `/api/state` `cover_groups`, `/api/covers/...`, `/api/cover-groups/...` from Task 6.
- Produces: `GET /windows.html` — the Windows page.

- [ ] **Step 1: Create `app/static/windows.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="theme-color" content="#2e86de">
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="default">
  <title>Home Dashboard — Windows</title>
  <link rel="manifest" href="/manifest.webmanifest">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <link rel="icon" type="image/png" href="/icon-192.png">
  <link rel="stylesheet" href="/style.css">
</head>
<body>
  <header>
    <nav class="pages">
      <a href="/" class="page-link">AC</a>
      <a href="/windows.html" class="page-link active">Windows</a>
    </nav>
    <span id="status-dot" class="dot" title="Connection to Home Assistant"></span>
  </header>
  <nav class="tabs">
    <button id="tab-control" class="tab active">Control</button>
    <button id="tab-schedule" class="tab">Schedule</button>
  </nav>
  <div id="banner" class="banner hidden">Can't reach Home Assistant</div>
  <main id="groups"></main>
  <main id="schedule" class="hidden"></main>
  <script src="/shared.js"></script>
  <script src="/windows.js"></script>
</body>
</html>
```

- [ ] **Step 2: Create `app/static/windows.js`**

```javascript
const UNGROUPED = "Ungrouped";

const STATE_LABELS = {
  open: "Open",
  closed: "Closed",
  opening: "Opening…",
  closing: "Closing…",
};

let state = { cover_groups: [] };
const pendingUntil = {}; // entity_id -> ms timestamp
const groupMsgs = {};    // group name -> {text, until} transient result message

const PAGE = {
  domain: "cover",
  presetsHint:
    "No window presets configured. Add a window_presets: section in the add-on configuration.",
  presetSummary,
};

// ---- polling ----

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

// Keep locally-changed covers as-is until their pending window expires,
// so optimistic updates aren't reverted by an in-flight poll.
function mergeState(fresh) {
  const now = Date.now();
  const oldCovers = {};
  for (const g of state.cover_groups)
    for (const c of g.units) oldCovers[c.entity_id] = c;
  for (const g of fresh.cover_groups) {
    g.units = g.units.map((c) =>
      (pendingUntil[c.entity_id] || 0) > now && oldCovers[c.entity_id]
        ? oldCovers[c.entity_id]
        : c
    );
  }
  state = fresh;
}

// ---- commands ----

function markPending(entityId) {
  pendingUntil[entityId] = Date.now() + PENDING_MS;
}

function coverAction(cover, action) {
  if (action === "open") cover.state = "opening";
  else if (action === "close") cover.state = "closing";
  if (action !== "stop") markPending(cover.entity_id);
  render();
  post(`/api/covers/${cover.entity_id}/set`, { action });
}

function setCoverPosition(cover, position) {
  cover.position = position;
  markPending(cover.entity_id);
  render();
  post(`/api/covers/${cover.entity_id}/set`, { position });
}

function groupAction(group, action) {
  for (const c of group.units) {
    if (action === "open") c.state = "opening";
    else c.state = "closing";
    markPending(c.entity_id);
  }
  render();
  post(`/api/cover-groups/${encodeURIComponent(group.name)}/set`, { action })
    .then((body) => reportGroupResult(group.name, body));
}

function reportGroupResult(name, body) {
  if (!body || !body.failed || !body.failed.length) return;
  groupMsgs[name] = {
    text: `${body.succeeded} of ${body.total} windows updated`,
    until: Date.now() + 6000,
  };
  render();
}

// ---- rendering ----

function render() {
  document
    .getElementById("groups")
    .replaceChildren(...state.cover_groups.map(renderGroup));
  renderSchedule();
}

function renderGroup(group) {
  const section = el("section", "group");
  const header = el("div", "group-header");
  header.append(el("h2", "", group.name));
  if (group.name !== UNGROUPED) {
    const controls = el("div", "group-controls");
    controls.append(
      btn("Open all", "ctl", () => groupAction(group, "open")),
      btn("Close all", "ctl", () => groupAction(group, "close"))
    );
    header.append(controls);
    const msg = groupMsgs[group.name];
    if (msg && msg.until > Date.now()) {
      header.append(el("span", "group-msg", msg.text));
    }
  }
  section.append(header, ...group.units.map(renderCover));
  return section;
}

function renderCover(cover) {
  const card = el("div", "card");
  card.dataset.state = cover.available ? cover.state : "unavailable";
  if (!cover.available) card.classList.add("unavailable");

  const top = el("div", "card-top");
  top.append(
    el("span", "unit-name", cover.name),
    el("span", "cover-state", stateLabel(cover))
  );
  card.append(top);

  const buttons = el("div", "cover-btns");
  for (const [action, label] of [
    ["open", "▲ Open"],
    ["stop", "■ Stop"],
    ["close", "▼ Close"],
  ]) {
    const b = btn(label, "cover-btn", () => coverAction(cover, action));
    b.disabled = !cover.available;
    buttons.append(b);
  }
  card.append(buttons);

  if (cover.supports_position) {
    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = 0;
    slider.max = 100;
    slider.value = cover.position ?? 0;
    slider.className = "position";
    slider.disabled = !cover.available;
    slider.addEventListener("change", () =>
      setCoverPosition(cover, Number(slider.value))
    );
    card.append(slider);
  }
  return card;
}

function stateLabel(cover) {
  if (!cover.available) return "Unavailable";
  const label = STATE_LABELS[cover.state] ?? cover.state ?? "–";
  if (cover.position != null && cover.position > 0 && cover.position < 100) {
    return `${label} · ${cover.position}%`;
  }
  return label;
}

// ---- helpers ----

function presetSummary(p) {
  const parts = [];
  if (p.action) parts.push(p.action === "open" ? "Open" : "Close");
  if (p.position != null) parts.push(`${p.position}%`);
  return `${parts.join(" to ")} — ${p.entities.map(coverName).join(", ")}`;
}

function coverName(entityId) {
  for (const g of state.cover_groups)
    for (const c of g.units)
      if (c.entity_id === entityId) return c.name;
  return entityId;
}

function showTab(name) {
  document.getElementById("groups").classList.toggle("hidden", name !== "control");
  document.getElementById("schedule").classList.toggle("hidden", name !== "schedule");
  document.getElementById("tab-control").classList.toggle("active", name === "control");
  document.getElementById("tab-schedule").classList.toggle("active", name === "schedule");
}

document.getElementById("tab-control").addEventListener("click", () => showTab("control"));
document.getElementById("tab-schedule").addEventListener("click", () => showTab("schedule"));

poll();
setInterval(poll, POLL_MS);
```

- [ ] **Step 3: Add the page nav to `index.html`**

Replace:

```html
  <title>AC Control</title>
```

with:

```html
  <title>Home Dashboard — AC</title>
```

and replace:

```html
  <header>
    <h1>AC Control</h1>
    <span id="status-dot" class="dot" title="Connection to Home Assistant"></span>
  </header>
```

with:

```html
  <header>
    <nav class="pages">
      <a href="/" class="page-link active">AC</a>
      <a href="/windows.html" class="page-link">Windows</a>
    </nav>
    <span id="status-dot" class="dot" title="Connection to Home Assistant"></span>
  </header>
```

- [ ] **Step 4: Append cover styles to `app/static/style.css`**

```css
/* ---- page navigation (AC | Windows) ---- */

.pages { display: flex; gap: 6px; }
.page-link {
  padding: 8px 16px;
  border-radius: 8px;
  text-decoration: none;
  color: var(--muted);
  font-weight: 600;
}
.page-link.active { background: #e3e7ee; color: var(--text); }

/* ---- windows page ---- */

.cover-state { color: var(--muted); }

.card[data-state="open"],
.card[data-state="opening"] { border-left-color: var(--accent-cool); }
.card[data-state="closing"] { border-left-color: var(--accent-heat); }

.cover-btns {
  display: flex;
  gap: 8px;
  margin-top: 12px;
}
.cover-btns .cover-btn {
  flex: 1;
  padding: 12px 0;
  font-weight: 600;
}

input[type="range"].position {
  width: 100%;
  margin: 14px 0 4px;
  accent-color: var(--accent-cool);
}
```

- [ ] **Step 5: Verify**

Run: `node --check app/static/windows.js && ../.venv/bin/pytest -q`
Expected: no syntax errors; all tests pass.

Optional manual check (needs reachable HA): start uvicorn, open `http://localhost:8088/windows.html` — covers appear (Ungrouped without local `window_groups.yaml`), buttons post to `/api/covers/...`, nav links switch pages.

- [ ] **Step 6: Commit**

```bash
git add app/static/windows.html app/static/windows.js app/static/index.html app/static/style.css
git commit -m "feat: windows page with cover controls, slider, and page navigation"
```

---

### Task 9: Packaging — rename to Home Dashboard, options schema, docs, v1.4.0

**Files:**
- Modify: `ac_dashboard/config.yaml`
- Modify: `ac_dashboard/run.sh`
- Modify: `ac_dashboard/app/static/manifest.webmanifest`
- Create: `ac_dashboard/window_groups.yaml.example`, `ac_dashboard/window_presets.yaml.example`
- Modify: `ac_dashboard/DOCS.md`, `ac_dashboard/CHANGELOG.md`, `README.md` (repo root)

**Interfaces:**
- Consumes: `window_groups.yaml` / `window_presets.yaml` file shapes from Task 3 (`{"groups": [...]}` / `{"presets": [...]}`).
- Produces: the released 1.4.0 add-on.

- [ ] **Step 1: Update `config.yaml`**

Change the top fields:

```yaml
name: Home Dashboard
version: "1.4.0"
slug: ac_dashboard
description: Simple web pages for controlling AC units and motorized windows — no HA login needed
```

(`slug` MUST stay `ac_dashboard`.) In `options:` add after `presets: []`:

```yaml
  window_groups: []
  window_presets: []
```

In `schema:` add after the `presets` block (same indentation as `groups`/`presets`):

```yaml
  window_groups:
    - name: str
      entities:
        - str
  window_presets:
    - name: str
      entities:
        - str
      action: str?
      position: int?
      time: str
```

- [ ] **Step 2: Update `run.sh`**

Replace the embedded Python block with (adds the two window files; time-fix now shared):

```python
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
```

Also change the two `bashio::log.info "Starting AC Dashboard..."` lines to say `Home Dashboard`, and the header comment `# Entrypoint for the AC Dashboard add-on.` to `# Entrypoint for the Home Dashboard add-on.`

- [ ] **Step 3: Update `app/static/manifest.webmanifest`**

```json
{
  "name": "Home Dashboard",
  "short_name": "Home",
  "display": "standalone",
  "start_url": "/",
  "background_color": "#f2f4f7",
  "theme_color": "#2e86de",
  "icons": [
    { "src": "/icon-192.png", "sizes": "192x192", "type": "image/png" },
    { "src": "/icon-512.png", "sizes": "512x512", "type": "image/png" }
  ]
}
```

- [ ] **Step 4: Create the local-dev example files**

`window_groups.yaml.example`:

```yaml
# Copy to window_groups.yaml and edit. Cover entities not listed here still
# appear under an "Ungrouped" section on the Windows page.
groups:
  - name: Living room
    entities:
      - cover.living_left
      - cover.living_right
```

`window_presets.yaml.example`:

```yaml
# Local development only — the add-on generates window_presets.yaml from its options.
presets:
  - name: Night close
    entities:
      - cover.living_left
      - cover.living_right
    action: close       # open | close — or omit if position is given
    position: 20        # optional 0–100; wins over action when both are set
    time: "22:00"
```

- [ ] **Step 5: Update `DOCS.md`**

- Retitle `# AC Dashboard` → `# Home Dashboard` and change the intro sentence to: `Simple web pages for controlling your AC units (any climate.* entities in Home Assistant) and motorized windows (any cover.* entities, e.g. Somfy TaHoma via the Overkiz integration) — large touch targets, no HA login, made for family use on phones.`
- After the `## Configuration` groups example, add:

````markdown
## Windows

The **Windows** page (top navigation) controls `cover.*` entities: open /
stop / close buttons, and a 0–100 % position slider for windows that support
it. Configure window groups the same way as AC groups:

```yaml
window_groups:
  - name: Living room
    entities:
      - cover.living_left
      - cover.living_right
```

Any cover entity not listed still appears under "Ungrouped" on the Windows
page.
````

- After the `## Schedule presets` example block, add:

````markdown
Window schedules work the same way with `window_presets` (shown on the
Windows page's Schedule tab):

```yaml
window_presets:
  - name: Night close
    entities:
      - cover.living_left
      - cover.living_right
    action: close       # open | close — or omit if position is given
    position: 20        # optional 0–100; wins over action when both are set
    time: "22:00"
```
````

- In `## Security`, change "can control your AC units" to "can control your AC units and windows".

- [ ] **Step 6: Update `CHANGELOG.md` and root `README.md`**

Prepend to `CHANGELOG.md`:

```markdown
## 1.4.0

- Renamed to **Home Dashboard** — now controls motorized windows as well as AC
- New **Windows** page: open/stop/close, position slider, window groups
  (`window_groups` option)
- Window schedule presets (`window_presets` option) with Once/Repeat arming,
  sharing the scheduler with AC presets
- Existing AC configuration and armed schedules carry over unchanged
```

In root `README.md`: change the title to `# Home Dashboard — Home Assistant App`, the intro to mention AC units and motorized windows (cover entities), and the install step 3 text `open **AC Dashboard**` → `open **Home Dashboard**`.

- [ ] **Step 7: Verify and commit**

Run: `../.venv/bin/pytest -q && bash -n run.sh && python3 -c "import yaml; yaml.safe_load(open('config.yaml'))"`
Expected: tests pass, run.sh parses, config.yaml is valid YAML.

```bash
cd ..
git add ac_dashboard/config.yaml ac_dashboard/run.sh ac_dashboard/app/static/manifest.webmanifest \
  ac_dashboard/window_groups.yaml.example ac_dashboard/window_presets.yaml.example \
  ac_dashboard/DOCS.md ac_dashboard/CHANGELOG.md README.md
git commit -m "feat: add-on v1.4.0 — Home Dashboard with windows page"
```
