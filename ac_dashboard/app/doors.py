"""Momentary "Open" for Inception doors.

HA's lock entities from the inception-mqtt add-on only know Lock/Unlock
(Unlock = latched). Inception's momentary "Open" (re-locks after the door's
unlock time) is reached by publishing "Open" straight to the door's MQTT
command topic — the add-on passes the payload through as DoorControlType.
The command topics come from the retained MQTT discovery configs, matched to
HA entities by name.
"""

import json
import logging
import time

from app.ha_client import HAClient, HAError

log = logging.getLogger(__name__)

DISCOVERY_TOPIC = "homeassistant/lock/#"
OPEN_PAYLOAD = "Open"


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
    """Cached name -> command topic map, refreshed from the broker."""

    def __init__(self, ttl: float = 600.0, clock=time.monotonic):
        self._ttl = ttl
        self._clock = clock
        self._topics: dict[str, str] = {}
        self._expires = 0.0

    async def _refresh(self, ha: HAClient) -> None:
        if self._clock() < self._expires:
            return
        try:
            messages = await ha.mqtt_subscribe_retained(DISCOVERY_TOPIC)
            self._topics = parse_lock_discovery(messages)
        except HAError as exc:
            log.warning("Could not read lock discovery configs (Open disabled): %s", exc)
            self._topics = {}
        self._expires = self._clock() + self._ttl

    async def names(self, ha: HAClient) -> set[str]:
        await self._refresh(ha)
        return set(self._topics)

    async def command_topic(self, ha: HAClient, name: str) -> str | None:
        await self._refresh(ha)
        return self._topics.get(name)
