/* WorkPulse mobile app. Talks to the laptop over your Wi-Fi with this phone's device token.
   Inside the Android app, window.WorkPulseAndroid (a JS bridge) adds automatic phone tracking controls. */
"use strict";

const $ = (s) => document.querySelector(s);
const bridge = window.WorkPulseAndroid || null;
const CAT_VAR = { "Coding": "--c-coding", "Learning/AI": "--c-learning", "Design": "--c-design", "Content Creation": "--c-content",
                  "Communication": "--c-comm", "Browsing": "--c-browsing", "Entertainment": "--c-ent", "Other": "--c-other" };
const catColor = (c) => `var(${CAT_VAR[c] || "--c-other"})`;
const state = { view: "home", day: todayISO(), status: null };

// ---------- utils ----------
function todayISO() { const d = new Date(); return new Date(d - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 10); }
function shiftISO(iso, n) { const d = new Date(iso + "T12:00:00"); d.setDate(d.getDate() + n); return new Date(d - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 10); }
function dur(sec) { const m = Math.round((sec || 0) / 60); const h = Math.floor(m / 60); return h ? `${h}h ${String(m % 60).padStart(2, "0")}m` : `${m}m`; }
function hm(ts) { return ts ? new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false }) : "--:--"; }
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) { if (k === "class") e.className = v; else if (k === "text") e.textContent = v; else if (k === "style") e.style.cssText = v; else e.setAttribute(k, v); }
  for (const k of kids) if (k != null) e.append(k);
  return e;
}
function toast(msg, ms = 2600) { const t = $("#toast"); t.textContent = msg; t.hidden = false; clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, ms); }
function waFormat(text) {  // escape FIRST, then WhatsApp-style *bold* / _italic_
  const esc = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  return esc.replace(/\*([^*\n]+)\*/g, "<b>$1</b>").replace(/(^|[\s(])_([^_\n]+)_(?=$|[\s).,!?])/gm, "$1<i>$2</i>");
}
const token = () => { try { return localStorage.getItem("wp-token"); } catch (e) { return null; } };
// Opened on the laptop itself (e.g. the docked side panel): no pairing needed, the laptop is trusted.
const ON_LAPTOP = ["127.0.0.1", "localhost", "[::1]"].includes(location.hostname);

class Unpaired extends Error {}
async function api(path, opts = {}) {
  let r;
  try {
    r = await fetch(path, { ...opts, headers: { "X-WorkPulse-UI": "1", ...(opts.body && !(opts.body instanceof FormData) ? { "Content-Type": "application/json" } : {}),
                                                  ...(token() ? { Authorization: `Bearer ${token()}` } : {}), ...(opts.headers || {}) } });
  } catch (e) { $("#offline").hidden = false; throw e; }
  $("#offline").hidden = true;
  if (r.status === 401) { showPairing("This phone isn't paired anymore. Ask the laptop for a new code."); throw new Unpaired(); }
  if (!r.ok) { let m = r.statusText; try { m = (await r.json()).detail; } catch (e) {} throw new Error(typeof m === "string" ? m : JSON.stringify(m)); }
  return r.json();
}
const post = (p, b) => api(p, { method: "POST", body: JSON.stringify(b) });
const patch = (p, b) => api(p, { method: "PATCH", body: JSON.stringify(b) });
async function safely(fn) { try { await fn(); } catch (e) { if (!(e instanceof Unpaired) && e.message) toast(`⚠️ ${e.message}`); } }

function rowsWithBars(target, items, colorOf, empty) {
  const max = Math.max(1, ...items.map((i) => i.seconds));
  target.replaceChildren(...(items.length ? items.map((i) => el("div", { class: "r" },
    el("span", { class: "name" }, i.swatch ? el("i", { class: "sw", style: `background:${i.swatch}` }) : null, i.name),
    el("span", { class: "num", text: dur(i.seconds) }),
    el("div", { class: "bar" }, el("i", { style: `width:${(100 * i.seconds / max).toFixed(1)}%;background:${colorOf(i)}` })))) : [el("div", { class: "empty", text: empty })]));
}

// ---------- pairing ----------
function showPairing(msg = "") {
  try { localStorage.removeItem("wp-token"); } catch (e) {}
  if (ON_LAPTOP) return start();  // the laptop never needs pairing
  $("#app").hidden = true; $("#pair").hidden = false;
  $("#pair-msg").textContent = msg;
  if (!$("#pair-name").value) $("#pair-name").value = bridge ? (bridge.deviceName?.() || "Android phone") : (/Android/.test(navigator.userAgent) ? "Android phone" : "My phone");
}

