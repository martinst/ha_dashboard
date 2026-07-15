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
        "available": state.get("state") not in ("unavailable", "unknown"),
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


def _build(states: list[dict], groups: list[Group], state_fn, missing_fn) -> list[dict]:
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
        key=lambda u: u["name"],
    )
    if ungrouped:
        result.append({"name": UNGROUPED, "units": ungrouped})
    return result


def build_groups(climate_states: list[dict], groups: list[Group]) -> list[dict]:
    return _build(climate_states, groups, unit_from_ha_state, missing_unit)


def build_cover_groups(cover_states: list[dict], groups: list[Group]) -> list[dict]:
    return _build(cover_states, groups, cover_from_ha_state, missing_cover)
