from app.config import Group
from app.state import build_groups

from tests.conftest import ha_state


def test_groups_units_in_configured_order():
    states = [ha_state("climate.office"), ha_state("climate.bedroom")]
    groups = [Group(name="Upstairs", entities=["climate.bedroom", "climate.office"])]
    result = build_groups(states, groups)
    assert len(result) == 1
    assert result[0]["name"] == "Upstairs"
    assert [u["entity_id"] for u in result[0]["units"]] == [
        "climate.bedroom", "climate.office"
    ]


def test_unit_fields_mapped_from_ha_state():
    states = [ha_state("climate.bedroom", state="heat", current_temperature=19.5,
                       temperature=23.0)]
    result = build_groups(states, [Group(name="G", entities=["climate.bedroom"])])
    unit = result[0]["units"][0]
    assert unit == {
        "entity_id": "climate.bedroom",
        "name": "Bedroom",
        "current_temp": 19.5,
        "target_temp": 23.0,
        "mode": "heat",
        "available_modes": ["off", "cool", "heat", "dry", "fan_only", "auto"],
        "min_temp": 16,
        "max_temp": 30,
        "available": True,
    }


def test_unavailable_state_maps_to_unavailable_unit():
    states = [ha_state("climate.bedroom", state="unavailable")]
    result = build_groups(states, [Group(name="G", entities=["climate.bedroom"])])
    assert result[0]["units"][0]["available"] is False


def test_configured_entity_missing_from_ha_shows_as_unavailable():
    result = build_groups([], [Group(name="G", entities=["climate.gone"])])
    unit = result[0]["units"][0]
    assert unit["entity_id"] == "climate.gone"
    assert unit["available"] is False
    assert unit["name"] == "Gone"


def test_unlisted_entities_land_in_ungrouped_sorted_by_name():
    states = [ha_state("climate.zeta"), ha_state("climate.alpha"),
              ha_state("climate.bedroom")]
    groups = [Group(name="G", entities=["climate.bedroom"])]
    result = build_groups(states, groups)
    assert [g["name"] for g in result] == ["G", "Ungrouped"]
    assert [u["name"] for u in result[1]["units"]] == ["Alpha", "Zeta"]


def test_no_ungrouped_section_when_everything_grouped():
    states = [ha_state("climate.bedroom")]
    groups = [Group(name="G", entities=["climate.bedroom"])]
    assert [g["name"] for g in build_groups(states, groups)] == ["G"]


from app.state import build_cover_groups

from tests.conftest import cover_ha_state


def test_cover_fields_mapped_from_ha_state():
    states = [cover_ha_state("cover.living_left", state="open", current_position=40)]
    result = build_cover_groups(
        states, [Group(name="Living", entities=["cover.living_left"])]
    )
    assert result[0]["units"][0] == {
        "entity_id": "cover.living_left",
        "name": "Living Left",
        "state": "open",
        "position": 40,
        "supports_position": True,
        "available": True,
    }


def test_cover_without_position_support():
    # 11 = OPEN | CLOSE | STOP, no SET_POSITION
    states = [
        cover_ha_state("cover.basic", supported_features=11, current_position=None)
    ]
    result = build_cover_groups(states, [Group(name="G", entities=["cover.basic"])])
    unit = result[0]["units"][0]
    assert unit["supports_position"] is False
    assert unit["position"] is None


def test_unavailable_cover_maps_to_unavailable():
    states = [cover_ha_state("cover.win", state="unavailable")]
    result = build_cover_groups(states, [Group(name="G", entities=["cover.win"])])
    assert result[0]["units"][0]["available"] is False


def test_configured_cover_missing_from_ha_shows_as_unavailable():
    result = build_cover_groups([], [Group(name="G", entities=["cover.gone"])])
    unit = result[0]["units"][0]
    assert unit["entity_id"] == "cover.gone"
    assert unit["name"] == "Gone"
    assert unit["available"] is False
    assert unit["supports_position"] is False


def test_unlisted_covers_land_in_ungrouped_sorted_by_name():
    states = [cover_ha_state("cover.zeta"), cover_ha_state("cover.alpha"),
              cover_ha_state("cover.win")]
    groups = [Group(name="G", entities=["cover.win"])]
    result = build_cover_groups(states, groups)
    assert [g["name"] for g in result] == ["G", "Ungrouped"]
    assert [u["name"] for u in result[1]["units"]] == ["Alpha", "Zeta"]
