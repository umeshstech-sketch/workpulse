/* WorkPulse dashboard. Plain JS + Chart.js; all numbers come from the API (same code as the CLI). */
"use strict";

const CATS = ["Coding", "Learning/AI", "Design", "Content Creation", "Communication", "Browsing", "Entertainment", "Other"];
const CAT_VAR = {
  "Coding": "--series-1", "Learning/AI": "--series-2", "Design": "--series-3", "Content Creation": "--series-4",
  "Communication": "--series-5", "Browsing": "--series-6", "Entertainment": "--series-7", "Other": "--series-other",
};
const $ = (sel) => document.querySelector(sel);
const css = (v) => getComputedStyle(document.documentElement).getPropertyValue(v).trim();
const catColor = (c) => css(CAT_VAR[c] || "--series-other");

// ?date=YYYY-MM-DD opens the dashboard on that day (handy for bookmarks and sharing a link to yourself).
const urlDate = new URLSearchParams(location.search).get("date");
const state = { day: /^\d{4}-\d{2}-\d{2}$/.test(urlDate || "") && urlDate <= todayISO() ? urlDate : todayISO(),
                tab: "today", charts: {}, settings: null, lastDay: null, lastWeek: null };

// ---------- utils ----------
function todayISO() { const d = new Date(); return new Date(d - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 10); }
function shiftISO(iso, days) { const d = new Date(iso + "T12:00:00"); d.setDate(d.getDate() + days); return new Date(d - d.getTimezoneOffset() * 6e4).toISOString().slice(0, 10); }
function dur(sec) { const m = Math.round((sec || 0) / 60); const h = Math.floor(m / 60); return h ? `${h}h ${String(m % 60).padStart(2, "0")}m` : `${m}m`; }
function hm(ts) { return ts ? new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false }) : "--:--"; }
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v; else if (k === "style") e.style.cssText = v; else if (k === "text") e.textContent = v; else e.setAttribute(k, v);
  }
  for (const k of kids) e.append(k);
  return e;
}
function deltaSpan(cur, ref, fmt = dur) {
  if (ref == null || ref === 0) return null;
  const d = cur - ref;
  return el("span", { class: d >= 0 ? "delta-up" : "delta-down", text: `${d >= 0 ? "▲" : "▼"} ${fmt(Math.abs(d))}` });
}
// On a paired phone (opened via the mobile app's "Full dashboard"), requests carry that phone's token.
const deviceToken = (() => { try { return localStorage.getItem("wp-token"); } catch (e) { return null; } })();
async function api(path, opts = {}) {
  const auth = deviceToken ? { Authorization: `Bearer ${deviceToken}` } : {};
  const r = await fetch(path, { ...opts, headers: { "Content-Type": "application/json", "X-WorkPulse-UI": "1", ...auth, ...(opts.headers || {}) } });
  if (r.status === 401 && location.hostname !== "127.0.0.1" && location.hostname !== "localhost") { location.href = "/m/"; throw new Error("not paired"); }
  if (!r.ok) { let msg = r.statusText; try { msg = JSON.stringify((await r.json()).detail); } catch (e) {} throw new Error(msg); }
  return r.json();
}

// ---------- tooltip ----------
const tip = $("#tooltip");
function showTip(evt, title, sub) {
  tip.replaceChildren(el("div", { class: "t-title", text: title }), ...(sub ? [el("div", { class: "t-sub", text: sub })] : []));
  tip.hidden = false;
  const x = Math.min(evt.clientX + 14, window.innerWidth - tip.offsetWidth - 8);
  const y = evt.clientY + 16 + tip.offsetHeight > window.innerHeight ? evt.clientY - tip.offsetHeight - 10 : evt.clientY + 16;
  tip.style.left = `${x}px`; tip.style.top = `${y}px`;
}
function hideTip() { tip.hidden = true; }

