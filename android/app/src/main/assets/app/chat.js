/* WorkPulse coach chat. Commands (today, week, limit…) are answered right here on the phone, instantly and offline.
   Anything else goes to the AI coach (Google Gemini, with your own API key) together with a short summary of your stats.
   Uses helpers from app.js (call, WP, state, dur, score, todayISO, …). */
"use strict";

const CHAT_KEY = "chat";
let chat = (call("getData", CHAT_KEY) || []).filter((m) => !m.pending);
let coachOn = !!(call("coachStatus") || {}).hasKey;

function saveChat() {
  chat = chat.slice(-200);
  WP.setData(CHAT_KEY, JSON.stringify(chat.filter((m) => !m.pending)));
}
function fmtMsg(text) {  // escape FIRST, then *bold* / _italic_
  return esc(text).replace(/\*([^*\n]+)\*/g, "<b>$1</b>").replace(/(^|[\s(])_([^_\n]+)_(?=$|[\s).,!?])/gm, "$1<i>$2</i>");
}

function renderChat() {
  const box = $("#c-msgs");
  if (!chat.length) {
    box.replaceChildren(el("div", { class: "msg bot", html: fmtMsg(
      "Hi! 👋 I'm your WorkPulse coach.\n\nAsk me how your day is going, or tap a button below. Try *today*, *week*, *improve*, *plan*, " +
      "*limit instagram 30* or *focus 25*. Type *help* for everything I can do." +
      (coachOn ? "\n\nYou can also ask me anything in your own words." : "\n\nFor questions in your own words, turn on the AI coach in More → AI coach.")) }));
  } else {
    box.replaceChildren(...chat.map((m) => el("div", { class: `msg ${m.role === "user" ? "me" : "bot"}${m.error ? " err" : ""}${m.pending ? " typing" : ""}`,
      html: m.pending ? "<span></span><span></span><span></span>" : fmtMsg(m.text) },
      m.ai && !m.pending ? el("div", { class: "msg-tag", text: "AI coach" }) : null)));
  }
  $("#c-ai").textContent = coachOn ? "AI coach on" : "Commands only";
  $("#c-ai").className = `pill small ${coachOn ? "on" : ""}`;
  requestAnimationFrame(() => window.scrollTo(0, document.body.scrollHeight));
}

function addMsg(role, text, extra = {}) {
  const m = { role, text, t: Date.now(), ...extra };
  chat.push(m);
  saveChat();
  renderChat();
  return m;
}

// ---------- data helpers ----------
const recent = (n) => call("range", n, todayISO()) || [];
function appTotals(days) {
  const apps = {};
  for (const d of days) for (const a of d.apps || []) {
    if (a.pkg === "private") continue;
    const x = (apps[a.pkg] ||= { pkg: a.pkg, name: a.name, cat: a.cat, s: 0, opens: 0 });
    x.s += a.s; x.opens += a.opens || 0;
  }
  return Object.values(apps).sort((a, b) => b.s - a.s);
}
function findApp(query, days = recent(14)) {
  const q = query.trim().toLowerCase();
  const apps = appTotals(days);
  return apps.find((a) => a.name.toLowerCase() === q) || apps.find((a) => a.name.toLowerCase().includes(q))
    || apps.find((a) => a.pkg.toLowerCase().includes(q.replace(/\s+/g, "")));
}
function parseMinutes(num, unit) {
  const n = Number(num);
  return /^h/.test(unit || "") ? Math.round(n * 60) : Math.round(n);
}
const habitsGet = () => call("getData", "habits") || [];
const habitsSet = (h) => WP.setData("habits", JSON.stringify(h));
function avgActive(days) { const a = days.filter((d) => d.total_s > 0); return a.length ? sum(a, (d) => d.total_s) / a.length : 0; }

