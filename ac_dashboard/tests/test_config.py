import pytest

from app.config import Settings, load_groups
from app.config import Preset, load_presets


def test_load_groups_parses_yaml(tmp_path):
    f = tmp_path / "groups.yaml"
    f.write_text(
        "groups:\n"
        "  - name: Upstairs\n"
        "    entities: [climate.bedroom, climate.office]\n"
        "  - name: Downstairs\n"
        "    entities: [climate.living_room]\n"
    )
    groups = load_groups(f)
    assert [g.name for g in groups] == ["Upstairs", "Downstairs"]
    assert groups[0].entities == ["climate.bedroom", "climate.office"]


def test_load_groups_missing_file_returns_empty(tmp_path):
    assert load_groups(tmp_path / "nope.yaml") == []


def test_load_groups_empty_file_returns_empty(tmp_path):
    f = tmp_path / "groups.yaml"
    f.write_text("")
    assert load_groups(f) == []


def test_load_groups_malformed_raises_value_error(tmp_path):
    f = tmp_path / "groups.yaml"
    f.write_text("groups: hello\n")
    with pytest.raises(ValueError, match="Invalid groups.yaml"):
        load_groups(f)


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.ha_url == "http://localhost:8123"
    assert s.ha_token == ""


def test_load_presets_parses_yaml(tmp_path):
    f = tmp_path / "presets.yaml"
    f.write_text(
        "presets:\n"
        "  - name: Evening warmth\n"
        "    entities: [climate.living_left, climate.living_right]\n"
        "    mode: heat\n"
        "    temperature: 23\n"
        "    time: '18:00'\n"
    )
    (p,) = load_presets(f)
    assert p.id == "evening_warmth"
    assert p.entities == ["climate.living_left", "climate.living_right"]
    assert p.mode == "heat"
    assert p.temperature == 23.0
    assert p.time == "18:00"


def test_load_presets_missing_file_returns_empty(tmp_path):
    assert load_presets(tmp_path / "nope.yaml") == []


def test_preset_invalid_time_raises(tmp_path):
    f = tmp_path / "presets.yaml"
    f.write_text(
        "presets:\n"
        "  - name: Bad\n"
        "    entities: [climate.x]\n"
        "    mode: heat\n"
        "    time: '25:99'\n"
    )
    with pytest.raises(ValueError, match="Invalid presets.yaml"):
        load_presets(f)


def test_preset_requires_mode_or_temperature():
    with pytest.raises(ValueError, match="mode and/or temperature"):
        Preset(name="X", entities=["climate.x"], time="18:00")


def test_preset_requires_entities():
    with pytest.raises(ValueError, match="entities"):
        Preset(name="X", entities=[], mode="heat", time="18:00")


def test_duplicate_preset_names_raise(tmp_path):
    f = tmp_path / "presets.yaml"
    f.write_text(
        "presets:\n"
        "  - {name: Same Name, entities: [climate.a], mode: heat, time: '18:00'}\n"
        "  - {name: same name, entities: [climate.b], mode: cool, time: '19:00'}\n"
    )
    with pytest.raises(ValueError, match="Duplicate preset"):
        load_presets(f)


def test_preset_id_strips_url_unsafe_characters():
    p = Preset(name="Living/Dining #1!", entities=["climate.x"], mode="cool", time="08:00")
    assert p.id == "livingdining_1"


def test_preset_name_without_alphanumerics_raises():
    with pytest.raises(ValueError, match="letter or digit"):
        Preset(name="!!!", entities=["climate.x"], mode="cool", time="08:00")
