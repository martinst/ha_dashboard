from pydantic import BaseModel, model_validator

from app.ha_client import HAClient


class CommandError(ValueError):
    """Raised when a command doesn't match the target entity's domain."""


class SetCommand(BaseModel):
    mode: str | None = None
    temperature: float | None = None

    @model_validator(mode="after")
    def at_least_one_field(self):
        if self.mode is None and self.temperature is None:
            raise ValueError("provide mode and/or temperature")
        return self


class CoverCommand(BaseModel):
    action: str | None = None
    position: int | None = None

    @model_validator(mode="after")
    def validate_command(self):
        if self.action is None and self.position is None:
            raise ValueError("provide action and/or position")
        if self.action is not None and self.action not in ("open", "close", "stop"):
            raise ValueError(f"action must be open, close or stop, got {self.action!r}")
        if self.position is not None and not 0 <= self.position <= 100:
            raise ValueError(f"position must be 0-100, got {self.position}")
        return self


async def apply_command(
    ha: HAClient, entity_id: str, cmd: SetCommand | CoverCommand
) -> None:
    if entity_id.startswith("climate."):
        if not isinstance(cmd, SetCommand):
            raise CommandError(f"{entity_id} requires a climate command")
        if cmd.mode == "on":
            await ha.turn_on(entity_id)
        elif cmd.mode is not None:
            await ha.set_hvac_mode(entity_id, cmd.mode)
        if cmd.temperature is not None:
            await ha.set_temperature(entity_id, cmd.temperature)
    elif entity_id.startswith("cover."):
        if not isinstance(cmd, CoverCommand):
            raise CommandError(f"{entity_id} requires a cover command")
        if cmd.action == "stop":
            await ha.stop_cover(entity_id)
        elif cmd.position is not None:
            await ha.set_cover_position(entity_id, cmd.position)
        elif cmd.action == "open":
            await ha.open_cover(entity_id)
        else:
            await ha.close_cover(entity_id)
    else:
        raise CommandError(f"unsupported entity domain: {entity_id}")
