import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
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


@dataclass
class OnceArm:
    """A one-shot armed schedule: fires once, then disarms."""

    fires_at: datetime

    @property
    def due_at(self) -> datetime:
        return self.fires_at

    def to_json(self) -> dict:
        return {"type": "once", "fires_at": self.fires_at.isoformat()}


@dataclass
class WeeklyArm:
    """A recurring armed schedule: fires on selected weekdays until cancelled."""

    days: set[int]  # Mon=0 .. Sun=6
    time: str  # "HH:MM"
    next_fire: datetime

    @property
    def due_at(self) -> datetime:
        return self.next_fire

    def to_json(self) -> dict:
        return {
            "type": "weekly",
            "days": sorted(self.days),
            "time": self.time,
            "next_fire": self.next_fire.isoformat(),
        }


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
        self.armed: dict[str, OnceArm | WeeklyArm] = {}
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
        for preset_id, entry in raw.items():
            if preset_id not in self.presets:
                log.warning("Dropping armed schedule for unknown preset %r", preset_id)
                continue
            try:
                self.armed[preset_id] = self._entry_from_json(entry)
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("Dropping unreadable schedule for %r: %s", preset_id, exc)

    @staticmethod
    def _entry_from_json(entry):
        if isinstance(entry, str):  # legacy v1.2.0 format: bare ISO datetime
            return OnceArm(fires_at=datetime.fromisoformat(entry))
        if entry["type"] == "once":
            return OnceArm(fires_at=datetime.fromisoformat(entry["fires_at"]))
        if entry["type"] == "weekly":
            return WeeklyArm(
                days=set(entry["days"]),
                time=entry["time"],
                next_fire=datetime.fromisoformat(entry["next_fire"]),
            )
        raise ValueError(f"unknown schedule type {entry.get('type')!r}")

    def _save(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({pid: arm.to_json() for pid, arm in self.armed.items()})
        )
        os.replace(tmp, self._path)

    # -- arm / cancel --

    def arm(self, preset_id: str, date_str: str, time_str: str) -> OnceArm:
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
        arm = OnceArm(fires_at=fires_at)
        self.armed[preset_id] = arm
        self._save()
        return arm

    def cancel(self, preset_id: str) -> None:
        if preset_id not in self.presets:
            raise KeyError(preset_id)
        if self.armed.pop(preset_id, None) is not None:
            self._save()

    def arm_weekly(self, preset_id: str, days: list[int], time_str: str) -> "WeeklyArm":
        if preset_id not in self.presets:
            raise KeyError(preset_id)
        day_set = set(days)
        if not day_set:
            raise ArmError("select at least one day")
        if not day_set <= set(range(7)):
            raise ArmError("repeat days must be 0-6 (Mon-Sun)")
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", time_str):
            raise ArmError(f"time must be HH:MM, got {time_str!r}")
        arm = WeeklyArm(
            days=day_set,
            time=time_str,
            next_fire=self._next_occurrence(self._now(), day_set, time_str),
        )
        self.armed[preset_id] = arm
        self._save()
        return arm

    def _next_occurrence(self, start: datetime, days: set[int], time_str: str) -> datetime:
        hour, minute = (int(part) for part in time_str.split(":"))
        for offset in range(8):
            day = (start + timedelta(days=offset)).date()
            if day.weekday() not in days:
                continue
            candidate = datetime(
                day.year, day.month, day.day, hour, minute, tzinfo=self._tz
            )
            if candidate > start:
                return candidate
        raise ArmError("no upcoming occurrence")  # unreachable with valid days

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
        for preset_id, arm in list(self.armed.items()):
            due = arm.due_at
            if due > now:
                continue
            if isinstance(arm, WeeklyArm):
                arm.next_fire = self._next_occurrence(now, arm.days, arm.time)
            else:
                del self.armed[preset_id]
            self._save()
            if now - due > GRACE:
                log.warning(
                    "Skipping %r: fire time %s is too far in the past",
                    preset_id,
                    due,
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
