/* WorkPulse dashboard, Phase 4 tabs: Goals (+ roadmap), Team, Insights, Coach.
   Uses helpers from app.js ($, el, api, dur, hm, css, catColor, kpi, showTip, hideTip, HAS_CHART, state). */
"use strict";

window.TAB_LOADERS = window.TAB_LOADERS || {};
const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body) });
const patch = (path, body) => api(path, { method: "PATCH", body: JSON.stringify(body) });
const del = (path) => api(path, { method: "DELETE" });
const niceDate = (iso) => new Date(iso + "T12:00").toLocaleDateString([], { day: "numeric", month: "short", year: "numeric" });
const shortDate = (iso) => new Date(iso + "T12:00").toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
const todayIso = () => todayISO();
function flash(msg) { showTip({ clientX: window.innerWidth / 2 - 100, clientY: 80 }, msg); setTimeout(hideTip, 2200); }
async function safely(fn) { try { await fn(); } catch (e) { flash(`⚠️ ${e.message}`); } }

// =============================== GOALS + ROADMAP ===============================
let goalFormReady = false;

async function loadGoals() {
  const [g, r] = await Promise.all([api("/api/goals?include_done=true"), api("/api/roadmap")]);
  if (!goalFormReady) {
    const sel = $("#goal-form [name=category]");
    sel.replaceChildren(el("option", { value: "", text: "Not linked" }), ...g.categories.map((c) => el("option", { value: c, text: c })));
    goalFormReady = true;
  }
  renderGoals(g.goals);
  renderRoadmap(r);
}

function renderGoals(goals) {
  $("#goals-empty").hidden = goals.length > 0;
  $("#goal-list").replaceChildren(...goals.map((g) => {
    const cb = el("input", { type: "checkbox", "aria-label": `Mark "${g.text}" done` });
    cb.checked = g.done;
    cb.addEventListener("change", () => safely(async () => { await patch(`/api/goals/${g.id}`, { done: cb.checked }); loadGoals(); }));
    const meta = el("div", { class: "g-meta" }, el("span", { class: "tag", text: g.kind }));
    if (g.category) meta.append(el("span", { class: "tag", style: `color:${catColor(g.category)}`, text: g.category }));
    if (g.deadline) meta.append(el("span", { text: `due ${niceDate(g.deadline)}` }));
    if (g.category && g.tracked_min != null) {
      meta.append(el("span", { text: `${dur(g.tracked_min * 60)} tracked${g.target_min ? ` of ${dur(g.target_min * 60)}` : ""} ${g.kind === "long-term" ? "since added" : "this " + { daily: "day", weekly: "week", monthly: "month" }[g.kind]}` }));
    }
    const body = el("div", {}, el("div", { class: "g-text", text: g.text }), meta);
    if (g.pct != null && (g.category || g.done)) body.append(el("div", { class: "g-bar", title: `${Math.round(g.pct)}%` }, el("div", { style: `width:${Math.min(100, g.pct).toFixed(1)}%` })));
    if (!g.category && !g.done) {
      const range = el("input", { type: "range", min: "0", max: "100", step: "5", "aria-label": "Progress percent" });
      range.value = g.manual_pct ?? 0;
      const label = el("span", { text: `${Math.round(g.manual_pct ?? 0)}%` });
      range.addEventListener("input", () => { label.textContent = `${range.value}%`; });
      range.addEventListener("change", () => safely(async () => { await patch(`/api/goals/${g.id}`, { manual_pct: +range.value }); loadGoals(); }));
      body.append(el("div", { class: "g-manual" }, el("span", { text: "Progress" }), range, label));
    }
    const rm = el("button", { class: "icon-btn", title: "Delete goal", "aria-label": "Delete goal", text: "✕" });
    rm.addEventListener("click", () => { if (confirm(`Delete goal "${g.text}"${g.kind === "long-term" ? " and its roadmap milestones" : ""}?`)) safely(async () => { await del(`/api/goals/${g.id}`); loadGoals(); }); });
    return el("div", { class: `goal${g.done ? " done" : ""}` }, cb, body, rm);
  }));
}

$("#goal-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const body = { text: f.get("text").trim(), kind: f.get("kind"), category: f.get("category") || null,
                 target_min: f.get("target_h") ? +f.get("target_h") * 60 : null, deadline: f.get("deadline") || null };
  safely(async () => { await post("/api/goals", body); e.target.reset(); loadGoals(); });
});