// ---------- commands ----------
function cmdHelp() {
  return [
    "Here's what I can do right away (works offline):",
    "- *today* / *yesterday*: how the day went",
    "- *week*: last 7 days vs the week before",
    "- *best*: your best recent day",
    "- *improve*: tips from your own numbers",
    "- *plan*: a plan for the rest of today",
    "- *apps*: your top apps today",
    "- *limit instagram 30* / *limits* / *remove limit instagram*",
    "- *goal 2h*: daily screen-time goal",
    "- *focus 25* (+ what) / *stop*: focus timer",
    "- *bedtime 23:00*: bedtime reminder",
    "- *habits* / *habit add read 20 min* / *done read*",
    coachOn ? "\nAnything else, just ask in your own words. 🤖" : "\nWant answers to any question? Turn on the AI coach in More → AI coach.",
  ].join("\n");
}

function daySummary(day) {
  const d = call("day", day), s = state.settings, label = dayName(day).toLowerCase();
  if (!d || !d.total_s) return `No phone use recorded ${label === "today" ? "yet today" : `for ${label}`}. 📭`;
  const T = d.total_s, goal = (s.dailyGoalMin || 180) * 60, sc = score(d, s);
  const top = (d.apps || []).filter((a) => a.pkg !== "private").slice(0, 3);
  const worst = [...sc.parts].sort((a, b) => b.lost - a.lost)[0];
  const lines = [
    `📱 *${dayName(day)}*: ${dur(T)} on your phone (${T > goal ? `${dur(T - goal)} over` : `${dur(goal - T)} left of`} your ${dur(goal)} goal)`,
    `⚖️ Balance score *${sc.score}*/100 · ${d.pickups || 0} pickups`,
  ];
  if (top.length) lines.push(`🔝 ${top.map((a) => `${a.name} ${dur(a.s)}`).join(" · ")}`);
  if (T >= 600) lines.push(`🎯 ${Math.round(((d.distracting_s || 0) / T) * 100)}% on distracting apps`);
  if (worst && worst.lost > 0) lines.push(`💡 Biggest drag on your score: ${worst.label.charAt(0).toLowerCase()}${worst.label.slice(1)}.`);
  else lines.push("💪 Nothing dragging your score down. Keep it up!");
  return lines.join("\n");
}

function cmdWeek() {
  const all = recent(14), cur = all.slice(-7), prev = all.slice(0, 7);
  const active = cur.filter((d) => d.total_s > 0);
  if (!active.length) return "No phone use recorded in the last 7 days yet.";
  const avg = avgActive(cur), pavg = avgActive(prev), p = pct(avg, pavg), goal = (state.settings.dailyGoalMin || 180) * 60;
  const full = active.filter((d) => d.day !== todayISO());
  const best = full.length ? full.reduce((a, b) => (b.total_s < a.total_s ? b : a)) : null;
  const top = appTotals(active).slice(0, 3);
  return [
    `📊 *Last 7 days*: ${dur(avg)} a day on average${p == null ? "" : ` (${p > 0 ? "▲" : "▼"} ${Math.abs(p)}% vs the week before)`}`,
    `✅ Within your ${dur(goal)} goal on ${active.filter((d) => d.total_s <= goal).length} of ${active.length} days`,
    best ? `🏆 Best day: ${dayName(best.day)} with ${dur(best.total_s)}` : null,
    top.length ? `🔝 ${top.map((a) => `${a.name} ${dur(a.s / active.length)}/day`).join(" · ")}` : null,
    `📲 ${Math.round(sum(active, (d) => d.pickups || 0) / active.length)} pickups a day`,
  ].filter(Boolean).join("\n");
}

function cmdBest() {
  const days = recent(30).filter((d) => d.total_s > 0 && d.day !== todayISO());
  if (!days.length) return "I need at least one full day of data first. Check back tomorrow! 🌅";
  const best = days.reduce((a, b) => (score(b, state.settings).score > score(a, state.settings).score || (score(b, state.settings).score === score(a, state.settings).score && b.total_s < a.total_s) ? b : a));
  const sc = score(best, state.settings), top = (best.apps || []).find((a) => a.pkg !== "private");
  return `🏆 Your best recent day: *${dayName(best.day, true)}*\n${dur(best.total_s)} on the phone, balance score *${sc.score}*, ${best.pickups || 0} pickups.` +
    (top ? `\nTop app that day: ${top.name} (${dur(top.s)}).` : "") + "\nLet's make today look like that. 💪";
}