// ---------- status ----------
async function refreshStatus() {
  try {
    const s = await api("/api/status");
    const pill = $("#status-pill");
    pill.className = "pill " + ({ on: "pill-on", paused: "pill-paused", off: "pill-off" }[s.tracking]);
    let text = { on: "Tracking", paused: "Paused", off: "Tracker off" }[s.tracking];
    if (s.tracking === "on" && s.current) text += ` · ${s.current.state === "away" ? "away" : s.current.category}`;
    $("#status-text").textContent = text;
    $("#pause-btn").textContent = s.tracking === "paused" ? "Resume" : "Pause";
    $("#pause-btn").dataset.action = s.tracking === "paused" ? "resume" : "pause";
    $("#pause-btn").title = s.tracking === "off" ? "Tracker isn't running: start it with .\\workpulse start" : "";
    $("#demo-badge").hidden = !s.demo;
    const nl = $("#now-line");
    if (s.current && state.day === todayISO()) nl.textContent = `Right now: ${s.current.state}${s.current.app ? " · " + s.current.app : ""} for ${dur(s.current.duration_s)}`;
    else nl.textContent = "";
  } catch (e) {
    $("#status-pill").className = "pill pill-off"; $("#status-text").textContent = "Backend unreachable";
  }
}
$("#pause-btn").addEventListener("click", async () => {
  await api(`/api/${$("#pause-btn").dataset.action || "pause"}`, { method: "POST" });
  refreshStatus();
});

// ---------- today ----------
function kpi(label, value, sub) {
  const s = el("div", { class: "sub" });
  if (sub) for (const p of [].concat(sub)) { if (p == null) continue; if (s.childNodes.length) s.append(" · "); s.append(p); }
  return el("div", { class: "kpi" }, el("div", { class: "label", text: label }), el("div", { class: "value", text: value }), s);
}

function renderKpis(d) {
  const c = d.comparison;
  const vsY = deltaSpan(d.active_s, c.yesterday_active_s);
  $("#kpis").replaceChildren(
    kpi("Active", dur(d.active_s), [vsY ? el("span", {}, vsY, " vs yesterday") : null, c.avg7_active_s ? `7-day avg ${dur(c.avg7_active_s)}` : null]),
    kpi("Focus score", `${d.focus_score}`, [`7-day avg ${Math.round(c.avg7_score)}`, c.best_score != null ? `best ${c.best_score}` : null]),
    kpi("Longest focus", dur(d.longest_streak_s), d.streak_category ? `${d.streak_category} from ${hm(d.streak_start)}` : "no streak yet"),
    kpi("Productive", dur(d.productive_s), d.active_s ? `${Math.round(100 * d.productive_s / d.active_s)}% of active` : null),
    kpi("Breaks", `${d.breaks}`, `idle ${dur(d.idle_s)}`),
    kpi("First → last", `${hm(d.first_activity)}–${hm(d.last_activity)}`, null),
  );
}

function renderLegend(target, cats, withIdle) {
  const items = cats.map((c) => el("span", {}, el("i", { class: "swatch", style: `background:${catColor(c)}` }), c));
  if (withIdle) items.push(el("span", {}, el("i", { class: "swatch idle" }), "Idle"));
  target.replaceChildren(...items);
}

function renderTimeline(d) {
  const tl = $("#timeline"), axis = $("#timeline-axis");
  const visible = d.timeline.filter((b) => b.state !== "away");
  tl.replaceChildren(); axis.replaceChildren();
  if (!visible.length) return;
  const day0 = new Date(d.day + "T00:00:00").getTime() / 1000;
  let h0 = Math.floor((Math.min(...visible.map((b) => b.start)) - day0) / 3600);
  let h1 = Math.ceil((Math.max(...visible.map((b) => b.end)) - day0) / 3600);
  if (h1 - h0 < 4) { h1 = Math.min(24, h0 + 4); h0 = Math.max(0, h1 - 4); }
  const t0 = day0 + h0 * 3600, span = (h1 - h0) * 3600;
  const pct = (t) => `${(100 * (t - t0) / span).toFixed(3)}%`;
  for (const b of visible) {
    const blk = el("div", { class: `blk ${b.state}` });
    blk.style.left = pct(b.start);
    blk.style.width = `${Math.max(0.15, 100 * (b.end - b.start) / span).toFixed(3)}%`;
    if (b.state === "active") blk.style.background = catColor(b.category);
    blk.addEventListener("mousemove", (e) => showTip(e,
      `${hm(b.start)}–${hm(b.end)} · ${dur(b.end - b.start)} · ${b.state === "idle" ? "Idle" : b.category}`,
      [b.app, b.title].filter(Boolean).join(" — ")));
    blk.addEventListener("mouseleave", hideTip);
    tl.append(blk);
  }
  const now = Date.now() / 1000;
  if (now > t0 && now < t0 + span) tl.append(el("div", { class: "now", style: `left:${pct(now)}`, title: "now" }));
  const step = h1 - h0 > 12 ? 3 : h1 - h0 > 6 ? 2 : 1;
  for (let h = h0; h <= h1; h += step) axis.append(el("span", { style: `left:${(100 * (h - h0) / (h1 - h0)).toFixed(2)}%`, text: `${String(h % 24).padStart(2, "0")}:00` }));
  const present = CATS.filter((c) => visible.some((b) => b.state === "active" && b.category === c));
  renderLegend($("#timeline-legend"), present, visible.some((b) => b.state === "idle"));
}

