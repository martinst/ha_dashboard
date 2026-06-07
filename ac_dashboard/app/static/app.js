const POLL_MS = 5000;
const PENDING_MS = 4000; // ignore poll data for a unit this long after a local change
const DEBOUNCE_MS = 600; // wait for temp-stepper taps to settle before sending
const UNGROUPED = "Ungrouped";

const MODE_LABELS = {
  off: "Off",
  cool: "Cool",
  heat: "Heat",
  dry: "Dry",
  fan_only: "Fan",
  auto: "Auto",
  heat_cool: "Auto",
};

const DAY_CHIP_LABELS = ["M", "T", "W", "T", "F", "S", "S"]; // Mon=0 .. Sun=6
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

let state = { groups: [] };
const pendingUntil = {}; // entity_id -> ms timestamp
const timers = {};       // debounce timers, keyed by entity_id or "group:<name>"
const groupTemps = {};   // group name -> locally chosen group target temp
const groupMsgs = {};    // group name -> {text, until} transient result message

let scheduleState = { presets: [] };
const armForm = {};         // preset id -> {day, time} (survives re-renders)
const pendingSchedule = {}; // preset id -> suppress-poll-until timestamp

// ---- polling ----

async function poll() {
  try {
    const [stateResp, schedResp] = await Promise.all([
      fetch("/api/state"),
      fetch("/api/schedule"),
    ]);
    if (!stateResp.ok || !schedResp.ok) throw new Error("poll failed");
    mergeState(await stateResp.json());
    mergeSchedule(await schedResp.json());
    setConnected(true);
  } catch {
    setConnected(false);
  }
  render();
}

// Keep locally-changed units as-is until their pending window expires,
// so optimistic updates aren't reverted by an in-flight poll.
function mergeState(fresh) {
  const now = Date.now();
  const oldUnits = {};
  for (const g of state.groups) for (const u of g.units) oldUnits[u.entity_id] = u;
  for (const g of fresh.groups) {
    g.units = g.units.map((u) =>
      (pendingUntil[u.entity_id] || 0) > now && oldUnits[u.entity_id]
        ? oldUnits[u.entity_id]
        : u
    );
  }
  state = fresh;
}

function mergeSchedule(fresh) {
  const now = Date.now();
  const old = {};
  for (const p of scheduleState.presets) old[p.id] = p;
  fresh.presets = fresh.presets.map((p) =>
    (pendingSchedule[p.id] || 0) > now && old[p.id] ? old[p.id] : p
  );
  scheduleState = fresh;
}

function setConnected(ok) {
  document.getElementById("status-dot").classList.toggle("ok", ok);
  document.getElementById("banner").classList.toggle("hidden", ok);
}

// ---- commands ----

function markPending(entityId) {
  pendingUntil[entityId] = Date.now() + PENDING_MS;
}

async function post(url, body) {
  try {
    const resp = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    setConnected(true);
    return await resp.json();
  } catch {
    setConnected(false);
    return null;
  }
}

function setUnitMode(unit, mode) {
  unit.mode = mode;
  markPending(unit.entity_id);
  render();
  post(`/api/units/${unit.entity_id}/set`, { mode });
}

function stepUnitTemp(unit, delta) {
  const lo = unit.min_temp ?? 16;
  const hi = unit.max_temp ?? 30;
  unit.target_temp = clamp((unit.target_temp ?? 22) + delta, lo, hi);
  markPending(unit.entity_id);
  render();
  debounce(unit.entity_id, () =>
    post(`/api/units/${unit.entity_id}/set`, { temperature: unit.target_temp })
  );
}

function groupAllOff(group) {
  for (const u of group.units) {
    u.mode = "off";
    markPending(u.entity_id);
  }
  render();
  post(`/api/groups/${encodeURIComponent(group.name)}/set`, { mode: "off" })
    .then((body) => reportGroupResult(group.name, body));
}

function groupAllOn(group) {
  // climate.turn_on restores each unit's previous mode — we can't predict it,
  // so no optimistic update; the next poll (≤5 s) shows the result.
  post(`/api/groups/${encodeURIComponent(group.name)}/set`, { mode: "on" })
    .then((body) => reportGroupResult(group.name, body));
}

function stepGroupTemp(group, delta) {
  const current = groupTemps[group.name] ?? avgTarget(group.units) ?? 22;
  const next = clamp(current + delta, 16, 30);
  groupTemps[group.name] = next;
  for (const u of group.units) {
    u.target_temp = next;
    markPending(u.entity_id);
  }
  render();
  debounce(`group:${group.name}`, () =>
    post(`/api/groups/${encodeURIComponent(group.name)}/set`, { temperature: next })
      .then((body) => reportGroupResult(group.name, body))
  );
}

function reportGroupResult(name, body) {
  if (!body || !body.failed || !body.failed.length) return;
  groupMsgs[name] = {
    text: `${body.succeeded} of ${body.total} units updated`,
    until: Date.now() + 6000,
  };
  render();
}

// ---- rendering ----

function render() {
  document
    .getElementById("groups")
    .replaceChildren(...state.groups.map(renderGroup));
  renderSchedule();
}

