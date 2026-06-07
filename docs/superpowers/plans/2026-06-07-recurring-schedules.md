# Recurring Schedules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A "Repeat" arm mode: presets fire on chosen weekdays at a chosen time until cancelled, alongside the existing one-shot arming.

**Architecture:** `Scheduler.armed` values become typed records (`OnceArm` | `WeeklyArm` dataclasses with a shared `due_at`); weekly entries advance `next_fire` after each fire (or missed-beyond-grace skip) and stay armed. The arm endpoint accepts `{date,time}` or `{repeat:[days],time}`; the UI gains a Once/Repeat toggle with weekday chips. Spec: `docs/superpowers/specs/2026-06-07-recurring-schedules-design.md`.

**Tech Stack:** existing (FastAPI, pydantic, vanilla JS). Weekday numbering: Python convention Mon=0…Sun=6 everywhere; JS converts from `Date.getDay()` (Sun=0) via `(d+6)%7`.

**Working directory: all commands run from `ac_dashboard/`** (venv at repo root: `../.venv/bin/pytest`; running pytest elsewhere gives bogus async failures). Current suite: 60 passed. Useful fact for tests: **2026-06-07 is a Sunday** (weekday 6); 2026-06-08 is a Monday (weekday 0).

---

## File structure

| File | Change |
|---|---|
| `app/scheduler.py` | `OnceArm`/`WeeklyArm` dataclasses, `arm_weekly`, `_next_occurrence`, typed `check_due`/persistence |
| `app/main.py` | `ArmRequest` gains `repeat`; arm endpoint dispatches; serialization via `to_json()` |
| `app/static/app.js` | Once/Repeat toggle, weekday chips, weekly armed labels |
| `app/static/style.css` | mode toggle + day chips |
| `config.yaml`, `CHANGELOG.md`, `DOCS.md` | v1.3.0 |
| `tests/test_scheduler.py`, `tests/test_api.py` | updated + extended |

---

### Task 1: Typed armed records (OnceArm refactor)

`armed` values change from bare datetimes to `OnceArm` records; persistence becomes `{"type": "once", "fires_at": iso}` with legacy plain-string values still loading. `arm()` returns the record. Behavior is otherwise identical.

**Files:**
- Modify: `app/scheduler.py`, `app/main.py`
- Test: `tests/test_scheduler.py` (3 tests updated, 1 added)

- [ ] **Step 1: Update tests in `tests/test_scheduler.py`**

Add to the imports: `from app.scheduler import ArmError, OnceArm, Scheduler`.

REPLACE `test_arm_returns_aware_datetime_and_persists` with:

```python
def test_arm_returns_once_record_and_persists(tmp_path):
    s = make_scheduler(tmp_path, Clock())
    arm = s.arm("evening_warmth", "2026-06-08", "18:00")
    assert isinstance(arm, OnceArm)
    assert arm.fires_at.isoformat().startswith("2026-06-08T18:00")
    assert arm.fires_at.tzinfo is not None
    saved = json.loads((tmp_path / "schedules.json").read_text())
    assert saved == {
        "evening_warmth": {"type": "once", "fires_at": arm.fires_at.isoformat()}
    }
```

REPLACE the two assert lines of `test_rearm_replaces` (keep the arm calls) with:

```python
    assert s.armed["evening_warmth"] is fires
    assert len(s.armed) == 1
```

(and rename its second-arm variable accordingly: `fires = s.arm("evening_warmth", "2026-06-08", "19:30")` already binds `fires` — only the asserts change.)

REPLACE the last line of `test_persistence_round_trip` with:

```python
    assert s2.armed == {"evening_warmth": fires}
```

(dataclass equality — `fires` is the `OnceArm` returned by `s1.arm(...)`.)

ADD a new test:

```python
def test_legacy_string_entry_loads_as_once(tmp_path):
    (tmp_path / "schedules.json").write_text(
        json.dumps({"evening_warmth": "2026-06-08T18:00:00+02:00"})
    )
    s = make_scheduler(tmp_path, Clock())
    arm = s.armed["evening_warmth"]
    assert isinstance(arm, OnceArm)
    assert arm.fires_at.isoformat() == "2026-06-08T18:00:00+02:00"
```

