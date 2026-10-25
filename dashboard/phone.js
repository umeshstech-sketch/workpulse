/* WorkPulse dashboard, Phase 5: the "Digital day" tab (laptop + phone) and adding phone screen time.
   Uses helpers from app.js / planning.js ($, el, api, post, dur, css, catColor, kpi, flash, safely, HAS_CHART, state). */
"use strict";

window.TAB_LOADERS = window.TAB_LOADERS || {};
let ddDay = null;

async function upload(path, file, extra = {}) {
  const fd = new FormData();
  fd.append("file", file);
  for (const [k, v] of Object.entries(extra)) fd.append(k, v);
  const r = await fetch(path, { method: "POST", body: fd, headers: { "X-WorkPulse-UI": "1" } });  // no JSON content-type: multipart
  if (!r.ok) { let msg = r.statusText; try { msg = (await r.json()).detail; } catch (e) {} throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg)); }
  return r.json();
}

async function loadDigital() {
  ddDay = ddDay || state.day || todayISO();
  const d = await api(`/api/digital?date=${ddDay}`);
  $("#dd-picker").value = ddDay;
  $("#dd-next").disabled = ddDay >= todayISO();
  if ($("#manual-form [name=source]").value !== "screenshot") $("#manual-form [name=day]").value = ddDay;  // form follows the day you're viewing
  $("#dd-note").textContent = d.has_phone_data ? "" : "No phone data for this day yet: add it below.";

  $("#dd-kpis").replaceChildren(
    kpi("Digital day", dur(d.total_s), "laptop active + phone screen time"),
    kpi("💻 Laptop", dur(d.laptop_active_s), `${dur(d.laptop_productive_s)} productive`),
    kpi("📱 Phone", d.has_phone_data ? dur(d.phone_s) : "–", d.has_phone_data ? `${Math.round(d.phone_share * 100)}% of your digital day` : "no data"),
    kpi("🔓 Pickups", d.pickups != null ? `${d.pickups}` : "–", d.phone_entertainment_s ? `${dur(d.phone_entertainment_s)} phone entertainment` : null),
  );

  const lap = css("--series-1"), ph = css("--series-2");
  $("#dd-legend").replaceChildren(el("span", {}, el("i", { class: "swatch", style: `background:${lap}` }), "Laptop (active)"),
                                  el("span", {}, el("i", { class: "swatch", style: `background:${ph}` }), "Phone (screen time)"));
  if (HAS_CHART) {
    state.charts.dd?.destroy();
    const labels = d.week.map((x) => new Date(x.date + "T12:00").toLocaleDateString([], { weekday: "short", day: "numeric" }));
    state.charts.dd = new Chart($("#dd-chart"), {
      type: "bar",
      data: { labels, datasets: [
        { label: "Laptop", data: d.week.map((x) => +(x.laptop_active_s / 3600).toFixed(2)), backgroundColor: lap, borderColor: css("--surface"), borderWidth: { top: 2 }, borderSkipped: false, maxBarThickness: 44 },
        { label: "Phone", data: d.week.map((x) => +(x.phone_s / 3600).toFixed(2)), backgroundColor: ph, borderColor: css("--surface"), borderWidth: { top: 2 }, borderSkipped: false, maxBarThickness: 44 }] },
      options: { maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
        scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, title: { display: true, text: "hours" }, grid: { color: css("--grid") } } },
        plugins: { legend: { display: false }, tooltip: { callbacks: { label: (c) => ` ${c.dataset.label}: ${dur(c.raw * 3600)}`,
          footer: (items) => `Digital day ${dur(items.reduce((s, i) => s + i.raw * 3600, 0))}` } } } },
    });
  }

  const tbl = $("#dd-cats");
  tbl.replaceChildren(el("tr", {}, el("th", { text: "Category" }), el("th", { class: "num", text: "Laptop" }), el("th", { class: "num", text: "Phone" }), el("th", { class: "num", text: "Total" })));
  for (const c of d.categories) {
    tbl.append(el("tr", {}, el("td", {}, el("i", { class: "swatch", style: `background:${catColor(c.name)};margin-right:6px` }), c.name),
      el("td", { class: "num", text: c.laptop_s ? dur(c.laptop_s) : "–" }), el("td", { class: "num", text: c.phone_s ? dur(c.phone_s) : "–" }),
      el("td", { class: "num", text: dur(c.laptop_s + c.phone_s) })));
  }
  if (!d.categories.length) tbl.append(el("tr", {}, el("td", { class: "muted", text: "Nothing tracked this day." })));

  const max = Math.max(1, ...d.phone_top_apps.map((a) => a.seconds));
  $("#dd-apps").replaceChildren(...(d.phone_top_apps.length ? d.phone_top_apps.map((a) => el("div", { class: "bar-row" },
    el("span", { class: "name", text: a.app }),
    el("div", { class: "bar-track" }, el("div", { class: "bar-fill", style: `width:${(100 * a.seconds / max).toFixed(1)}%;background:${ph}` })),
    el("span", { class: "num", text: dur(a.seconds) }))) : [el("p", { class: "muted", text: "No phone apps for this day." })]));
  const devs = $("#dd-devices");
  devs.replaceChildren(...d.phone_devices.map((x) => {
    const rm = el("button", { class: "icon-btn", title: `Delete ${x.device} data for this day`, "aria-label": `Delete ${x.device} data for this day`, text: "✕" });
    rm.addEventListener("click", () => { if (confirm(`Delete ${x.device} screen time for ${ddDay}?`)) safely(async () => { await api(`/api/phone/day?date=${ddDay}&device=${encodeURIComponent(x.device)}`, { method: "DELETE" }); loadDigital(); }); });
    return el("span", {}, `${x.device} · ${x.source} `, rm);
  }));
}