const HAS_CHART = typeof window.Chart !== "undefined"; // CDN unreachable (offline) => tables still work
function chartDefaults() {
  if (!HAS_CHART) return;
  Chart.defaults.font.family = css("font-family") || "system-ui";
  Chart.defaults.color = css("--muted");
  Chart.defaults.borderColor = css("--grid");
}

function renderCategories(d) {
  const cats = d.categories.filter((c) => c.seconds > 0);
  const tbl = $("#cat-table");
  tbl.replaceChildren(el("tr", {}, el("th", { text: "Category" }), el("th", { class: "num", text: "Time" }), el("th", { class: "num", text: "Share" })));
  for (const c of cats) {
    tbl.append(el("tr", {},
      el("td", {}, el("i", { class: "swatch", style: `background:${catColor(c.name)};margin-right:6px` }), c.name),
      el("td", { class: "num", text: dur(c.seconds) }),
      el("td", { class: "num", text: `${Math.round(100 * c.seconds / d.active_s)}%` })));
  }
  const data = { labels: cats.map((c) => c.name), datasets: [{ data: cats.map((c) => c.seconds), backgroundColor: cats.map((c) => catColor(c.name)), borderColor: css("--surface"), borderWidth: 2, hoverOffset: 4 }] };
  if (!HAS_CHART) return;
  state.charts.cat?.destroy();
  state.charts.cat = new Chart($("#cat-chart"), {
    type: "doughnut", data,
    options: { cutout: "62%", maintainAspectRatio: false, plugins: { legend: { display: false },
      tooltip: { callbacks: { label: (ctx) => ` ${ctx.label}: ${dur(ctx.raw)} (${Math.round(100 * ctx.raw / d.active_s)}%)` } } } },
  });
}

function renderApps(d) {
  const max = Math.max(...d.top_apps.map((a) => a.seconds), 1);
  $("#apps").replaceChildren(...d.top_apps.slice(0, 8).map((a) => {
    const row = el("div", { class: "bar-row" },
      el("span", { class: "name", text: a.name, title: a.app || "" }),
      el("div", { class: "bar-track" }, el("div", { class: "bar-fill", style: `width:${(100 * a.seconds / max).toFixed(1)}%` })),
      el("span", { class: "num", text: dur(a.seconds) }));
    row.addEventListener("mousemove", (e) => showTip(e, a.name, `${dur(a.seconds)} · ${Math.round(100 * a.seconds / d.active_s)}% of active time`));
    row.addEventListener("mouseleave", hideTip);
    return row;
  }));
}

function renderBreakdown(d) {
  const b = d.score_breakdown;
  const parts = [
    ["Deep work", b.deep_work, 40, "productive time vs your daily target"],
    ["Focus ratio", b.focus_ratio, 25, "share of active time that was productive"],
    ["Longest streak", b.streak, 20, "longest single-category focus run vs target"],
    ["Low distraction", b.low_distraction, 15, "loses points as Entertainment grows"],
  ];
  $("#score-breakdown").replaceChildren(...parts.map(([name, v, max, why]) =>
    el("div", { class: "bd" },
      el("div", { class: "top-line" }, el("span", { text: name }), el("b", { text: `${v} / ${max}` })),
      el("div", { class: "track" }, el("div", { class: "fill", style: `width:${(100 * v / max).toFixed(1)}%` })),
      el("div", { class: "why", text: why }))));
}

