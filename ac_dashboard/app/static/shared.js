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

// ---- theme (Auto follows the phone; Light/Dark override, per device) ----

const THEMES = ["auto", "light", "dark"];
const THEME_LABELS = { auto: "Auto", light: "Light", dark: "Dark" };

function storedTheme() {
  try {
    const t = localStorage.getItem("theme");
    return THEMES.includes(t) ? t : "auto";
  } catch {
    return "auto";
  }
}

function applyTheme(theme) {
  if (theme === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = theme;
  document.getElementById("theme-btn").textContent = THEME_LABELS[theme];
}

document.getElementById("theme-btn").addEventListener("click", () => {
  const next = THEMES[(THEMES.indexOf(storedTheme()) + 1) % THEMES.length];
  try { localStorage.setItem("theme", next); } catch { /* private mode */ }
  applyTheme(next);
});
applyTheme(storedTheme());

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

// ---- outdoor / indoor / pool temperature strip ----

// `temps` is the /api/state "temperatures" object: {outdoor, indoor, pool},
// each a sensor ({temp, unit, available}) or null when no sensor is
// configured/found.
function renderTemperatures(temps) {
  const strip = document.getElementById("temps");
  const slots = [["outdoor", "Outdoor"], ["indoor", "Indoor"], ["pool", "Pool"]]
    .filter(([key]) => temps && temps[key]);
  strip.classList.toggle("hidden", !slots.length);
  strip.replaceChildren(
    ...slots.map(([key, label]) => {
      const sensor = temps[key];
      const tile = el("div", `temp-tile ${key}`);
      if (!sensor.available) tile.classList.add("unavailable");
      tile.title = sensor.name;
      tile.setAttribute("role", "button");
      tile.addEventListener("click", () => openHistory(key, label));
      tile.append(
        el("span", "temp-label", label),
        el("span", "temp-value", sensor.temp != null
          ? `${formatTemp(sensor.temp)}${sensor.unit ?? "°"}`
          : "–")
      );
      return tile;
    })
  );
}

function formatTemp(value) {
  return (Math.round(value * 10) / 10).toFixed(1);
}

// ---- temperature history sheet ----

const HISTORY_RANGES = [["24h", "24h"], ["7d", "7 days"], ["30d", "30 days"]];
const PERIOD_MS = { "5minute": 300000, hour: 3600000 };
const CHART_W = 640, CHART_H = 260;
const PAD = { top: 14, right: 14, bottom: 28, left: 40 };

const history = { slot: null, label: "", range: "24h", data: null, loading: false };

function openHistory(slot, label) {
  history.slot = slot;
  history.label = label;
  history.data = null;
  document.getElementById("sheet").classList.remove("hidden");
  document.body.classList.add("sheet-open");
  loadHistory();
}

function closeHistory() {
  history.slot = null;
  document.getElementById("sheet").classList.add("hidden");
  document.body.classList.remove("sheet-open");
}

async function loadHistory() {
  const { slot, range } = history;
  history.loading = true;
  renderHistory();
  let data = null;
  try {
    const resp = await fetch(`/api/temperatures/${slot}/history?range=${range}`);
    if (resp.ok) data = await resp.json();
  } catch { /* shown as error below */ }
  // Ignore a reply for a range/slot the user has since moved away from.
  if (history.slot !== slot || history.range !== range) return;
  history.loading = false;
  history.data = data;
  renderHistory();
}

function renderHistory() {
  if (!history.slot) return;
  document.getElementById("sheet-title").textContent = `${history.label} temperature`;

  const ranges = document.getElementById("sheet-ranges");
  ranges.replaceChildren(
    ...HISTORY_RANGES.map(([key, label]) => {
      const b = btn(label, "range-opt", () => {
        if (history.range === key) return;
        history.range = key;
        loadHistory();
      });
      if (history.range === key) b.classList.add("active");
      return b;
    })
  );

  const summary = document.getElementById("sheet-summary");
  const chart = document.getElementById("sheet-chart");
  const d = history.data;
  if (history.loading && !d) {
    summary.replaceChildren(el("span", "hint-inline", "Loading…"));
    chart.replaceChildren();
    return;
  }
  if (!d) {
    summary.replaceChildren(el("span", "hint-inline", "Couldn't load history"));
    chart.replaceChildren();
    return;
  }
  if (!d.points.length) {
    summary.replaceChildren(el("span", "hint-inline", "No data yet for this period"));
    chart.replaceChildren();
    return;
  }
  const unit = d.unit ?? "°";
  const lo = Math.min(...d.points.map((p) => p.min ?? p.mean));
  const hi = Math.max(...d.points.map((p) => p.max ?? p.mean));
  const last = d.points[d.points.length - 1];
  summary.replaceChildren(
    statEl("Low", `${formatTemp(lo)}${unit}`),
    statEl("High", `${formatTemp(hi)}${unit}`),
    statEl("Latest", `${formatTemp(last.mean)}${unit}`)
  );
  chart.replaceChildren(chartSvg(d));
}

function statEl(label, value) {
  const wrap = el("div", "stat");
  wrap.append(el("span", "stat-label", label), el("span", "stat-value", value));
  return wrap;
}

// ---- SVG chart: min–max band + mean line, gap-aware ----

function svgEl(tag, attrs) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  return node;
}

