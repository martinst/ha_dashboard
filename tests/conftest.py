def ha_state(entity_id, state="cool", **attrs):
    """Build an HA climate state dict like GET /api/states returns."""
    base = {
        "friendly_name": entity_id.split(".")[1].replace("_", " ").title(),
        "current_temperature": 24.0,
        "temperature": 22.0,
        "hvac_modes": ["off", "cool", "heat", "dry", "fan_only", "auto"],
        "min_temp": 16,
        "max_temp": 30,
    }
    base.update(attrs)
    return {"entity_id": entity_id, "state": state, "attributes": base}
