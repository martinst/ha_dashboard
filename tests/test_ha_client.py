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
