import asyncio
import json
import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.commands import SetCommand, apply_command
from app.config import Preset
from app.ha_client import HAClient

log = logging.getLogger(__name__)

GRACE = timedelta(hours=1)
MAX_AHEAD = timedelta(days=7)
TICK_SECONDS = 10


class ArmError(ValueError):
    """Raised when an arm request is invalid (past time, too far ahead)."""


async def fetch_timezone(ha: HAClient):
    """HA's configured timezone, falling back to system local time."""
    try:
        config = await ha.get_config()
        return ZoneInfo(config["time_zone"])
    except Exception as exc:
        log.warning("Could not get HA timezone (%s); using system local time", exc)
        return datetime.now().astimezone().tzinfo


class Scheduler:
    """One-shot preset schedules: armed state, persistence, firing loop."""

    def __init__(self, presets: list[Preset], ha: HAClient, path, tz, now=None):
        self.presets = {p.id: p for p in presets}
        self._ha = ha
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._tz = tz
        self._now = now or (lambda: datetime.now(self._tz))
        self.armed: dict[str, datetime] = {}
        self._task: asyncio.Task | None = None
        self._load()

    # -- persistence --

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text())
        except (OSError, ValueError) as exc:
            log.warning("Ignoring corrupt %s: %s", self._path, exc)
            return
        for preset_id, iso in raw.items():
            if preset_id not in self.presets:
                log.warning("Dropping armed schedule for unknown preset %r", preset_id)
                continue
            self.armed[preset_id] = datetime.fromisoformat(iso)

    def _save(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({pid: dt.isoformat() for pid, dt in self.armed.items()})
        )
        os.replace(tmp, self._path)

    # -- arm / cancel --

    def arm(self, preset_id: str, date_str: str, time_str: str) -> datetime:
        if preset_id not in self.presets:
            raise KeyError(preset_id)
        fires_at = datetime.fromisoformat(f"{date_str}T{time_str}").replace(
            tzinfo=self._tz
        )
        now = self._now()
        if fires_at <= now:
            raise ArmError("fire time is in the past")
        if fires_at - now > MAX_AHEAD:
            raise ArmError("fire time is more than 7 days ahead")
        self.armed[preset_id] = fires_at
        self._save()
        return fires_at

    def cancel(self, preset_id: str) -> None:
        if preset_id not in self.presets:
            raise KeyError(preset_id)
        if self.armed.pop(preset_id, None) is not None:
            self._save()

    # -- firing loop --

    def start(self) -> None:
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _run(self) -> None:
        while True:
            try:
                await self.check_due()
            except Exception:
                log.exception("Scheduler tick failed")
            await asyncio.sleep(TICK_SECONDS)

    async def check_due(self) -> None:
        now = self._now()
        for preset_id, fires_at in list(self.armed.items()):
            if fires_at > now:
                continue
            del self.armed[preset_id]
            self._save()
            if now - fires_at > GRACE:
                log.warning(
                    "Discarding %r: fire time %s is too far in the past",
                    preset_id,
                    fires_at,
                )
                continue
            await self._fire(self.presets[preset_id])

    async def _fire(self, preset: Preset) -> None:
        cmd = SetCommand(mode=preset.mode, temperature=preset.temperature)
        results = await asyncio.gather(
            *(apply_command(self._ha, entity_id, cmd) for entity_id in preset.entities),
            return_exceptions=True,
        )
        failed = [
            entity_id
            for entity_id, result in zip(preset.entities, results)
            if isinstance(result, Exception)
        ]
        if failed:
            log.warning("Preset %r fired with failures: %s", preset.id, failed)
        else:
            log.info("Preset %r fired for %d unit(s)", preset.id, len(preset.entities))
