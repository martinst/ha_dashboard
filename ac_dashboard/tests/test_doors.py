import asyncio

import pytest

from app.doors import DoorTopics, parse_lock_discovery

from tests.conftest import FakeHAClient, lock_discovery


def test_parse_lock_discovery_maps_name_to_command_topic():
    messages = [
        lock_discovery("abc", "Front Door"),
        ("homeassistant/lock/junk/config", "not json"),
        ("homeassistant/lock/x/config", "{}"),
    ]
    assert parse_lock_discovery(messages) == {"Front Door": "inception/lock/abc/set"}


async def test_door_topics_resolves_by_name_after_refresh():
    fake = FakeHAClient()
    fake.mqtt_retained = [lock_discovery("abc", "Front Door")]
    topics = DoorTopics()
    await topics.refresh(fake)
    assert topics.command_topic("Front Door") == "inception/lock/abc/set"
    assert topics.command_topic("Garage") is None
    assert topics.names() == {"Front Door"}
    assert fake.mqtt_subscriptions == ["homeassistant/lock/#"]


def test_door_topics_empty_before_refresh():
    topics = DoorTopics()
    assert topics.names() == set()
    assert topics.command_topic("Front Door") is None


async def test_door_topics_tolerates_subscribe_failure_and_keeps_last_good():
    # e.g. a transient proxy error: keep the previous mapping rather than
    # dropping the Open buttons.
    fake = FakeHAClient()
    fake.mqtt_retained = [lock_discovery("abc", "Front Door")]
    topics = DoorTopics()
    await topics.refresh(fake)
    fake.fail_mqtt_subscribe = True
    await topics.refresh(fake)  # must not raise
    assert topics.command_topic("Front Door") == "inception/lock/abc/set"


async def test_door_topics_refresh_is_serialised():
    fake = FakeHAClient()
    fake.mqtt_retained = [lock_discovery("abc", "Front Door")]
    topics = DoorTopics()
    await asyncio.gather(*(topics.refresh(fake) for _ in range(5)))
    assert fake.mqtt_subscriptions == ["homeassistant/lock/#"]  # coalesced


async def test_door_topics_background_loop_refreshes_periodically():
    fake = FakeHAClient()
    fake.mqtt_retained = [lock_discovery("abc", "Front Door")]
    topics = DoorTopics()
    task = topics.start(fake, interval=0.05)
    await asyncio.sleep(0.18)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert len(fake.mqtt_subscriptions) >= 3
    assert topics.command_topic("Front Door") == "inception/lock/abc/set"
