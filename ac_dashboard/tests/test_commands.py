import pytest
from pydantic import ValidationError

from app.commands import CommandError, CoverCommand, SetCommand, apply_command

from tests.conftest import FakeHAClient


def test_cover_command_requires_action_or_position():
    with pytest.raises(ValidationError, match="action and/or position"):
        CoverCommand()


def test_cover_command_rejects_unknown_action():
    with pytest.raises(ValidationError, match="open, close or stop"):
        CoverCommand(action="tilt")


def test_cover_command_rejects_position_out_of_range():
    with pytest.raises(ValidationError, match="0-100"):
        CoverCommand(position=101)


async def test_cover_open_calls_open_cover():
    fake = FakeHAClient()
    await apply_command(fake, "cover.win", CoverCommand(action="open"))
    assert fake.calls == [("open_cover", "cover.win")]


async def test_cover_close_calls_close_cover():
    fake = FakeHAClient()
    await apply_command(fake, "cover.win", CoverCommand(action="close"))
    assert fake.calls == [("close_cover", "cover.win")]


async def test_cover_stop_wins_over_position():
    fake = FakeHAClient()
    await apply_command(fake, "cover.win", CoverCommand(action="stop", position=50))
    assert fake.calls == [("stop_cover", "cover.win")]


async def test_cover_position_wins_over_open_close():
    fake = FakeHAClient()
    await apply_command(fake, "cover.win", CoverCommand(action="open", position=40))
    assert fake.calls == [("set_cover_position", "cover.win", 40)]


async def test_cover_position_only():
    fake = FakeHAClient()
    await apply_command(fake, "cover.win", CoverCommand(position=0))
    assert fake.calls == [("set_cover_position", "cover.win", 0)]


async def test_climate_command_on_cover_entity_raises():
    with pytest.raises(CommandError):
        await apply_command(FakeHAClient(), "cover.win", SetCommand(mode="off"))


async def test_cover_command_on_climate_entity_raises():
    with pytest.raises(CommandError):
        await apply_command(
            FakeHAClient(), "climate.bedroom", CoverCommand(action="open")
        )


async def test_unknown_domain_raises():
    with pytest.raises(CommandError):
        await apply_command(FakeHAClient(), "light.kitchen", SetCommand(mode="off"))
