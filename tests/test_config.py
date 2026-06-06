from app.config import Settings, load_groups


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


def test_settings_defaults():
    s = Settings(_env_file=None)
    assert s.ha_url == "http://localhost:8123"
    assert s.ha_token == ""