$("#dd-prev").addEventListener("click", () => { ddDay = shiftISO(ddDay, -1); loadDigital(); });
$("#dd-next").addEventListener("click", () => { if (ddDay < todayISO()) { ddDay = shiftISO(ddDay, 1); loadDigital(); } });
$("#dd-picker").addEventListener("change", (e) => { if (e.target.value) { ddDay = e.target.value; loadDigital(); } });

// ---- adding data -------------------------------------------------------------------------------
function fillForm(day, total, pickups, apps, source) {
  const f = $("#manual-form");
  f.day.value = day || ddDay;
  f.total.value = total || "";
  f.pickups.value = pickups ?? "";
  f.apps.value = apps.map((a) => `${a.name} = ${a.time}`).join("\n");
  f.source.value = source;
}

$("#shot-btn").addEventListener("click", async () => {
  const file = $("#shot-file").files[0];
  if (!file) return flash("Choose a screenshot first");
  const btn = $("#shot-btn");
  btn.disabled = true; btn.textContent = "Reading…";
  try {
    const r = await upload("/api/phone/screenshot", file);
    const m = (x) => `${Math.round(x)}m`;
    fillForm(r.day, r.total_minutes != null ? m(r.total_minutes) : "", r.pickups, r.apps.map((a) => ({ name: a.name, time: m(a.minutes) })), "screenshot");
    $("#manual-msg").textContent = r.period === "week" ? "⚠️ That looks like a WEEKLY view; use a single day's screenshot or fix the numbers." : "Check the numbers, fix anything wrong, then save. (The screenshot wasn't kept.)";
    $("#manual-form").scrollIntoView({ behavior: "smooth", block: "center" });
  } catch (e) { flash(`⚠️ ${e.message}`); }
  btn.disabled = false; btn.textContent = "Read screenshot";
  $("#shot-file").value = "";
});

$("#imp-btn").addEventListener("click", () => {
  const file = $("#imp-file").files[0];
  if (!file) return flash("Choose a CSV or JSON file first");
  safely(async () => {
    const r = await upload("/api/phone/import", file);
    flash(`Imported ${r.stored.length} day(s) ✓`);
    $("#imp-file").value = "";
    if (r.stored.length) ddDay = r.stored[r.stored.length - 1].day;
    loadDigital();
  });
});

$("#setup-btn").addEventListener("click", () => safely(async () => {
  const s = await api("/api/phone/setup");
  const box = $("#setup-box");
  box.textContent = `POST ${s.local_url}\n(or https://<your-tunnel>${s.path})\n${s.header}: ${s.token}\nContent-Type: application/json\n\n${JSON.stringify(s.example, null, 2)}`;
  box.hidden = !box.hidden;
}));

function parseAppLines(text) {
  const out = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line) continue;
    let name, time;
    if (line.includes("=")) { [name, time] = line.split(/=(.*)/s).map((x) => x.trim()); }
    else { const m = line.match(/^(.*?)\s+((?:\d+(?:\.\d+)?\s*(?:h|hr|hrs|m|min|mins|s)?\s*)+|\d{1,2}:\d{2})$/i); if (m) { name = m[1].trim(); time = m[2].trim(); } }
    if (!name || !time) throw new Error(`Can't read the line "${line}". Use: Instagram = 1h 10m`);
    out.push({ name, time });
  }
  return out;
}