$("#pair-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("#pair-btn"), msg = $("#pair-msg");
  btn.disabled = true; msg.textContent = "Connecting…";
  try {
    const r = await fetch("/api/pair", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ code: $("#pair-code").value.replace(/\D/g, ""), name: $("#pair-name").value.trim() || "My phone", kind: bridge ? "android" : "web" }) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.detail || `Error ${r.status}`);
    localStorage.setItem("wp-token", j.token);
    localStorage.setItem("wp-name", j.name);
    if (bridge?.onPaired) bridge.onPaired(j.token, j.name);  // the Android app keeps a copy for background sync
    msg.textContent = "";
    start();
  } catch (err) { msg.textContent = err.message === "Failed to fetch" ? "Can't reach the laptop. Same Wi-Fi? Is Wi-Fi access on (.\\workpulse lan on)?" : err.message; }
  btn.disabled = false;
});

// ---------- status / pause ----------
async function refreshStatus() {
  const s = await api("/api/status");
  state.status = s;
  const p = $("#pill");
  p.className = "pill " + ({ on: "on", paused: "paused", off: "off" }[s.tracking]);
  $("#pill-text").textContent = { on: "Tracking", paused: "Paused", off: "Laptop tracker off" }[s.tracking];
  const now = $("#now");
  now.textContent = s.current && state.day === todayISO() ? `Right now: ${s.current.state}${s.current.app ? " · " + s.current.app : ""} for ${dur(s.current.duration_s)}` : "";
}
$("#pill").addEventListener("click", () => safely(async () => {
  if (!state.status) return;
  const pausing = state.status.tracking !== "paused";
  if (pausing && !confirm("Pause laptop tracking? Nothing is recorded until you resume.")) return;
  await post(`/api/${pausing ? "pause" : "resume"}`, {});
  toast(pausing ? "⏸️ Laptop tracking paused" : "▶️ Tracking resumed");
  refreshStatus();
}));

// ---------- home ----------
async function loadHome() {
  $("#day-label").textContent = state.day === todayISO() ? "Today" : new Date(state.day + "T12:00").toLocaleDateString([], { weekday: "long", day: "numeric", month: "short" });
  $("#next").disabled = state.day >= todayISO();
  const [d, dd] = await Promise.all([api(`/api/day?date=${state.day}`), api(`/api/digital?date=${state.day}`)]);
  $("#h-total").textContent = dur(dd.total_s);
  $("#h-laptop").textContent = dur(dd.laptop_active_s);
  $("#h-phone").textContent = dd.has_phone_data ? dur(dd.phone_s) : "–";
  $("#h-score").textContent = d.active_s ? d.focus_score : "–";
  $("#h-score-sub").textContent = d.comparison.avg7_score ? `7-day avg ${Math.round(d.comparison.avg7_score)}` : "";
  $("#h-streak").textContent = dur(d.longest_streak_s);
  $("#h-streak-sub").textContent = d.streak_category || "";
  $("#h-prod").textContent = dur(dd.productive_s);
  $("#h-prod-sub").textContent = "laptop + phone";
  $("#h-pickups").textContent = dd.pickups ?? "–";
  renderTimeline(d);
  rowsWithBars($("#cats"), dd.categories.map((c) => ({ name: c.name, seconds: c.laptop_s + c.phone_s, swatch: catColor(c.name) })), (i) => catColor(i.name), "Nothing tracked yet.");
  rowsWithBars($("#lapps"), d.top_apps.slice(0, 5).map((a) => ({ name: a.name, seconds: a.seconds })), () => "var(--accent)", "No laptop activity.");
  rowsWithBars($("#papps"), dd.phone_top_apps.slice(0, 5).map((a) => ({ name: a.app, seconds: a.seconds })), () => "var(--c-learning)", "No phone data yet.");
  if (state.day === todayISO()) {
    const ins = await api("/api/insights").catch(() => null);
    const pick = ins ? [ins.best[0], ins.improve[0]].filter(Boolean) : [];
    $("#insight").replaceChildren(...(pick.length ? pick.map((i, n) => el("div", { text: `${n === 0 ? "🏆" : "🛠️"} ${i.text}` })) : [el("div", { class: "empty", text: "Insights appear after a few days of tracking." })]));
    $("#insight").parentElement.hidden = false;
  } else { $("#insight").parentElement.hidden = true; }
}