function cmdImprove() {
  const s = state.settings, days = recent(7).filter((d) => d.total_s > 0);
  if (!days.length) return "Use your phone as usual for a day and I'll have real tips for you. 🙂";
  const n = days.length, tips = [], limits = s.limits || {}, dist = new Set(s.distracting || []);
  const goal = (s.dailyGoalMin || 180) * 60, avg = sum(days, (d) => d.total_s) / n;
  const topDist = appTotals(days).find((a) => dist.has(a.cat) && !limits[a.pkg] && a.s / n >= 1800);
  if (topDist) tips.push(`- ${topDist.name} takes ${dur(topDist.s / n)} a day. Set a limit: *limit ${topDist.name.toLowerCase()} ${Math.max(15, Math.round(topDist.s / n / 60 / 2 / 5) * 5)}*`);
  const pk = sum(days, (d) => d.pickups || 0) / n;
  if (pk > (s.pickupGoal || 60)) tips.push(`- You pick up your phone ~${Math.round(pk)} times a day (goal ${s.pickupGoal || 60}). Put it in another room for one block: *focus 25*`);
  const night = sum(days, (d) => nightSeconds(d, s)) / n;
  if (night >= 900) tips.push(`- ${dur(night)} a day during bedtime hours. ${s.bedtimeReminder ? "Charge it outside the bedroom tonight." : `Turn on the reminder: *bedtime ${s.bedtime || "23:00"}*`}`);
  if (avg > goal) tips.push(`- You average ${dur(avg)}, ${dur(avg - goal)} over your goal. Try one phone-free hour after dinner.`);
  if (!tips.length) return "Honestly? You're doing great. 🌟 Under your goal, few pickups, calm nights. Maybe start a habit: *habit add read 20 min*";
  return `Here's what would help most (from your last ${n} day${n > 1 ? "s" : ""}):\n${tips.slice(0, 4).join("\n")}`;
}

function cmdApps() {
  const d = call("day", todayISO()), limits = state.settings.limits || {};
  const apps = (d.apps || []).filter((a) => a.pkg !== "private").slice(0, 5);
  if (!apps.length) return "No app use yet today.";
  return "📱 *Top apps today*\n" + apps.map((a, i) => `${i + 1}. ${a.name}: ${dur(a.s)}, ${plural(a.opens || 0, "open")}` +
    (limits[a.pkg] ? ` (limit ${dur(limits[a.pkg] * 60)}${a.s >= limits[a.pkg] * 60 ? " ⚠️ over" : ""})` : "")).join("\n");
}

function cmdLimits() {
  const limits = state.settings.limits || {}, today = call("day", todayISO()), apps = appTotals(recent(14));
  const keys = Object.keys(limits);
  if (!keys.length) return "No app limits yet. Add one like *limit instagram 30*.";
  return "⏳ *Your limits*\n" + keys.map((pkg) => {
    const used = (today.apps || []).find((a) => a.pkg === pkg)?.s || 0;
    return `- ${apps.find((a) => a.pkg === pkg)?.name || pkg.split(".").pop()}: ${dur(used)} of ${dur(limits[pkg] * 60)} today`;
  }).join("\n");
}

function cmdLimit(m) {
  const app = findApp(m[1]);
  if (!app) return `I couldn't find an app called "${m[1]}" in the last 2 weeks. Check the name in *apps*.`;
  const min = Math.min(600, Math.max(1, parseMinutes(m[2], m[3])));
  save({ limits: { ...(state.settings.limits || {}), [app.pkg]: min } });
  if (state.status.notifications === false) WP.requestNotifications();
  return `⏳ Done: *${app.name}* is limited to ${dur(min * 60)} a day. I'll nudge you at 80% and when you hit it.`;
}

