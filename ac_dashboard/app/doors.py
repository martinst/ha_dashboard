"""Momentary "Open" for Inception doors.

HA's lock entities from the inception-mqtt add-on only know Lock/Unlock
(Unlock = latched). Inception's momentary "Open" (re-locks after the door's
unlock time) is reached by publishing "Open" straight to the door's MQTT
command topic — the add-on passes the payload through as DoorControlType.
The command topics come from the retained MQTT discovery configs, matched to
HA entities by name. They are read in a background task so page polls never
wait on (or coincide with) a websocket round-trip.
"""

import asyncio
import json
import logging

from app.ha_client import HAClient, HAError

log = logging.getLogger(__name__)

DISCOVERY_TOPIC = "homeassistant/lock/#"
OPEN_PAYLOAD = "Open"
REFRESH_INTERVAL = 600.0


def parse_lock_discovery(messages: list[tuple[str, str]]) -> dict[str, str]:
    """{discovery name: command_topic} from retained (topic, payload) pairs."""
    result = {}
    for _topic, payload in messages:
        try:
            cfg = json.loads(payload)
        except ValueError:
            continue
        if isinstance(cfg, dict) and cfg.get("name") and cfg.get("command_topic"):
            result[cfg["name"]] = cfg["command_topic"]
    return result


class DoorTopics:
    """Name -> command topic map, refreshed from the broker in the background."""

    def __init__(self):
        self._topics: dict[str, str] = {}
        self._lock = asyncio.Lock()
        self._loaded = False

    def names(self) -> set[str]:
        return set(self._topics)

    def command_topic(self, name: str) -> str | None:
        return self._topics.get(name)

    async def refresh(self, ha: HAClient) -> None:
        """Re-read discovery configs. Concurrent calls coalesce into one read;
        a failed read keeps the last good mapping."""
        if self._lock.locked():
            async with self._lock:  # wait for the in-flight refresh
                return
        async with self._lock:
            try:
                messages = await ha.mqtt_subscribe_retained(DISCOVERY_TOPIC)
            except HAError as exc:
                log.warning("Door discovery read failed (keeping %d topics): %s",
                            len(self._topics), exc)
                return
            self._topics = parse_lock_discovery(messages)
            if not self._loaded:
                log.info("Door discovery: %d openable doors", len(self._topics))
            self._loaded = True

    def start(self, ha: HAClient, interval: float = REFRESH_INTERVAL) -> asyncio.Task:
        async def loop():
            while True:
                await self.refresh(ha)
                await asyncio.sleep(interval)
        return asyncio.create_task(loop(), name="door-topics-refresh")
