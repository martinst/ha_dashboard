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


# ---- Google login, sessions, Doors page -----------------------------------

from urllib.parse import parse_qs, urlparse

from tests.conftest import fake_google, lock_ha_state, make_auth

LOCKS = [
    lock_ha_state("lock.front_door", state="locked"),
    lock_ha_state("lock.garage", state="unlocked"),
]
DOOR_GROUPS = [Group(name="Street", entities=["lock.front_door", "lock.garage"])]


def login(client, state_from_location=True):
    """Run the OAuth dance against the fake Google; leaves a session cookie."""
    resp = client.get("/auth/login?next=/doors.html", follow_redirects=False)
    assert resp.status_code == 302
    state = parse_qs(urlparse(resp.headers["location"]).query)["state"][0]
    return client.get(f"/auth/callback?code=c1&state={state}", follow_redirects=False)


def test_login_redirects_to_google_and_sets_state_cookie(make_client, tmp_path):
    client = make_client(FakeHAClient(), auth=make_auth(tmp_path))
    resp = client.get("/auth/login?next=/doors.html", follow_redirects=False)
    assert resp.status_code == 302
    loc = resp.headers["location"]
    assert loc.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    q = parse_qs(urlparse(loc).query)
    assert q["redirect_uri"] == ["http://testserver/auth/callback"]
    assert "oauth_state" in resp.cookies
    assert "session" not in resp.cookies


def test_callback_with_allowed_email_sets_session_and_redirects_to_next(make_client, tmp_path):
    transport, _ = fake_google(email="martin@example.com")
    client = make_client(FakeHAClient(), auth=make_auth(tmp_path, transport))
    resp = login(client)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/doors.html"
    assert "session" in resp.cookies
    cookie_header = resp.headers["set-cookie"]
    assert "HttpOnly" in cookie_header
    assert "SameSite=lax" in cookie_header.lower().replace("samesite=lax", "SameSite=lax")
    assert "Max-Age=31536000" in cookie_header  # a year: stay logged in
    assert client.get("/auth/me").json() == {"email": "martin@example.com"}


def test_callback_with_unlisted_email_is_403_and_no_session(make_client, tmp_path):
    transport, _ = fake_google(email="mallory@example.com")
    client = make_client(FakeHAClient(), auth=make_auth(tmp_path, transport))
    resp = login(client)
    assert resp.status_code == 403
    assert "mallory@example.com" in resp.text
    assert "session" not in resp.cookies
    assert client.get("/auth/me").status_code == 401


def test_callback_with_wrong_state_is_400(make_client, tmp_path):
    transport, _ = fake_google()
    client = make_client(FakeHAClient(), auth=make_auth(tmp_path, transport))
    client.get("/auth/login", follow_redirects=False)
    resp = client.get("/auth/callback?code=c1&state=forged", follow_redirects=False)
    assert resp.status_code == 400
    assert "session" not in resp.cookies


def test_callback_without_state_cookie_is_400(make_client, tmp_path):
    transport, _ = fake_google()
    client = make_client(FakeHAClient(), auth=make_auth(tmp_path, transport))
    resp = client.get("/auth/callback?code=c1&state=x", follow_redirects=False)
    assert resp.status_code == 400


def test_callback_google_error_is_502(make_client, tmp_path):
    transport, _ = fake_google(token_status=400)
    client = make_client(FakeHAClient(), auth=make_auth(tmp_path, transport))
    resp = login(client)
    assert resp.status_code == 502


def test_logout_clears_session(make_client, tmp_path):
    transport, _ = fake_google()
    client = make_client(FakeHAClient(), auth=make_auth(tmp_path, transport))
    login(client)
    resp = client.get("/auth/logout", follow_redirects=False)
    assert resp.status_code == 302
    assert client.get("/auth/me").status_code == 401