function renderGroup(group) {
  const section = el("section", "group");
  const header = el("div", "group-header");
  header.append(el("h2", "", group.name));
  if (group.name !== UNGROUPED) {
    const controls = el("div", "group-controls");
    controls.append(
      btn("All Off", "ctl", () => groupAllOff(group)),
      btn("All On", "ctl", () => groupAllOn(group)),
      stepperEl(groupTemps[group.name] ?? avgTarget(group.units), (d) =>
        stepGroupTemp(group, d)
      )
    );
    header.append(controls);
    const msg = groupMsgs[group.name];
    if (msg && msg.until > Date.now()) {
      header.append(el("span", "group-msg", msg.text));
    }
  }
  section.append(header, ...group.units.map(renderUnit));
  return section;
}

function renderUnit(unit) {
  const card = el("div", "card");
  card.dataset.mode = unit.available ? unit.mode : "unavailable";
  if (!unit.available) card.classList.add("unavailable");

  const top = el("div", "card-top");
  top.append(
    el("span", "unit-name", unit.name),
    el("span", "current-temp",
       unit.current_temp != null ? `${unit.current_temp}°` : "–")
  );

  const temp = stepperEl(unit.target_temp, (d) => stepUnitTemp(unit, d),
                         !unit.available);

  const modes = el("div", "modes");
  for (const mode of unit.available_modes) {
    const b = btn(MODE_LABELS[mode] ?? mode, "mode-btn", () =>
      setUnitMode(unit, mode)
    );
    b.dataset.mode = mode;
    if (mode === unit.mode) b.classList.add("active");
    b.disabled = !unit.available;
    modes.append(b);
  }

  card.append(top, temp, modes);
  return card;
}

function stepperEl(value, onStep, disabled = false) {
  const wrap = el("div", "stepper");
  const minus = btn("−", "step", () => onStep(-0.5));
  const plus = btn("+", "step", () => onStep(0.5));
  minus.disabled = plus.disabled = disabled;
  wrap.append(minus, el("span", "target", value != null ? `${value}°` : "–"), plus);
  return wrap;
}

// ---- schedule tab ----

function renderSchedule() {
  const main = document.getElementById("schedule");
  if (!scheduleState.presets.length) {
    main.replaceChildren(
      el("p", "hint",
         "No presets configured. Add a presets: section in the add-on configuration.")
    );
    return;
  }
  main.replaceChildren(...scheduleState.presets.map(renderPreset));
}

function renderPreset(p) {
  const card = el("div", "card preset");
  card.append(el("div", "unit-name", p.name));
  card.append(el("div", "preset-summary", presetSummary(p)));
  const row = el("div", "arm-row");
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
}

function presetSummary(p) {
  const action = [
    p.mode ? (MODE_LABELS[p.mode] ?? p.mode) : null,
    p.temperature != null ? `${p.temperature}°` : null,
  ].filter(Boolean).join(" ");
  return `${action} — ${p.entities.map(unitName).join(", ")}`;
}

function unitName(entityId) {
  for (const g of state.groups)
    for (const u of g.units)
      if (u.entity_id === entityId) return u.name;
  return entityId;
}

function timePassedToday(hhmm) {
  const [h, m] = hhmm.split(":").map(Number);
  const now = new Date();
  return now.getHours() > h || (now.getHours() === h && now.getMinutes() >= m);
}

function isoDate(offsetDays) {
  const d = new Date(Date.now() + offsetDays * 86400000);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function firesLabel(iso) {
  const time = iso.slice(11, 16);
  const day = iso.slice(0, 10);
  if (day === isoDate(0)) return `Fires today at ${time}`;
  if (day === isoDate(1)) return `Fires tomorrow at ${time}`;
  return `Fires ${day} at ${time}`;
}

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

async function cancelPreset(p) {
  const previous = p.armed;
  p.armed = null;
  pendingSchedule[p.id] = Date.now() + PENDING_MS;
  render();
  const body = await post(`/api/schedule/${p.id}/cancel`, {});
  if (!body) {
    p.armed = previous;
    delete pendingSchedule[p.id];
    render();
  }
}

// ---- helpers ----

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

function btn(label, cls, onClick) {
  const b = el("button", cls, label);
  b.addEventListener("click", onClick);
  return b;
}

function clamp(value, lo, hi) {
  return Math.min(hi, Math.max(lo, Math.round(value * 2) / 2));
}

function avgTarget(units) {
  const temps = units.map((u) => u.target_temp).filter((t) => t != null);
  if (!temps.length) return null;
  return Math.round((temps.reduce((a, b) => a + b, 0) / temps.length) * 2) / 2;
}

function debounce(key, fn) {
  clearTimeout(timers[key]);
  timers[key] = setTimeout(fn, DEBOUNCE_MS);
}

function showTab(name) {
  document.getElementById("groups").classList.toggle("hidden", name !== "control");
  document.getElementById("schedule").classList.toggle("hidden", name !== "schedule");
  document.getElementById("tab-control").classList.toggle("active", name === "control");
  document.getElementById("tab-schedule").classList.toggle("active", name === "schedule");
}

document.getElementById("tab-control").addEventListener("click", () => showTab("control"));
document.getElementById("tab-schedule").addEventListener("click", () => showTab("schedule"));

poll();
setInterval(poll, POLL_MS);