function cmdUnlimit(m) {
  const limits = { ...(state.settings.limits || {}) }, app = findApp(m[2]);
  if (!app || !limits[app.pkg]) return `There's no limit on "${m[2]}". See *limits*.`;
  delete limits[app.pkg];
  save({ limits });
  return `Removed the limit on *${app.name}*.`;
}

function cmdGoal(m) {
  const min = Math.min(720, Math.max(30, parseMinutes(m[1], m[2] || (Number(m[1]) <= 12 ? "h" : "m"))));
  save({ dailyGoalMin: min });
  return `🎯 New daily screen-time goal: *${dur(min * 60)}*.`;
}

function cmdHabits() {
  const hs = habitsGet(), today = todayISO();
  if (!hs.length) return "No habits yet. Add one: *habit add read 20 min*";
  return "✅ *Habits*\n" + hs.map((h) => `- ${(h.done || []).includes(today) ? "☑️" : "⬜"} ${h.name}${streakOf(new Set(h.done || [])) ? ` 🔥 ${streakOf(new Set(h.done || []))}` : ""}`).join("\n") +
    "\nMark one done: *done <name>*";
}
function cmdHabitAdd(m) {
  const name = m[1].trim().slice(0, 40), hs = habitsGet();
  if (hs.some((h) => h.name.toLowerCase() === name.toLowerCase())) return `You already have "${name}".`;
  hs.push({ id: Date.now(), name: name.charAt(0).toUpperCase() + name.slice(1), done: [] });
  habitsSet(hs);
  return `New habit: *${hs[hs.length - 1].name}*. Tick it off with *done ${name.split(" ")[0].toLowerCase()}*.`;
}
function cmdHabitDone(m) {
  const q = m[1].trim().toLowerCase(), hs = habitsGet(), today = todayISO();
  const h = hs.find((x) => x.name.toLowerCase() === q) || hs.find((x) => x.name.toLowerCase().includes(q));
  if (!h) return hs.length ? `No habit matches "${m[1]}". See *habits*.` : "No habits yet. Add one: *habit add read 20 min*";
  h.done = [...new Set([...(h.done || []), today])].sort();
  habitsSet(hs);
  const st = streakOf(new Set(h.done));
  return `☑️ *${h.name}* done for today!${st > 1 ? ` That's a ${st}-day streak 🔥` : ""}`;
}

function cmdFocus(m) {
  const fs = call("focus") || {};
  if (fs.active) return `You're already focusing (${mmss((fs.active.end - Date.now()) / 1000)} left). Type *stop* to end it.`;
  const min = Math.min(240, Math.max(1, Number(m[1] || 25)));
  if (state.status.notifications === false) WP.requestNotifications();
  call("focusStart", min, (m[2] || "").trim());
  refreshFocus();
  return `⏱️ Focus started: *${min} min*${m[2] ? ` on ${m[2].trim()}` : ""}. Put the phone down 📵 I'll tell you when it's done, and whether you got distracted.`;
}
function cmdStop() {
  const s = call("focusStop");
  refreshFocus();
  if (!s || !s.start) return "No focus session is running. Start one with *focus 25*.";
  const d = s.distractions || [];
  return `⏹ Stopped after ${dur((s.end - s.start) / 1000)} of ${s.planned_min} min. ` +
    (d.length ? `Distractions: ${d.slice(0, 3).map((x) => `${x.name} (${x.opens}×)`).join(", ")}.` : "No distracting apps opened. 🎯");
}

function cmdBedtime(m) {
  let h = Number(m[1]);
  const min = Number(m[2] || 0);
  if (m[3] === "pm" && h < 12) h += 12;
  if (m[3] === "am" && h === 12) h = 0;
  if (h > 23 || min > 59) return "That doesn't look like a time. Try *bedtime 23:00* or *bedtime 11pm*.";
  const t = `${String(h).padStart(2, "0")}:${String(min).padStart(2, "0")}`;
  save({ bedtime: t, bedtimeReminder: true });
  if (state.status.notifications === false) WP.requestNotifications();
  return `🌙 Bedtime set to *${t}*. If you're still on your phone after that, I'll remind you.`;
}