Note: `test_arm_creates_missing_state_directory`, the grace tests, and the others need no edits — they don't touch the record shape.

- [ ] **Step 2: Run to verify failure**

Run: `../.venv/bin/pytest tests/test_scheduler.py -v`
Expected: ImportError (`OnceArm`), or the updated tests fail.

- [ ] **Step 3: Implement in `app/scheduler.py`**

Add `from dataclasses import dataclass` to the imports. Add below the constants:

```python
@dataclass
class OnceArm:
    """A one-shot armed schedule: fires once, then disarms."""

    fires_at: datetime

    @property
    def due_at(self) -> datetime:
        return self.fires_at

    def to_json(self) -> dict:
        return {"type": "once", "fires_at": self.fires_at.isoformat()}
```

Replace `_load` with:

```python
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
        raise ValueError(f"unknown schedule type {entry.get('type')!r}")
```

Replace `_save` with:

```python
    def _save(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps({pid: arm.to_json() for pid, arm in self.armed.items()})
        )
        os.replace(tmp, self._path)
```

In `arm()`, replace the last three lines (`self.armed[...] = fires_at` / `self._save()` / `return fires_at`) with:

```python
        arm = OnceArm(fires_at=fires_at)
        self.armed[preset_id] = arm
        self._save()
        return arm
```

and change its return annotation to `-> OnceArm`. Update the `armed` attribute annotation to `self.armed: dict[str, OnceArm] = {}`.

In `check_due`, change the due comparison to use the record:

```python
    async def check_due(self) -> None:
        now = self._now()
        for preset_id, arm in list(self.armed.items()):
            due = arm.due_at
            if due > now:
                continue
            del self.armed[preset_id]
            self._save()
            if now - due > GRACE:
                log.warning(
                    "Discarding %r: fire time %s is too far in the past",
                    preset_id,
                    due,
                )
                continue
            await self._fire(self.presets[preset_id])
```

- [ ] **Step 4: Adapt `app/main.py`**

In `serialize_schedule`, replace the `armed` expression with:

```python
                "armed": (
                    scheduler.armed[p.id].to_json()
                    if p.id in scheduler.armed
                    else None
                ),
```

In `arm_preset`, rename the local and return its JSON form (keep the try/except structure unchanged): the line `fires_at = scheduler.arm(preset_id, req.date, req.time)` becomes `arm = scheduler.arm(preset_id, req.date, req.time)`, and the final `return {"fires_at": fires_at.isoformat()}` becomes:

```python
    return arm.to_json()
```

- [ ] **Step 5: Run the full suite**

Run: `../.venv/bin/pytest -v`
Expected: 61 passed, no warnings. (The existing api tests still pass: `to_json()` keeps the `fires_at` key.)

- [ ] **Step 6: Commit**

```bash
git add app/scheduler.py app/main.py tests/test_scheduler.py
git commit -m "refactor: typed armed records with legacy load"
```

---

### Task 2: WeeklyArm + arm_weekly + next-occurrence logic

**Files:**
- Modify: `app/scheduler.py`
- Test: `tests/test_scheduler.py` (append)

- [ ] **Step 1: Append the failing tests** (remember: START is Sunday 2026-06-07 12:00; Mon=0…Sun=6)

Extend the scheduler import line to: `from app.scheduler import ArmError, OnceArm, Scheduler, WeeklyArm`.

