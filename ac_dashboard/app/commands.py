from pydantic import BaseModel, model_validator

from app.ha_client import HAClient


class SetCommand(BaseModel):
    mode: str | None = None
    temperature: float | None = None

    @model_validator(mode="after")
    def at_least_one_field(self):
        if self.mode is None and self.temperature is None:
            raise ValueError("provide mode and/or temperature")
        return self


async def apply_command(ha: HAClient, entity_id: str, cmd: SetCommand) -> None:
    if cmd.mode == "on":
        await ha.turn_on(entity_id)
    elif cmd.mode is not None:
        await ha.set_hvac_mode(entity_id, cmd.mode)
    if cmd.temperature is not None:
        await ha.set_temperature(entity_id, cmd.temperature)