def test_doors_page_redirects_to_login_when_logged_out(make_client, tmp_path):
    client = make_client(FakeHAClient(), auth=make_auth(tmp_path))
    resp = client.get("/doors.html", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/auth/login?next=%2Fdoors.html"


def test_doors_page_served_when_logged_in(make_client, tmp_path):
    transport, _ = fake_google()
    client = make_client(FakeHAClient(), auth=make_auth(tmp_path, transport))
    login(client)
    resp = client.get("/doors.html")
    assert resp.status_code == 200
    assert "doors.js" in resp.text
    assert resp.headers["cache-control"] == "no-cache"


def test_doors_page_is_503_when_google_login_not_configured(make_client):
    client = make_client(FakeHAClient(), auth=None)
    resp = client.get("/doors.html")
    assert resp.status_code == 503
    assert "google_client_id" in resp.text


def test_login_is_503_when_not_configured(make_client):
    resp = make_client(FakeHAClient(), auth=None).get("/auth/login", follow_redirects=False)
    assert resp.status_code == 503


def test_doors_api_requires_session(make_client, tmp_path):
    client = make_client(FakeHAClient(states=LOCKS), auth=make_auth(tmp_path))
    assert client.get("/api/doors").status_code == 401
    assert client.post("/api/doors/lock.front_door/set", json={"action": "lock"}).status_code == 401
    assert client.post("/api/door-groups/Street/set", json={"action": "lock"}).status_code == 401


def test_doors_state_for_logged_in_user(make_client, tmp_path):
    transport, _ = fake_google(email="maria@example.com")
    fake = FakeHAClient(states=LOCKS + [ha_state("climate.bedroom")])
    client = make_client(fake, door_groups=DOOR_GROUPS, auth=make_auth(tmp_path, transport))
    login(client)
    body = client.get("/api/doors").json()
    assert body["user"] == "maria@example.com"
    assert body["groups"][0]["name"] == "Street"
    assert body["groups"][0]["units"] == [
        {"entity_id": "lock.front_door", "name": "Front Door", "ha_name": "Front Door",
         "state": "locked", "available": True, "supports_open": False},
        {"entity_id": "lock.garage", "name": "Garage", "ha_name": "Garage",
         "state": "unlocked", "available": True, "supports_open": False},
    ]


def test_lock_and_unlock_door(make_client, tmp_path):
    transport, _ = fake_google()
    fake = FakeHAClient(states=LOCKS)
    client = make_client(fake, auth=make_auth(tmp_path, transport))
    login(client)
    assert client.post("/api/doors/lock.front_door/set", json={"action": "unlock"}).status_code == 200
    assert client.post("/api/doors/lock.front_door/set", json={"action": "lock"}).status_code == 200
    assert fake.calls == [("unlock", "lock.front_door"), ("lock", "lock.front_door")]


def test_door_command_rejects_bad_action_and_wrong_domain(make_client, tmp_path):
    transport, _ = fake_google()
    client = make_client(FakeHAClient(), auth=make_auth(tmp_path, transport))
    login(client)
    assert client.post("/api/doors/lock.front_door/set", json={"action": "jiggle"}).status_code == 422
    assert client.post("/api/doors/cover.win/set", json={"action": "lock"}).status_code == 400
    assert client.post("/api/doors/cover.win/set", json={"action": "open"}).status_code == 400


def test_door_group_lock_all(make_client, tmp_path):
    transport, _ = fake_google()
    fake = FakeHAClient(fail_entities=["lock.garage"])
    client = make_client(fake, door_groups=DOOR_GROUPS, auth=make_auth(tmp_path, transport))
    login(client)
    resp = client.post("/api/door-groups/Street/set", json={"action": "lock"})
    assert resp.json() == {"total": 2, "succeeded": 1, "failed": ["lock.garage"]}


def test_door_group_unlock_all_is_refused(make_client, tmp_path):
    # Unlocking every door in one tap is a footgun; groups only lock.
    transport, _ = fake_google()
    client = make_client(FakeHAClient(), door_groups=DOOR_GROUPS, auth=make_auth(tmp_path, transport))
    login(client)
    resp = client.post("/api/door-groups/Street/set", json={"action": "unlock"})
    assert resp.status_code == 400


def test_session_survives_restart_with_persisted_secret(make_client, tmp_path):
    transport, _ = fake_google()
    client = make_client(FakeHAClient(), auth=make_auth(tmp_path, transport))
    login(client)
    cookie = client.cookies["session"]
    # "Restart": a new Auth built from the same secret file must accept the cookie
    client2 = make_client(FakeHAClient(), auth=make_auth(tmp_path, transport))
    client2.cookies.set("session", cookie)
    assert client2.get("/auth/me").json() == {"email": "martin@example.com"}


def test_static_asset_links_include_doors_page():
    from pathlib import Path

    import yaml

    root = Path(__file__).parent.parent
    version = yaml.safe_load((root / "config.yaml").read_text())["version"]
    html = (root / "app" / "static" / "doors.html").read_text()
    for asset in ("/style.css", "/shared.js", "/doors.js"):
        assert f'"{asset}?v={version}"' in html, asset
    for page in ("index.html", "windows.html", "doors.html"):
        assert 'href="/doors.html"' in (root / "app" / "static" / page).read_text(), page


# ---- momentary Open via MQTT -------------------------------------------------

from tests.conftest import lock_discovery


def test_doors_state_reports_supports_open(make_client, tmp_path):
    transport, _ = fake_google()
    fake = FakeHAClient(states=LOCKS)
    fake.mqtt_retained = [lock_discovery("abc", "Front Door")]  # no config for Garage
    client = make_client(fake, auth=make_auth(tmp_path, transport))
    login(client)
    units = client.get("/api/doors").json()["groups"][0]["units"]
    by_id = {u["entity_id"]: u for u in units}
    assert by_id["lock.front_door"]["supports_open"] is True
    assert by_id["lock.garage"]["supports_open"] is False


def test_open_door_publishes_open_to_command_topic(make_client, tmp_path):
    transport, _ = fake_google()
    fake = FakeHAClient(states=LOCKS)
    fake.mqtt_retained = [lock_discovery("abc", "Front Door")]
    client = make_client(fake, auth=make_auth(tmp_path, transport))
    login(client)
    resp = client.post("/api/doors/lock.front_door/set", json={"action": "open"})
    assert resp.status_code == 200
    assert fake.calls == [("mqtt_publish", "inception/lock/abc/set", "Open")]


def test_open_door_without_topic_is_409(make_client, tmp_path):
    transport, _ = fake_google()
    fake = FakeHAClient(states=LOCKS)
    client = make_client(fake, auth=make_auth(tmp_path, transport))
    login(client)
    resp = client.post("/api/doors/lock.garage/set", json={"action": "open"})
    assert resp.status_code == 409
    assert fake.calls == []


def test_open_unknown_door_is_404(make_client, tmp_path):
    transport, _ = fake_google()
    client = make_client(FakeHAClient(states=LOCKS), auth=make_auth(tmp_path, transport))
    login(client)
    assert client.post("/api/doors/lock.nope/set", json={"action": "open"}).status_code == 404


def test_door_group_open_all_is_refused(make_client, tmp_path):
    transport, _ = fake_google()
    client = make_client(FakeHAClient(), door_groups=DOOR_GROUPS, auth=make_auth(tmp_path, transport))
    login(client)
    assert client.post("/api/door-groups/Street/set", json={"action": "open"}).status_code == 400


# ---- diagnostics + single-poll doors page -----------------------------------

import logging


def test_ha_error_is_logged_with_path_and_cause(make_client, caplog):
    client = make_client(FakeHAClient(fail_states=True))
    with caplog.at_level(logging.WARNING, logger="app.main"):
        resp = client.get("/api/state")
    assert resp.status_code == 502
    assert any("/api/state" in r.getMessage() and "HA unreachable" in r.getMessage()
               for r in caplog.records)


def test_doors_state_includes_temperatures(make_client, tmp_path):
    transport, _ = fake_google()
    fake = FakeHAClient(states=LOCKS + [
        sensor_ha_state("sensor.wn1980c_outdoor_temperature", state="11.9"),
    ])
    client = make_client(fake, auth=make_auth(tmp_path, transport))
    login(client)
    body = client.get("/api/doors").json()
    assert body["temperatures"]["outdoor"]["temp"] == 11.9
    assert body["temperatures"]["indoor"] is None


# ---- door display names ------------------------------------------------------


def test_doors_use_display_names_and_open_still_resolves(make_client, tmp_path):
    transport, _ = fake_google()
    fake = FakeHAClient(states=LOCKS)
    fake.mqtt_retained = [lock_discovery("abc", "Front Door")]  # discovery uses HA name
    client = make_client(
        fake, auth=make_auth(tmp_path, transport),
        door_names={"lock.front_door": "Front door (street)"},
    )
    login(client)
    units = {u["entity_id"]: u for g in client.get("/api/doors").json()["groups"] for u in g["units"]}
    assert units["lock.front_door"]["name"] == "Front door (street)"
    assert units["lock.front_door"]["supports_open"] is True
    assert units["lock.garage"]["name"] == "Garage"
    resp = client.post("/api/doors/lock.front_door/set", json={"action": "open"})
    assert resp.status_code == 200
    assert fake.calls == [("mqtt_publish", "inception/lock/abc/set", "Open")]
