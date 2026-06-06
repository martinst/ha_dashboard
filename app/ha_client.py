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