async function loadDay() {
  const d = await api(`/api/day?date=${state.day}`);
  state.lastDay = d;
  $("#day-picker").value = state.day;
  $("#next-day").disabled = state.day >= todayISO();
  const empty = d.active_s === 0;
  $("#empty-day").hidden = !empty;
  $("#day-content").hidden = empty;
  if (empty) return;
  renderKpis(d); renderTimeline(d); renderCategories(d); renderApps(d); renderBreakdown(d);
}

$("#prev-day").addEventListener("click", () => { state.day = shiftISO(state.day, -1); loadDay(); refreshStatus(); });
$("#next-day").addEventListener("click", () => { if (state.day < todayISO()) { state.day = shiftISO(state.day, 1); loadDay(); refreshStatus(); } });
$("#day-picker").addEventListener("change", (e) => { if (e.target.value) { state.day = e.target.value; loadDay(); refreshStatus(); } });

// ---------- week ----------
async function loadWeek() {
  const w = await api(`/api/week?end=${state.day}`);
  state.lastWeek = w;
  const t = w.trend;
  const span = w.trend_full_days_only ? "last 7 full days" : "7 days";
  const pctSpan = (p) => p == null ? null : el("span", { class: p >= 0 ? "delta-up" : "delta-down", text: `${p >= 0 ? "▲" : "▼"} ${Math.abs(p)}%` });
  $("#week-kpis").replaceChildren(
    kpi(`Active (${span})`, dur(t.active_s), [pctSpan(t.active_change_pct) && el("span", {}, pctSpan(t.active_change_pct), " vs prior 7")]),
    kpi(`Productive (${span})`, dur(t.productive_s), [pctSpan(t.productive_change_pct) && el("span", {}, pctSpan(t.productive_change_pct), " vs prior 7")]),
    kpi("Avg focus score", `${Math.round(t.score_avg)}`, `prior week ${Math.round(t.prev_score_avg)}`),
    kpi("Best day", w.best_day ? new Date(w.best_day.date + "T12:00").toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" }) : "–",
        w.best_day ? `score ${w.best_day.score} · ${dur(w.best_day.active_s)}` : null),
  );
  const labels = w.days.map((d) => new Date(d.date + "T12:00").toLocaleDateString([], { weekday: "short", day: "numeric" }));
  const present = CATS.filter((c) => w.days.some((d) => (d.per_category[c] || 0) > 0));
  renderLegend($("#week-legend"), present, false);
  const hours = (s) => +(s / 3600).toFixed(2);
  if (HAS_CHART) {
  state.charts.week?.destroy();
  state.charts.week = new Chart($("#week-chart"), {
    type: "bar",
    data: { labels, datasets: present.map((c) => ({ label: c, data: w.days.map((d) => hours(d.per_category[c] || 0)), backgroundColor: catColor(c),
      borderColor: css("--surface"), borderWidth: { top: 2 }, borderSkipped: false, borderRadius: 0, maxBarThickness: 44 })) },
    options: { maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, title: { display: true, text: "hours" }, grid: { color: css("--grid") } } },
      plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => ` ${ctx.dataset.label}: ${dur(ctx.raw * 3600)}`,
        footer: (items) => `Total ${dur(items.reduce((s, i) => s + i.raw * 3600, 0))}` } } } },
  });
  state.charts.score?.destroy();
  state.charts.score = new Chart($("#score-chart"), {
    type: "line",
    data: { labels, datasets: [{ label: "Focus score", data: w.days.map((d) => d.active_s ? d.focus_score : null), borderColor: css("--series-1"), backgroundColor: css("--series-1"),
      borderWidth: 2, pointRadius: 4, pointHoverRadius: 6, pointBorderColor: css("--surface"), pointBorderWidth: 2, spanGaps: true, tension: 0.25 }] },
    options: { maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      scales: { y: { min: 0, max: 100, grid: { color: css("--grid") } }, x: { grid: { display: false } } }, plugins: { legend: { display: false } } },
  });
  }
  $("#trend-text").textContent = w.trend_text;
  $("#streaks").replaceChildren(...(w.streaks.length ? w.streaks.map((s) => el("li", { text: `🔥 ${s.text}` })) : [el("li", { class: "muted", text: "No multi-day streaks yet. Two days in a row over 1h of anything productive starts one." })]));
  const tbl = $("#week-table");
  tbl.replaceChildren(el("tr", {}, el("th", { text: "Category" }), ...labels.map((l) => el("th", { class: "num", text: l })), el("th", { class: "num", text: "Total" })));
  for (const c of present) {
    tbl.append(el("tr", {}, el("td", {}, el("i", { class: "swatch", style: `background:${catColor(c)};margin-right:6px` }), c),
      ...w.days.map((d) => el("td", { class: "num", text: d.per_category[c] ? dur(d.per_category[c]) : "–" })),
      el("td", { class: "num", text: dur(w.category_totals[c] || 0) })));
  }
}