function cmdPlan() {
  const s = state.settings, d = call("day", todayISO()) || {}, T = d.total_s || 0, goal = (s.dailyGoalMin || 180) * 60;
  const lines = ["🗓️ *Plan for the rest of today*"];
  lines.push(T < goal ? `- You have ${dur(goal - T)} of phone time left in your ${dur(goal)} goal. Spend it on purpose.` : `- You're ${dur(T - goal)} over your goal: phone-light from here.`);
  const fs = (call("focus") || {}).sessions || [];
  if (!fs.some((x) => iso(new Date(x.start)) === todayISO())) lines.push("- One deep-work block, phone in another room: *focus 25*");
  const limits = s.limits || {};
  const near = (d.apps || []).filter((a) => limits[a.pkg] && a.s >= limits[a.pkg] * 60 * 0.7);
  for (const a of near.slice(0, 2)) lines.push(`- ${a.name}: ${a.s >= limits[a.pkg] * 60 ? "limit reached, done for today" : `${dur(limits[a.pkg] * 60 - a.s)} left`}`);
  const todo = habitsGet().filter((h) => !(h.done || []).includes(todayISO()));
  if (todo.length) lines.push(`- Habits still open: ${todo.map((h) => h.name).join(", ")}`);
  lines.push(`- Phone down at ${s.bedtime || "23:00"} 🌙`);
  return lines.join("\n");
}

function cmdScore() {
  const d = call("day", todayISO()), sc = score(d, state.settings);
  return `⚖️ *Balance score ${sc.score}/100* today. It starts at 100 and loses points for:\n` +
    sc.parts.map((p) => `- ${p.label}: ${p.lost ? `−${p.lost}` : "✓"}`).join("\n");
}

const COMMANDS = [
  [/^(help|commands|menu|\?)$/, cmdHelp],
  [/^(today|status|now|how am i doing( today)?)$/, () => daySummary(todayISO())],
  [/^yesterday$/, () => daySummary(shiftISO(todayISO(), -1))],
  [/^(week|this week|last week|7 days)$/, cmdWeek],
  [/^(best|best day)$/, cmdBest],
  [/^(improve|tips?|advice)$/, cmdImprove],
  [/^(apps|top|top apps)$/, cmdApps],
  [/^limits$/, cmdLimits],
  [/^limit (.+?) (\d+(?:\.\d+)?)\s*(m|min|mins|minutes|h|hr|hrs|hour|hours)?$/, cmdLimit],
  [/^(remove limit|unlimit|no limit)(?: on)? (.+)$/, cmdUnlimit],
  [/^goal (\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|m|min|mins|minutes)?$/, cmdGoal],
  [/^habits$/, cmdHabits],
  [/^(?:habit add|add habit|new habit) (.+)$/, cmdHabitAdd],
  [/^(?:done|did|habit done) (.+)$/, cmdHabitDone],
  [/^focus(?: (\d+)\s*(?:m|min|mins|minutes)?)?(?: (?:on )?(.+))?$/, cmdFocus],
  [/^(stop|stop focus|end focus)$/, cmdStop],
  [/^bedtime (\d{1,2})(?:[:.](\d{2}))?\s*(am|pm)?$/, cmdBedtime],
  [/^(plan|plan my day|my plan)$/, cmdPlan],
  [/^(score|balance|balance score)$/, cmdScore],
];

