const UNGROUPED = "Ungrouped";
const LOGIN_URL = "/auth/login?next=%2Fdoors.html";
const CONFIRM_MS = 4000; // second tap must come within this window

const STATE_LABELS = {
  locked: "Locked",
  unlocked: "Unlocked",
  locking: "Locking…",
  unlocking: "Unlocking…",
  jammed: "Jammed",
  open: "Open",
  opening: "Opening…",
};

let state = { user: null, groups: [], temperatures: null };
const pendingUntil = {}; // entity_id -> ms timestamp
const confirmUntil = {}; // entity_id -> ms timestamp (unlock armed)
const groupMsgs = {};    // group name -> {text, until}

const PAGE = { domain: "lock", presetsHint: "", presetSummary: () => "" };

// ---- polling ----

async function poll() {
  try {
    const [doorsResp, stateResp] = await Promise.all([
      fetch("/api/doors"),
      fetch("/api/state"),
    ]);
    if (doorsResp.status === 401) {
      window.location.href = LOGIN_URL;
      return;
    }
    if (!doorsResp.ok || !stateResp.ok) throw new Error("poll failed");
    const doors = await doorsResp.json();
    const st = await stateResp.json();
    mergeState({ user: doors.user, groups: doors.groups, temperatures: st.temperatures });
    setConnected(true);
  } catch {
    setConnected(false);
  }
  render();
}

function mergeState(fresh) {
  const now = Date.now();
  const old = {};
  for (const g of state.groups) for (const d of g.units) old[d.entity_id] = d;
  for (const g of fresh.groups) {
    g.units = g.units.map((d) =>
      (pendingUntil[d.entity_id] || 0) > now && old[d.entity_id] ? old[d.entity_id] : d
    );
  }
  state = fresh;
}

// ---- commands ----

function markPending(entityId) {
  pendingUntil[entityId] = Date.now() + PENDING_MS;
}

function lockDoor(door) {
  delete confirmUntil[door.entity_id];
  door.state = "locking";
  markPending(door.entity_id);
  render();
  post(`/api/doors/${door.entity_id}/set`, { action: "lock" });
}

// Unlock needs two taps within CONFIRM_MS so a pocket tap can't open a door.
function unlockDoor(door) {
  const now = Date.now();
  if ((confirmUntil[door.entity_id] || 0) < now) {
    confirmUntil[door.entity_id] = now + CONFIRM_MS;
    render();
    setTimeout(render, CONFIRM_MS + 50);
    return;
  }
  delete confirmUntil[door.entity_id];
  door.state = "unlocking";
  markPending(door.entity_id);
  render();
  post(`/api/doors/${door.entity_id}/set`, { action: "unlock" });
}

function lockAll(group) {
  for (const d of group.units) {
    d.state = "locking";
    markPending(d.entity_id);
  }
  render();
  post(`/api/door-groups/${encodeURIComponent(group.name)}/set`, { action: "lock" })
    .then((body) => {
      if (!body || !body.failed || !body.failed.length) return;
      groupMsgs[group.name] = {
        text: `${body.succeeded} of ${body.total} doors locked`,
        until: Date.now() + 6000,
      };
      render();
    });
}

// ---- rendering ----

function render() {
  const line = document.getElementById("user-line");
  if (state.user) {
    line.replaceChildren(
      `Signed in as ${state.user} · `,
      Object.assign(document.createElement("a"), { href: "/auth/logout", textContent: "Sign out" })
    );
  }
  document.getElementById("groups").replaceChildren(...state.groups.map(renderGroup));
  renderTemperatures(state.temperatures);
}

function renderGroup(group) {
  const section = el("section", "group");
  const header = el("div", "group-header");
  header.append(el("h2", "", group.name));
  if (group.name !== UNGROUPED) {
    const controls = el("div", "group-controls");
    controls.append(btn("Lock all", "ctl", () => lockAll(group)));
    header.append(controls);
    const msg = groupMsgs[group.name];
    if (msg && msg.until > Date.now()) header.append(el("span", "group-msg", msg.text));
  }
  section.append(header, ...group.units.map(renderDoor));
  return section;
}

function renderDoor(door) {
  const card = el("div", "card");
  card.dataset.state = door.available ? door.state : "unavailable";
  if (!door.available) card.classList.add("unavailable");

  const top = el("div", "card-top");
  top.append(
    el("span", "unit-name", door.name),
    el("span", "lock-state", door.available ? (STATE_LABELS[door.state] ?? door.state ?? "–") : "Unavailable")
  );
  card.append(top);

  const buttons = el("div", "lock-btns");
  const lockBtn = btn("🔒 Lock", "lock-btn", () => lockDoor(door));
  const armed = (confirmUntil[door.entity_id] || 0) > Date.now();
  const unlockBtn = btn(armed ? "Tap again to unlock" : "🔓 Unlock", "lock-btn unlock", () => unlockDoor(door));
  if (armed) unlockBtn.classList.add("confirm");
  lockBtn.disabled = unlockBtn.disabled = !door.available;
  buttons.append(lockBtn, unlockBtn);
  card.append(buttons);
  card.append(el("div", "lock-hint", "Unlock opens the door for the time set in Inception, then it re-locks."));
  return card;
}

poll();
setInterval(poll, POLL_MS);