```python
def test_arm_weekly_returns_record_and_persists(tmp_path):
    s = make_scheduler(tmp_path, Clock())
    arm = s.arm_weekly("evening_warmth", [0, 1, 2, 3, 4], "18:00")
    assert isinstance(arm, WeeklyArm)
    assert arm.days == {0, 1, 2, 3, 4}
    assert arm.time == "18:00"
    assert arm.next_fire.isoformat().startswith("2026-06-08T18:00")  # Monday
    saved = json.loads((tmp_path / "schedules.json").read_text())
    assert saved == {
        "evening_warmth": {
            "type": "weekly",
            "days": [0, 1, 2, 3, 4],
            "time": "18:00",
            "next_fire": arm.next_fire.isoformat(),
        }
    }


def test_arm_weekly_empty_days_raises(tmp_path):
    s = make_scheduler(tmp_path, Clock())
    with pytest.raises(ArmError, match="at least one day"):
        s.arm_weekly("evening_warmth", [], "18:00")


def test_arm_weekly_invalid_day_raises(tmp_path):
    s = make_scheduler(tmp_path, Clock())
    with pytest.raises(ArmError, match="0-6"):
        s.arm_weekly("evening_warmth", [0, 7], "18:00")


def test_arm_weekly_bad_time_raises(tmp_path):
    s = make_scheduler(tmp_path, Clock())
    with pytest.raises(ArmError, match="HH:MM"):
        s.arm_weekly("evening_warmth", [0], "25:99")


def test_arm_weekly_unknown_preset_raises(tmp_path):
    s = make_scheduler(tmp_path, Clock())
    with pytest.raises(KeyError):
        s.arm_weekly("ghost", [0], "18:00")


def test_weekly_next_fire_today_when_time_ahead(tmp_path):
    s = make_scheduler(tmp_path, Clock())  # Sunday 12:00
    arm = s.arm_weekly("evening_warmth", [6], "14:00")  # Sunday selected
    assert arm.next_fire.isoformat().startswith("2026-06-07T14:00")


def test_weekly_next_fire_wraps_to_next_week_when_time_passed(tmp_path):
    s = make_scheduler(tmp_path, Clock())  # Sunday 12:00
    arm = s.arm_weekly("evening_warmth", [6], "11:00")  # already passed today
    assert arm.next_fire.isoformat().startswith("2026-06-14T11:00")


async def test_weekly_fire_advances_and_stays_armed(tmp_path):
    clock = Clock()
    ha = FakeHAClient()
    s = make_scheduler(tmp_path, clock, ha=ha)
    s.arm_weekly("evening_warmth", [6], "14:00")
    clock.now = datetime(2026, 6, 7, 14, 0, 30, tzinfo=TZ)
    await s.check_due()
    assert ("set_hvac_mode", "climate.a", "heat") in ha.calls
    arm = s.armed["evening_warmth"]
    assert arm.next_fire.isoformat().startswith("2026-06-14T14:00")


async def test_weekly_missed_beyond_grace_advances_without_firing(tmp_path):
    clock = Clock()
    ha = FakeHAClient()
    s = make_scheduler(tmp_path, clock, ha=ha)
    s.arm_weekly("evening_warmth", [6], "14:00")
    clock.now = datetime(2026, 6, 7, 16, 0, tzinfo=TZ)  # 2h late
    await s.check_due()
    assert ha.calls == []
    arm = s.armed["evening_warmth"]
    assert arm.next_fire.isoformat().startswith("2026-06-14T14:00")


def test_weekly_persistence_round_trip(tmp_path):
    clock = Clock()
    s1 = make_scheduler(tmp_path, clock)
    arm = s1.arm_weekly("evening_warmth", [0, 6], "18:00")
    s2 = make_scheduler(tmp_path, clock)
    assert s2.armed == {"evening_warmth": arm}


def test_rearm_across_types_replaces(tmp_path):
    s = make_scheduler(tmp_path, Clock())
    s.arm("evening_warmth", "2026-06-08", "18:00")
    weekly = s.arm_weekly("evening_warmth", [0], "18:00")
    assert s.armed == {"evening_warmth": weekly}
```

- [ ] **Step 2: Run to verify failure**

Run: `../.venv/bin/pytest tests/test_scheduler.py -v`
Expected: ImportError (`WeeklyArm`); existing tests pass once imports are fixed... the import error fails collection — that's the expected failure.

- [ ] **Step 3: Implement in `app/scheduler.py`**

Add `import re` to the imports. Add below `OnceArm`:

```python
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
```

Update `_entry_from_json` to handle weekly:

```python
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
```

Add below `arm()`:

```python
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
```

Replace `check_due` with the type-aware version:

```python
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
```

Update the `armed` annotation: `self.armed: dict[str, OnceArm | WeeklyArm] = {}`.

- [ ] **Step 4: Run the full suite**

Run: `../.venv/bin/pytest -v`
Expected: 72 passed (scheduler 28), no warnings.

- [ ] **Step 5: Commit**

```bash
git add app/scheduler.py tests/test_scheduler.py
git commit -m "feat: weekly recurring schedules in the scheduler"
```

---