/** Answer a non-command without the AI: point at what the question seems to be about. */
function offlineAnswer(text) {
  const t = text.toLowerCase();
  const app = appTotals(recent(7)).find((a) => t.includes(a.name.toLowerCase()) && a.name.length >= 3);
  let ans;
  if (app) {
    const n = recent(7).filter((d) => d.total_s > 0).length || 1;
    ans = `📱 *${app.name}*: ${dur(app.s / n)} a day on average this week, opened ~${Math.round(app.opens / n)} times a day.` +
      `\nWant a limit? *limit ${app.name.toLowerCase()} 30*`;
  } else if (/sleep|night|bed|late/.test(t)) ans = `🌙 Your bedtime is set to ${state.settings.bedtime}. Change it with *bedtime 23:00*.\n${daySummary(todayISO()).split("\n")[0]}`;
  else if (/focus|study|concentrat|distract|work/.test(t)) ans = "🎯 Try a focus block with the phone out of reach: *focus 25*. Afterwards I'll tell you if you opened distracting apps.";
  else if (/hi\b|hello|hey|yo\b/.test(t)) ans = `Hey! 👋 ${daySummary(todayISO())}`;
  else ans = `I didn't catch that. ${cmdHelp().split("\n")[0]} Type *help* for the list.`;
  return ans + (coachOn ? "" : "\n\n_For answers to any question in your own words, turn on the AI coach in More → AI coach._");
}

/** The stats summary the AI coach gets (numbers only; private apps are never included). */
function buildFacts() {
  const s = state.settings, days = recent(14), today = days[days.length - 1] || {}, cur = days.slice(-7), prev = days.slice(0, 7);
  const sc = score(today, s), now = new Date();
  const top = (d) => (d.apps || []).filter((a) => a.pkg !== "private").slice(0, 6).map((a) => `${a.name} ${dur(a.s)} (${a.opens || 0} opens, ${a.cat})`).join(", ") || "none";
  const lines = [
    `now: ${now.toLocaleString([], { weekday: "long", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}`,
    `today so far: screen time ${dur(today.total_s)} (daily goal ${dur((s.dailyGoalMin || 180) * 60)}), ${today.pickups || 0} pickups (goal ${s.pickupGoal || 60}), balance score ${sc.score}/100`,
    `today score breakdown: ${sc.parts.map((p) => `${p.label} ${p.lost ? `-${p.lost}` : "ok"}`).join("; ")}`,
    `today first pickup: ${today.first_pickup ? clock(today.first_pickup) : "n/a"}; longest stretch: ${today.longest ? `${dur(today.longest.s)} in ${today.longest.name}` : "n/a"}`,
    `today by category: ${Object.entries(today.cats || {}).sort((a, b) => b[1] - a[1]).map(([c, v]) => `${c} ${dur(v)}`).join(", ") || "none"}`,
    `today top apps: ${top(today)}`,
  ];
  const y = days[days.length - 2];
  if (y && y.total_s) lines.push(`yesterday: ${dur(y.total_s)}, ${y.pickups || 0} pickups, score ${score(y, s).score}; top apps: ${top(y)}`);
  const avg = avgActive(cur), pavg = avgActive(prev), act = cur.filter((d) => d.total_s > 0);
  lines.push(`last 7 days: average ${dur(avg)}/day over ${act.length} days with data${pavg ? `, previous 7 days ${dur(pavg)}/day` : ""}; ` +
    `average pickups ${act.length ? Math.round(sum(act, (d) => d.pickups || 0) / act.length) : 0}/day; days within goal ${act.filter((d) => d.total_s <= (s.dailyGoalMin || 180) * 60).length}/${act.length}`);
  lines.push(`last 7 days top apps (per day): ${appTotals(act).slice(0, 6).map((a) => `${a.name} ${dur(a.s / Math.max(1, act.length))}`).join(", ") || "none"}`);
  lines.push(`bedtime ${s.bedtime}, wake ${s.wake}, reminder ${s.bedtimeReminder ? "on" : "off"}; bedtime-hours use today ${dur(nightSeconds(today, s))}`);
  lines.push(`distracting categories: ${(s.distracting || []).join(", ")}`);
  const limits = s.limits || {}, names = appTotals(days);
  lines.push(`app limits: ${Object.entries(limits).map(([pkg, m]) => {
    const used = (today.apps || []).find((a) => a.pkg === pkg)?.s || 0;
    return `${names.find((a) => a.pkg === pkg)?.name || pkg.split(".").pop()} ${dur(m * 60)} (used ${dur(used)} today)`;
  }).join(", ") || "none"}`);
  const hs = habitsGet();
  lines.push(`habits: ${hs.map((h) => `${h.name} (done today: ${(h.done || []).includes(todayISO()) ? "yes" : "no"}, streak ${streakOf(new Set(h.done || []))})`).join(", ") || "none"}`);
  const fs = (call("focus") || {}).sessions || [], todays = fs.filter((x) => iso(new Date(x.start)) === todayISO());
  lines.push(`focus sessions today: ${todays.length} (${dur(sum(todays, (x) => (x.end - x.start) / 1000))}); focus streak ${streakOf(new Set(fs.map((x) => iso(new Date(x.start)))))} days`);
  return lines.join("\n");
}

