const UNGROUPED = "Ungrouped";

const STATE_LABELS = {
  open: "Open",
  closed: "Closed",
  opening: "Opening…",
  closing: "Closing…",
  unknown: "–", // stateless covers (e.g. Somfy RTS) report no state
};

let state = { cover_groups: [] };
const pendingUntil = {}; // entity_id -> ms timestamp
const groupMsgs = {};    // group name -> {text, until} transient result message

const PAGE = {
  domain: "cover",
  presetsHint:
    "No window presets configured. Add a window_presets: section in the add-on configuration.",
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

// Keep locally-changed covers as-is until their pending window expires,
// so optimistic updates aren't reverted by an in-flight poll.
function mergeState(fresh) {
  const now = Date.now();
  const oldCovers = {};
  for (const g of state.cover_groups)
    for (const c of g.units) oldCovers[c.entity_id] = c;
  for (const g of fresh.cover_groups) {
    g.units = g.units.map((c) =>
      (pendingUntil[c.entity_id] || 0) > now && oldCovers[c.entity_id]
        ? oldCovers[c.entity_id]
        : c
    );
  }
  state = fresh;
}

// ---- commands ----

function markPending(entityId) {
  pendingUntil[entityId] = Date.now() + PENDING_MS;
}

function coverAction(cover, action) {
  if (action === "open") cover.state = "opening";
  else if (action === "close") cover.state = "closing";
  if (action !== "stop") markPending(cover.entity_id);
  render();
  post(`/api/covers/${cover.entity_id}/set`, { action });
}

function setCoverPosition(cover, position) {
  cover.position = position;
  markPending(cover.entity_id);
  render();
  post(`/api/covers/${cover.entity_id}/set`, { position });
}

function groupAction(group, action) {
  for (const c of group.units) {
    if (action === "open") c.state = "opening";
    else c.state = "closing";
    markPending(c.entity_id);
  }
  render();
  post(`/api/cover-groups/${encodeURIComponent(group.name)}/set`, { action })
    .then((body) => reportGroupResult(group.name, body));
}

function reportGroupResult(name, body) {
  if (!body || !body.failed || !body.failed.length) return;
  groupMsgs[name] = {
    text: `${body.succeeded} of ${body.total} windows updated`,
    until: Date.now() + 6000,
  };
  render();
}

// ---- rendering ----

function render() {
  document
    .getElementById("groups")
    .replaceChildren(...state.cover_groups.map(renderGroup));
  renderTemperatures(state.temperatures);
  renderSchedule();
}

function renderGroup(group) {
  const section = el("section", "group");
  const header = el("div", "group-header");
  header.append(el("h2", "", group.name));
  if (group.name !== UNGROUPED) {
    const controls = el("div", "group-controls");
    controls.append(
      btn("Open all", "ctl", () => groupAction(group, "open")),
      btn("Close all", "ctl", () => groupAction(group, "close"))
    );
    header.append(controls);
    const msg = groupMsgs[group.name];
    if (msg && msg.until > Date.now()) {
      header.append(el("span", "group-msg", msg.text));
    }
  }
  section.append(header, ...group.units.map(renderCover));
  return section;
}

function renderCover(cover) {
  const card = el("div", "card");
  card.dataset.state = cover.available ? cover.state : "unavailable";
  if (!cover.available) card.classList.add("unavailable");

  const top = el("div", "card-top");
  top.append(
    el("span", "unit-name", cover.name),
    el("span", "cover-state", stateLabel(cover))
  );
  card.append(top);

  const buttons = el("div", "cover-btns");
  for (const [action, label] of [
    ["open", "▲ Open"],
    ["stop", "■ Stop"],
    ["close", "▼ Close"],
  ]) {
    const b = btn(label, "cover-btn", () => coverAction(cover, action));
    b.disabled = !cover.available;
    buttons.append(b);
  }
  card.append(buttons);

  if (cover.supports_position) {
    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = 0;
    slider.max = 100;
    slider.value = cover.position ?? 0;
    slider.className = "position";
    slider.disabled = !cover.available;
    slider.addEventListener("change", () =>
      setCoverPosition(cover, Number(slider.value))
    );
    card.append(slider);
  }
  return card;
}

function stateLabel(cover) {
  if (!cover.available) return "Unavailable";
  const label = STATE_LABELS[cover.state] ?? cover.state ?? "–";
  if (cover.position != null && cover.position > 0 && cover.position < 100) {
    return `${label} · ${cover.position}%`;
  }
  return label;
}

// ---- helpers ----

function presetSummary(p) {
  const parts = [];
  if (p.action) parts.push(p.action === "open" ? "Open" : "Close");
  if (p.position != null) parts.push(`${p.position}%`);
  return `${parts.join(" to ")} — ${p.entities.map(coverName).join(", ")}`;
}

function coverName(entityId) {
  for (const g of state.cover_groups)
    for (const c of g.units)
      if (c.entity_id === entityId) return c.name;
  return entityId;
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