function chartSvg(d) {
  const pts = d.points;
  const periodMs = PERIOD_MS[d.period] ?? 3600000;
  const lookbackMs = { "24h": 864e5, "7d": 7 * 864e5, "30d": 30 * 864e5 }[d.range];
  const tEnd = Math.max(pts[pts.length - 1].t + periodMs, Date.now());
  const tStart = tEnd - lookbackMs;

  const vals = pts.flatMap((p) => [p.min ?? p.mean, p.max ?? p.mean]);
  let yMin = Math.floor(Math.min(...vals)) - 1;
  let yMax = Math.ceil(Math.max(...vals)) + 1;
  if (yMax - yMin < 4) { const mid = (yMax + yMin) / 2; yMin = Math.floor(mid - 2); yMax = Math.ceil(mid + 2); }

  const x = (t) => PAD.left + ((t - tStart) / (tEnd - tStart)) * (CHART_W - PAD.left - PAD.right);
  const y = (v) => PAD.top + (1 - (v - yMin) / (yMax - yMin)) * (CHART_H - PAD.top - PAD.bottom);

  const svg = svgEl("svg", { viewBox: `0 0 ${CHART_W} ${CHART_H}`, class: "chart-svg" });

  // y grid + labels
  const yStep = niceStep((yMax - yMin) / 4);
  for (let v = Math.ceil(yMin / yStep) * yStep; v <= yMax; v += yStep) {
    svg.append(svgEl("line", { x1: PAD.left, x2: CHART_W - PAD.right, y1: y(v), y2: y(v), class: "grid" }));
    const t = svgEl("text", { x: PAD.left - 6, y: y(v) + 4, class: "axis-label", "text-anchor": "end" });
    t.textContent = `${v}°`;
    svg.append(t);
  }
  // x labels
  for (const [t, label] of xTicks(d.range, tStart, tEnd)) {
    svg.append(svgEl("line", { x1: x(t), x2: x(t), y1: PAD.top, y2: CHART_H - PAD.bottom, class: "grid" }));
    const tx = svgEl("text", { x: x(t), y: CHART_H - 8, class: "axis-label", "text-anchor": "middle" });
    tx.textContent = label;
    svg.append(tx);
  }

  // split into contiguous segments so gaps in data don't get bridged
  const segments = [];
  let seg = [];
  for (const p of pts) {
    if (seg.length && p.t - seg[seg.length - 1].t > periodMs * 2.5) { segments.push(seg); seg = []; }
    seg.push(p);
  }
  if (seg.length) segments.push(seg);

  for (const s of segments) {
    const px = (p) => x(p.t + periodMs / 2);
    if (s.some((p) => p.min != null && p.max != null)) {
      const top = s.map((p) => `${px(p)},${y(p.max ?? p.mean)}`);
      const bottom = [...s].reverse().map((p) => `${px(p)},${y(p.min ?? p.mean)}`);
      svg.append(svgEl("polygon", { points: [...top, ...bottom].join(" "), class: "band" }));
    }
    const line = s.length === 1
      ? svgEl("circle", { cx: px(s[0]), cy: y(s[0].mean), r: 3, class: "mean-dot" })
      : svgEl("polyline", { points: s.map((p) => `${px(p)},${y(p.mean)}`).join(" "), class: "mean" });
    svg.append(line);
  }
  return svg;
}

function niceStep(raw) {
  // ~4 gridlines: a 10° span gets 2° steps, a 4° span gets 1° steps.
  if (raw <= 1) return 1;
  if (raw <= 2.5) return 2;
  if (raw <= 5) return 5;
  return 10;
}

function xTicks(range, tStart, tEnd) {
  const ticks = [];
  const d = new Date(tStart);
  if (range === "24h") {
    d.setMinutes(0, 0, 0);
    d.setHours(d.getHours() + 1);
    for (; d.getTime() <= tEnd; d.setHours(d.getHours() + 1)) {
      if (d.getHours() % 6 === 0) ticks.push([d.getTime(), `${String(d.getHours()).padStart(2, "0")}:00`]);
    }
  } else {
    const every = range === "7d" ? 1 : 5;
    d.setHours(0, 0, 0, 0);
    d.setDate(d.getDate() + 1);
    let i = 0;
    for (; d.getTime() <= tEnd; d.setDate(d.getDate() + 1), i++) {
      if (i % every !== 0) continue;
      ticks.push([
        d.getTime(),
        range === "7d" ? DAY_NAMES[(d.getDay() + 6) % 7] : `${d.getDate()}/${d.getMonth() + 1}`,
      ]);
    }
  }
  return ticks;
}

document.getElementById("sheet-close").addEventListener("click", closeHistory);
document.querySelector("#sheet .sheet-backdrop").addEventListener("click", closeHistory);
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && history.slot) closeHistory(); });

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