### Task 3: API — repeat support in the arm endpoint

**Files:**
- Modify: `app/main.py`
- Test: `tests/test_api.py` (append)

- [ ] **Step 1: Append the failing tests to `tests/test_api.py`**

```python
def test_arm_weekly_endpoint(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    resp = client.post(
        "/api/schedule/evening_warmth/arm",
        json={"repeat": [0, 1, 2, 3, 4], "time": "18:00"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["type"] == "weekly"
    assert body["days"] == [0, 1, 2, 3, 4]
    assert body["time"] == "18:00"
    assert body["next_fire"].startswith("2026-06-08T18:00")  # Monday
    armed = client.get("/api/schedule").json()["presets"][0]["armed"]
    assert armed["type"] == "weekly"


def test_arm_weekly_empty_repeat_is_400(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    resp = client.post(
        "/api/schedule/evening_warmth/arm", json={"repeat": [], "time": "18:00"}
    )
    assert resp.status_code == 400


def test_arm_weekly_invalid_day_is_400(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    resp = client.post(
        "/api/schedule/evening_warmth/arm", json={"repeat": [7], "time": "18:00"}
    )
    assert resp.status_code == 400


def test_arm_both_date_and_repeat_is_422(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    resp = client.post(
        "/api/schedule/evening_warmth/arm",
        json={"date": "2026-06-08", "repeat": [0], "time": "18:00"},
    )
    assert resp.status_code == 422


def test_arm_neither_date_nor_repeat_is_422(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    resp = client.post(
        "/api/schedule/evening_warmth/arm", json={"time": "18:00"}
    )
    assert resp.status_code == 422


def test_cancel_weekly_arm(make_client, tmp_path):
    fake = FakeHAClient()
    client = make_client(fake, scheduler=make_sched(tmp_path, fake))
    client.post(
        "/api/schedule/evening_warmth/arm", json={"repeat": [0], "time": "18:00"}
    )
    resp = client.post("/api/schedule/evening_warmth/cancel")
    assert resp.status_code == 200
    assert client.get("/api/schedule").json()["presets"][0]["armed"] is None
```

- [ ] **Step 2: Run to verify failure**

Run: `../.venv/bin/pytest tests/test_api.py -v`
Expected: the weekly tests FAIL (422 — `date` is currently required-ish / `repeat` unknown... specifically `{repeat: ...}` bodies fail because ArmRequest has no repeat field and `date` missing handling differs); the both/neither 422 tests may accidentally pass. Old tests pass.

- [ ] **Step 3: Implement in `app/main.py`**

Change the pydantic import to include the validator: `from pydantic import BaseModel, model_validator`.

Replace `ArmRequest` with:

```python
class ArmRequest(BaseModel):
    date: str | None = None
    time: str
    repeat: list[int] | None = None

    @model_validator(mode="after")
    def exactly_one_mode(self):
        if (self.date is None) == (self.repeat is None):
            raise ValueError("provide exactly one of date or repeat")
        return self
```

Replace the body of `arm_preset` with:

```python
    try:
        if req.repeat is not None:
            arm = scheduler.arm_weekly(preset_id, req.repeat, req.time)
        else:
            arm = scheduler.arm(preset_id, req.date, req.time)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown preset: {preset_id}")
    except ValueError as exc:  # ArmError or unparsable date/time
        raise HTTPException(status_code=400, detail=str(exc))
    return arm.to_json()
```

- [ ] **Step 4: Run the full suite**

Run: `../.venv/bin/pytest -v`
Expected: 78 passed (api 23), no warnings.

- [ ] **Step 5: Commit**

```bash
git add app/main.py tests/test_api.py
git commit -m "feat: arm endpoint accepts weekly repeat bodies"
```

---

### Task 4: Frontend — Once/Repeat toggle and weekly display

**Files:**
- Modify: `app/static/app.js`, `app/static/style.css`

- [ ] **Step 1: Update `app/static/app.js`**

(a) Add day-name constants after `MODE_LABELS`:

```javascript
const DAY_CHIP_LABELS = ["M", "T", "W", "T", "F", "S", "S"]; // Mon=0 .. Sun=6
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
```

(b) In `renderPreset`, replace the whole `if (p.armed) { ... } else { ... }` block with:

