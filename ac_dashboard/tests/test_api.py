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
