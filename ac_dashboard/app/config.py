import re
from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Group(BaseModel):
    name: str
    entities: list[str]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ha_url: str = "http://localhost:8123"
    ha_token: str = ""
    schedules_path: str = "schedules.json"


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
        if self.mode is None and self.temperature is None:
            raise ValueError("provide mode and/or temperature")
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", self.time):
            raise ValueError(f"time must be HH:MM, got {self.time!r}")
        return self

    @property
    def id(self) -> str:
        return self.name.lower().replace(" ", "_")


def load_presets(path: str | Path = "presets.yaml") -> list[Preset]:
    path = Path(path)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    try:
        presets = [Preset(**p) for p in data.get("presets", [])]
    except (TypeError, ValidationError) as exc:
        raise ValueError(f"Invalid presets.yaml ({path}): {exc}") from exc
    ids = [p.id for p in presets]
    duplicates = sorted({i for i in ids if ids.count(i) > 1})
    if duplicates:
        raise ValueError(f"Duplicate preset ids in {path}: {duplicates}")
    return presets


def load_groups(path: str | Path = "groups.yaml") -> list[Group]:
    path = Path(path)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    try:
        return [Group(**g) for g in data.get("groups", [])]
    except (TypeError, ValidationError) as exc:
        raise ValueError(f"Invalid groups.yaml ({path}): {exc}") from exc
