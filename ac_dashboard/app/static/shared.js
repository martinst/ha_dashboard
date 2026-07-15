// Shared between pages. Each page script defines:
//   const PAGE = { domain, presetsHint, presetSummary };  // page identity
//   function render() { ... }                              // full re-render
// and is loaded AFTER this file.

const POLL_MS = 5000;
const PENDING_MS = 4000; // ignore poll data for a unit this long after a local change
const DEBOUNCE_MS = 600; // wait for stepper taps to settle before sending

const DAY_CHIP_LABELS = ["M", "T", "W", "T", "F", "S", "S"]; // Mon=0 .. Sun=6
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

const timers = {}; // debounce timers, keyed by entity_id or "group:<name>"

let scheduleState = { presets: [] };
const armForm = {};         // preset id -> form state (survives re-renders)
const pendingSchedule = {}; // preset id -> suppress-poll-until timestamp

// ---- connection + fetch ----

function setConnected(ok) {
  document.getElementById("status-dot").classList.toggle("ok", ok);
  document.getElementById("banner").classList.toggle("hidden", ok);
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

// ---- DOM helpers ----

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

function debounce(key, fn) {
  clearTimeout(timers[key]);
  timers[key] = setTimeout(fn, DEBOUNCE_MS);
}

// ---- schedule tab ----

function mergeSchedule(fresh) {
  const now = Date.now();
  const old = {};
  for (const p of scheduleState.presets) old[p.id] = p;
  fresh.presets = fresh.presets.map((p) =>
    (pendingSchedule[p.id] || 0) > now && old[p.id] ? old[p.id] : p
  );
  scheduleState = fresh;
}

function renderSchedule() {
  const main = document.getElementById("schedule");
  const presets = scheduleState.presets.filter((p) => p.domain === PAGE.domain);
  if (!presets.length) {
    main.replaceChildren(el("p", "hint", PAGE.presetsHint));
    return;
  }
  main.replaceChildren(...presets.map(renderPreset));
}

function renderPreset(p) {
  const card = el("div", "card preset");
  card.append(el("div", "unit-name", p.name));
  card.append(el("div", "preset-summary", PAGE.presetSummary(p)));
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
