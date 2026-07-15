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

let state = { groups: [] };
const pendingUntil = {}; // entity_id -> ms timestamp
const groupTemps = {};   // group name -> locally chosen group target temp
const groupMsgs = {};    // group name -> {text, until} transient result message

const PAGE = {
  domain: "climate",
  presetsHint:
    "No presets configured. Add a presets: section in the add-on configuration.",
  presetSummary,
};

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

// ---- commands ----

function markPending(entityId) {
  pendingUntil[entityId] = Date.now() + PENDING_MS;
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

// ---- helpers ----

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

function avgTarget(units) {
  const temps = units.map((u) => u.target_temp).filter((t) => t != null);
  if (!temps.length) return null;
  return Math.round((temps.reduce((a, b) => a + b, 0) / temps.length) * 2) / 2;
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
