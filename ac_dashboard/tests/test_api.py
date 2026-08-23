from app.config import Group

from tests.conftest import FakeHAClient, ha_state


def test_get_state_returns_groups(make_client):
    fake = FakeHAClient(states=[ha_state("climate.bedroom")])
    client = make_client(fake, [Group(name="Upstairs", entities=["climate.bedroom"])])
    resp = client.get("/api/state")
    assert resp.status_code == 200
    body = resp.json()
    assert body["groups"][0]["name"] == "Upstairs"
    assert body["groups"][0]["units"][0]["entity_id"] == "climate.bedroom"


def test_get_state_returns_502_when_ha_unreachable(make_client):
    client = make_client(FakeHAClient(fail_states=True))
    resp = client.get("/api/state")
    assert resp.status_code == 502


def test_set_unit_mode_calls_set_hvac_mode(make_client):
    fake = FakeHAClient()
    client = make_client(fake)
    resp = client.post("/api/units/climate.bedroom/set", json={"mode": "cool"})
    assert resp.status_code == 200
    assert fake.calls == [("set_hvac_mode", "climate.bedroom", "cool")]


def test_set_unit_mode_on_calls_turn_on(make_client):
    fake = FakeHAClient()
    client = make_client(fake)
    client.post("/api/units/climate.bedroom/set", json={"mode": "on"})
    assert fake.calls == [("turn_on", "climate.bedroom")]


def test_set_unit_temperature(make_client):
    fake = FakeHAClient()
    client = make_client(fake)
    client.post("/api/units/climate.bedroom/set", json={"temperature": 21.5})
    assert fake.calls == [("set_temperature", "climate.bedroom", 21.5)]


def test_set_unit_mode_and_temperature_together(make_client):
    fake = FakeHAClient()
    client = make_client(fake)
    client.post("/api/units/climate.bedroom/set",
                json={"mode": "heat", "temperature": 23.0})
    assert fake.calls == [
        ("set_hvac_mode", "climate.bedroom", "heat"),
        ("set_temperature", "climate.bedroom", 23.0),
    ]


def test_set_unit_empty_body_is_422(make_client):
    client = make_client(FakeHAClient())
    resp = client.post("/api/units/climate.bedroom/set", json={})
    assert resp.status_code == 422


def test_set_unit_returns_502_when_ha_unreachable(make_client):
    client = make_client(FakeHAClient(fail_entities=["climate.bedroom"]))
    resp = client.post("/api/units/climate.bedroom/set", json={"mode": "cool"})
    assert resp.status_code == 502


GROUPS = [Group(name="Upstairs", entities=["climate.bedroom", "climate.office"])]


def test_set_group_fans_out_to_all_units(make_client):
    fake = FakeHAClient()
    client = make_client(fake, GROUPS)
    resp = client.post("/api/groups/Upstairs/set", json={"mode": "off"})
    assert resp.status_code == 200
    assert resp.json() == {"total": 2, "succeeded": 2, "failed": []}
    assert sorted(fake.calls) == [
        ("set_hvac_mode", "climate.bedroom", "off"),
        ("set_hvac_mode", "climate.office", "off"),
    ]


def test_set_group_reports_partial_failure(make_client):
    fake = FakeHAClient(fail_entities=["climate.office"])
    client = make_client(fake, GROUPS)
    resp = client.post("/api/groups/Upstairs/set", json={"temperature": 22.0})
    assert resp.status_code == 200
    assert resp.json() == {"total": 2, "succeeded": 1, "failed": ["climate.office"]}


def test_set_group_unknown_group_is_404(make_client):
    client = make_client(FakeHAClient(), GROUPS)
    resp = client.post("/api/groups/Basement/set", json={"mode": "off"})
    assert resp.status_code == 404


from datetime import datetime
from zoneinfo import ZoneInfo

from app.config import Preset
from app.scheduler import Scheduler

TZ = ZoneInfo("Europe/Stockholm")

SCHED_PRESET = Preset(
    name="Evening warmth",
    entities=["climate.bedroom"],
    mode="heat",
    temperature=23.0,
    time="18:00",
)


def make_sched(tmp_path, fake_ha):
    return Scheduler(
        [SCHED_PRESET],
        fake_ha,
        tmp_path / "schedules.json",
        TZ,
        now=lambda: datetime(2026, 6, 7, 12, 0, tzinfo=TZ),
    )