```javascript
  if (p.armed) {
    const label =
      p.armed.type === "weekly"
        ? `Repeats ${dayRangeLabel(p.armed.days)} at ${p.armed.time} · next ${nextLabel(p.armed.next_fire)}`
        : firesLabel(p.armed.fires_at);
    row.append(el("span", "fires", label));
    row.append(btn("Cancel", "ctl cancel", () => cancelPreset(p)));
  } else {
    const form = armForm[p.id] ?? (armForm[p.id] = {
      mode: "once",
      day: timePassedToday(p.time) ? "tomorrow" : "today",
      time: p.time,
      days: [0, 1, 2, 3, 4, 5, 6],
    });
    const modeRow = el("div", "mode-toggle");
    for (const [value, label] of [["once", "Once"], ["repeat", "Repeat"]]) {
      const b = btn(label, "mode-opt", () => { form.mode = value; render(); });
      if (form.mode === value) b.classList.add("active");
      modeRow.append(b);
    }
    card.append(modeRow);
    if (form.mode === "repeat") {
      const chips = el("div", "day-chips");
      for (let d = 0; d < 7; d++) {
        const chip = btn(DAY_CHIP_LABELS[d], "day-chip", () => {
          form.days = form.days.includes(d)
            ? form.days.filter((x) => x !== d)
            : [...form.days, d];
          render();
        });
        if (form.days.includes(d)) chip.classList.add("active");
        chips.append(chip);
      }
      card.append(chips);
      const timeInput = document.createElement("input");
      timeInput.type = "time";
      timeInput.value = form.time;
      timeInput.addEventListener("change", () => { form.time = timeInput.value; });
      const armBtn = btn("Arm", "ctl arm", () => armPreset(p));
      armBtn.disabled = !form.days.length;
      row.append(timeInput, armBtn);
    } else {
      const daySel = document.createElement("select");
      for (const [value, label] of [["today", "Today"], ["tomorrow", "Tomorrow"]]) {
        const o = document.createElement("option");
        o.value = value;
        o.textContent = label;
        if (form.day === value) o.selected = true;
        daySel.append(o);
      }
      daySel.addEventListener("change", () => { form.day = daySel.value; });
      const timeInput = document.createElement("input");
      timeInput.type = "time";
      timeInput.value = form.time;
      timeInput.addEventListener("change", () => { form.time = timeInput.value; });
      row.append(daySel, timeInput, btn("Arm", "ctl arm", () => armPreset(p)));
    }
  }
  card.append(row);
  return card;
```

(NOTE to implementer: the current function builds `row` before the if/else and appends `card.append(row)` at the end — keep that structure; the block above includes the final two lines for clarity. The net change: armed branch reads the typed record; unarmed branch adds the mode toggle and the repeat variant.)

(c) Add helpers after `firesLabel`:

```javascript
function dayRangeLabel(days) {
  if (days.length === 7) return "every day";
  const sorted = [...days].sort((a, b) => a - b);
  const contiguous = sorted.every((d, i) => i === 0 || d === sorted[i - 1] + 1);
  if (contiguous && sorted.length > 2) {
    return `${DAY_NAMES[sorted[0]]}–${DAY_NAMES[sorted[sorted.length - 1]]}`;
  }
  return sorted.map((d) => DAY_NAMES[d]).join(", ");
}

function nextLabel(iso) {
  const day = iso.slice(0, 10);
  if (day === isoDate(0)) return "today";
  if (day === isoDate(1)) return "tomorrow";
  return day;
}

function nextFireIso(days, time) {
  for (let offset = 0; offset < 8; offset++) {
    const d = new Date(Date.now() + offset * 86400000);
    const apiDay = (d.getDay() + 6) % 7; // JS Sun=0 -> API Mon=0
    if (!days.includes(apiDay)) continue;
    if (offset === 0 && timePassedToday(time)) continue;
    return `${isoDate(offset)}T${time}:00`;
  }
  return `${isoDate(0)}T${time}:00`; // fallback; poll reconciles
}
```

(d) Replace `armPreset` with:

