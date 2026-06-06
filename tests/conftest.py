import pytest

from app.ha_client import HAError


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
    from fastapi.testclient import TestClient

    from app.main import app, get_groups, get_ha_client

    def _make(fake_ha, groups=()):
        app.dependency_overrides[get_ha_client] = lambda: fake_ha
        app.dependency_overrides[get_groups] = lambda: list(groups)
        return TestClient(app)

    yield _make
    from app.main import app as _app
    _app.dependency_overrides.clear()