function renderRoadmap(r) {
  const lt = $("#lt-goals");
  if (!r.long_term_goals.length) {
    lt.replaceChildren(el("span", { class: "muted", text: "Add a long-term goal above (e.g. “Launch my startup”) to get coach-suggested milestones." }));
  } else {
    lt.replaceChildren(...r.long_term_goals.map((g) => {
      const b = el("button", { class: "btn", text: "✨ Suggest milestones" });
      b.addEventListener("click", () => suggestFor(g, b));
      return el("span", { class: "lt" }, el("span", { text: g.text }), b);
    }));
  }
  $("#roadmap").replaceChildren(...r.horizons.map((h) => {
    const items = h.milestones.map((m) => {
      const cb = el("input", { type: "checkbox", "aria-label": `Mark milestone done` });
      cb.checked = m.done;
      cb.addEventListener("change", () => safely(async () => { await patch(`/api/roadmap/milestones/${m.id}`, { done: cb.checked }); loadGoals(); }));
      const t = el("div", { class: "t" }, m.text);
      if (m.source === "coach") t.append(" ", el("span", { class: "tag coach", text: "coach" }));
      const rm = el("button", { class: "icon-btn", title: "Remove", "aria-label": "Remove milestone", text: "✕" });
      rm.addEventListener("click", () => safely(async () => { await del(`/api/roadmap/milestones/${m.id}`); loadGoals(); }));
      return el("div", { class: `ms${m.done ? " done" : ""}` }, cb, t, rm);
    });
    const input = el("input", { placeholder: "Add a milestone…", maxlength: "300", "aria-label": `Add milestone to ${h.label}` });
    const form = el("form", {}, input, el("button", { class: "btn", text: "Add" }));
    form.addEventListener("submit", (e) => {
      e.preventDefault();
      if (!input.value.trim()) return;
      safely(async () => { await post("/api/roadmap/milestones", { horizon: h.key, text: input.value.trim() }); loadGoals(); });
    });
    return el("div", { class: "lane" }, el("h3", { text: h.label }), el("div", { class: "until", text: `until ${niceDate(h.until)}` }),
      ...(items.length ? items : [el("div", { class: "muted", text: "Nothing here yet." })]), form);
  }));
}

async function suggestFor(goal, btn) {
  const box = $("#suggestions");
  btn.disabled = true; btn.textContent = "Thinking…";
  try {
    const r = await post("/api/roadmap/suggest", { goal_id: goal.id });
    const label = { "100d": "100 days", "6m": "6 months", "1y": "1 year" };
    const rows = r.suggestions.map((s) => {
      const add = el("button", { class: "btn", text: "Add" });
      add.addEventListener("click", () => safely(async () => {
        await post("/api/roadmap/milestones", { horizon: s.horizon, text: s.text, goal_id: goal.id, source: "coach" });
        add.replaceWith(el("span", { class: "tag", text: "added ✓" })); loadGoals();
      }));
      return el("div", { class: "sugg" }, el("span", { class: "tag", text: label[s.horizon] }), el("span", { class: "txt", text: s.text }), add);
    });
    const close = el("button", { class: "btn btn-ghost", text: "Close" });
    close.addEventListener("click", () => { box.hidden = true; });
    const addAll = el("button", { class: "btn btn-primary", text: "Add all" });
    addAll.addEventListener("click", () => safely(async () => {
      for (const s of r.suggestions) await post("/api/roadmap/milestones", { horizon: s.horizon, text: s.text, goal_id: goal.id, source: "coach" });
      box.hidden = true; loadGoals();
    }));
    box.replaceChildren(
      el("h3", { text: `Suggested milestones for “${goal.text}”` }),
      el("p", { class: "muted", text: r.source === "coach" ? "Written by your AI coach. Keep what fits." : "Starter template (AI coach is off: add ANTHROPIC_API_KEY to .env for tailored ones)." }),
      ...rows, el("div", { class: "row", style: "margin-top:10px" }, addAll, close));
    box.hidden = false;
  } catch (e) { flash(`⚠️ ${e.message}`); }
  btn.disabled = false; btn.textContent = "✨ Suggest milestones";
}

