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

    async def _request(self, method: str, path: str, body: dict | None = None):
        try:
            resp = await self._client.request(method, path, json=body)
            resp.raise_for_status()
            return resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            # ValueError covers json.JSONDecodeError from resp.json()
            raise HAError(f"Home Assistant request failed: {exc}") from exc