def test_get_schedule_lists_presets(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    resp = client.get("/api/schedule")
    assert resp.status_code == 200
    (p,) = resp.json()["presets"]
    assert p["id"] == "evening_warmth"
    assert p["name"] == "Evening warmth"
    assert p["time"] == "18:00"
    assert p["armed"] is None


def test_arm_endpoint_arms_preset(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    resp = client.post(
        "/api/schedule/evening_warmth/arm",
        json={"date": "2026-06-08", "time": "18:00"},
    )
    assert resp.status_code == 200
    assert resp.json()["fires_at"].startswith("2026-06-08T18:00")
    armed = client.get("/api/schedule").json()["presets"][0]["armed"]
    assert armed["fires_at"].startswith("2026-06-08T18:00")


def test_arm_past_time_is_400(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    resp = client.post(
        "/api/schedule/evening_warmth/arm",
        json={"date": "2026-06-07", "time": "11:00"},
    )
    assert resp.status_code == 400


def test_arm_bad_date_is_400(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    resp = client.post(
        "/api/schedule/evening_warmth/arm",
        json={"date": "not-a-date", "time": "18:00"},
    )
    assert resp.status_code == 400


def test_arm_unknown_preset_is_404(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    resp = client.post(
        "/api/schedule/ghost/arm", json={"date": "2026-06-08", "time": "18:00"}
    )
    assert resp.status_code == 404


def test_cancel_endpoint_disarms(make_client, tmp_path):
    fake = FakeHAClient()
    sched = make_sched(tmp_path, fake)
    client = make_client(fake, scheduler=sched)
    client.post(
        "/api/schedule/evening_warmth/arm",
        json={"date": "2026-06-08", "time": "18:00"},
    )
    resp = client.post("/api/schedule/evening_warmth/cancel")
    assert resp.status_code == 200
    assert client.get("/api/schedule").json()["presets"][0]["armed"] is None


def test_arm_weekly_endpoint(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    resp = client.post(
        "/api/schedule/evening_warmth/arm",
        json={"repeat": [0, 1, 2, 3, 4], "time": "18:00"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "weekly"
    assert body["days"] == [0, 1, 2, 3, 4]
    assert body["time"] == "18:00"
    assert body["next_fire"].startswith("2026-06-08T18:00")  # Monday
    armed = client.get("/api/schedule").json()["presets"][0]["armed"]
    assert armed["type"] == "weekly"


def test_arm_weekly_empty_repeat_is_400(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    resp = client.post(
        "/api/schedule/evening_warmth/arm", json={"repeat": [], "time": "18:00"}
    )
    assert resp.status_code == 400


def test_arm_weekly_invalid_day_is_400(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    resp = client.post(
        "/api/schedule/evening_warmth/arm", json={"repeat": [7], "time": "18:00"}
    )
    assert resp.status_code == 400


def test_arm_both_date_and_repeat_is_422(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    resp = client.post(
        "/api/schedule/evening_warmth/arm",
        json={"date": "2026-06-08", "repeat": [0], "time": "18:00"},
    )
    assert resp.status_code == 422


def test_arm_neither_date_nor_repeat_is_422(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    resp = client.post(
        "/api/schedule/evening_warmth/arm", json={"time": "18:00"}
    )
    assert resp.status_code == 422


def test_cancel_weekly_arm(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    client.post(
        "/api/schedule/evening_warmth/arm", json={"repeat": [0], "time": "18:00"}
    )
    resp = client.post("/api/schedule/evening_warmth/cancel")
    assert resp.status_code == 200
    assert client.get("/api/schedule").json()["presets"][0]["armed"] is None


from app.config import CoverPreset
from tests.conftest import cover_ha_state

COVER_GROUPS = [Group(name="Living", entities=["cover.left", "cover.right"])]


def test_get_state_includes_cover_groups(make_client):
    fake = FakeHAClient(states=[
        ha_state("climate.bedroom"),
        cover_ha_state("cover.left", state="open", current_position=40),
    ])
    client = make_client(
        fake,
        [Group(name="Upstairs", entities=["climate.bedroom"])],
        cover_groups=[Group(name="Living", entities=["cover.left"])],
    )
    body = client.get("/api/state").json()
    assert body["groups"][0]["units"][0]["entity_id"] == "climate.bedroom"
    assert body["cover_groups"][0]["name"] == "Living"
    assert body["cover_groups"][0]["units"][0]["position"] == 40


def test_set_cover_action(make_client):
    fake = FakeHAClient()
    client = make_client(fake)
    resp = client.post("/api/covers/cover.left/set", json={"action": "open"})
    assert resp.status_code == 200
    assert fake.calls == [("open_cover", "cover.left")]


def test_set_cover_position(make_client):
    fake = FakeHAClient()
    client = make_client(fake)
    resp = client.post("/api/covers/cover.left/set", json={"position": 40})
    assert resp.status_code == 200
    assert fake.calls == [("set_cover_position", "cover.left", 40)]


def test_set_cover_empty_body_is_422(make_client):
    resp = make_client(FakeHAClient()).post("/api/covers/cover.left/set", json={})
    assert resp.status_code == 422


def test_set_cover_on_climate_entity_is_400(make_client):
    resp = make_client(FakeHAClient()).post(
        "/api/covers/climate.bedroom/set", json={"action": "open"}
    )
    assert resp.status_code == 400


def test_set_cover_group_fans_out(make_client):
    fake = FakeHAClient()
    client = make_client(fake, cover_groups=COVER_GROUPS)
    resp = client.post("/api/cover-groups/Living/set", json={"action": "close"})
    assert resp.status_code == 200
    assert resp.json() == {"total": 2, "succeeded": 2, "failed": []}
    assert sorted(fake.calls) == [
        ("close_cover", "cover.left"),
        ("close_cover", "cover.right"),
    ]


def test_set_cover_group_partial_failure(make_client):
    fake = FakeHAClient(fail_entities=["cover.right"])
    client = make_client(fake, cover_groups=COVER_GROUPS)
    resp = client.post("/api/cover-groups/Living/set", json={"action": "open"})
    assert resp.json() == {"total": 2, "succeeded": 1, "failed": ["cover.right"]}


def test_set_cover_group_unknown_is_404(make_client):
    client = make_client(FakeHAClient(), cover_groups=COVER_GROUPS)
    resp = client.post("/api/cover-groups/Kitchen/set", json={"action": "open"})
    assert resp.status_code == 404


COVER_SCHED_PRESET = CoverPreset(
    name="Night close", entities=["cover.left"], action="close", time="22:00"
)


def make_mixed_sched(tmp_path, fake_ha):
    return Scheduler(
        [SCHED_PRESET, COVER_SCHED_PRESET],
        fake_ha,
        tmp_path / "schedules.json",
        TZ,
        now=lambda: datetime(2026, 6, 7, 12, 0, tzinfo=TZ),
    )


def test_schedule_serializes_domain_fields(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_mixed_sched(tmp_path, fake))
    presets = {p["id"]: p for p in client.get("/api/schedule").json()["presets"]}
    climate = presets["evening_warmth"]
    assert climate["domain"] == "climate"
    assert climate["mode"] == "heat"
    assert climate["temperature"] == 23.0
    cover = presets["cover:night_close"]
    assert cover["domain"] == "cover"
    assert cover["action"] == "close"
    assert cover["position"] is None
    assert "mode" not in cover


def test_arm_and_cancel_cover_preset(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_mixed_sched(tmp_path, fake))
    resp = client.post(
        "/api/schedule/cover:night_close/arm",
        json={"date": "2026-06-08", "time": "22:00"},
    )
    assert resp.status_code == 200
    assert resp.json()["fires_at"].startswith("2026-06-08T22:00")
    resp = client.post("/api/schedule/cover:night_close/cancel")
    assert resp.status_code == 200


def test_static_files_are_served_no_cache(make_client):
    # Phones cache JS/CSS aggressively; without no-cache a release can pair
    # fresh HTML with stale scripts (const collisions -> blank page).
    client = make_client(FakeHAClient())
    for path in ("/", "/style.css", "/app.js", "/shared.js", "/windows.html"):
        resp = client.get(path)
        assert resp.status_code == 200
        assert resp.headers["cache-control"] == "no-cache", path


def test_static_asset_links_are_version_busted():
    # Cached assets from older versions must never pair with fresh HTML:
    # asset URLs carry ?v=<add-on version> so each release gets new URLs.
    from pathlib import Path

    import yaml

    root = Path(__file__).parent.parent
    version = yaml.safe_load((root / "config.yaml").read_text())["version"]
    pages = {
        "index.html": ("/style.css", "/shared.js", "/app.js"),
        "windows.html": ("/style.css", "/shared.js", "/windows.js"),
    }
    for page, assets in pages.items():
        html = (root / "app" / "static" / page).read_text()
        for asset in assets:
            assert f'"{asset}?v={version}"' in html, f"{page}: {asset}"


from app.config import SensorConfig
from tests.conftest import sensor_ha_state


def test_get_state_includes_temperatures(make_client):
    fake = FakeHAClient(states=[
        ha_state("climate.bedroom"),
        sensor_ha_state("sensor.wn1980c_outdoor_temperature", state="11.9"),
        sensor_ha_state("sensor.wn1980c_indoor_temperature", state="23.1"),
    ])
    client = make_client(fake)
    body = client.get("/api/state").json()
    assert body["temperatures"]["outdoor"]["temp"] == 11.9
    assert body["temperatures"]["indoor"]["temp"] == 23.1


def test_get_state_uses_configured_sensors(make_client):
    fake = FakeHAClient(states=[
        sensor_ha_state("sensor.wn1980c_outdoor_temperature", state="11.9"),
        sensor_ha_state("sensor.garden_probe", state="10.2"),
        sensor_ha_state("sensor.hall", state="20.0"),
    ])
    client = make_client(
        fake, sensors=SensorConfig(outdoor="sensor.garden_probe", indoor="sensor.hall")
    )
    body = client.get("/api/state").json()
    assert body["temperatures"]["outdoor"]["entity_id"] == "sensor.garden_probe"
    assert body["temperatures"]["indoor"]["entity_id"] == "sensor.hall"


def test_get_state_temperatures_null_when_no_sensors(make_client):
    client = make_client(FakeHAClient(states=[ha_state("climate.bedroom")]))
    body = client.get("/api/state").json()
    assert body["temperatures"] == {"outdoor": None, "indoor": None}


from datetime import timedelta

STAT_ROWS = [
    {"start": 1.0e12, "end": 1.0e12 + 3.6e6, "mean": 12.456, "min": 12.0, "max": 13.0},
]


def temp_sensors():
    return [
        sensor_ha_state("sensor.wn1980c_outdoor_temperature", state="11.9"),
        sensor_ha_state("sensor.wn1980c_indoor_temperature", state="23.1"),
    ]


def test_history_endpoint_returns_points_for_slot(make_client):
    fake = FakeHAClient(
        states=temp_sensors(),
        statistics={"sensor.wn1980c_outdoor_temperature": STAT_ROWS},
    )
    client = make_client(fake)
    resp = client.get("/api/temperatures/outdoor/history?range=7d")
    assert resp.status_code == 200
    body = resp.json()
    assert body["range"] == "7d"
    assert body["period"] == "hour"
    assert body["unit"] == "°C"
    assert body["entity_id"] == "sensor.wn1980c_outdoor_temperature"
    assert body["points"] == [{"t": 1_000_000_000_000, "mean": 12.5, "min": 12.0, "max": 13.0}]
    (ids, start, period) = fake.statistics_calls[0]
    assert ids == ["sensor.wn1980c_outdoor_temperature"]
    assert period == "hour"
    assert timedelta(days=7) - timedelta(minutes=1) < (
        __import__("datetime").datetime.now(start.tzinfo) - start
    ) < timedelta(days=7, minutes=1)


def test_history_endpoint_uses_5minute_period_for_24h(make_client):
    fake = FakeHAClient(states=temp_sensors(), statistics={})
    client = make_client(fake)
    resp = client.get("/api/temperatures/indoor/history?range=24h")
    assert resp.status_code == 200
    assert resp.json()["points"] == []
    assert fake.statistics_calls[0][0] == ["sensor.wn1980c_indoor_temperature"]
    assert fake.statistics_calls[0][2] == "5minute"


def test_history_endpoint_defaults_to_24h(make_client):
    fake = FakeHAClient(states=temp_sensors())
    resp = make_client(fake).get("/api/temperatures/outdoor/history")
    assert resp.json()["range"] == "24h"


def test_history_endpoint_caches_per_slot_and_range(make_client):
    fake = FakeHAClient(states=temp_sensors())
    client = make_client(fake)
    client.get("/api/temperatures/outdoor/history?range=7d")
    client.get("/api/temperatures/outdoor/history?range=7d")
    client.get("/api/temperatures/outdoor/history?range=30d")
    assert len(fake.statistics_calls) == 2


def test_history_endpoint_unknown_slot_is_404(make_client):
    resp = make_client(FakeHAClient(states=temp_sensors())).get(
        "/api/temperatures/garage/history"
    )
    assert resp.status_code == 404


def test_history_endpoint_bad_range_is_422(make_client):
    resp = make_client(FakeHAClient(states=temp_sensors())).get(
        "/api/temperatures/outdoor/history?range=1y"
    )
    assert resp.status_code == 422


def test_history_endpoint_slot_without_sensor_is_404(make_client):
    resp = make_client(FakeHAClient(states=[ha_state("climate.bedroom")])).get(
        "/api/temperatures/outdoor/history"
    )
    assert resp.status_code == 404


def test_history_endpoint_502_when_statistics_fail(make_client):
    fake = FakeHAClient(states=temp_sensors(), fail_statistics=True)
    resp = make_client(fake).get("/api/temperatures/outdoor/history")
    assert resp.status_code == 502