// =============================== TEAM ===============================
async function loadTeam() {
  const t = await api("/api/team");
  const c = t.collaboration;
  const open = t.tasks.filter((x) => x.status !== "done");
  const overdue = open.filter((x) => x.due && x.due < todayIso());
  const meetSecs = t.meetings.reduce((s, m) => s + m.minutes * 60, 0);
  $("#team-kpis").replaceChildren(
    kpi("Collaboration (7 days)", `${Math.round(c.share * 100)}%`, `meetings ${dur(c.meeting_s)} + chat apps ${dur(c.communication_s)}`),
    kpi("Open tasks", `${open.length}`, overdue.length ? el("span", { class: "delta-down", text: `${overdue.length} overdue` }) : "none overdue"),
    kpi("Meetings (30 days)", dur(meetSecs), `${t.meetings.length} logged`),
    kpi("People", `${t.members.length}`, t.members.length ? t.members.map((m) => m.name).slice(0, 3).join(", ") : "add your team below"),
  );
  $("#task-form [name=owner]").replaceChildren(el("option", { value: "me", text: "Me" }), ...t.members.map((m) => el("option", { value: m.name, text: m.name })));
  renderBoard(t.tasks);
  renderMembers(t.members);
  renderMeetings(t.meetings);
}

function renderBoard(tasks) {
  const cols = [["todo", "To do"], ["doing", "Doing"], ["done", "Done (7 days)"]];
  const order = cols.map((c) => c[0]);
  $("#board").replaceChildren(...cols.map(([key, label]) => {
    const items = tasks.filter((t) => t.status === key);
    return el("div", { class: "col" }, el("h3", {}, el("span", { text: label }), el("span", { text: `${items.length}` })),
      ...items.map((t) => {
        const due = !t.due ? null : t.due < todayIso() && key !== "done" ? el("span", { class: "overdue", text: `overdue · ${shortDate(t.due)}` })
          : t.due === todayIso() && key !== "done" ? el("span", { class: "today", text: "due today" }) : el("span", { text: shortDate(t.due) });
        const btns = el("span", {});
        const i = order.indexOf(key);
        const mk = (txt, title, fn) => { const b = el("button", { class: "icon-btn", title, "aria-label": title, text: txt }); b.addEventListener("click", fn); return b; };
        if (i > 0) btns.append(mk("←", `Move to ${cols[i - 1][1]}`, () => safely(async () => { await patch(`/api/tasks/${t.id}`, { status: order[i - 1] }); loadTeam(); })));
        if (i < 2) btns.append(mk("→", `Move to ${cols[i + 1][1]}`, () => safely(async () => { await patch(`/api/tasks/${t.id}`, { status: order[i + 1] }); loadTeam(); })));
        btns.append(mk("✕", "Delete task", () => { if (confirm(`Delete task "${t.text}"?`)) safely(async () => { await del(`/api/tasks/${t.id}`); loadTeam(); }); }));
        return el("div", { class: "tcard" }, el("div", { class: "t", text: t.text }),
          el("div", { class: "meta" }, el("span", {}, el("b", { text: t.owner === "me" ? "You" : t.owner }), ...(due ? [" · ", due] : [])), btns));
      }));
  }));
}

function renderMembers(members) {
  $("#members").replaceChildren(...(members.length ? members.map((m) => {
    const rm = el("button", { class: "icon-btn", title: `Remove ${m.name}`, "aria-label": `Remove ${m.name}`, text: "✕" });
    rm.addEventListener("click", () => { if (confirm(`Remove ${m.name} from the team? Their tasks stay.`)) safely(async () => { await del(`/api/team/members/${m.id}`); loadTeam(); }); });
    const who = el("div", { class: "who" }, el("b", { text: m.name }), m.role ? ` · ${m.role}` : "", m.contact ? el("div", { class: "muted", text: m.contact }) : "");
    return el("div", { class: "member" }, who, el("span", { class: "muted", text: m.open_tasks ? `${m.open_tasks} open` : "" }), rm);
  }) : [el("p", { class: "muted", text: "No one yet: add hackathon teammates, cofounders, study buddies." })]));
}

function renderMeetings(meetings) {
  $("#meetings").replaceChildren(...(meetings.length ? meetings.map((m) => {
    const rm = el("button", { class: "icon-btn", title: "Delete meeting", "aria-label": "Delete meeting", text: "✕" });
    rm.addEventListener("click", () => safely(async () => { await del(`/api/meetings/${m.id}`); loadTeam(); }));
    const when = new Date(m.start_ts * 1000).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
    return el("div", { class: "meeting" }, el("span", {}, el("b", { text: m.title }), el("span", { class: "muted", text: ` · ${when} · ${dur(m.minutes * 60)}${m.attendees.length ? " · " + m.attendees.join(", ") : ""}` })), rm);
  }) : [el("p", { class: "muted", text: "Log standups, calls and pitch prep here (or WhatsApp: meeting 45 standup @Riya)." })]));
}

