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
        await make_ha_client(handler).get_states()


async def test_connection_error_raises_haerror():
    def handler(request):
        raise httpx.ConnectError("connection refused")

    with pytest.raises(HAError):
        await make_ha_client(handler).get_states()


async def test_non_json_response_raises_haerror():
    def handler(request):
        return httpx.Response(200, text="<html>not json</html>")

    with pytest.raises(HAError):
        await make_ha_client(handler).get_states()


async def test_get_config_fetches_api_config():
    def handler(request):
        assert request.url.path == "/api/config"
        return httpx.Response(200, json={"time_zone": "Europe/Stockholm"})

    config = await make_ha_client(handler).get_config()
    assert config["time_zone"] == "Europe/Stockholm"


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


import asyncio

import websockets

from datetime import datetime, timezone


async def fake_ha_ws(received, result):
    """Serve one HA-style websocket session: auth handshake, one command."""

    async def handler(ws):
        await ws.send(json.dumps({"type": "auth_required", "ha_version": "2026.7.2"}))
        auth = json.loads(await ws.recv())
        received["auth"] = auth
        if auth.get("access_token") != "secret-token":
            await ws.send(json.dumps({"type": "auth_invalid", "message": "bad token"}))
            return
        await ws.send(json.dumps({"type": "auth_ok", "ha_version": "2026.7.2"}))
        cmd = json.loads(await ws.recv())
        received["cmd"] = cmd
        await ws.send(json.dumps({"id": cmd["id"], "type": "result", **result}))

    return await websockets.serve(handler, "127.0.0.1", 0)


async def test_get_statistics_authenticates_and_sends_command():
    received = {}
    rows = {"sensor.out": [{"start": 1.0e12, "end": 1.0e12 + 3.6e6, "mean": 12.5, "min": 12.0, "max": 13.0}]}
    server = await fake_ha_ws(received, {"success": True, "result": rows})
    port = server.sockets[0].getsockname()[1]
    client = HAClient("http://ha.test", "secret-token", ws_url=f"ws://127.0.0.1:{port}/api/websocket")
    try:
        start = datetime(2026, 8, 16, 0, 0, tzinfo=timezone.utc)
        result = await client.get_statistics(["sensor.out"], start, "hour")
    finally:
        server.close()
        await server.wait_closed()
        await client.aclose()
    assert received["auth"] == {"type": "auth", "access_token": "secret-token"}
    assert received["cmd"] == {
        "id": 1,
        "type": "recorder/statistics_during_period",
        "start_time": "2026-08-16T00:00:00+00:00",
        "statistic_ids": ["sensor.out"],
        "period": "hour",
        "types": ["mean", "min", "max"],
    }
    assert result == rows


async def test_get_statistics_raises_haerror_on_failed_command():
    server = await fake_ha_ws({}, {"success": False, "error": {"code": "x", "message": "nope"}})
    port = server.sockets[0].getsockname()[1]
    client = HAClient("http://ha.test", "secret-token", ws_url=f"ws://127.0.0.1:{port}/api/websocket")
    try:
        with pytest.raises(HAError):
            await client.get_statistics(["sensor.out"], datetime.now(timezone.utc), "hour")
    finally:
        server.close()
        await server.wait_closed()
        await client.aclose()


async def test_get_statistics_raises_haerror_on_bad_token():
    server = await fake_ha_ws({}, {"success": True, "result": {}})
    port = server.sockets[0].getsockname()[1]
    client = HAClient("http://ha.test", "wrong", ws_url=f"ws://127.0.0.1:{port}/api/websocket")
    try:
        with pytest.raises(HAError):
            await client.get_statistics(["sensor.out"], datetime.now(timezone.utc), "hour")
    finally:
        server.close()
        await server.wait_closed()
        await client.aclose()


async def test_get_statistics_raises_haerror_when_unreachable():
    client = HAClient("http://ha.test", "secret-token", ws_url="ws://127.0.0.1:1/api/websocket")
    try:
        with pytest.raises(HAError):
            await client.get_statistics(["sensor.out"], datetime.now(timezone.utc), "hour")
    finally:
        await client.aclose()


def test_ws_url_derived_from_base_url():
    assert HAClient("http://homeassistant.local:8123", "t").ws_url == "ws://homeassistant.local:8123/api/websocket"
    assert HAClient("https://ha.example:8123", "t").ws_url == "wss://ha.example:8123/api/websocket"
    # The Supervisor proxies the core websocket at a different path
    assert HAClient("http://supervisor/core", "t", ws_url="ws://supervisor/core/websocket").ws_url == "ws://supervisor/core/websocket"
