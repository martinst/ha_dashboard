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

    async def _request(self, method: str, path: str, body: dict | None = None):
        try:
            resp = await self._client.request(method, path, json=body)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            # ValueError covers json.JSONDecodeError from resp.json()
            raise HAError(f"Home Assistant request failed: {exc}") from exc
