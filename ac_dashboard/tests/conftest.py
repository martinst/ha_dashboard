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


def cover_ha_state(entity_id, state="closed", **attrs):
    """Build an HA cover state dict like GET /api/states returns."""
    base = {
        "friendly_name": entity_id.split(".")[1].replace("_", " ").title(),
        "current_position": 0,
        "supported_features": 15,  # OPEN(1) | CLOSE(2) | SET_POSITION(4) | STOP(8)
    }
    base.update(attrs)
    return {"entity_id": entity_id, "state": state, "attributes": base}


def lock_ha_state(entity_id, state="locked", **attrs):
    """Build an HA lock state dict like GET /api/states returns."""
    base = {
        "friendly_name": entity_id.split(".")[1].replace("_", " ").title(),
        "supported_features": 0,
    }
    base.update(attrs)
    return {"entity_id": entity_id, "state": state, "attributes": base}


def lock_discovery(door_id, name):
    """(topic, payload) pair as the inception-mqtt add-on retains it."""
    import json as _json
    return (
        f"homeassistant/lock/{door_id}/config",
        _json.dumps({
            "name": name,
            "state_topic": f"inception/lock/{door_id}",
            "command_topic": f"inception/lock/{door_id}/set",
            "payload_lock": "Lock",
            "payload_unlock": "Unlock",
        }),
    )


def sensor_ha_state(entity_id, state="21.5", **attrs):
    """Build an HA temperature sensor state dict (e.g. an Ecowitt console)."""
    base = {
        "friendly_name": entity_id.split(".")[1].replace("_", " ").title(),
        "device_class": "temperature",
        "unit_of_measurement": "°C",
    }
    base.update(attrs)
    return {"entity_id": entity_id, "state": state, "attributes": base}


class FakeHAClient:
    """In-memory stand-in for HAClient; records service calls."""

    def __init__(self, states=None, fail_entities=(), fail_states=False,
                 statistics=None, fail_statistics=False):
        self.states = states or []
        self.fail_entities = set(fail_entities)
        self.fail_states = fail_states
        self.statistics = statistics or {}  # entity_id -> statistics rows
        self.fail_statistics = fail_statistics
        self.calls = []
        self.statistics_calls = []  # (statistic_ids, start, period)
        self.mqtt_retained = []  # [(topic, payload)] returned by mqtt_subscribe_retained
        self.fail_mqtt_subscribe = False
        self.mqtt_subscriptions = []

    async def mqtt_publish(self, topic, payload):
        self.calls.append(("mqtt_publish", topic, payload))

    async def mqtt_subscribe_retained(self, topic, wait=2.0):
        import asyncio
        self.mqtt_subscriptions.append(topic)
        await asyncio.sleep(0)  # yield like a real network call would
        if self.fail_mqtt_subscribe:
            raise HAError("not admin")
        return list(self.mqtt_retained)

    async def get_statistics(self, statistic_ids, start, period):
        self.statistics_calls.append((list(statistic_ids), start, period))
        if self.fail_statistics:
            raise HAError("HA unreachable")
        return {i: self.statistics[i] for i in statistic_ids if i in self.statistics}

    async def get_states(self):
        if self.fail_states:
            raise HAError("HA unreachable")
        return self.states

    async def set_hvac_mode(self, entity_id, mode):
        self._record(("set_hvac_mode", entity_id, mode), entity_id)

    async def set_temperature(self, entity_id, temperature):
        self._record(("set_temperature", entity_id, temperature), entity_id)

    async def turn_on(self, entity_id):
        self._record(("turn_on", entity_id), entity_id)

    async def open_cover(self, entity_id):
        self._record(("open_cover", entity_id), entity_id)

    async def close_cover(self, entity_id):
        self._record(("close_cover", entity_id), entity_id)

    async def stop_cover(self, entity_id):
        self._record(("stop_cover", entity_id), entity_id)

    async def set_cover_position(self, entity_id, position):
        self._record(("set_cover_position", entity_id, position), entity_id)

    async def lock(self, entity_id):
        self._record(("lock", entity_id), entity_id)

    async def unlock(self, entity_id):
        self._record(("unlock", entity_id), entity_id)

    def _record(self, call, entity_id):
        if entity_id in self.fail_entities:
            raise HAError("HA unreachable")
        self.calls.append(call)


ALLOWED = ["martin@example.com", "maria@example.com"]


def fake_google(email="martin@example.com", verified=True, token_status=200):
    """httpx transport standing in for Google's token + userinfo endpoints."""
    import httpx

    seen = {"token_requests": [], "userinfo_auth": []}

    def handler(request):
        if request.url.host == "oauth2.googleapis.com" and request.url.path == "/token":
            seen["token_requests"].append(dict(httpx.QueryParams(request.content.decode())))
            if token_status != 200:
                return httpx.Response(token_status, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "at-123", "token_type": "Bearer"})
        if request.url.host == "openidconnect.googleapis.com":
            seen["userinfo_auth"].append(request.headers.get("Authorization"))
            return httpx.Response(200, json={"sub": "1", "email": email, "email_verified": verified})
        return httpx.Response(404)

    return httpx.MockTransport(handler), seen


def make_auth(tmp_path, transport=None, allowed=ALLOWED, client_id="cid", secret="csecret"):
    from app.auth import Auth, SessionSigner, load_or_create_secret

    signer = SessionSigner(load_or_create_secret(tmp_path / "session_secret"))
    return Auth(
        client_id=client_id,
        client_secret=secret,
        allowed_emails=allowed,
        signer=signer,
        transport=transport,
    )


@pytest.fixture
def make_client():
    """Returns a factory: make_client(fake_ha, groups, scheduler, cover_groups,
    sensors, door_groups, auth)."""
    from fastapi.testclient import TestClient

    from app.config import SensorConfig
    from app.main import (
        app,
        get_auth,
        get_cover_groups,
        get_door_groups,
        get_door_topics,
        get_groups,
        get_ha_client,
        get_history_cache,
        get_scheduler,
        get_sensor_config,
    )

    def _make(fake_ha, groups=(), scheduler=None, cover_groups=(), sensors=None,
              door_groups=(), auth=None):
        app.dependency_overrides[get_ha_client] = lambda: fake_ha
        app.dependency_overrides[get_groups] = lambda: list(groups)
        app.dependency_overrides[get_cover_groups] = lambda: list(cover_groups)
        app.dependency_overrides[get_door_groups] = lambda: list(door_groups)
        app.dependency_overrides[get_auth] = lambda: auth
        # The lifespan (and its background refresh) doesn't run under
        # TestClient; load the fake's discovery configs once, like startup would.
        import asyncio as _asyncio
        from app.doors import DoorTopics
        topics = DoorTopics()
        if getattr(fake_ha, "mqtt_retained", None):
            _asyncio.run(topics.refresh(fake_ha))
            fake_ha.mqtt_subscriptions.clear()
        app.dependency_overrides[get_door_topics] = lambda: topics
        app.dependency_overrides[get_sensor_config] = lambda: sensors or SensorConfig()
        cache = {}
        app.dependency_overrides[get_history_cache] = lambda: cache
        if scheduler is not None:
            app.dependency_overrides[get_scheduler] = lambda: scheduler
        return TestClient(app)

    yield _make
    from app.main import app as _app
    _app.dependency_overrides.clear()