function renderTimeline(d) {
  const tl = $("#timeline"), axis = $("#tl-axis");
  const vis = d.timeline.filter((b) => b.state !== "away");
  tl.replaceChildren(); axis.replaceChildren();
  if (!vis.length) { tl.append(el("div", { class: "empty", style: "padding:8px", text: "No laptop activity" })); return; }
  const day0 = new Date(d.day + "T00:00:00").getTime() / 1000;
  let h0 = Math.floor((Math.min(...vis.map((b) => b.start)) - day0) / 3600), h1 = Math.ceil((Math.max(...vis.map((b) => b.end)) - day0) / 3600);
  if (h1 - h0 < 4) { h1 = Math.min(24, h0 + 4); h0 = Math.max(0, h1 - 4); }
  const t0 = day0 + h0 * 3600, span = (h1 - h0) * 3600;
  for (const b of vis) {
    const blk = el("div", { class: `b ${b.state}`, title: `${hm(b.start)}–${hm(b.end)} ${b.state === "idle" ? "Idle" : b.category}${b.app ? " · " + b.app : ""}` });
    blk.style.left = `${(100 * (b.start - t0) / span).toFixed(3)}%`;
    blk.style.width = `${Math.max(0.3, 100 * (b.end - b.start) / span).toFixed(3)}%`;
    if (b.state === "active") blk.style.background = catColor(b.category);
    tl.append(blk);
  }
  const step = h1 - h0 > 12 ? 4 : h1 - h0 > 6 ? 2 : 1;
  for (let h = h0; h <= h1; h += step) axis.append(el("span", { style: `left:${(100 * (h - h0) / (h1 - h0)).toFixed(1)}%`, text: `${String(h % 24).padStart(2, "0")}` }));
}
$("#prev").addEventListener("click", () => { state.day = shiftISO(state.day, -1); safely(loadHome); });
$("#next").addEventListener("click", () => { if (state.day < todayISO()) { state.day = shiftISO(state.day, 1); safely(loadHome); } });

// ---------- coach ----------
const KIND = { morning: "☀️ morning", midday: "🕐 midday", night: "🌙 night report", weekly: "📅 weekly", reminder: "⏰ reminder" };
async function loadCoach() {
  const r = await api("/api/messages?limit=80");
  const t = $("#thread");
  t.replaceChildren(...(r.messages.length ? r.messages.map((m) => {
    const b = el("div", { class: `bubble ${m.direction}` });
    const kind = KIND[m.kind] || (m.kind.startsWith("nudge") ? "👋 nudge" : "");
    b.append(el("div", { class: "meta", text: [new Date(m.ts * 1000).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false }), kind,
      m.direction === "in" ? ({ app: "phone app", local: "laptop", received: "WhatsApp" }[m.status] || "") : ""].filter(Boolean).join(" · ") }));
    const body = el("div"); body.innerHTML = waFormat(m.body); b.append(body);
    return b;
  }) : [el("div", { class: "bubble out", text: "Hi! 👋 I'm your WorkPulse coach. Ask me anything, or tap a shortcut." })]));
  window.scrollTo(0, document.body.scrollHeight);
}
$("#chips").replaceChildren(...["today", "plan", "best", "improve", "phone", "goals", "tasks", "week"].map((q) => {
  const b = el("button", { type: "button", text: q }); b.addEventListener("click", () => sendChat(q)); return b;
}));
async function sendChat(text) {
  text = text.trim(); if (!text) return;
  const t = $("#thread");
  t.append(el("div", { class: "bubble in", text }));
  const typing = el("div", { class: "bubble out muted", text: "Coach is thinking…" }); t.append(typing);
  window.scrollTo(0, document.body.scrollHeight);
  $("#chat-in").value = "";
  try { await post("/api/chat", { text }); await loadCoach(); } catch (e) { typing.textContent = e instanceof Unpaired ? "" : `⚠️ ${e.message}`; }
}
$("#chat-form").addEventListener("submit", (e) => { e.preventDefault(); sendChat($("#chat-in").value); });

