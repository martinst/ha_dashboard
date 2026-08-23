import re
from pathlib import Path
from typing import ClassVar

import yaml
from pydantic import BaseModel, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.commands import CoverCommand, SetCommand


class Group(BaseModel):
    name: str
    entities: list[str]


class SensorConfig(BaseModel):
    """Temperature sensors shown at the top of every page.

    Empty means auto-detect (Ecowitt-style *_outdoor_temperature /
    *_indoor_temperature sensors)."""

    outdoor: str | None = None
    indoor: str | None = None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ha_url: str = "http://localhost:8123"
    ha_token: str = ""
    ha_ws_url: str = ""  # empty = derive from ha_url (…/api/websocket)
    schedules_path: str = "schedules.json"
    outdoor_sensor: str = ""
    indoor_sensor: str = ""
    # Google sign-in for the Doors page (empty client id = page disabled)
    google_client_id: str = ""
    google_client_secret: str = ""
    allowed_emails: str = ""  # comma-separated
    session_secret_path: str = "session_secret"
    session_days: int = 365

    def sensor_config(self) -> SensorConfig:
        return SensorConfig(
            outdoor=self.outdoor_sensor.strip() or None,
            indoor=self.indoor_sensor.strip() or None,
        )


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "", name.lower().replace(" ", "_"))


class Preset(BaseModel):
    name: str
    entities: list[str]
    mode: str | None = None
    temperature: float | None = None
    time: str

    @model_validator(mode="after")
    def validate_preset(self):
        if not self.entities:
            raise ValueError("entities must be non-empty")
        if not _slug(self.name):
            raise ValueError("name must contain at least one letter or digit")
        if self.mode is None and self.temperature is None:
            raise ValueError("provide mode and/or temperature")
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", self.time):
            raise ValueError(f"time must be HH:MM, got {self.time!r}")
        return self

    @property
    def id(self) -> str:
        return _slug(self.name)

    domain: ClassVar[str] = "climate"

    def command(self) -> SetCommand:
        return SetCommand(mode=self.mode, temperature=self.temperature)


class CoverPreset(BaseModel):
    name: str
    entities: list[str]
    action: str | None = None
    position: int | None = None
    time: str

    domain: ClassVar[str] = "cover"

    @model_validator(mode="after")
    def validate_preset(self):
        if not self.entities:
            raise ValueError("entities must be non-empty")
        if not _slug(self.name):
            raise ValueError("name must contain at least one letter or digit")
        if self.action is None and self.position is None:
            raise ValueError("provide action and/or position")
        if self.action is not None and self.action not in ("open", "close"):
            raise ValueError(f"action must be open or close, got {self.action!r}")
        if self.position is not None and not 0 <= self.position <= 100:
            raise ValueError(f"position must be 0-100, got {self.position}")
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", self.time):
            raise ValueError(f"time must be HH:MM, got {self.time!r}")
        return self

    @property
    def id(self) -> str:
        return f"cover:{_slug(self.name)}"

    def command(self) -> CoverCommand:
        return CoverCommand(action=self.action, position=self.position)


def _load_preset_file(path: Path, model, label: str) -> list:
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    try:
        presets = [model(**p) for p in data.get("presets", [])]
    except (TypeError, ValidationError) as exc:
        raise ValueError(f"Invalid {label} ({path}): {exc}") from exc
    ids = [p.id for p in presets]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"Duplicate preset ids in {path}: {duplicates}")
    return presets


def load_presets(path: str | Path = "presets.yaml") -> list[Preset]:
    return _load_preset_file(Path(path), Preset, "presets.yaml")


def load_cover_presets(path: str | Path = "window_presets.yaml") -> list[CoverPreset]:
    return _load_preset_file(Path(path), CoverPreset, "window_presets.yaml")


def load_groups(path: str | Path = "groups.yaml") -> list[Group]:
    path = Path(path)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    try:
        return [Group(**g) for g in data.get("groups", [])]
    except (TypeError, ValidationError) as exc:
        raise ValueError(f"Invalid groups.yaml ({path}): {exc}") from exc


class DoorName(BaseModel):
    entity: str
    name: str


def load_door_names(path: str | Path = "door_names.yaml") -> dict[str, str]:
    """{entity_id: display name} overrides for the Doors page."""
    path = Path(path)
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    try:
        entries = [DoorName(**n) for n in data.get("names", [])]
    except (TypeError, ValidationError) as exc:
        raise ValueError(f"Invalid door_names ({path}): {exc}") from exc
    return {n.entity: n.name for n in entries}


def load_door_order(path: str | Path = "door_order.yaml") -> list[str]:
    """Entity ids in display order for the Doors page (unlisted sort after)."""
    path = Path(path)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    order = data.get("order", [])
    if not isinstance(order, list) or any(not isinstance(e, str) for e in order):
        raise ValueError(f"Invalid door_order ({path}): must be a list of entity ids")
    return order
