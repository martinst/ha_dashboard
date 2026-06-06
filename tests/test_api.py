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
