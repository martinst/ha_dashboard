import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.config import Preset
from app.scheduler import ArmError, OnceArm, Scheduler

from tests.conftest import FakeHAClient

TZ = ZoneInfo("Europe/Stockholm")
START = datetime(2026, 6, 7, 12, 0, tzinfo=TZ)

PRESET = Preset(
    name="Evening warmth",
    entities=["climate.a", "climate.b"],
    mode="heat",
    temperature=23.0,
    time="18:00",
)


class Clock:
    def __init__(self, now=START):
        self.now = now

    def __call__(self):
        return self.now


def make_scheduler(tmp_path, clock, presets=(PRESET,), ha=None):
    return Scheduler(
        list(presets),
        ha or FakeHAClient(),
        tmp_path / "schedules.json",
        TZ,
        now=clock,
    )


def test_arm_returns_once_record_and_persists(tmp_path):
    s = make_scheduler(tmp_path, Clock())
    arm = s.arm("evening_warmth", "2026-06-08", "18:00")
    assert isinstance(arm, OnceArm)
    assert arm.fires_at.isoformat().startswith("2026-06-08T18:00")
    assert arm.fires_at.tzinfo is not None
    saved = json.loads((tmp_path / "schedules.json").read_text())
    assert saved == {
        "evening_warmth": {"type": "once", "fires_at": arm.fires_at.isoformat()}
    }


def test_arm_past_raises(tmp_path):
    s = make_scheduler(tmp_path, Clock())
    with pytest.raises(ArmError, match="past"):
        s.arm("evening_warmth", "2026-06-07", "11:00")


def test_arm_too_far_ahead_raises(tmp_path):
    s = make_scheduler(tmp_path, Clock())
    with pytest.raises(ArmError, match="7 days"):
        s.arm("evening_warmth", "2026-06-20", "18:00")


def test_arm_unknown_preset_raises(tmp_path):
    s = make_scheduler(tmp_path, Clock())
    with pytest.raises(KeyError):
        s.arm("ghost", "2026-06-08", "18:00")


def test_rearm_replaces(tmp_path):
    s = make_scheduler(tmp_path, Clock())
    s.arm("evening_warmth", "2026-06-08", "18:00")
    fires = s.arm("evening_warmth", "2026-06-08", "19:30")
    assert s.armed["evening_warmth"] is fires
    assert len(s.armed) == 1


def test_cancel_disarms_and_is_idempotent(tmp_path):
    s = make_scheduler(tmp_path, Clock())
    s.arm("evening_warmth", "2026-06-08", "18:00")
    s.cancel("evening_warmth")
    assert s.armed == {}
    s.cancel("evening_warmth")  # no error
    assert json.loads((tmp_path / "schedules.json").read_text()) == {}


def test_cancel_unknown_preset_raises(tmp_path):
    s = make_scheduler(tmp_path, Clock())
    with pytest.raises(KeyError):
        s.cancel("ghost")


def test_persistence_round_trip(tmp_path):
    clock = Clock()
    s1 = make_scheduler(tmp_path, clock)
    fires = s1.arm("evening_warmth", "2026-06-08", "18:00")
    s2 = make_scheduler(tmp_path, clock)
    assert s2.armed == {"evening_warmth": fires}


def test_unknown_preset_in_file_dropped(tmp_path):
    (tmp_path / "schedules.json").write_text(
        json.dumps({"ghost": "2026-06-08T18:00:00+02:00"})
    )
    s = make_scheduler(tmp_path, Clock())
    assert s.armed == {}


def test_corrupt_file_ignored(tmp_path):
    (tmp_path / "schedules.json").write_text("not json{")
    s = make_scheduler(tmp_path, Clock())
    assert s.armed == {}


async def test_check_due_fires_and_disarms(tmp_path):
    clock = Clock()
    ha = FakeHAClient()
    s = make_scheduler(tmp_path, clock, ha=ha)
    s.arm("evening_warmth", "2026-06-07", "14:00")
    clock.now = datetime(2026, 6, 7, 14, 0, 30, tzinfo=TZ)
    await s.check_due()
    assert s.armed == {}
    assert ("set_hvac_mode", "climate.a", "heat") in ha.calls
    assert ("set_temperature", "climate.a", 23.0) in ha.calls
    assert ("set_hvac_mode", "climate.b", "heat") in ha.calls
    assert ("set_temperature", "climate.b", 23.0) in ha.calls
    assert json.loads((tmp_path / "schedules.json").read_text()) == {}


async def test_check_due_not_yet_due_does_nothing(tmp_path):
    clock = Clock()
    ha = FakeHAClient()
    s = make_scheduler(tmp_path, clock, ha=ha)
    s.arm("evening_warmth", "2026-06-07", "14:00")
    clock.now = datetime(2026, 6, 7, 13, 59, tzinfo=TZ)
    await s.check_due()
    assert ha.calls == []
    assert "evening_warmth" in s.armed


async def test_check_due_within_grace_fires(tmp_path):
    clock = Clock()
    ha = FakeHAClient()
    s = make_scheduler(tmp_path, clock, ha=ha)
    s.arm("evening_warmth", "2026-06-07", "14:00")
    clock.now = datetime(2026, 6, 7, 14, 50, tzinfo=TZ)
    await s.check_due()
    assert ha.calls != []
    assert s.armed == {}


async def test_check_due_past_grace_discards(tmp_path):
    clock = Clock()
    ha = FakeHAClient()
    s = make_scheduler(tmp_path, clock, ha=ha)
    s.arm("evening_warmth", "2026-06-07", "14:00")
    clock.now = datetime(2026, 6, 7, 15, 30, tzinfo=TZ)
    await s.check_due()
    assert ha.calls == []
    assert s.armed == {}


async def test_fire_partial_failure_still_disarms(tmp_path):
    clock = Clock()
    ha = FakeHAClient(fail_entities=["climate.a"])
    s = make_scheduler(tmp_path, clock, ha=ha)
    s.arm("evening_warmth", "2026-06-07", "14:00")
    clock.now = datetime(2026, 6, 7, 14, 1, tzinfo=TZ)
    await s.check_due()  # must not raise
    assert s.armed == {}
    assert ("set_hvac_mode", "climate.b", "heat") in ha.calls


def test_arm_creates_missing_state_directory(tmp_path):
    s = Scheduler(
        [PRESET],
        FakeHAClient(),
        tmp_path / "nested" / "dir" / "schedules.json",
        TZ,
        now=Clock(),
    )
    s.arm("evening_warmth", "2026-06-08", "18:00")
    assert (tmp_path / "nested" / "dir" / "schedules.json").exists()


def test_legacy_string_entry_loads_as_once(tmp_path):
    (tmp_path / "schedules.json").write_text(
        json.dumps({"evening_warmth": "2026-06-08T18:00:00+02:00"})
    )
    s = make_scheduler(tmp_path, Clock())
    arm = s.armed["evening_warmth"]
    assert isinstance(arm, OnceArm)
    assert arm.fires_at.isoformat() == "2026-06-08T18:00:00+02:00"
