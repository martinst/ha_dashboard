import asyncio
import json
from datetime import datetime

import httpx
import websockets


class HAError(Exception):
    """Raised when Home Assistant can't be reached or returns an error."""


class HAClient:
    """Thin async client for Home Assistant's REST API."""

    def __init__(
        self,
        base_url: str,
        token: str,
        transport: httpx.AsyncBaseTransport | None = None,
        ws_url: str | None = None,
    ):
        self._token = token
        # Core serves its websocket at /api/websocket; the Supervisor proxy
        # exposes it at ws://supervisor/core/websocket instead (pass ws_url).
        self.ws_url = ws_url or (
            base_url.rstrip("/").replace("http", "ws", 1) + "/api/websocket"
        )
        self._client = httpx.AsyncClient(
            base_url=base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
            transport=transport,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_states(self) -> list[dict]:
        return await self._request("GET", "/api/states")

    async def get_config(self) -> dict:
        return await self._request("GET", "/api/config")

    async def set_hvac_mode(self, entity_id: str, mode: str) -> None:
        await self._request(
            "POST",
            "/api/services/climate/set_hvac_mode",
            body={"entity_id": entity_id, "hvac_mode": mode},
        )

    async def set_temperature(self, entity_id: str, temperature: float) -> None:
        await self._request(
            "POST",
            "/api/services/climate/set_temperature",
            body={"entity_id": entity_id, "temperature": temperature},
        )

    async def turn_on(self, entity_id: str) -> None:
        """climate.turn_on restores the unit's previous HVAC mode."""
        await self._request(
            "POST",
            "/api/services/climate/turn_on",
            body={"entity_id": entity_id},
        )

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

    async def lock(self, entity_id: str) -> None:
        await self._request(
            "POST", "/api/services/lock/lock", body={"entity_id": entity_id}
        )

    async def unlock(self, entity_id: str) -> None:
        await self._request(
            "POST", "/api/services/lock/unlock", body={"entity_id": entity_id}
        )

    async def mqtt_publish(self, topic: str, payload: str) -> None:
        await self._request(
            "POST", "/api/services/mqtt/publish",
            body={"topic": topic, "payload": payload},
        )

    async def get_statistics(
        self, statistic_ids: list[str], start: datetime, period: str
    ) -> dict[str, list[dict]]:
        """recorder/statistics_during_period — only available over websocket.

        Returns {statistic_id: [{start, end, mean, min, max}, ...]} with
        start/end as epoch milliseconds."""
        command = {
            "type": "recorder/statistics_during_period",
            "start_time": start.isoformat(),
            "statistic_ids": list(statistic_ids),
            "period": period,
            "types": ["mean", "min", "max"],
        }
        try:
            async with websockets.connect(self.ws_url, open_timeout=10) as ws:
                await self._ws_auth(ws)
                reply = await self._ws_command(ws, command)
        except (OSError, websockets.WebSocketException, ValueError, TimeoutError) as exc:
            raise HAError(f"Home Assistant websocket failed: {exc}") from exc
        return reply.get("result") or {}

    async def mqtt_subscribe_retained(
        self, topic: str, wait: float = 2.0
    ) -> list[tuple[str, str]]:
        """Collect the retained messages for a topic filter (mqtt/subscribe).

        The broker replays retained messages immediately on subscribe; we
        gather until `wait` seconds pass without a new message."""
        messages: list[tuple[str, str]] = []
        try:
            async with websockets.connect(self.ws_url, open_timeout=10) as ws:
                await self._ws_auth(ws)
                await self._ws_command(ws, {"type": "mqtt/subscribe", "topic": topic})
                while True:
                    try:
                        msg = json.loads(await asyncio.wait_for(ws.recv(), wait))
                    except asyncio.TimeoutError:
                        break
                    if msg.get("type") == "event":
                        event = msg.get("event") or {}
                        messages.append((event.get("topic", ""), event.get("payload", "")))
        except (OSError, websockets.WebSocketException, ValueError, TimeoutError) as exc:
            raise HAError(f"Home Assistant websocket failed: {exc}") from exc
        return messages

    async def _ws_command(self, ws, command: dict) -> dict:
        await ws.send(json.dumps({"id": 1, **command}))
        reply = json.loads(await ws.recv())
        if not reply.get("success"):
            raise HAError(f"Home Assistant {command['type']} failed: {reply.get('error')}")
        return reply

    async def _ws_auth(self, ws) -> None:
        hello = json.loads(await ws.recv())
        if hello.get("type") != "auth_required":
            raise HAError(f"unexpected websocket greeting: {hello.get('type')}")
        await ws.send(json.dumps({"type": "auth", "access_token": self._token}))
        auth = json.loads(await ws.recv())
        if auth.get("type") != "auth_ok":
            raise HAError(f"websocket auth failed: {auth.get('message')}")

    async def _request(self, method: str, path: str, body: dict | None = None):
        try:
            resp = await self._client.request(method, path, json=body)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            # ValueError covers json.JSONDecodeError from resp.json()
            raise HAError(f"Home Assistant request failed: {exc}") from exc
