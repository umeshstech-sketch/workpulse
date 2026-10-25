/* Fake window.WorkPulse with made-up data, so the screens can be previewed in a desktop browser.
   Only loaded when the page runs outside the Android app (see index.html). */
(function () {
  const APPS = [
    ["com.instagram.android", "Instagram", "Social", 3200, 40], ["com.google.android.youtube", "YouTube", "Entertainment", 2900, 12],
    ["com.whatsapp", "WhatsApp", "Communication", 2400, 55], ["com.android.chrome", "Chrome", "Browsing", 1500, 18],
    ["com.anthropic.claude", "Claude", "Learning", 1300, 9], ["com.spotify.music", "Spotify", "Entertainment", 900, 6],
    ["com.duolingo", "Duolingo", "Learning", 600, 2], ["com.google.android.gm", "Gmail", "Communication", 420, 11],
    ["com.pubg.imobile", "BGMI", "Games", 1100, 3], ["com.google.android.keep", "Keep Notes", "Productivity", 300, 5],
    ["private", "Private apps", "Other", 240, 4],
  ];
  const ls = (k, v) => { try { if (v === undefined) return localStorage.getItem(`wpmock:${k}`); localStorage.setItem(`wpmock:${k}`, v); } catch (e) { return null; } };
  const iso = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
  const rnd = (seed) => { const x = Math.sin(seed) * 10000; return x - Math.floor(x); };
  let settings = Object.assign({ dailyGoalMin: 180, pickupGoal: 60, bedtime: "23:00", wake: "06:30", bedtimeReminder: true, notifyLimits: true,
    limits: { "com.instagram.android": 45 }, categoryOverrides: {}, distracting: ["Social", "Entertainment", "Games"],
    privateKeywords: ["bank", "paytm", "phonepe", "gpay"], theme: "auto" }, JSON.parse(ls("settings") || "{}"));
  function day(s) {
    const d = new Date(`${s}T12:00:00`), seed = d.getDate() + d.getMonth() * 31, isToday = s === iso(new Date());
    const frac = isToday ? Math.min(1, new Date().getHours() / 22) : 1;
    const apps = APPS.map(([pkg, name, cat, sec, opens], i) => ({ pkg, name, cat: settings.categoryOverrides[pkg] || cat,
      s: Math.round(sec * (0.5 + rnd(seed + i)) * frac), opens: Math.round(opens * (0.6 + rnd(seed * 2 + i)) * frac) }))
      .filter((a) => a.s > 30).sort((a, b) => b.s - a.s);
    const total = apps.reduce((t, a) => t + a.s, 0);
    const shape = [3, 1, 0, 0, 0, 0, 1, 4, 6, 5, 4, 5, 7, 6, 4, 5, 6, 7, 8, 9, 10, 9, 8, 6];
    const lastH = isToday ? new Date().getHours() : 23;
    const w = shape.map((v, h) => (h <= lastH ? v : 0)), ws = w.reduce((a, b) => a + b, 0) || 1;
    const cats = {};
    let dist = 0;
    for (const a of apps) { cats[a.cat] = (cats[a.cat] || 0) + a.s; if (settings.distracting.includes(a.cat) && a.pkg !== "private") dist += a.s; }
    return { day: s, total_s: total, pickups: Math.round((50 + rnd(seed) * 60) * frac), first_pickup: new Date(`${s}T07:${10 + (seed % 40)}:00`).getTime(),
      last_use: Date.now(), longest: { s: 2100 + Math.round(rnd(seed) * 1800), pkg: "com.google.android.youtube", name: "YouTube" },
      hourly: w.map((v) => Math.round((total * v) / ws)), apps, cats, distracting_s: dist };
  }
  const shift = (s, n) => { const d = new Date(`${s}T12:00:00`); d.setDate(d.getDate() + n); return iso(d); };
  window.WorkPulse = {
    status: () => JSON.stringify({ usageAccess: true, notifications: true, version: "2.0.0 (preview)", firstDay: shift(iso(new Date()), -40) }),
    day: (s) => JSON.stringify(day(s)),
    range: (n, end) => JSON.stringify(Array.from({ length: n }, (_, i) => day(shift(end, i - n + 1)))),
    settings: () => JSON.stringify(settings),
    saveSettings: (c) => { settings = Object.assign(settings, JSON.parse(c)); ls("settings", JSON.stringify(settings)); return JSON.stringify(settings); },
    getData: (k) => ls(`data:${k}`) || "null",
    setData: (k, v) => { ls(`data:${k}`, v); },
    focus: () => {
      const a = JSON.parse(ls("focus") || "null"), sessions = JSON.parse(ls("sessions") || "[]");
      let just = null;
      if (a && Date.now() >= a.end) { just = { ...a, completed: true, planned_min: a.minutes, distractions: [], distracting_s: 0 }; sessions.push(just); ls("sessions", JSON.stringify(sessions)); ls("focus", "null"); }
      return JSON.stringify({ active: just ? null : a, sessions, just_finished: just, now: Date.now() });
    },
    focusStart: (m, label) => { const a = { start: Date.now(), end: Date.now() + m * 60000, minutes: m, label }; ls("focus", JSON.stringify(a)); return JSON.stringify(a); },
    focusStop: () => {
      const a = JSON.parse(ls("focus") || "null"); if (!a) return "{}";
      const s = { start: a.start, end: Date.now(), planned_min: a.minutes, label: a.label, completed: false,
        distractions: [{ name: "Instagram", cat: "Social", s: 95, opens: 2 }], distracting_s: 95 };
      const sessions = JSON.parse(ls("sessions") || "[]"); sessions.push(s); ls("sessions", JSON.stringify(sessions)); ls("focus", "null");
      return JSON.stringify(s);
    },
    openUsageAccess: () => alert("(preview) would open Android's Usage access settings"),
    requestNotifications: () => {},
    exportCsv: () => window.wpToast && wpToast("(preview) would save a CSV"),
    wipe: () => { localStorage.clear(); return "true"; },
    laptop: () => JSON.stringify({ paired: false }),
    openLaptop: () => alert("(preview) would open the laptop sync screen"),
    coachStatus: () => JSON.stringify({ hasKey: ls("coachkey") === "1" }),
    setCoachKey: (k) => { if (k.trim().length < 20) return JSON.stringify({ ok: false, error: "That doesn't look like a Gemini API key. Copy it again from aistudio.google.com." }); ls("coachkey", "1"); return JSON.stringify({ ok: true }); },
    clearCoachKey: () => { ls("coachkey", "0"); },
    coachAsk: (id, q, facts) => { console.log(facts); setTimeout(() => window.wpCoachReply(id, { ok: true, text: "(preview) This is where Gemini answers, using your stats. *Bold* works, and so do\n- bullets" }), 900); },
  };
})();