$("#task-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  safely(async () => { await post("/api/tasks", { text: f.get("text").trim(), owner: f.get("owner") || "me", due: f.get("due") || null }); e.target.reset(); loadTeam(); });
});
$("#member-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  safely(async () => { await post("/api/team/members", { name: f.get("name").trim(), role: f.get("role").trim() || null, contact: f.get("contact").trim() || null }); e.target.reset(); loadTeam(); });
});
$("#meeting-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  const attendees = (f.get("attendees") || "").split(",").map((x) => x.trim().replace(/^@/, "")).filter(Boolean);
  safely(async () => { await post("/api/meetings", { title: f.get("title").trim(), minutes: +f.get("minutes"), attendees, when: f.get("when") || null }); e.target.reset(); loadTeam(); });
});

// =============================== INSIGHTS ===============================
async function loadInsights() {
  const r = await api("/api/insights");
  const list = (items, empty) => items.length ? items.map((i) => el("li", { text: i.text })) : [el("li", { class: "muted", text: empty })];
  $("#ins-best").replaceChildren(...list(r.best, "Not enough data yet. Give it a few days of tracking."));
  $("#ins-improve").replaceChildren(...list(r.improve, "Nothing obvious to fix yet 🎉"));
  const p = r.profile;

  const prodColor = css("--series-1"), entColor = css("--series-7");
  $("#hours-legend").replaceChildren(
    el("span", {}, el("i", { class: "swatch", style: `background:${prodColor}` }), "Productive"),
    el("span", {}, el("i", { class: "swatch", style: `background:${entColor}` }), "Entertainment"));
  if (HAS_CHART) {
    state.charts.hours?.destroy();
    state.charts.hours = new Chart($("#hours-chart"), {
      type: "bar",
      data: { labels: p.hours.map((h) => String(h.hour).padStart(2, "0")), datasets: [
        { label: "Productive", data: p.hours.map((h) => +h.productive_min.toFixed(1)), backgroundColor: prodColor, borderRadius: { topLeft: 4, topRight: 4 }, maxBarThickness: 18 },
        { label: "Entertainment", data: p.hours.map((h) => +h.entertainment_min.toFixed(1)), backgroundColor: entColor, borderRadius: { topLeft: 4, topRight: 4 }, maxBarThickness: 18 }] },
      options: { maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        scales: { x: { grid: { display: false }, title: { display: true, text: "hour of day" } }, y: { title: { display: true, text: "min / day" }, grid: { color: css("--grid") } } },
        plugins: { legend: { display: false }, tooltip: { callbacks: { title: (it) => `${it[0].label}:00–${it[0].label}:59`, label: (ctx) => ` ${ctx.dataset.label}: ${ctx.raw} min/day` } } } },
    });
    state.charts.weekday?.destroy();
    state.charts.weekday = new Chart($("#weekday-chart"), {
      type: "bar",
      data: { labels: p.weekdays.map((w) => w.weekday), datasets: [{ label: "Avg productive", data: p.weekdays.map((w) => +(w.avg_productive_s / 3600).toFixed(2)), backgroundColor: prodColor, borderRadius: { topLeft: 4, topRight: 4 }, maxBarThickness: 40 }] },
      options: { maintainAspectRatio: false, scales: { x: { grid: { display: false } }, y: { title: { display: true, text: "hours" }, grid: { color: css("--grid") } } },
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (ctx) => ` ${dur(ctx.raw * 3600)} productive on average` } } } },
    });
  }

  const max = Math.max(1, ...p.sources.map((s) => s.seconds));
  const total = p.sources.reduce((a, s) => a + s.seconds, 0) || 1;
  $("#sources").replaceChildren(...(p.sources.length ? p.sources.map((s) => el("div", { class: "bar-row" },
    el("span", { class: "name", text: s.name }),
    el("div", { class: "bar-track" }, el("div", { class: "bar-fill", style: `width:${(100 * s.seconds / max).toFixed(1)}%;background:${entColor}` })),
    el("span", { class: "num", text: `${dur(s.seconds)} · ${Math.round(100 * s.seconds / total)}%` }))) : [el("p", { class: "muted", text: "No browsing or entertainment time tracked." })]));

  const level = (h) => h <= 0 ? "" : h < 1 ? "l1" : h < 2 ? "l2" : h < 3 ? "l3" : h < 5 ? "l4" : "l5";
  $("#calendar").replaceChildren(...p.calendar.map((d) => {
    const hrs = d.productive_s / 3600;
    const cell = el("div", { class: `day ${level(hrs)}`, text: String(new Date(d.date + "T12:00").getDate()), "aria-label": `${d.date}: ${dur(d.productive_s)} productive` });
    cell.addEventListener("mousemove", (e) => showTip(e, shortDate(d.date), d.active_s ? `${dur(d.productive_s)} productive · ${dur(d.active_s)} active · score ${d.focus_score}` : "nothing tracked"));
    cell.addEventListener("mouseleave", hideTip);
    return cell;
  }));
  $("#cal-legend").replaceChildren(...[["", "0"], ["l1", "<1h"], ["l2", "1–2h"], ["l3", "2–3h"], ["l4", "3–5h"], ["l5", "5h+"]].map(([cls, txt]) =>
    el("span", {}, el("i", { class: "swatch", style: cls ? `background:var(--seq-${cls[1]})` : "background:var(--surface-2);outline:1px solid var(--border)" }), txt)));
}

