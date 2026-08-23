import pytest

from app.doors import DoorTopics, parse_lock_discovery
from app.ha_client import HAError

from tests.conftest import FakeHAClient, lock_discovery


def test_parse_lock_discovery_maps_name_to_command_topic():
    messages = [
        lock_discovery("abc", "Front Door"),
        ("homeassistant/lock/junk/config", "not json"),
        ("homeassistant/lock/x/config", "{}"),
    ]
    assert parse_lock_discovery(messages) == {"Front Door": "inception/lock/abc/set"}


async def test_door_topics_resolves_by_name_and_caches():
    fake = FakeHAClient()
    fake.mqtt_retained = [lock_discovery("abc", "Front Door")]
    topics = DoorTopics(ttl=600)
    assert await topics.command_topic(fake, "Front Door") == "inception/lock/abc/set"
    assert await topics.command_topic(fake, "Garage") is None
    assert fake.mqtt_subscriptions == ["homeassistant/lock/#"]  # one subscribe, cached


async def test_door_topics_refreshes_after_ttl():
    fake = FakeHAClient()
    fake.mqtt_retained = [lock_discovery("abc", "Front Door")]
    now = [1000.0]
    topics = DoorTopics(ttl=60, clock=lambda: now[0])
    await topics.command_topic(fake, "Front Door")
    now[0] += 61
    await topics.command_topic(fake, "Front Door")
    assert len(fake.mqtt_subscriptions) == 2


async def test_door_topics_tolerates_subscribe_failure():
    # e.g. the add-on token lacks admin rights: Open is simply unavailable.
    fake = FakeHAClient()
    fake.fail_mqtt_subscribe = True
    topics = DoorTopics(ttl=600)
    assert await topics.command_topic(fake, "Front Door") is None
    assert await topics.names(fake) == set()
