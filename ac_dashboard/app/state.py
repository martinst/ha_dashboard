from app.config import Group

UNGROUPED = "Ungrouped"


def unit_from_ha_state(state: dict) -> dict:
    attrs = state.get("attributes", {})
    return {
        "entity_id": state["entity_id"],
        "name": attrs.get("friendly_name", state["entity_id"]),
        "current_temp": attrs.get("current_temperature"),
        "target_temp": attrs.get("temperature"),
        "mode": state.get("state"),
        "available_modes": attrs.get("hvac_modes", []),
        "min_temp": attrs.get("min_temp"),
        "max_temp": attrs.get("max_temp"),
        "available": state.get("state") not in ("unavailable", "unknown"),
    }


def missing_unit(entity_id: str) -> dict:
    """Placeholder for a groups.yaml entity that HA doesn't know about."""
    return {
        "entity_id": entity_id,
        "name": entity_id.removeprefix("climate.").replace("_", " ").title(),
        "current_temp": None,
        "target_temp": None,
        "mode": None,
        "available_modes": [],
        "min_temp": None,
        "max_temp": None,
        "available": False,
    }


SUPPORT_SET_POSITION = 4  # cover supported_features flag


def cover_from_ha_state(state: dict) -> dict:
    attrs = state.get("attributes", {})
    features = attrs.get("supported_features") or 0
    position = attrs.get("current_position")
    return {
        "entity_id": state["entity_id"],
        "name": attrs.get("friendly_name", state["entity_id"]),
        "state": state.get("state"),
        "position": position,
        "supports_position": bool(features & SUPPORT_SET_POSITION)
        or position is not None,
        # "unknown" stays available: stateless covers (e.g. Somfy RTS) report
        # no position/state but still accept commands.
        "available": state.get("state") != "unavailable",
    }


def missing_cover(entity_id: str) -> dict:
    """Placeholder for a window_groups entity that HA doesn't know about."""
    return {
        "entity_id": entity_id,
        "name": entity_id.removeprefix("cover.").replace("_", " ").title(),
        "state": None,
        "position": None,
        "supports_position": False,
        "available": False,
    }


def _build(
    states: list[dict], groups: list[Group], state_fn, missing_fn, sort_key=None
) -> list[dict]:
    by_id = {s["entity_id"]: s for s in states}
    grouped_ids: set[str] = set()
    result = []
    for group in groups:
        units = []
        for entity_id in group.entities:
            grouped_ids.add(entity_id)
            state = by_id.get(entity_id)
            units.append(state_fn(state) if state else missing_fn(entity_id))
        result.append({"name": group.name, "units": units})

    ungrouped = sorted(
        (state_fn(s) for eid, s in by_id.items() if eid not in grouped_ids),
        key=sort_key or (lambda u: u["name"]),
    )
    if ungrouped:
        result.append({"name": UNGROUPED, "units": ungrouped})
    return result


def build_groups(climate_states: list[dict], groups: list[Group]) -> list[dict]:
    return _build(climate_states, groups, unit_from_ha_state, missing_unit)


def build_cover_groups(cover_states: list[dict], groups: list[Group]) -> list[dict]:
    return _build(cover_states, groups, cover_from_ha_state, missing_cover)


def lock_from_ha_state(state: dict) -> dict:
    attrs = state.get("attributes", {})
    return {
        "entity_id": state["entity_id"],
        "name": attrs.get("friendly_name", state["entity_id"]),
        "state": state.get("state"),
        "available": state.get("state") not in ("unavailable", "unknown"),
    }


def missing_lock(entity_id: str) -> dict:
    return {
        "entity_id": entity_id,
        "name": entity_id.removeprefix("lock.").replace("_", " ").title(),
        "state": None,
        "available": False,
    }


def build_lock_groups(
    lock_states: list[dict],
    groups: list[Group],
    names: dict[str, str] | None = None,
    order: list[str] | None = None,
) -> list[dict]:
    """Lock groups with optional display-name overrides and explicit ordering.

    The HA name is kept as `ha_name` — it is what MQTT discovery configs are
    matched on. Doors listed in `order` come first, in that order; the rest
    follow sorted by display name."""
    names = names or {}
    rank = {entity_id: i for i, entity_id in enumerate(order or [])}

    def _display(unit: dict) -> dict:
        unit["ha_name"] = unit["name"]
        unit["name"] = names.get(unit["entity_id"], unit["name"])
        return unit

    return _build(
        lock_states,
        groups,
        lambda s: _display(lock_from_ha_state(s)),
        lambda eid: _display(missing_lock(eid)),
        sort_key=lambda u: (rank.get(u["entity_id"], len(rank)), u["name"]),
    )


# ---- temperature sensors (e.g. an Ecowitt weather console) ----

OUTDOOR_SUFFIX = "_outdoor_temperature"
INDOOR_SUFFIX = "_indoor_temperature"


def _is_temperature_sensor(state: dict) -> bool:
    return state.get("attributes", {}).get("device_class") == "temperature"


def _auto_detect(states: list[dict], suffix: str) -> str | None:
    """Ecowitt names its console sensors sensor.<model>_outdoor_temperature
    and sensor.<model>_indoor_temperature; pick the first such sensor."""
    matches = sorted(
        s["entity_id"]
        for s in states
        if s["entity_id"].endswith(suffix) and _is_temperature_sensor(s)
    )
    return matches[0] if matches else None


def temperature_from_ha_state(state: dict) -> dict:
    attrs = state.get("attributes", {})
    try:
        temp = float(state.get("state"))
    except (TypeError, ValueError):
        temp = None
    return {
        "entity_id": state["entity_id"],
        "name": attrs.get("friendly_name", state["entity_id"]),
        "temp": temp,
        "unit": attrs.get("unit_of_measurement"),
        "available": temp is not None,
    }


def missing_temperature(entity_id: str) -> dict:
    return {
        "entity_id": entity_id,
        "name": entity_id.removeprefix("sensor.").replace("_", " ").title(),
        "temp": None,
        "unit": None,
        "available": False,
    }


def build_temperatures(
    sensor_states: list[dict], outdoor: str | None, indoor: str | None
) -> dict:
    by_id = {s["entity_id"]: s for s in sensor_states}
    result = {}
    for key, configured, suffix in (
        ("outdoor", outdoor, OUTDOOR_SUFFIX),
        ("indoor", indoor, INDOOR_SUFFIX),
    ):
        entity_id = configured or _auto_detect(sensor_states, suffix)
        if not entity_id:
            result[key] = None
        elif entity_id in by_id:
            result[key] = temperature_from_ha_state(by_id[entity_id])
        else:
            result[key] = missing_temperature(entity_id)
    return result