// ---------- phone ----------
async function loadPhone() {
  const dd = await api(`/api/digital?date=${todayISO()}`);
  $("#p-total").textContent = dd.has_phone_data ? dur(dd.phone_s) : "–";
  $("#p-pickups").textContent = dd.pickups != null ? `🔓 ${dd.pickups} pickups` : "";
  $("#p-source").textContent = dd.phone_devices.map((x) => `${x.device} · ${x.source}`).join(", ");
  rowsWithBars($("#p-apps"), dd.phone_top_apps.map((a) => ({ name: a.app, seconds: a.seconds })), () => "var(--c-learning)",
    bridge ? "Waiting for the first sync…" : "No phone data yet today.");
  if (bridge) {
    $("#android-card").hidden = false;
    const ok = bridge.hasUsageAccess();
    $("#android-status").textContent = ok ? `On. Syncs every 15 min over Wi-Fi. Last sync: ${bridge.lastSync() || "not yet"}` : "Off: WorkPulse needs Usage access to see which apps you use (it never sees what's inside them).";
    $("#grant").hidden = ok;
    $("#sync-now").hidden = !ok;
  }
}
$("#sync-now").addEventListener("click", () => { bridge.syncNow(); toast("Syncing…"); setTimeout(() => safely(loadPhone), 4000); });
$("#grant").addEventListener("click", () => bridge.openUsageAccessSettings());

function parseApps(text) {
  return text.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
    const [name, time] = l.includes("=") ? l.split(/=(.*)/s).map((x) => x.trim()) : [l.replace(/\s+[\d:hms ]+$/i, "").trim(), (l.match(/[\d:hms ]+$/i) || [""])[0].trim()];
    if (!name || !time) throw new Error(`Can't read "${l}". Use: Instagram = 1h 10m`);
    return { name, time };
  });
}
$("#manual").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = e.target, msg = $("#manual-msg");
  let apps; try { apps = parseApps(f.apps.value); } catch (err) { msg.textContent = err.message; return; }
  safely(async () => {
    await post("/api/phone/manual", { day: todayISO(), device: localStorage.getItem("wp-name") || null, total: f.total.value.trim() || null, apps, source: f.dataset.source || "manual" });
    msg.textContent = "Saved ✓"; f.reset(); f.dataset.source = "manual"; loadPhone();
  });
});
$("#shot").addEventListener("change", (e) => safely(async () => {
  const file = e.target.files[0]; if (!file) return;
  const fd = new FormData(); fd.append("file", file);
  $("#manual-msg").textContent = "Reading screenshot…";
  const r = await api("/api/phone/screenshot", { method: "POST", body: fd });
  const f = $("#manual");
  f.total.value = r.total_minutes != null ? `${Math.round(r.total_minutes)}m` : "";
  f.apps.value = r.apps.map((a) => `${a.name} = ${Math.round(a.minutes)}m`).join("\n");
  f.dataset.source = "screenshot";
  $("#manual-msg").textContent = r.period === "week" ? "⚠️ Looks like a weekly view; check the numbers." : "Check the numbers, then Save. (The image wasn't kept.)";
  e.target.value = "";
}));

// ---------- plan ----------
async function loadPlan() {
  const [g, t, r] = await Promise.all([api("/api/goals"), api("/api/team"), api("/api/roadmap")]);
  $("#goals").replaceChildren(...(g.goals.length ? g.goals.map((x) => {
    const cb = el("input", { type: "checkbox", "aria-label": `Done: ${x.text}` });
    cb.addEventListener("change", () => safely(async () => { await patch(`/api/goals/${x.id}`, { done: true }); toast("✅ Goal done!"); loadPlan(); }));
    const pct = x.pct != null ? el("div", { class: "r" }, el("div", { class: "bar" }, el("i", { style: `width:${Math.min(100, x.pct)}%;background:var(--accent)` }))) : null;
    return el("label", { class: "check" }, cb, el("div", {}, el("div", { class: "t", text: x.text }), el("div", { class: "sub", text: `${x.kind}${x.tracked_min != null ? " · " + x.summary.split(" · ").slice(1).join(" · ") : x.pct != null ? ` · ${Math.round(x.pct)}%` : ""}` }), pct));
  }) : [el("div", { class: "empty", text: "No goals yet." })]));
  const open = t.tasks.filter((x) => x.status !== "done");
  const today = todayISO();
  $("#tasks").replaceChildren(...(open.length ? open.map((x) => {
    const cb = el("input", { type: "checkbox", "aria-label": `Done: ${x.text}` });
    cb.addEventListener("change", () => safely(async () => { await patch(`/api/tasks/${x.id}`, { status: "done" }); toast("🙌 Task done"); loadPlan(); }));
    const due = x.due ? (x.due < today ? el("span", { class: "overdue", text: `overdue ${x.due}` }) : x.due === today ? el("span", { class: "overdue", text: "due today" }) : x.due) : null;
    return el("label", { class: "check" }, cb, el("div", {}, el("div", { class: "t", text: x.text }), el("div", { class: "sub" }, x.owner === "me" ? "You" : x.owner, x.status === "doing" ? " · doing" : "", due ? " · " : "", due)));
  }) : [el("div", { class: "empty", text: "No open tasks 🎉" })]));
  const next = r.horizons.flatMap((h) => h.milestones.filter((m) => !m.done).slice(0, 2).map((m) => ({ ...m, label: h.label })));
  $("#milestones").replaceChildren(...(next.length ? next.map((m) => el("div", { class: "check" }, el("span", { class: "tag", text: m.label }), el("div", { text: m.text })))
    : [el("div", { class: "empty", text: "Add a long-term goal on the laptop and let the coach suggest milestones." })]));
}
$("#goal-form").addEventListener("submit", (e) => {
  e.preventDefault(); const text = e.target.text.value.trim(); if (!text) return;
  safely(async () => { await post("/api/goals", { text, kind: "daily" }); e.target.reset(); loadPlan(); });
});
$("#task-form").addEventListener("submit", (e) => {
  e.preventDefault(); let text = e.target.text.value.trim(); if (!text) return;
  let owner = "me", due = null;
  const m = text.match(/^@(\S+)\s+(.+)$/); if (m) { owner = m[1]; text = m[2]; }
  const d = text.match(/\s+by\s+(today|tomorrow)$/i);
  if (d) { due = d[1].toLowerCase() === "today" ? todayISO() : shiftISO(todayISO(), 1); text = text.slice(0, d.index); }
  safely(async () => { await post("/api/tasks", { text, owner, due }); e.target.reset(); loadPlan(); });
});

