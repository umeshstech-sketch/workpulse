/* WorkPulse for Android: the screens. All data comes from window.WorkPulse (the app itself, on this phone). */
"use strict";
const WP = window.WorkPulse;
const $ = (s) => document.querySelector(s);

// ---------- helpers ----------
function el(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null || v === false) continue;
    if (k === "text") e.textContent = v;
    else if (k === "html") e.innerHTML = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const k of kids.flat()) if (k != null && k !== false) e.append(k);
  return e;
}
function svg(tag, attrs = {}, text) {
  const e = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text != null) e.textContent = text;
  return e;
}
function call(name, ...args) {
  try {
    const r = WP[name](...args);
    return typeof r === "string" ? JSON.parse(r) : r ?? null;
  } catch (e) { console.error(name, e); return null; }
}
const esc = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
function dur(s) {
  s = Math.max(0, Math.round(s || 0));
  const m = Math.round(s / 60);
  if (m === 0) return s > 0 ? "<1m" : "0m";
  const h = Math.floor(m / 60);
  return h ? (m % 60 ? `${h}h ${m % 60}m` : `${h}h`) : `${m}m`;
}
const pct = (a, b) => (b ? Math.round(((a - b) / b) * 100) : null);
const sum = (xs, f) => xs.reduce((t, x) => t + (f ? f(x) : x), 0);
function iso(d) { return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); }
const todayISO = () => iso(new Date());
function shiftISO(s, n) { const d = new Date(`${s}T12:00:00`); d.setDate(d.getDate() + n); return iso(d); }
function dayName(s, long) {
  if (s === todayISO()) return "Today";
  if (s === shiftISO(todayISO(), -1)) return "Yesterday";
  return new Date(`${s}T12:00:00`).toLocaleDateString([], long ? { weekday: "long", day: "numeric", month: "short" } : { weekday: "short", day: "numeric" });
}
const clock = (ms) => new Date(ms).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const hourLabel = (h) => new Date(2000, 0, 1, h).toLocaleTimeString([], { hour: "numeric" });
const hourTime = (h) => new Date(2000, 0, 1, h).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
const mmss = (s) => { s = Math.max(0, Math.ceil(s)); return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`; };

const CATS = ["Social", "Entertainment", "Games", "Communication", "Productivity", "Learning", "Browsing", "Other"];
const CAT_VAR = { Social: "--c-social", Entertainment: "--c-ent", Games: "--c-games", Communication: "--c-comm",
  Productivity: "--c-prod", Learning: "--c-learn", Browsing: "--c-browse", Other: "--c-other" };
const catColor = (c) => `var(${CAT_VAR[c] || "--c-other"})`;

function toast(msg, ms = 2600) {
  const t = $("#toast"); t.textContent = msg; t.hidden = false;
  clearTimeout(toast.t); toast.t = setTimeout(() => { t.hidden = true; }, ms);
}
window.wpToast = toast;
function safely(fn) { try { fn(); } catch (e) { console.error(e); toast(`⚠️ ${e.message}`); } }

const state = { view: "today", day: todayISO(), period: 7, settings: call("settings") || {}, status: {}, focusMin: 25, ticker: null, showAllApps: false };
const save = (changes) => { state.settings = call("saveSettings", JSON.stringify(changes)) || state.settings; };

function applyTheme() {
  const t = state.settings.theme || "auto";
  const dark = t === "dark" || (t === "auto" && !matchMedia("(prefers-color-scheme: light)").matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
}
function refreshStatus() {
  state.status = call("status") || {};
  $("#banner").hidden = state.status.usageAccess !== false;
}
$("#grant").addEventListener("click", () => WP.openUsageAccess());

// ---------- shared pieces ----------
function hoursOf(s, key, fallback) { return parseInt(String(s[key] || fallback).split(":")[0], 10); }
function isNightHour(h, s) {
  const bed = hoursOf(s, "bedtime", "23:00"), wake = hoursOf(s, "wake", "06:30");
  return bed > wake ? h >= bed || h < wake : h >= bed && h < wake;
}
function nightSeconds(d, s) { return sum((d.hourly || []).map((v, h) => (isNightHour(h, s) ? v : 0))); }

/** The balance score: 100 minus four plainly-explained penalties, so it's never a mystery number. */
function score(d, s) {
  const goal = (s.dailyGoalMin || 180) * 60, T = d.total_s || 0, P = d.pickups || 0, PG = s.pickupGoal || 60;
  const share = T ? (d.distracting_s || 0) / T : 0, night = nightSeconds(d, s);
  const parts = [
    { label: `Screen time ${dur(T)} (goal ${dur(goal)})`, lost: T <= goal ? 0 : Math.min(40, Math.round((40 * (T - goal)) / goal)) },
    { label: `Distracting apps: ${Math.round(share * 100)}% of time (up to 30% is free)`, lost: Math.round((30 * Math.max(0, share - 0.3)) / 0.7) },
    { label: `${P} pickups (goal ${PG})`, lost: P <= PG ? 0 : Math.min(20, Math.round((20 * (P - PG)) / PG)) },
    { label: `${dur(night)} in bedtime hours`, lost: Math.min(10, Math.round(night / 180)) },
  ];
  return { score: Math.max(0, 100 - sum(parts, (p) => p.lost)), parts };
}

function hourChart(hourly, s) {
  const W = 288, H = 92, bw = 12, max = Math.max(900, ...hourly);
  const g = svg("svg", { viewBox: `0 0 ${W} ${H + 16}`, role: "img", "aria-label": "Screen time by hour" });
  g.append(svg("line", { x1: 0, x2: W, y1: H + 0.5, y2: H + 0.5, class: "grid" }));
  g.append(svg("line", { x1: 0, x2: W, y1: 0.5, y2: 0.5, class: "grid" }));
  g.append(svg("text", { x: W, y: 10, "text-anchor": "end" }, dur(max)));
  hourly.forEach((v, h) => {
    const bh = v ? Math.max(2, (v / max) * (H - 2)) : 0;
    const r = svg("rect", { x: h * bw + 1.5, y: H - bh, width: bw - 3, height: bh, rx: 2, style: `fill:var(${isNightHour(h, s) ? "--night" : "--accent"})` });
    r.append(svg("title", {}, `${hourTime(h)}: ${dur(v)}`));
    g.append(r);
  });
  for (const h of [0, 6, 12, 18]) g.append(svg("text", { x: h * bw + 1, y: H + 13 }, hourLabel(h)));
  return g;
}

/** One bar per day; `goal` (seconds) draws the dashed line and turns bars over it red. */
function dayBars(days, goal, onPick) {
  const n = days.length, W = 300, H = 100, bw = W / n;
  const max = Math.max(goal ? goal * 1.15 : 0, 1800, ...days.map((d) => d.total_s || 0));
  const g = svg("svg", { viewBox: `0 0 ${W} ${H + 16}`, role: "img", "aria-label": "Screen time per day" });
  g.append(svg("line", { x1: 0, x2: W, y1: H + 0.5, y2: H + 0.5, class: "grid" }));
  days.forEach((d, i) => {
    const v = d.total_s || 0, bh = v ? Math.max(2, (v / max) * (H - 4)) : 0;
    const r = svg("rect", { x: i * bw + bw * 0.18, y: H - bh, width: bw * 0.64, height: bh, rx: Math.min(3, bw * 0.2),
      style: `fill:var(${goal && v > goal ? "--bad" : "--accent"})` });
    r.append(svg("title", {}, `${dayName(d.day)}: ${dur(v)}`));
    g.append(r);
    if (onPick) {
      const hit = svg("rect", { x: i * bw, y: 0, width: bw, height: H + 16, fill: "transparent" });
      hit.addEventListener("click", () => onPick(d.day));
      g.append(hit);
    }
    const show = n <= 7 || i % 5 === 0 || i === n - 1;
    if (show) {
      const dt = new Date(`${d.day}T12:00:00`);
      const label = n <= 7 ? dt.toLocaleDateString([], { weekday: "short" }) : String(dt.getDate());
      g.append(svg("text", { x: i * bw + bw / 2, y: H + 13, "text-anchor": "middle" }, label));
    }
  });
  if (goal) {
    const y = H - (goal / max) * (H - 4);
    g.append(svg("line", { x1: 0, x2: W, y1: y, y2: y, class: "goal" }));
  }
  return g;
}

function catBreakdown(cats, barEl, listEl, perDay = 1) {
  const entries = Object.entries(cats || {}).filter(([, s]) => s > 0).sort((a, b) => b[1] - a[1]);
  const total = sum(entries, ([, s]) => s);
  barEl.replaceChildren(...entries.map(([c, s]) => el("span", { style: `width:${(s / total) * 100}%;background:${catColor(c)}`, title: c })));
  listEl.replaceChildren(...(entries.length
    ? entries.map(([c, s]) => el("div", {}, el("span", {}, el("i", { class: "dotc", style: `background:${catColor(c)}` }), c), el("b", { text: dur(s / perDay) })))
    : [el("div", { class: "empty", text: "No app use recorded." })]));
}

function appRows(apps, container, { perDay = 1, limit = 0 } = {}) {
  const limits = state.settings.limits || {};
  if (!apps.length) { container.replaceChildren(el("div", { class: "empty", text: "No app use recorded." })); return; }
  const top = apps[0].s / perDay || 1;
  const shown = limit && !state.showAllApps ? apps.slice(0, limit) : apps;
  const rows = shown.map((a) => {
    const s = a.s / perDay, lim = (limits[a.pkg] || 0) * 60;
    const sub = [el("span", {}, el("i", { class: "dotc", style: `background:${catColor(a.cat)}` }), a.cat)];
    if (a.opens) sub.push(el("span", { text: plural(Math.round(a.opens / perDay), "open") }));
    if (lim) sub.push(el("span", { class: s >= lim ? "over" : "", text: `limit ${dur(lim)}` }));
    return el("button", { class: "app", onclick: () => { if (a.pkg !== "private") openApp(a.pkg); } },
      el("div", { class: "app-top" }, el("span", { class: "app-name", text: a.name }), el("span", { class: "app-time", text: dur(s) })),
      el("div", { class: "app-sub" }, sub),
      el("div", { class: "bar" }, el("span", { style: `width:${Math.max(2, (s / top) * 100)}%;background:${catColor(a.cat)}` })));
  });
  if (shown.length < apps.length) rows.push(el("button", { class: "btn", style: "margin-top:10px", onclick: () => { state.showAllApps = true; appRows(apps, container, { perDay, limit }); } }, `Show all ${apps.length} apps`));
  container.replaceChildren(...rows);
}

// ---------- today ----------
function insights(d, avg, s, isToday) {
  const out = [], T = d.total_s || 0, apps = d.apps || [];
  if (!T) return [isToday ? "Nothing yet today. Use your phone as usual; WorkPulse updates every 15 minutes and whenever you open it." : "No app use recorded for this day."];
  if (avg) {
    const p = pct(T, avg);
    out.push(isToday ? `So far <b>${dur(T)}</b>; your 7-day average is ${dur(avg)} a day.`
      : `<b>${Math.abs(p)}% ${p > 0 ? "more" : "less"}</b> than your 7-day average (${dur(avg)}).`);
  }
  if (d.pickups && d.first_pickup) {
    const awake = ((isToday ? Date.now() : d.last_use || Date.now()) - d.first_pickup) / 60000;
    if (awake > 60) out.push(`You picked up your phone about every <b>${Math.max(1, Math.round(awake / d.pickups))} minutes</b>.`);
  }
  const top = apps.find((a) => a.pkg !== "private");
  if (top) out.push(`<b>${esc(top.name)}</b> took ${Math.round((top.s / T) * 100)}% of your screen time (${dur(top.s)}).`);
  const opened = [...apps].sort((a, b) => b.opens - a.opens)[0];
  if (opened && opened.opens >= 10 && opened.pkg !== "private") out.push(`You opened <b>${esc(opened.name)}</b> ${opened.opens} times.`);
  const hourly = d.hourly || [], peak = Math.max(...hourly);
  if (peak >= 600) out.push(`Busiest hour: <b>${hourTime(hourly.indexOf(peak))}</b> (${dur(peak)}).`);
  const night = nightSeconds(d, s);
  if (night >= 900) out.push(`<b>${dur(night)}</b> during bedtime hours (${esc(s.bedtime)} to ${esc(s.wake)}).`);
  if (T >= 1800) {
    const share = (d.distracting_s || 0) / T;
    out.push(share > 0.5 ? `More than half (<b>${dur(d.distracting_s)}</b>) went to distracting apps.`
      : `Only <b>${Math.round(share * 100)}%</b> went to distracting apps. Nice balance.`);
  }
  return out;
}

function loadToday() {
  const s = state.settings, isToday = state.day === todayISO();
  const days = call("range", 8, state.day) || [];
  const d = days[days.length - 1] || { apps: [], hourly: Array(24).fill(0), total_s: 0, pickups: 0 };
  const prev = days.slice(0, -1).filter((x) => x.total_s > 0);
  const avg = prev.length ? sum(prev, (x) => x.total_s) / prev.length : 0;
  const T = d.total_s || 0, goal = (s.dailyGoalMin || 180) * 60;

  $("#day-title").textContent = dayName(state.day, true);
  $("#next-day").disabled = isToday;
  $("#t-total").textContent = dur(T);
  const bar = $("#t-goal-bar");
  bar.style.width = `${Math.min(100, (T / goal) * 100)}%`;
  bar.classList.toggle("over", T > goal);
  $("#t-goal").textContent = T > goal ? `${dur(T - goal)} over your ${dur(goal)} goal` : `${dur(goal - T)} left of your ${dur(goal)} goal`;
  const vs = $("#t-vs");
  if (avg && !isToday) {
    const p = pct(T, avg);
    vs.textContent = `${p > 0 ? "▲" : "▼"} ${Math.abs(p)}% vs avg`;
    vs.className = p > 0 ? "up" : "down";
  } else { vs.textContent = avg ? `avg ${dur(avg)}` : ""; vs.className = ""; }

  const sc = score(d, s), C = 2 * Math.PI * 19, ring = $("#t-score-ring");
  ring.style.strokeDasharray = C;
  ring.style.strokeDashoffset = C * (1 - sc.score / 100);
  ring.style.stroke = `var(${sc.score >= 75 ? "--good" : sc.score >= 50 ? "--warn" : "--bad"})`;
  $("#t-score-num").textContent = T ? sc.score : "–";
  $("#t-score-sub").textContent = !T ? "Starts counting once you use your phone." : sc.score >= 85 ? "Great balance" : sc.score >= 70 ? "Pretty balanced" : sc.score >= 50 ? "Room to improve" : "Phone-heavy day";
  $("#t-score-parts").replaceChildren(...sc.parts.map((p) => el("div", { class: "part" }, el("span", { text: p.label }),
    el("b", { class: p.lost ? "lost" : "", text: p.lost ? `−${p.lost}` : "✓" }))));

  $("#t-pickups").textContent = d.pickups || 0;
  $("#t-pickups-sub").textContent = `goal ${s.pickupGoal || 60}`;
  $("#t-first").textContent = d.first_pickup ? clock(d.first_pickup) : "–";
  $("#t-longest").textContent = d.longest ? dur(d.longest.s) : "–";
  $("#t-longest-sub").textContent = d.longest ? `in ${d.longest.name}` : "";
  const fs = (call("focus") || {}).sessions || [];
  const todays = fs.filter((x) => iso(new Date(x.start)) === state.day);
  $("#t-focus").textContent = dur(sum(todays, (x) => (x.end - x.start) / 1000));
  $("#t-focus-sub").textContent = todays.length ? `${todays.length} session${todays.length > 1 ? "s" : ""}` : "none yet";

  $("#t-hours").replaceChildren(hourChart(d.hourly || Array(24).fill(0), s));
  catBreakdown(d.cats, $("#t-catbar"), $("#t-cats"));
  $("#t-insights").replaceChildren(...insights(d, avg, s, isToday).map((h) => el("li", { html: h })));
  appRows(d.apps || [], $("#t-apps"), { limit: 12 });
}
$("#prev-day").addEventListener("click", () => { state.day = shiftISO(state.day, -1); state.showAllApps = false; safely(loadToday); });
$("#next-day").addEventListener("click", () => { if (state.day < todayISO()) { state.day = shiftISO(state.day, 1); state.showAllApps = false; safely(loadToday); } });

// ---------- trends ----------
function loadTrends() {
  const n = state.period, s = state.settings, goal = (s.dailyGoalMin || 180) * 60;
  const all = call("range", n * 2, todayISO()) || [];
  const cur = all.slice(-n), prev = all.slice(0, -n);
  const active = cur.filter((d) => d.total_s > 0), prevActive = prev.filter((d) => d.total_s > 0);
  $("#w-bars").replaceChildren(dayBars(cur, goal, (day) => { state.day = day; show("today"); }));
  const avg = active.length ? sum(active, (d) => d.total_s) / active.length : 0;
  const pavg = prevActive.length ? sum(prevActive, (d) => d.total_s) / prevActive.length : 0;
  $("#w-avg").textContent = active.length ? dur(avg) : "–";
  const p = pct(avg, pavg), vs = $("#w-vs");
  vs.textContent = p == null || !active.length ? `over ${active.length} day${active.length === 1 ? "" : "s"}` : `${p > 0 ? "▲" : "▼"} ${Math.abs(p)}% vs previous ${n} days`;
  vs.className = `sub ${p == null ? "" : p > 0 ? "up" : "down"}`;
  const pk = active.length ? sum(active, (d) => d.pickups || 0) / active.length : 0;
  const ppk = prevActive.length ? sum(prevActive, (d) => d.pickups || 0) / prevActive.length : 0;
  $("#w-pick").textContent = active.length ? Math.round(pk) : "–";
  const pp = pct(pk, ppk);
  $("#w-pick-vs").textContent = pp == null || !ppk ? `goal ${s.pickupGoal || 60}` : `${pp > 0 ? "▲" : "▼"} ${Math.abs(pp)}% vs before`;
  const full = active.filter((d) => d.day !== todayISO());
  const best = full.length ? full.reduce((a, b) => (b.total_s < a.total_s ? b : a)) : null;
  $("#w-best").textContent = best ? dur(best.total_s) : "–";
  $("#w-best-sub").textContent = best ? dayName(best.day) : "needs a full day";
  const within = active.filter((d) => d.total_s <= goal).length;
  $("#w-goal").textContent = active.length ? `${within}/${active.length}` : "–";
  $("#w-goal-sub").textContent = `goal ${dur(goal)} a day`;

  const cats = {};
  const apps = {};
  for (const d of active) {
    for (const [c, v] of Object.entries(d.cats || {})) cats[c] = (cats[c] || 0) + v;
    for (const a of d.apps || []) {
      const x = (apps[a.pkg] ||= { pkg: a.pkg, name: a.name, cat: a.cat, s: 0, opens: 0 });
      x.s += a.s; x.opens += a.opens || 0;
    }
  }
  const per = Math.max(1, active.length);
  catBreakdown(cats, $("#w-catbar"), $("#w-cats"), per);
  appRows(Object.values(apps).sort((a, b) => b.s - a.s).slice(0, 10), $("#w-apps"), { perDay: per });
}
for (const b of document.querySelectorAll("#v-trends .seg button")) {
  b.addEventListener("click", () => {
    state.period = Number(b.dataset.n);
    for (const x of document.querySelectorAll("#v-trends .seg button")) x.setAttribute("aria-selected", String(x === b));
    safely(loadTrends);
  });
}

// ---------- focus ----------
let focusState = { sessions: [] };
function updateTimer() {
  const a = focusState.active, C = 2 * Math.PI * 52, ring = $("#f-ring");
  ring.style.strokeDasharray = C;
  const pill = $("#focus-pill");
  if (!a) {
    $("#f-time").textContent = mmss(state.focusMin * 60);
    $("#f-label").textContent = "Ready";
    ring.style.strokeDashoffset = 0;
    pill.hidden = true;
    return;
  }
  const left = Math.max(0, a.end - Date.now());
  $("#f-time").textContent = mmss(left / 1000);
  $("#f-label").textContent = a.label || "Focusing…";
  ring.style.strokeDashoffset = C * (1 - left / (a.end - a.start));
  pill.hidden = false;
  $("#focus-pill-text").textContent = `Focus ${mmss(left / 1000)}`;
  if (left <= 0) { clearInterval(state.ticker); state.ticker = null; setTimeout(() => { refreshFocus(); if (state.view === "focus") loadFocus(); }, 1500); }
}
function refreshFocus() {
  focusState = call("focus") || { sessions: [] };
  clearInterval(state.ticker); state.ticker = null;
  if (focusState.active) state.ticker = setInterval(updateTimer, 1000);
  updateTimer();
}
$("#focus-pill").addEventListener("click", () => show("focus"));

function showResult(s) {
  const box = $("#f-result"), d = s.distractions || [], mins = Math.round((s.end - s.start) / 60000);
  box.hidden = false;
  box.classList.toggle("bad", d.length > 0);
  box.replaceChildren(
    el("div", { class: "card-title", text: s.completed ? `✅ Focus complete: ${s.planned_min} min` : `Stopped after ${mins} of ${s.planned_min} min` }),
    el("div", { text: d.length ? `You opened ${d.slice(0, 3).map((x) => `${x.name} (${x.opens}×)`).join(", ")}: ${dur(s.distracting_s)} in distracting apps.` : "No distracting apps opened. Great focus! 🎯" }));
}

function streakOf(daysSet) {
  let n = 0, d = todayISO();
  if (!daysSet.has(d)) d = shiftISO(d, -1);
  while (daysSet.has(d)) { n++; d = shiftISO(d, -1); }
  return n;
}

function loadFocus() {
  refreshFocus();
  if (focusState.just_finished) showResult(focusState.just_finished);
  $("#f-setup").hidden = !!focusState.active;
  $("#f-running").hidden = !focusState.active;
  for (const b of document.querySelectorAll("#f-presets button")) b.classList.toggle("on", Number(b.dataset.m) === state.focusMin);
  const ss = focusState.sessions || [], today = todayISO(), weekStart = shiftISO(today, -6);
  const secs = (x) => (x.end - x.start) / 1000;
  const todays = ss.filter((x) => iso(new Date(x.start)) === today);
  const week = ss.filter((x) => iso(new Date(x.start)) >= weekStart);
  $("#f-today").textContent = dur(sum(todays, secs));
  $("#f-today-sub").textContent = `${todays.length} session${todays.length === 1 ? "" : "s"}`;
  $("#f-streak").textContent = streakOf(new Set(ss.filter((x) => secs(x) >= 300).map((x) => iso(new Date(x.start)))));
  $("#f-week").textContent = dur(sum(week, secs));
  $("#f-week-sub").textContent = `${week.length} session${week.length === 1 ? "" : "s"}`;
  $("#f-clean").textContent = week.length ? `${Math.round((week.filter((x) => !(x.distractions || []).length).length / week.length) * 100)}%` : "–";
  const recent = [...ss].reverse().slice(0, 20);
  $("#f-sessions").replaceChildren(...(recent.length ? recent.map((x) => {
    const d = x.distractions || [];
    return el("div", { class: "item" }, el("div", { class: "grow" },
      el("div", { text: `${x.label || "Focus"} · ${dur(secs(x))}` }),
      el("div", { class: "muted small", text: `${dayName(iso(new Date(x.start)))} ${clock(x.start)} · ${x.completed ? "completed" : "stopped early"} · ${d.length ? `${d.length} distracting app${d.length > 1 ? "s" : ""}` : "no distractions"}` })),
      el("span", { text: x.completed && !d.length ? "🎯" : x.completed ? "✓" : "⏹" }));
  }) : [el("div", { class: "empty", text: "No sessions yet. Pick a length and start one." })]));
}
for (const b of document.querySelectorAll("#f-presets button")) {
  b.addEventListener("click", () => { state.focusMin = Number(b.dataset.m); loadFocus(); });
}
$("#f-start").addEventListener("click", () => safely(() => {
  if (state.status.notifications === false) WP.requestNotifications();
  call("focusStart", state.focusMin, $("#f-what").value.trim());
  $("#f-result").hidden = true;
  $("#f-what").value = "";
  loadFocus();
  toast("Focus started. Put the phone down 📵");
}));
$("#f-stop").addEventListener("click", () => safely(() => {
  if (!confirm("Stop this focus session early?")) return;
  const s = call("focusStop");
  if (s && s.start) showResult(s);
  loadFocus();
}));

// ---------- goals ----------
function habitStreak(h) { return streakOf(new Set(h.done || [])); }
function loadHabits() {
  const habits = call("getData", "habits") || [], today = todayISO();
  const write = (hs) => { WP.setData("habits", JSON.stringify(hs)); loadHabits(); };
  $("#g-habits").replaceChildren(...(habits.length ? habits.map((h, i) => {
    const done = (h.done || []).includes(today);
    const cb = el("input", { type: "checkbox", "aria-label": `Done today: ${h.name}` });
    cb.checked = done;
    cb.addEventListener("change", () => {
      const days = new Set(h.done || []);
      if (cb.checked) days.add(today); else days.delete(today);
      habits[i] = { ...h, done: [...days].filter((d) => d >= shiftISO(today, -400)).sort() };
      write(habits);
    });
    const streak = habitStreak(h);
    return el("div", { class: "item" }, cb, el("div", { class: "grow" }, el("div", { text: h.name }),
      el("div", { class: "muted small", text: `${(h.done || []).filter((d) => d >= shiftISO(today, -6)).length}/7 days this week` })),
      streak ? el("span", { class: "streak", text: `🔥 ${streak}` }) : null,
      el("button", { class: "x", "aria-label": `Delete ${h.name}`, onclick: () => { if (confirm(`Delete "${h.name}"?`)) { habits.splice(i, 1); write(habits); } } }, "✕"));
  }) : [el("div", { class: "empty", text: "No habits yet. Add one below." })]));
}
$("#g-habit-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const name = $("#g-habit").value.trim();
  if (!name) return;
  const habits = call("getData", "habits") || [];
  habits.push({ id: Date.now(), name, done: [] });
  WP.setData("habits", JSON.stringify(habits));
  $("#g-habit").value = "";
  loadHabits();
});

function loadGoals() {
  const s = state.settings;
  const goal = $("#g-goal"), pick = $("#g-pick");
  goal.value = s.dailyGoalMin || 180; pick.value = s.pickupGoal || 60;
  $("#g-goal-v").textContent = dur(goal.value * 60);
  $("#g-pick-v").textContent = pick.value;
  $("#g-notify").checked = s.notifyLimits !== false;
  $("#g-bed").value = s.bedtime || "23:00";
  $("#g-wake").value = s.wake || "06:30";
  $("#g-bed-remind").checked = s.bedtimeReminder !== false;

  const recent = call("range", 7, todayISO()) || [];
  const apps = {};
  for (const d of recent) for (const a of d.apps || []) { const x = (apps[a.pkg] ||= { pkg: a.pkg, name: a.name, s: 0 }); x.s += a.s; }
  const limits = s.limits || {};
  $("#g-limits").replaceChildren(...(Object.keys(limits).length ? Object.entries(limits).map(([pkg, min]) =>
    el("div", { class: "item" }, el("div", { class: "grow" }, el("div", { text: apps[pkg]?.name || pkg.split(".").pop() }),
      el("div", { class: "muted small", text: `${dur(min * 60)} a day` })),
      el("button", { class: "x", "aria-label": "Remove limit", onclick: () => { const l = { ...limits }; delete l[pkg]; save({ limits: l }); loadGoals(); } }, "✕")))
    : [el("div", { class: "empty", text: "No app limits yet." })]));
  const options = Object.values(apps).filter((a) => a.pkg !== "private" && !limits[a.pkg]).sort((a, b) => b.s - a.s);
  $("#g-limit-app").replaceChildren(...(options.length ? options.map((a) => el("option", { value: a.pkg, text: `${a.name} (${dur(a.s / 7)}/day)` })) : [el("option", { value: "", text: "No apps used recently" })]));
  loadHabits();
}
$("#g-goal").addEventListener("input", (e) => { $("#g-goal-v").textContent = dur(e.target.value * 60); });
$("#g-goal").addEventListener("change", (e) => save({ dailyGoalMin: Number(e.target.value) }));
$("#g-pick").addEventListener("input", (e) => { $("#g-pick-v").textContent = e.target.value; });
$("#g-pick").addEventListener("change", (e) => save({ pickupGoal: Number(e.target.value) }));
$("#g-notify").addEventListener("change", (e) => { save({ notifyLimits: e.target.checked }); if (e.target.checked && state.status.notifications === false) WP.requestNotifications(); });
$("#g-bed").addEventListener("change", (e) => { if (e.target.value) save({ bedtime: e.target.value }); });
$("#g-wake").addEventListener("change", (e) => { if (e.target.value) save({ wake: e.target.value }); });
$("#g-bed-remind").addEventListener("change", (e) => { save({ bedtimeReminder: e.target.checked }); if (e.target.checked && state.status.notifications === false) WP.requestNotifications(); });
$("#g-limit-add").addEventListener("click", () => {
  const pkg = $("#g-limit-app").value, min = Math.round(Number($("#g-limit-min").value));
  if (!pkg || !(min >= 1)) { toast("Pick an app and a number of minutes."); return; }
  save({ limits: { ...(state.settings.limits || {}), [pkg]: Math.min(600, min) } });
  if (state.status.notifications === false) WP.requestNotifications();
  loadGoals();
  toast("Limit added ✓");
});

// ---------- more ----------
function loadMore() {
  refreshStatus();
  const s = state.settings, st = state.status;
  const permBtn = (ok, fn) => (ok ? el("span", { class: "ok", text: "✓ Allowed" }) : el("button", { class: "btn primary", onclick: fn }, "Allow"));
  $("#m-usage").replaceChildren(permBtn(st.usageAccess, () => WP.openUsageAccess()));
  $("#m-notif").replaceChildren(permBtn(st.notifications, () => WP.requestNotifications()));
  const dist = new Set(s.distracting || []);
  $("#m-distracting").replaceChildren(...CATS.map((c) => {
    const cb = el("input", { type: "checkbox" });
    cb.checked = dist.has(c);
    cb.addEventListener("change", () => {
      const next = CATS.filter((x) => (x === c ? cb.checked : dist.has(x)));
      save({ distracting: next });
      loadMore();
    });
    return el("label", {}, cb, el("i", { class: "dotc", style: `background:${catColor(c)}` }), c);
  }));
  $("#m-private").value = (s.privateKeywords || []).join(", ");
  for (const b of document.querySelectorAll("#m-theme button")) b.setAttribute("aria-selected", String(b.dataset.t === (s.theme || "auto")));
  const lp = call("laptop") || {};
  $("#m-laptop").textContent = lp.paired
    ? `Also sending your phone usage to WorkPulse on ${lp.host}. Last sync: ${lp.lastSync ? new Date(lp.lastSync).toLocaleString() : "not yet"}${lp.lastError ? ` (${lp.lastError})` : ""}.`
    : "Not connected. Only needed if you also run WorkPulse on a computer; this app works fully on its own.";
  $("#m-laptop-btn").textContent = lp.paired ? "Laptop sync settings" : "Connect to a laptop";
  $("#m-version").textContent = `WorkPulse ${st.version || ""} · everything stays on this phone`;
}
$("#m-private-save").addEventListener("click", () => {
  const words = $("#m-private").value.split(/[,\n]/).map((w) => w.trim().toLowerCase()).filter(Boolean);
  save({ privateKeywords: [...new Set(words)] });
  $("#m-private-msg").textContent = "Saved. Already-recorded days were updated too.";
  setTimeout(() => { $("#m-private-msg").textContent = ""; }, 4000);
});
for (const b of document.querySelectorAll("#m-theme button")) {
  b.addEventListener("click", () => { save({ theme: b.dataset.t }); applyTheme(); loadMore(); });
}
$("#m-export").addEventListener("click", () => WP.exportCsv());
$("#m-wipe").addEventListener("click", () => {
  if (!confirm("Delete ALL WorkPulse data on this phone (history, goals, habits, focus sessions)? This can't be undone.")) return;
  call("wipe");
  state.settings = call("settings") || {};
  state.day = todayISO();
  applyTheme();
  toast("All data deleted.");
  show("today");
});
$("#m-laptop-btn").addEventListener("click", () => WP.openLaptop());

// ---------- app detail sheet ----------
function openApp(pkg) {
  const days = call("range", 14, todayISO()) || [];
  const rows = days.map((d) => ({ day: d.day, active: d.total_s > 0, a: (d.apps || []).find((x) => x.pkg === pkg) }));
  const info = rows.map((r) => r.a).filter(Boolean).pop();
  if (!info) return;
  const s = state.settings, limitMin = (s.limits || {})[pkg] || 0;
  const today = rows[rows.length - 1].a;
  const activeDays = rows.filter((r) => r.active);
  const avg = activeDays.length ? sum(activeDays, (r) => r.a?.s || 0) / activeDays.length : 0;
  $("#s-name").textContent = info.name;
  $("#s-today").textContent = dur(today?.s || 0);
  $("#s-today-sub").textContent = plural(today?.opens || 0, "open");
  $("#s-avg").textContent = dur(avg);
  $("#s-avg-sub").textContent = `${Math.round(activeDays.length ? sum(activeDays, (r) => r.a?.opens || 0) / activeDays.length : 0)} opens a day`;
  $("#s-bars").replaceChildren(dayBars(rows.map((r) => ({ day: r.day, total_s: r.a?.s || 0 })), limitMin * 60, null));
  $("#s-cat").replaceChildren(...CATS.map((c) => el("option", { value: c, text: c })));
  $("#s-cat").value = info.cat;
  $("#s-limit").value = limitMin;
  $("#s-save").onclick = () => {
    const overrides = { ...(s.categoryOverrides || {}) }, limits = { ...(s.limits || {}) };
    if ($("#s-cat").value !== info.cat) overrides[pkg] = $("#s-cat").value;
    const m = Math.round(Number($("#s-limit").value) || 0);
    if (m > 0) limits[pkg] = Math.min(600, m); else delete limits[pkg];
    save({ categoryOverrides: overrides, limits });
    if (m > 0 && state.status.notifications === false) WP.requestNotifications();
    closeSheet();
    toast("Saved ✓");
    safely(LOADERS[state.view]);
  };
  $("#sheet").hidden = false;
}
function closeSheet() { $("#sheet").hidden = true; }
$("#s-close").addEventListener("click", closeSheet);
$("#sheet").addEventListener("click", (e) => { if (e.target.id === "sheet") closeSheet(); });

// ---------- navigation ----------
const LOADERS = { today: loadToday, trends: loadTrends, focus: loadFocus, goals: loadGoals, more: loadMore };
function show(v) {
  if (!LOADERS[v]) v = "today";
  state.view = v;
  for (const b of document.querySelectorAll(".tabbar button")) b.setAttribute("aria-selected", String(b.dataset.v === v));
  for (const s of document.querySelectorAll(".view")) s.hidden = s.id !== `v-${v}`;
  window.scrollTo(0, 0);
  safely(LOADERS[v]);
}
for (const b of document.querySelectorAll(".tabbar button")) b.addEventListener("click", () => { if (b.dataset.v === "today" && state.view === "today") state.day = todayISO(); show(b.dataset.v); });
window.wpShow = show;
window.wpResume = () => {
  state.settings = call("settings") || state.settings;
  applyTheme();
  refreshStatus();
  refreshFocus();
  safely(LOADERS[state.view]);
};
window.wpBack = () => {
  if (!$("#sheet").hidden) { closeSheet(); return true; }
  if (state.view !== "today") { show("today"); return true; }
  if (state.day !== todayISO()) { state.day = todayISO(); safely(loadToday); return true; }
  return false;
};

// ---------- boot ----------
(function boot() {
  const v = new URLSearchParams(location.hash.slice(1)).get("view");
  applyTheme();
  matchMedia("(prefers-color-scheme: light)").addEventListener?.("change", applyTheme);
  refreshStatus();
  refreshFocus();
  show(v || "today");
  setInterval(() => { if (!document.hidden && state.view === "today" && state.day === todayISO() && $("#sheet").hidden) safely(loadToday); }, 60000);
})();
