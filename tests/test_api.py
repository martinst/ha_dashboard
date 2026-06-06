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