```javascript
async function armPreset(p) {
  const form = armForm[p.id];
  if (!form.time) return;
  let body;
  let optimistic;
  if (form.mode === "repeat") {
    if (!form.days.length) return;
    const days = [...form.days].sort((a, b) => a - b);
    body = { repeat: days, time: form.time };
    optimistic = {
      type: "weekly",
      days,
      time: form.time,
      next_fire: nextFireIso(days, form.time),
    };
  } else {
    const date = isoDate(form.day === "tomorrow" ? 1 : 0);
    body = { date, time: form.time };
    optimistic = { type: "once", fires_at: `${date}T${form.time}:00` };
  }
  p.armed = optimistic;
  pendingSchedule[p.id] = Date.now() + PENDING_MS;
  render();
  const resp = await post(`/api/schedule/${p.id}/arm`, body);
  if (!resp) {
    p.armed = null;
    delete pendingSchedule[p.id];
    render();
  }
}
```

- [ ] **Step 2: Add to `app/static/style.css`** (at the end):

```css
.mode-toggle {
  display: flex;
  gap: 6px;
  margin-top: 12px;
}
.mode-opt {
  flex: 1;
  padding: 6px 10px;
  font-size: 0.9rem;
}
.mode-opt.active {
  background: var(--text);
  color: #fff;
}

.day-chips {
  display: flex;
  gap: 6px;
  margin-top: 10px;
}
.day-chip {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  padding: 0;
  font-size: 0.85rem;
}
.day-chip.active {
  background: var(--accent-cool);
  color: #fff;
}
```

- [ ] **Step 3: Verify**

Run: `node --check app/static/app.js` → no output.
Run: `../.venv/bin/pytest` → 78 passed.
Smoke: create a temporary `presets.yaml` in this directory (copy `presets.yaml.example`), run `HA_URL=http://localhost:19999 HA_TOKEN=x SCHEDULES_PATH=/tmp/rec-smoke.json ../.venv/bin/uvicorn app.main:app --port 18090`, then:
- `curl -s -X POST localhost:18090/api/schedule/evening_warmth/arm -H 'Content-Type: application/json' -d '{"repeat": [0,1,2,3,4], "time": "18:00"}'` → weekly record with next_fire
- `curl -s localhost:18090/api/schedule` → armed type weekly
- cancel → armed null
Kill the server; delete the temporary `presets.yaml` and `/tmp/rec-smoke.json`. `git status --porcelain` must show only app.js/style.css modified.

- [ ] **Step 4: Commit**

```bash
git add app/static/app.js app/static/style.css
git commit -m "feat: Once/Repeat arm modes with weekday chips"
```

---

### Task 5: Packaging v1.3.0

**Files:**
- Modify: `config.yaml`, `CHANGELOG.md`, `DOCS.md`

- [ ] **Step 1:** `config.yaml`: `version: "1.3.0"` (no other changes — schema is untouched).

- [ ] **Step 2:** `CHANGELOG.md`, new entry at top (below `# Changelog`):

```markdown
## 1.3.0

- Repeat mode: arm a preset to fire on chosen weekdays at a chosen time
  until cancelled. One-shot arming unchanged. Armed schedules from 1.2.0
  carry over.
```

- [ ] **Step 3:** `DOCS.md`, in the "Schedule presets" section, append after the "Armed schedules survive app restarts..." paragraph:

```markdown
When arming you can pick **Once** (fires once, then disarms) or **Repeat**
(pick weekdays; fires on each selected day at the chosen time until
cancelled).
```

- [ ] **Step 4:** `../.venv/bin/pytest` → 78 passed. Validate `config.yaml` still parses: `../.venv/bin/python -c "import yaml; print(yaml.safe_load(open('config.yaml'))['version'])"` → 1.3.0.

- [ ] **Step 5: Commit**

```bash
git add config.yaml CHANGELOG.md DOCS.md
git commit -m "feat: add-on v1.3.0 — recurring schedules"
```

---

### Task 6: Ship and verify on the Pi

Manual, with the user:

- [ ] **Step 1:** `git push` (from the repo root)
- [ ] **Step 2:** HA: Settings → Apps → ⋮ → Check for updates → update AC Dashboard to 1.3.0
- [ ] **Step 3:** On a phone: Schedule tab → a preset now shows Once/Repeat; arm Repeat with today selected and a time a few minutes out; confirm it fires and the card still shows armed with "next" advanced a week; Cancel works; one-shot arming still works.