// ---------- settings ----------
function getPath(obj, path) { return path.split(".").reduce((o, k) => o?.[k], obj); }

const ON_LAPTOP = ["127.0.0.1", "localhost"].includes(location.hostname);

async function loadSettings() {
  if (!ON_LAPTOP) {  // a paired phone can look, but settings and data deletion stay on the laptop
    for (const x of document.querySelectorAll("#settings-form input, #settings-form textarea, #settings-form select, #settings-form button, #wipe-btn")) x.disabled = true;
    $("#save-msg").textContent = "Settings can only be changed on the laptop.";
  }
  const s = await api("/api/settings");
  state.settings = s;
  state.savedApps = { ...s.categories.apps };
  const form = $("#settings-form");
  for (const inp of form.querySelectorAll("[name]")) {
    const v = getPath(s, inp.name);
    if (inp.type === "checkbox") inp.checked = !!v;
    else if (inp.tagName === "TEXTAREA") inp.value = (v || []).join("\n");
    else inp.value = inp.dataset.scale ? +(v / +inp.dataset.scale).toFixed(2) : v;
  }
  $("#productive-cats").replaceChildren(...s.category_names.map((c) => {
    const cb = el("input", { type: "checkbox", value: c });
    cb.checked = s.scoring.productive_categories.includes(c);
    return el("label", {}, cb, c);
  }));
  const catOptions = (sel) => s.category_names.map((c) => { const o = el("option", { value: c, text: c }); if (c === sel) o.selected = true; return o; });
  $("#new-app-cat").replaceChildren(...catOptions("Coding"));
  renderAppsTable(s.categories.apps, catOptions);
}

function renderAppsTable(apps, catOptions) {
  const tbl = $("#apps-table");
  tbl.replaceChildren(el("tr", {}, el("th", { text: "App (process)" }), el("th", { text: "Category" })));
  for (const [app, cat] of Object.entries(apps).sort()) {
    const sel = el("select", { "data-app": app, "aria-label": `Category for ${app}` }, ...catOptions(cat));
    tbl.append(el("tr", {}, el("td", { text: app }), el("td", {}, sel)));
  }
}

$("#add-app-btn").addEventListener("click", () => {
  const name = $("#new-app").value.trim().toLowerCase().replace(/\.exe$/, "");
  if (!name) return;
  const apps = { ...state.settings.categories.apps, ...collectApps(), [name]: $("#new-app-cat").value };
  state.settings.categories.apps = apps;
  const catOptions = (sel) => state.settings.category_names.map((c) => { const o = el("option", { value: c, text: c }); if (c === sel) o.selected = true; return o; });
  renderAppsTable(apps, catOptions);
  $("#new-app").value = "";
  $("#save-msg").textContent = `Added ${name}. Remember to save.`;
});

function collectApps() {
  const out = {};
  for (const sel of document.querySelectorAll("#apps-table select")) out[sel.dataset.app] = sel.value;
  return out;
}