$("#manual-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const f = e.target, msg = $("#manual-msg");
  let apps;
  try { apps = parseAppLines(f.apps.value); } catch (err) { msg.textContent = `⚠️ ${err.message}`; return; }
  const body = { day: f.day.value, total: f.total.value.trim() || null, pickups: f.pickups.value ? +f.pickups.value : null,
                 device: f.device.value.trim() || null, apps, source: f.source.value };
  safely(async () => {
    const r = await post("/api/phone/manual", body);
    msg.textContent = `Saved ${r.stored[0].device} · ${r.stored[0].day} ✓`;
    ddDay = r.stored[0].day;
    f.apps.value = ""; f.total.value = ""; f.pickups.value = ""; f.source.value = "manual";
    loadDigital();
  });
});

window.TAB_LOADERS.digital = loadDigital;
if (state.tab === "digital") loadDigital();

// ---- Settings → Connect a phone (laptop only) ---------------------------------------------------
async function loadConnect() {
  if (location.hostname !== "127.0.0.1" && location.hostname !== "localhost") { $("#connect-card").hidden = true; return; }
  const st = await api("/api/lan");
  $("#lan-toggle").checked = st.enabled;
  $("#lan-on").hidden = !st.enabled;
  $("#lan-url").textContent = st.url || "no Wi-Fi address found";
  $("#lan-warnings").replaceChildren(...(st.enabled ? st.warnings : []).map((w) => el("li", { text: w })));
  const rs = await api("/api/remote");
  $("#remote-toggle").checked = rs.enabled;
  $("#remote-on").hidden = !rs.enabled || !rs.url;
  $("#remote-url").textContent = rs.url || "";
  $("#remote-warnings").replaceChildren(...(rs.enabled ? rs.warnings : []).map((w) => el("li", { text: w })));
  $("#pair-area").hidden = !st.enabled && !rs.enabled;
  const d = await api("/api/devices");
  $("#devices").replaceChildren(...(d.devices.length ? d.devices.map((x) => {
    const rm = el("button", { class: "icon-btn", title: `Remove ${x.name}`, "aria-label": `Remove ${x.name}`, text: "✕" });
    rm.addEventListener("click", () => { if (confirm(`Remove ${x.name}? It will need a new code to connect again.`)) safely(async () => { await api(`/api/devices/${x.id}`, { method: "DELETE" }); loadConnect(); }); });
    const seen = x.last_seen ? new Date(x.last_seen * 1000).toLocaleString([], { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "never";
    return el("div", { class: "member" }, el("div", { class: "who" }, el("b", { text: x.name }), ` · ${x.kind === "android" ? "Android app" : "web app"}`,
      el("div", { class: "muted", text: `last seen ${seen}${x.last_ip ? " from " + x.last_ip : ""}` })), rm);
  }) : [el("p", { class: "muted", text: "None yet." })]));
}

function accessToggle(id, endpoint) {
  $(`#${id}-toggle`).addEventListener("change", (e) => safely(async () => {
    const msg = $(`#${id}-msg`);
    msg.textContent = e.target.checked ? "Turning on… (the dashboard may restart for a moment)" : "Turning off…";
    const r = await api(endpoint, { method: "PUT", body: JSON.stringify({ enabled: e.target.checked }) });
    if (r.restarting) {  // wait for the server to come back on its new address
      await new Promise((ok) => setTimeout(ok, 2500));
      for (let i = 0; i < 30; i++) { try { if ((await fetch("/api/ping")).ok) break; } catch (err) {} await new Promise((ok) => setTimeout(ok, 1000)); }
    }
    msg.textContent = e.target.checked ? "On ✓" : "Off ✓";
    loadConnect();
  }));
}
accessToggle("lan", "/api/lan");
accessToggle("remote", "/api/remote");

$("#pair-btn").addEventListener("click", () => safely(async () => {
  const r = await api("/api/pairing/start", { method: "POST", body: "{}" });
  $("#pair-box").hidden = false;
  $("#pair-code").textContent = `${r.code.slice(0, 3)} ${r.code.slice(3)}`;
  $("#qr-web").innerHTML = r.web_qr || "";  // SVG generated by our own server from our own URL
  $("#qr-app").innerHTML = r.app_qr || "";
  const apk = await fetch("/m/workpulse.apk", { method: "HEAD" }).then((x) => x.ok).catch(() => false);
  $("#apk-hint").textContent = apk && r.hosts.length ? `No Android app yet? On the phone open http://${r.hosts[0]}/m/ → More → "Get the Android app".` : "";
}));

window.TAB_LOADERS.settings = loadConnect;
if (state.tab === "settings") loadConnect();