// ---------- more ----------
async function loadMore() {
  const w = await api("/api/whoami");
  $("#unpair").hidden = ON_LAPTOP;
  $("#me").textContent = `${ON_LAPTOP ? "This laptop" : w.device} · connected to ${location.host} · WorkPulse ${w.version}${bridge ? " · Android app" : ""}`;
  const hasApk = !bridge && /Android/.test(navigator.userAgent) && await fetch("/m/workpulse.apk", { method: "HEAD" }).then((r) => r.ok).catch(() => false);
  $("#apk").hidden = !hasApk;
}
$("#theme").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next; try { localStorage.setItem("wp-theme", next); } catch (e) {}
});
$("#unpair").addEventListener("click", () => {
  if (!confirm("Disconnect this phone? You'll need a new code from the laptop to connect again.")) return;
  if (bridge?.onUnpaired) bridge.onUnpaired();
  showPairing("Disconnected. (To fully remove it, also delete it on the laptop: Settings → Connect a phone.)");
});

// ---------- navigation ----------
const LOADERS = { home: loadHome, coach: loadCoach, phone: loadPhone, plan: loadPlan, more: loadMore };
function show(v) {
  state.view = v;
  for (const b of document.querySelectorAll(".tabbar button")) b.setAttribute("aria-selected", String(b.dataset.v === v));
  for (const s of document.querySelectorAll(".view")) s.hidden = s.id !== `v-${v}`;
  window.scrollTo(0, 0);
  safely(LOADERS[v]);
}
for (const b of document.querySelectorAll(".tabbar button")) b.addEventListener("click", () => show(b.dataset.v));
$("#retry").addEventListener("click", () => { safely(refreshStatus); safely(LOADERS[state.view]); });

function start() {
  $("#pair").hidden = true; $("#app").hidden = false;
  safely(refreshStatus);
  show(state.view);
}

// ---------- boot ----------
(function boot() {
  const frag = new URLSearchParams(location.hash.slice(1));
  if (frag.get("auth")) {  // handed over by the Android app after it paired
    localStorage.setItem("wp-token", frag.get("auth"));
    if (frag.get("name")) localStorage.setItem("wp-name", frag.get("name"));
  }
  if (frag.get("pair")) $("#pair-code").value = frag.get("pair");
  if (LOADERS[frag.get("view")]) state.view = frag.get("view");  // e.g. #view=coach (bookmarks, screenshots)
  if (/^\d{4}-\d{2}-\d{2}$/.test(frag.get("day") || "") && frag.get("day") <= todayISO()) state.day = frag.get("day");
  if (location.hash) history.replaceState(null, "", location.pathname);  // keep tokens/codes out of history
  if (!token() && !ON_LAPTOP) return showPairing();
  start();
  setInterval(() => { if (!document.hidden && !$("#app").hidden) { safely(refreshStatus); if (state.view === "home" && state.day === todayISO()) safely(loadHome); } }, 30000);
  if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("/m/sw.js").catch(() => {});
})();
