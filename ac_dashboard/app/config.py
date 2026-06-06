from pathlib import Path

import yaml
from pydantic import BaseModel, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict


class Group(BaseModel):
    name: str
    entities: list[str]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ha_url: str = "http://localhost:8123"
    ha_token: str = ""


def load_groups(path: str | Path = "groups.yaml") -> list[Group]:
    path = Path(path)
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text()) or {}
    try:
        return [Group(**g) for g in data.get("groups", [])]
    except (TypeError, ValidationError) as exc:
        raise ValueError(f"Invalid groups.yaml ({path}): {exc}") from exc