$("#settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const changes = { tracking: {}, privacy: {}, scoring: {}, categories: { apps: collectApps() } };
  for (const inp of e.target.querySelectorAll("[name]")) {
    const [sec, key] = inp.name.split(".");
    if (inp.type === "checkbox") changes[sec][key] = inp.checked;
    else if (inp.tagName === "TEXTAREA") changes[sec][key] = inp.value.split("\n").map((x) => x.trim()).filter(Boolean);
    else changes[sec][key] = +inp.value * (+inp.dataset.scale || 1);
  }
  changes.scoring.productive_categories = [...document.querySelectorAll("#productive-cats input:checked")].map((c) => c.value);
  // Send only what changed, so untouched settings keep following config.yaml.
  const same = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  for (const sec of ["tracking", "privacy", "scoring"]) {
    for (const k of Object.keys(changes[sec])) if (same(changes[sec][k], state.settings[sec][k])) delete changes[sec][k];
    if (!Object.keys(changes[sec]).length) delete changes[sec];
  }
  const apps = changes.categories.apps;
  for (const k of Object.keys(apps)) if (apps[k] === state.savedApps[k]) delete apps[k];
  if (!Object.keys(apps).length) delete changes.categories;
  const msg = $("#save-msg");
  if (!Object.keys(changes).length) { msg.textContent = "Nothing changed."; return; }
  try {
    await api("/api/settings", { method: "PUT", body: JSON.stringify(changes) });
    msg.textContent = "Saved ✓ The tracker picks this up within ~10 seconds.";
    await loadSettings();
  } catch (err) { msg.textContent = `Not saved: ${err.message}`; }
});

$("#wipe-btn").addEventListener("click", async () => {
  const typed = prompt('This permanently deletes ALL tracked activity on this laptop.\nType DELETE to confirm.');
  if (typed !== "DELETE") return;
  const r = await api("/api/wipe", { method: "POST", body: JSON.stringify({ confirm: "DELETE" }) });
  alert(`Deleted ${r.deleted} sessions.`);
  loadDay();
});

// ---------- tabs, theme, refresh ----------
function showTab(name) {
  state.tab = name;
  for (const b of document.querySelectorAll(".tabs button")) b.setAttribute("aria-selected", String(b.dataset.tab === name));
  for (const s of document.querySelectorAll(".tab")) s.hidden = s.id !== `tab-${name}`;
  const report = (e) => { console.error(e); showTip({ clientX: window.innerWidth / 2 - 120, clientY: 90 }, `⚠️ ${e.message}`); setTimeout(hideTip, 3500); };
  if (name === "today") loadDay().catch(report);
  if (name === "week") loadWeek().catch(report);
  if (name === "settings") loadSettings().catch(report);
  const extra = (window.TAB_LOADERS || {})[name];  // Phase 4 tabs (planning.js)
  if (extra) Promise.resolve().then(extra).catch(report);
  try { history.replaceState(null, "", `#${name}`); } catch (e) {}
}
for (const b of document.querySelectorAll(".tabs button")) b.addEventListener("click", () => showTab(b.dataset.tab));

$("#theme-btn").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  try { localStorage.setItem("wp-theme", next); } catch (e) {}
  chartDefaults();
  if (state.tab === "today" && state.lastDay && state.lastDay.active_s) { renderTimeline(state.lastDay); renderCategories(state.lastDay); }
  if (state.tab === "week") loadWeek();
  if (state.tab === "insights" || state.tab === "digital") window.TAB_LOADERS[state.tab]();
});

chartDefaults();
refreshStatus();
const TABS = ["today", "week", "digital", "goals", "team", "insights", "coach", "settings"];
const initial = (location.hash || "").slice(1);
showTab(TABS.includes(initial) ? initial : "today");
window.addEventListener("hashchange", () => { const t = location.hash.slice(1); if (TABS.includes(t) && t !== state.tab) showTab(t); });
setInterval(refreshStatus, 10000);
setInterval(() => { if (state.tab === "today" && state.day === todayISO() && !document.hidden) loadDay(); }, 30000);