// =============================== COACH ===============================
const KIND_LABEL = { morning: "☀️ morning report", midday: "🕐 midday check", night: "🌙 night report", weekly: "📅 weekly review",
                     reminder: "⏰ reminder", test: "test" };
function waFormat(text) {
  const esc = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");  // escape FIRST
  return esc.replace(/\*([^*\n]+)\*/g, "<b>$1</b>").replace(/(^|[\s(])_([^_\n]+)_(?=$|[\s).,!?])/gm, "$1<i>$2</i>");
}
let lastThreadKey = "";

function bubble(m) {
  const meta = el("div", { class: "meta" }, el("span", { text: new Date(m.ts * 1000).toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit", hour12: false }) }));
  const kind = KIND_LABEL[m.kind] || (m.kind.startsWith("nudge") ? "👋 nudge" : null);
  if (kind) meta.append(el("span", { class: "tag", text: kind }));
  if (m.status === "local") meta.append(el("span", { class: "tag", title: "Typed in the dashboard or terminal; not sent to WhatsApp", text: "this laptop" }));
  else if (m.status === "app") meta.append(el("span", { class: "tag", title: "Typed in the phone app; not sent to WhatsApp", text: "phone app" }));
  else if (m.direction === "in") meta.append(el("span", { class: "tag", text: "WhatsApp" }));
  if (m.status === "dry-run") meta.append(el("span", { class: "tag", title: "WhatsApp isn't configured yet, so this was logged, not sent", text: "not sent (dry run)" }));
  if (m.status === "failed") meta.append(el("span", { class: "tag", style: "color:var(--bad)", title: m.error || "", text: "failed" }));
  const body = el("div", {});
  body.innerHTML = waFormat(m.body);
  return el("div", { class: `bubble ${m.direction}` }, meta, body);
}

async function loadCoach(force = false) {
  const r = await api("/api/messages?limit=120");
  const key = r.messages.map((m) => m.id).join(",");
  if (!force && key === lastThreadKey) return;
  lastThreadKey = key;
  const thread = $("#thread");
  thread.replaceChildren(...(r.messages.length ? r.messages.map(bubble)
    : [el("div", { class: "bubble out" }, el("div", { text: "Hi! 👋 I'm your WorkPulse coach. Ask me anything about your day, or tap a shortcut below." }))]));
  thread.scrollTop = thread.scrollHeight;
}

const QUICK = ["today", "plan", "best", "improve", "goals", "roadmap", "tasks", "week", "help"];
$("#quick").replaceChildren(...QUICK.map((q) => { const b = el("button", { type: "button", text: q }); b.addEventListener("click", () => sendChat(q)); return b; }));

async function sendChat(text) {
  text = text.trim();
  if (!text) return;
  const thread = $("#thread"), input = $("#chat-input"), send = $("#chat-send");
  thread.append(bubble({ ts: Date.now() / 1000, direction: "in", kind: "chat", body: text, status: "local" }));
  const typing = el("div", { class: "bubble out typing", text: "Coach is thinking…" });
  thread.append(typing);
  thread.scrollTop = thread.scrollHeight;
  input.value = ""; send.disabled = true;
  try { await post("/api/chat", { text }); } catch (e) { typing.textContent = `⚠️ ${e.message}`; send.disabled = false; return; }
  send.disabled = false;
  await loadCoach(true);
  input.focus();
}
$("#chat-form").addEventListener("submit", (e) => { e.preventDefault(); sendChat($("#chat-input").value); });

// =============================== wiring ===============================
Object.assign(window.TAB_LOADERS, { goals: loadGoals, team: loadTeam, insights: loadInsights, coach: () => loadCoach(true) });
if (window.TAB_LOADERS[state.tab]) window.TAB_LOADERS[state.tab]();  // page opened directly on one of these tabs
setInterval(() => { if (typeof state !== "undefined" && state.tab === "coach" && !document.hidden) loadCoach(); }, 15000);