function send(text) {
  text = text.trim();
  if (!text) return;
  addMsg("user", text);
  const q = text.toLowerCase().replace(/^\/+/, "").replace(/[!?.]+$/, "").trim();
  for (const [re, fn] of COMMANDS) {
    const m = q.match(re);
    if (m) {
      let reply;
      try { reply = fn(m); } catch (e) { console.error(e); reply = `⚠️ Something went wrong: ${e.message}`; }
      addMsg("assistant", reply);
      return;
    }
  }
  if (!coachOn) { addMsg("assistant", offlineAnswer(text)); return; }
  const id = `c${Date.now()}`;
  const history = chat.filter((m) => !m.pending && !m.error).slice(-9, -1).map((m) => ({ role: m.role, text: m.text }));
  addMsg("assistant", "", { pending: true, id, ai: true });
  WP.coachAsk(id, text, buildFacts(), JSON.stringify(history));
}

window.wpCoachReply = (id, res) => {
  const m = chat.find((x) => x.id === id);
  if (!m) return;
  m.pending = false;
  m.text = res && res.text ? res.text : "The coach couldn't answer. Try again.";
  if (!res || !res.ok) { m.error = true; m.ai = false; }
  saveChat();
  if (state.view === "coach") renderChat();
};

function loadCoach() {
  coachOn = !!(call("coachStatus") || {}).hasKey;
  renderChat();
}

$("#c-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $("#c-input");
  send(input.value);
  input.value = "";
});
for (const b of document.querySelectorAll("#c-chips button")) b.addEventListener("click", () => send(b.dataset.q));
$("#c-clear").addEventListener("click", () => { if (confirm("Clear the chat history?")) { chat = []; saveChat(); renderChat(); } });

// ---------- More → AI coach ----------
function loadCoachSettings() {
  coachOn = !!(call("coachStatus") || {}).hasKey;
  $("#m-coach-status").textContent = coachOn ? "✓ On. Free-form questions in the Coach tab go to Gemini with your key." : "Off. The Coach tab answers commands only.";
  $("#m-coach-set").hidden = coachOn;
  $("#m-coach-remove").hidden = !coachOn;
}
$("#m-coach-save").addEventListener("click", () => {
  const r = call("setCoachKey", $("#m-coach-key").value) || {};
  if (!r.ok) { toast(r.error || "Couldn't save the key."); return; }
  $("#m-coach-key").value = "";
  loadCoachSettings();
  toast("AI coach on ✓");
});
$("#m-coach-remove").addEventListener("click", () => {
  if (!confirm("Remove your API key from this phone? The coach will answer commands only.")) return;
  WP.clearCoachKey();
  loadCoachSettings();
});

LOADERS.coach = loadCoach;
const _loadMore = LOADERS.more;
LOADERS.more = () => { _loadMore(); loadCoachSettings(); };
if (new URLSearchParams(location.hash.slice(1)).get("view") === "coach") show("coach");
