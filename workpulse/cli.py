"""`workpulse` command line. Run `workpulse --help` for the list of commands."""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from rich.console import Console
from rich.table import Table
from rich.text import Text

# pythonw (autostart) has no stdout; print into the void instead of crashing.
# pythonw (auto-start) has no stdout: print into the void, in UTF-8 so symbols like ● can't crash it.
console = Console(highlight=False, file=None if sys.stdout is not None else open(os.devnull, "w", encoding="utf-8"))

CATEGORY_COLORS = {
    "Coding": "green", "Learning/AI": "cyan", "Design": "magenta", "Content Creation": "yellow",
    "Communication": "blue", "Browsing": "white", "Entertainment": "red", "Other": "grey50",
}


def _cfg():
    from workpulse.config import get_config
    return get_config()


def _hm(ts: float | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M") if ts else "--:--"


def _delta(cur: float, ref: float) -> str:
    from workpulse.core.stats import fmt_dur
    d = cur - ref
    sign = "+" if d >= 0 else "-"
    color = "green" if d >= 0 else "red"
    return f"[{color}]{sign}{fmt_dur(abs(d))}[/]"


def _tracking_line(cfg) -> str:
    from workpulse.agent import control
    pid = control.running_pid(cfg)
    if control.is_paused(cfg):
        return "[yellow]⏸  tracking PAUSED[/] (workpulse resume)"
    if pid:
        return f"[green]●  tracking ON[/] [dim](agent pid {pid})[/]"
    return "[red]○  agent not running[/] (workpulse start)"


def _dashboard_line(cfg) -> str:
    from workpulse.agent import control
    if control.running_pid(cfg, "server"):
        return f"[green]●  dashboard[/] {cfg.server.url}"
    return "[dim]○  dashboard not running (workpulse start)[/]"


def timeline(sessions, day: date, slot_min: int = 10) -> Text:
    """One character per `slot_min` minutes, colored by what dominated that slot."""
    from workpulse.core.stats import day_bounds
    start, _ = day_bounds(day)
    active = [s for s in sessions if s.state != "away"]
    if not active:
        return Text("(no activity)", style="dim")
    first_h = int((min(s.start_ts for s in active) - start) // 3600)
    last_h = int((max(s.end_ts for s in active) - start) // 3600) + 1
    slot = slot_min * 60
    text = Text(f"{first_h:02d}:00 ")
    for i in range(first_h * 3600 // slot, last_h * 3600 // slot):
        a, b = start + i * slot, start + (i + 1) * slot
        tally: dict[tuple[str, str], float] = {}
        for s in sessions:
            ov = min(b, s.end_ts) - max(a, s.start_ts)
            if ov > 0:
                k = (s.state, s.category)
                tally[k] = tally.get(k, 0) + ov
        if not tally:
            text.append(" ")
            continue
        (state, cat), _ = max(tally.items(), key=lambda kv: kv[1])
        if state == "active":
            text.append("█", style=CATEGORY_COLORS.get(cat, "grey50"))
        elif state == "idle":
            text.append("·", style="grey50")
        else:
            text.append(" ")
    text.append(f" {last_h:02d}:00")
    return text


# ---- commands ----------------------------------------------------------------------------------

def cmd_today(args) -> None:
    from workpulse.core.service import day_with_comparison
    from workpulse.core.stats import fmt_dur
    cfg = _cfg()
    d = date.fromisoformat(args.date) if args.date else date.today() - timedelta(days=1 if args.yesterday else 0)
    st, cmp = day_with_comparison(cfg, d)

    console.print()
    console.print(f"[bold]WorkPulse[/] · {d.strftime('%a %d %b %Y')}{'  [magenta](demo data)[/]' if cfg.demo else ''}")
    console.print(_tracking_line(cfg))
    console.print()
    if st.active_s == 0:
        console.print("No activity recorded for this day yet. Leave the agent running, or try [bold]workpulse --demo today[/].")
        return

    vs = []
    if cmp.yesterday and cmp.yesterday.active_s:
        vs.append(f"vs yesterday {_delta(st.active_s, cmp.yesterday.active_s)}")
    if cmp.avg7_active_s:
        vs.append(f"vs 7-day avg {_delta(st.active_s, cmp.avg7_active_s)}")
    console.print(f"⏱  Active        [bold]{fmt_dur(st.active_s)}[/]   {'   '.join(vs)}")
    console.print(f"🎯 Focus score   [bold]{st.focus_score}/100[/]   "
                  f"[dim]7-day avg {cmp.avg7_score:.0f}" + (f" · best {cmp.best.focus_score} on {cmp.best.day:%d %b}" if cmp.best else "") + "[/]")
    console.print(f"🔥 Longest focus [bold]{fmt_dur(st.longest_streak_s)}[/] "
                  + (f"of {st.streak_category} from {_hm(st.streak_start)}" if st.streak_category else ""))
    console.print(f"🧠 Productive    {fmt_dur(st.productive_s)}   😴 Idle {fmt_dur(st.idle_s)}   ☕ Breaks {st.breaks}")
    console.print(f"🕘 First {_hm(st.first_activity)} · Last {_hm(st.last_activity)}")
    console.print()
    console.print(timeline(st.sessions, d))
    console.print()

    t = Table(title="By category", show_edge=False, title_justify="left")
    t.add_column("Category"); t.add_column("Time", justify="right"); t.add_column("")
    for cat, secs in st.per_category.items():
        bar = "█" * max(1, round(30 * secs / st.active_s))
        t.add_row(Text(cat, style=CATEGORY_COLORS.get(cat, "")), fmt_dur(secs), Text(bar, style=CATEGORY_COLORS.get(cat, "")))
    console.print(t)
    console.print()
    t = Table(title="Top apps", show_edge=False, title_justify="left")
    t.add_column("App"); t.add_column("Time", justify="right"); t.add_column("Share", justify="right")
    for app, secs in list(st.per_app.items())[:8]:
        t.add_row(cfg.alias(app), fmt_dur(secs), f"{100 * secs / st.active_s:.0f}%")
    console.print(t)
    b = st.score_breakdown
    console.print(f"\n[dim]Score = deep work {b['deep_work']}/40 + focus ratio {b['focus_ratio']}/25 + "
                  f"streak {b['streak']}/20 + low distraction {b['low_distraction']}/15[/]")


def cmd_status(args) -> None:
    from workpulse.core.db import latest_session
    from workpulse.core.stats import fmt_dur
    cfg = _cfg()
    console.print(_tracking_line(cfg))
    console.print(_dashboard_line(cfg))
    s = latest_session(cfg.db_path)
    if not s:
        console.print("No data yet.")
        return
    from workpulse.agent import control
    age = time.time() - s.end_ts
    if control.is_paused(cfg):
        console.print(f"Last recorded before pause: {s.state}, {cfg.alias(s.app)} ({fmt_dur(age)} ago)")
    elif age < cfg.tracking.flush_interval_s * 3:
        what = f"{s.category} in {cfg.alias(s.app)}" if s.state != "away" else "away"
        console.print(f"Right now: [bold]{s.state}[/] · {what} · for {fmt_dur(s.duration)}")
    else:
        console.print(f"Last seen {fmt_dur(age)} ago ({s.state}, {cfg.alias(s.app)})")


def cmd_agent(args) -> None:
    from workpulse.agent.runner import Agent, setup_logging
    cfg = _cfg()
    setup_logging(cfg)
    overrides = {k: v for k, v in (("idle_after_s", args.idle_after), ("away_after_s", args.away_after)) if v}
    Agent(cfg, tracking_overrides=overrides).run()


def _wait_running(cfg, name: str, timeout: float = 20) -> int | None:
    from workpulse.agent import control
    deadline = time.time() + timeout  # first start can be slow (imports, antivirus scans)
    while time.time() < deadline and not control.running_pid(cfg, name):
        time.sleep(0.5)
    return control.running_pid(cfg, name)


def cmd_start(args) -> None:
    """Start the tracker and the dashboard server in the background (no windows), kept alive by the supervisor."""
    from workpulse.agent import control
    cfg = _cfg()
    from workpulse.logs import tail
    names = ["agent"] if args.agent_only else ["agent", "server"]
    supervised = False
    if not args.agent_only:
        control.start_background(cfg, "supervisor")  # starts both, and restarts them if they ever stop
        supervised = bool(_wait_running(cfg, "supervisor", 10))
        if not supervised:
            console.print("[yellow]![/] The keep-alive supervisor didn't start (see .\\workpulse logs supervisor); starting directly.")
    ok = True
    for name in names:
        label = "Tracker" if name == "agent" else "Dashboard"
        if pid := control.running_pid(cfg, name):
            console.print(f"[green]●[/] {label} running (pid {pid})")
            continue
        if not supervised:
            control.start_background(cfg, name)
        if pid := _wait_running(cfg, name, 25):
            console.print(f"[green]●[/] {label} started (pid {pid})")
        else:
            ok = False
            log_name = "agent" if name == "agent" else "server"
            console.print(f"[red]✗ {label} didn't start.[/] Last lines of data/logs/{log_name}.log:")
            for line in tail(cfg, log_name, 8):
                console.print(Text("   " + line.rstrip()), style="dim")
            console.print("Run [bold].\\workpulse doctor[/] for a full check.")
    if "server" in names and ok:
        console.print(f"Dashboard: [bold]{cfg.server.url}[/]   Side panel: [bold].\\workpulse panel[/]   Logs: {cfg.log_dir}")


def cmd_stop(args) -> None:
    from workpulse.agent import control, panel
    cfg = _cfg()
    control.stop_background(cfg, "supervisor")  # first, so it doesn't bring the others back
    panel.focus_or_close_existing(cfg, close=True)
    for name, label in (("agent", "Tracker"), ("server", "Dashboard")):
        console.print(f"{label} stopped." if control.stop_background(cfg, name) else f"{label} wasn't running.")
    if control.autostart_status():
        console.print("[dim]Auto-start is on, so it starts again at your next login.[/]")


def cmd_supervise(args) -> None:
    from workpulse.agent.supervisor import main
    main()


def cmd_panel(args) -> None:
    """Open the dashboard as a slim panel docked to the side of the screen (Windows)."""
    from workpulse.agent import control, panel
    from workpulse.config import save_settings
    cfg = _cfg()
    if args.watch:
        import logging

        from workpulse.logs import setup_logging
        setup_logging(cfg, "panel", console=False)
        try:
            panel.run_watcher(cfg)
        except RuntimeError as e:
            logging.getLogger("workpulse.panel").error("panel failed: %s", e)
            raise SystemExit(f"Side panel: {e}")
        return
    if args.close:
        console.print("Side panel closed." if panel.focus_or_close_existing(cfg, close=True) else "The side panel isn't open.")
        return
    if sys.platform != "win32":
        console.print(f"The docked panel is Windows-only. Open [bold]{cfg.server.url}/m/[/] in a narrow browser window instead.")
        return
    changes = {k: v for k, v in (("panel_side", "left" if args.left else "right" if args.right else None),
                                 ("panel_width", args.width),
                                 ("panel_dock", False if args.float else True if args.dock else None)) if v is not None}
    if changes:
        cfg = save_settings({"startup": changes})  # remembered for next time (and for auto-start)
        if panel.focus_or_close_existing(cfg, close=True):
            time.sleep(2)  # let the old panel give its screen edge back
    elif panel.focus_or_close_existing(cfg):
        console.print("The side panel is already open (brought it to the front). Close it with [bold].\\workpulse panel --close[/]")
        return
    control.start_background(cfg, "panel", "--watch")
    st = cfg.startup
    console.print(f"Opening the side panel on the {st.panel_side} ({st.panel_width}px, {'docked' if st.panel_dock else 'floating'})."
                  " Close it with its X or [bold].\\workpulse panel --close[/]")


def cmd_serve(args) -> None:
    """Run the API + dashboard in this terminal."""
    import logging

    import uvicorn

    from workpulse.agent import control
    from workpulse.agent.runner import setup_logging
    cfg = _cfg()
    if args.port:
        cfg.server.port = args.port
    if (pid := control.running_pid(cfg, "server")) and pid != os.getpid():
        console.print(f"Dashboard already running (pid {pid}): {cfg.server.url}")
        return
    setup_logging(cfg, "server")
    handlers = logging.getLogger("workpulse").handlers
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers, lg.propagate, lg.level = list(handlers), False, logging.INFO
    control.write_pid(cfg, "server")
    console.print(f"WorkPulse dashboard on [bold]{cfg.server.url}[/]{'  (demo data)' if cfg.demo else ''}  (Ctrl+C to stop)")
    try:
        # proxy_headers=False: request.client is always the real connecting address. Access control relies on
        # it (laptop vs. Wi-Fi phone), so it must never be taken from a forwarded header.
        uvicorn.run("workpulse.backend.app:app", host=cfg.server.bind_host, port=cfg.server.port,
                    log_config=None, access_log=False, proxy_headers=False)
    finally:
        control.clear_pid(cfg, "server")


def cmd_dashboard(args) -> None:
    import webbrowser
    cfg = _cfg()
    console.print(_dashboard_line(cfg))
    webbrowser.open(cfg.server.url)


def cmd_pause(args) -> None:
    from workpulse.agent import control
    control.pause(_cfg())
    console.print("[yellow]⏸  Tracking paused.[/] Nothing is recorded until you run [bold]workpulse resume[/].")


def cmd_resume(args) -> None:
    from workpulse.agent import control
    cfg = _cfg()
    control.resume(cfg)
    console.print("[green]▶  Tracking resumed.[/]" + ("" if control.running_pid(cfg) else " (agent not running: workpulse start)"))


def cmd_autostart(args) -> None:
    from workpulse.agent import control
    from workpulse.config import save_settings
    if args.action == "on":
        if args.panel is not None:
            save_settings({"startup": {"panel": args.panel}})
        console.print(control.autostart_enable())
        if _cfg().startup.panel:
            console.print("The side panel opens at login too. (Turn that off: [bold].\\workpulse autostart on --no-panel[/])")
    elif args.action == "off":
        console.print(control.autostart_disable())
    else:
        console.print("Auto-start is " + ("[green]ON[/]" if control.autostart_status() else "[red]OFF[/]")
                      + (" · side panel at login" if _cfg().startup.panel else ""))


def cmd_doctor(args) -> None:
    """Health check of everything, with a fix for each problem, then live readings of what the tracker sees."""
    from workpulse.agent.platforms.base import get_platform
    from workpulse.core.categorize import scrub
    from workpulse.core.maintenance import run_checks
    cfg = _cfg()
    p = get_platform()
    console.print(f"[bold]WorkPulse doctor[/] · {p.name} · Python {sys.version.split()[0]} · data: {cfg.data_dir}\n")
    icon = {"ok": "[green]✓[/]", "warn": "[yellow]![/]", "fail": "[red]✗[/]"}
    checks = run_checks(cfg)
    for c in checks:
        console.print(f" {icon[c.status]} [bold]{c.name:<11}[/] {c.detail}")
        if c.fix:
            console.print(f"   [dim]→ {c.fix}[/]")
    fails = sum(c.status == "fail" for c in checks)
    console.print(f"\n{'[red]' + str(fails) + ' problem(s) to fix[/]' if fails else '[green]All essentials OK[/]'}"
                  f" · {sum(c.status == 'warn' for c in checks)} optional item(s)\n")
    console.print("[bold]Live readings[/] (what the tracker sees right now):")
    for _ in range(args.samples):
        raw_app, raw_title = p.active_window()
        app, title, cat = scrub(raw_app, raw_title, cfg.categories, cfg.privacy)
        console.print(f"idle={p.idle_seconds():6.1f}s locked={p.is_locked()!s:5} app={app!s:18} cat={cat:15} title={title!r}")
        if args.samples > 1:
            time.sleep(1)


def cmd_logs(args) -> None:
    from workpulse.logs import tail
    cfg = _cfg()
    lines = tail(cfg, args.name, args.n)
    if not lines:
        console.print(f"No {args.name}.log yet in {cfg.log_dir}")
    for line in lines:
        style = "red" if " ERROR " in line else "yellow" if " WARNING " in line else None
        console.print(Text(line.rstrip(), style=style or ""))


def cmd_backup(args) -> None:
    from workpulse.core.maintenance import backup, list_backups
    cfg = _cfg()
    if args.list:
        for b in list_backups(cfg):
            console.print(f"{b.name}  {b.stat().st_size / 1e6:.1f} MB")
        return
    dest = backup(cfg, keep=args.keep)
    console.print(f"[green]✓[/] Backed up to {dest}  (keeping the newest {args.keep})")


def cmd_restart(args) -> None:
    from workpulse.agent import control
    cfg = _cfg()
    if args.delay:
        time.sleep(args.delay)
    names = ["server"] if args.server_only else ["agent", "server"]
    control.hold_supervisor(cfg)  # so the supervisor doesn't race us to start them
    try:
        for name in names:
            control.stop_background(cfg, name)
        for name in names:
            control.start_background(cfg, name)
            label = "Tracker" if name == "agent" else "Dashboard"
            console.print(f"{label} {'restarted' if _wait_running(cfg, name) else '[red]failed to restart[/] (see .\\workpulse logs)'}")
    finally:
        control.release_supervisor(cfg)


def _print_lan_warnings(st: dict) -> None:
    for w in st["warnings"]:
        console.print(f"[yellow]![/] {w}")


def cmd_lan(args) -> None:
    """Let paired phones on your Wi-Fi reach WorkPulse (mobile app), or turn that off."""
    from workpulse.agent import control
    from workpulse.backend.pairing_api import lan_status
    from workpulse.config import save_settings
    cfg = _cfg()
    if args.action in ("on", "off"):
        old = cfg.server.bind_host
        cfg = save_settings({"server": {"lan": args.action == "on"}})
        if cfg.server.bind_host != old:
            _restart_server_now(cfg)
    st = lan_status(cfg)
    if not st["enabled"]:
        console.print("Wi-Fi access is [bold]OFF[/]: only this laptop can open WorkPulse. Turn on with [bold].\\workpulse lan on[/]")
        return
    console.print("Wi-Fi access is [green]ON[/]: paired phones on your network can connect.")
    for a in st["addresses"]:
        console.print(f"  http://{a['ip']}:{st['port']}/m/   [dim]({a['interface']}{', looks like a VPN' if a['likely_vpn'] else ''})[/]")
    _print_lan_warnings(st)
    console.print("Next: [bold].\\workpulse connect[/] to pair your phone.")


def _restart_server_now(cfg) -> None:
    """Restart the dashboard so it listens on the new address (after Wi-Fi / away access changes)."""
    from workpulse.agent import control
    if not control.running_pid(cfg, "server"):
        return
    control.hold_supervisor(cfg)
    try:
        control.stop_background(cfg, "server")
        control.start_background(cfg, "server")
        _wait_running(cfg, "server")
    finally:
        control.release_supervisor(cfg)


def cmd_remote(args) -> None:
    """Reach WorkPulse from your phone when you're out, over Tailscale (your own private network)."""
    from workpulse.backend.pairing_api import remote_status
    from workpulse.config import save_settings
    cfg = _cfg()
    if args.action in ("on", "off"):
        old = cfg.server.bind_host
        cfg = save_settings({"server": {"remote": args.action == "on"}})
        if cfg.server.bind_host != old:
            _restart_server_now(cfg)
    st = remote_status(cfg)
    if not st["enabled"]:
        console.print("Away-from-home access is [bold]OFF[/]. Turn on with [bold].\\workpulse remote on[/] (uses Tailscale).")
    else:
        console.print("Away-from-home access is [green]ON[/]: paired phones on your Tailscale network can connect from anywhere.")
        for ip in st["addresses"]:
            console.print(f"  http://{ip}:{st['port']}/m/")
        if st["dns_name"]:
            console.print(f"  http://{st['dns_name']}:{st['port']}/m/   [dim](MagicDNS name)[/]")
    _print_lan_warnings(st)
    if st["enabled"] and st["connected"]:
        console.print("Already-paired Android phones pick up the new address at their next sync (or pair again: [bold].\\workpulse connect[/]).")


def cmd_connect(args) -> None:
    """Show a pairing code + QR code for the phone."""
    import io

    import qrcode

    from workpulse.agent import control
    from workpulse.backend.pairing_api import lan_status, phone_hosts
    from workpulse.core import devices
    cfg = _cfg()
    if not cfg.server.lan and not cfg.server.remote:
        console.print("Phone access is off, so the phone can't reach this laptop yet. Run [bold].\\workpulse lan on[/] "
                      "(home Wi-Fi) and/or [bold].\\workpulse remote on[/] (from anywhere, via Tailscale) first.")
        return
    if not control.running_pid(cfg, "server"):
        console.print("The dashboard isn't running, so the phone has nothing to connect to. Start it with [bold].\\workpulse start[/], then run this again.")
        return
    hosts = phone_hosts(cfg)
    if not hosts:
        console.print("[red]No address for the phone:[/] this laptop isn't on a Wi-Fi/LAN network"
                      + (" and Tailscale isn't connected." if cfg.server.remote else "."))
        return
    code, _ = devices.new_code(cfg)
    url = f"http://{hosts[0]}/m/#pair={code}"
    qr = qrcode.QRCode(border=2)
    qr.add_data(url)
    buf = io.StringIO()
    qr.print_ascii(out=buf, invert=True)
    console.print(Text(buf.getvalue()))
    console.print(f"Scan with your phone camera, or open [bold]http://{hosts[0]}/m/[/] and type the code:")
    console.print(f"\n      [bold]{code[:3]} {code[3:]}[/]   [dim](valid 10 minutes, one phone)[/]\n")
    console.print("Android app: tap [bold]Connect[/], enter the address above and this code"
                  " (or scan the app QR in the dashboard: Settings → Connect a phone, which carries every address).")
    if hosts[1:]:
        console.print("Other addresses for this laptop: " + ", ".join(hosts[1:]))
    if cfg.server.lan:
        _print_lan_warnings(lan_status(cfg))


def cmd_devices(args) -> None:
    from workpulse.core import devices
    cfg = _cfg()
    if args.remove:
        console.print("Removed." if devices.revoke(cfg, args.remove) else f"No device #{args.remove}.")
        return
    devs = devices.list_devices(cfg)
    if not devs:
        console.print("No phones paired yet. Pair one with: .\\workpulse connect")
    for d in devs:
        seen = datetime.fromtimestamp(d.last_seen).strftime("%d %b %H:%M") if d.last_seen else "never"
        console.print(f"#{d.id}  {d.name}  [dim]({d.kind}, last seen {seen}{', ' + d.last_ip if d.last_ip else ''})[/]")
    if devs:
        console.print("[dim]Remove one with: .\\workpulse devices --remove <#>[/]")


def cmd_demo(args) -> None:
    from workpulse.core import db, demo
    os.environ["WORKPULSE_DEMO"] = "1"
    cfg = _cfg()
    from workpulse.core import phone
    if args.action == "clear":
        n = db.delete_sessions(cfg.db_path)
        phone.delete_all(cfg)
        console.print(f"Removed {n} demo sessions (and demo phone data) from {cfg.db_path.name}.")
        return
    db.delete_sessions(cfg.db_path)
    phone.delete_all(cfg)
    n = db.upsert_sessions(cfg.db_path, demo.generate(days=args.days), source="demo")
    for day in demo.generate_phone(days=args.days):
        phone.save_day(cfg, day, "demo")
    demo.seed_planning(cfg)
    console.print(f"Seeded {n} demo sessions over {args.days} days into {cfg.db_path.name} (your real data is untouched).\n"
                  "Try: [bold]workpulse --demo today[/]")


def cmd_export(args) -> None:
    from workpulse.core.db import sessions_between
    cfg = _cfg()
    out = Path(args.out or cfg.data_dir / f"workpulse-export-{date.today()}.csv")
    from workpulse.core.export import write_csv
    rows = sessions_between(cfg.db_path, 0, time.time() + 86400)
    with out.open("w", newline="", encoding="utf-8") as f:
        write_csv(rows, f)
    console.print(f"Exported {len(rows)} sessions to {out}")


def cmd_wipe(args) -> None:
    from workpulse.core.db import delete_sessions
    cfg = _cfg()
    if not args.yes:
        console.print("This permanently deletes ALL tracked activity. Re-run with [bold]--yes[/] to confirm.")
        return
    console.print(f"Deleted {delete_sessions(cfg.db_path)} sessions.")


def _wa_status(cfg) -> None:
    from workpulse.bot.messenger import Messenger
    from workpulse.bot.providers import my_number
    m = Messenger(cfg)
    num = my_number()
    console.print(f"Provider: [bold]{cfg.whatsapp.provider}[/] → "
                  + ("[green]configured[/]" if m.live else "[yellow]not configured: messages are dry-run logged only[/]"))
    console.print(f"Your number: {'+' + num[:4] + '…' + num[-3:] if num else '[red]MY_WHATSAPP_NUMBER not set in .env[/]'}")
    s = cfg.whatsapp.schedule
    console.print(f"Schedule: morning {s.morning or 'off'} · midday {s.midday or 'off'} · night {s.night or 'off'} · weekly {s.weekly or 'off'}")


def cmd_wa(args) -> None:
    from workpulse.bot.messenger import Messenger
    cfg = _cfg()
    _wa_status(cfg)
    if args.action == "test":
        ok = Messenger(cfg).send("👋 Hi from WorkPulse! Your WhatsApp coach is connected. Reply *help* to see what I can do.", kind="test")
        console.print("[green]Test message sent ✓[/]" if ok else "[red]Send failed; see the error above and data/logs[/]")


def cmd_bot(args) -> None:
    """Talk to the bot from the terminal exactly as if you'd sent a WhatsApp message."""
    from workpulse.bot import coach
    from workpulse.bot.commands import handle
    from workpulse.bot.messenger import Messenger
    cfg = _cfg()
    if args.facts:
        console.print(coach.build_facts(cfg))
        return
    reply = handle(cfg, " ".join(args.text), source="cli")
    console.print(Text(reply))  # plain text: WhatsApp's [brackets] aren't rich markup
    if args.send:
        Messenger(cfg).send(reply, kind="chat")
    else:  # keep the coach's chat memory consistent
        from workpulse.core.store import log_message
        log_message(cfg.db_path, "out", reply, kind="chat", status="local")


def cmd_report(args) -> None:
    from workpulse.bot import reports
    from workpulse.bot.scheduler import send_report
    cfg = _cfg()
    if args.send:
        ok = send_report(args.kind, cfg, force=True)
        console.print(f"{args.kind} report {'sent ✓' if ok else 'NOT sent (see logs)'}")
    else:
        console.print(Text(reports.build(cfg, args.kind)))
        console.print("\n[dim](preview only; add --send to send it)[/]")


def cmd_messages(args) -> None:
    from workpulse.core.store import recent_messages
    cfg = _cfg()
    for m in recent_messages(cfg.db_path, limit=args.n):
        arrow = "[cyan]→ you[/]" if m.direction == "out" else "[magenta]← you[/]"
        status = "" if m.status in ("sent", "received") else f" [yellow]({m.status}{': ' + m.error if m.error else ''})[/]"
        console.print(f"[dim]{datetime.fromtimestamp(m.ts):%d %b %H:%M}[/] {arrow} [dim]{m.kind}[/]{status}")
        console.print(Text(m.body))
        console.print()


def cmd_phone(args) -> None:
    """Phone screen time: setup token, import files, ADB pull (Android), manual add, show."""
    import subprocess

    from workpulse.backend.phone_api import PHONE_TOKEN_HEADER, phone_token
    from workpulse.core import phone
    from workpulse.core.stats import fmt_dur
    cfg = _cfg()
    if args.action == "token":
        console.print(f"Phone token: [bold]{phone_token(cfg)}[/]\nSend it as the [bold]{PHONE_TOKEN_HEADER}[/] header to "
                      f"POST {cfg.server.url}/api/phone/ingest (or https://<your-tunnel>/api/phone/ingest). See README → Phone.")
    elif args.action == "import":
        if not args.arg:
            console.print("Usage: workpulse phone import <file.csv|file.json> [--device phone]")
            return
        for row in phone.import_file(cfg, Path(args.arg), args.device):
            console.print(f"Saved {row.device} {row.day}: {fmt_dur(row.total_s)}")
    elif args.action == "pull-android":
        try:
            out = subprocess.run(["adb", "shell", "dumpsys", "usagestats"], capture_output=True, text=True, timeout=60)
        except FileNotFoundError:
            console.print("[red]adb not found.[/] Install it with: winget install Google.PlatformTools  (then enable USB debugging)")
            return
        if out.returncode != 0:
            console.print(f"[red]adb failed:[/] {out.stderr.strip() or out.stdout.strip()}")
            return
        data = phone.parse_adb_usagestats(out.stdout, device=args.device or cfg.phone.default_device)
        row = phone.save_day(cfg, data, "adb")
        console.print(f"Saved {row.device} {row.day}: {fmt_dur(row.total_s)} across {len(data.apps)} apps (experimental: compare with Digital Wellbeing)")
    elif args.action == "add":
        if not args.total and not args.app:
            console.print('Usage: workpulse phone add --total 3h20m --app "Instagram=1h10m" --app "WhatsApp=45m" [--date 2026-10-20]')
            return
        apps = []
        for a in args.app or []:
            name, _, t = a.partition("=")
            apps.append({"name": name.strip(), "time": t.strip()})
        items = phone.from_json(cfg, {"day": args.date, "device": args.device, "total": args.total, "pickups": args.pickups, "apps": apps})
        row = phone.save_day(cfg, items[0], "manual")
        console.print(f"Saved {row.device} {row.day}: {fmt_dur(row.total_s)}")
    else:
        d = date.fromisoformat(args.date) if args.date else date.today()
        dd = phone.digital_day(cfg, d)
        if not dd["has_phone_data"]:
            console.print(f"No phone data for {d}. Add some: workpulse phone add --total 3h --app \"Instagram=1h\"")
            return
        console.print(f"📱 Phone {fmt_dur(dd['phone_s'])} + 💻 laptop {fmt_dur(dd['laptop_active_s'])} = [bold]{fmt_dur(dd['total_s'])}[/] digital day"
                      + (f" · {dd['pickups']} pickups" if dd["pickups"] else ""))
        for a in dd["phone_top_apps"][:8]:
            console.print(f"  {a['app']:<22} {fmt_dur(a['seconds'])}")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="workpulse", description="Private laptop activity tracker + coach.")
    p.add_argument("--demo", action="store_true", help="use the separate demo database (see `workpulse demo seed`)")
    p.add_argument("--debug", action="store_true", help="show full error tracebacks")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("today", help="today's stats (or --yesterday / --date)")
    s.add_argument("--date"); s.add_argument("--yesterday", action="store_true"); s.set_defaults(fn=cmd_today)
    sub.add_parser("status", help="is tracking on, and what am I doing").set_defaults(fn=cmd_status)
    s = sub.add_parser("agent", help="run the tracker in this terminal (Ctrl+C to stop)")
    s.add_argument("--idle-after", type=float, help="override idle threshold (seconds) for testing")
    s.add_argument("--away-after", type=float, help="override away threshold (seconds) for testing")
    s.set_defaults(fn=cmd_agent)
    s = sub.add_parser("start", help="start the tracker + dashboard in the background")
    s.add_argument("--agent-only", action="store_true", help="don't start the dashboard server")
    s.set_defaults(fn=cmd_start)
    sub.add_parser("stop", help="stop the background tracker + dashboard").set_defaults(fn=cmd_stop)
    sub.add_parser("supervise", help="keep the tracker + dashboard running (what auto-start launches)").set_defaults(fn=cmd_supervise)
    s = sub.add_parser("panel", help="open the dashboard docked to the side of the screen (--left, --width N, --float, --close)")
    g = s.add_mutually_exclusive_group(); g.add_argument("--left", action="store_true"); g.add_argument("--right", action="store_true")
    g = s.add_mutually_exclusive_group(); g.add_argument("--float", action="store_true", help="a normal window; don't reserve the edge")
    g.add_argument("--dock", action="store_true")
    s.add_argument("--width", type=int, help="width in points (320-900, default 420)")
    s.add_argument("--close", action="store_true"); s.add_argument("--watch", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_panel)
    s = sub.add_parser("serve", help="run the API + dashboard in this terminal")
    s.add_argument("--port", type=int, help="override server.port (e.g. a demo dashboard next to the real one)")
    s.set_defaults(fn=cmd_serve)
    sub.add_parser("dashboard", help="open the dashboard in your browser").set_defaults(fn=cmd_dashboard)
    sub.add_parser("pause", help="pause tracking immediately").set_defaults(fn=cmd_pause)
    sub.add_parser("resume", help="resume tracking").set_defaults(fn=cmd_resume)
    s = sub.add_parser("autostart", help="start the tracker at login: on | off | status")
    s.add_argument("action", choices=["on", "off", "status"])
    s.add_argument("--panel", action=argparse.BooleanOptionalAction, help="also open the side panel at login")
    s.set_defaults(fn=cmd_autostart)
    s = sub.add_parser("doctor", help="health check with fixes + live readings of what the tracker sees")
    s.add_argument("-n", "--samples", type=int, default=1); s.set_defaults(fn=cmd_doctor)
    s = sub.add_parser("restart", help="restart the tracker + dashboard")
    s.add_argument("--server-only", action="store_true"); s.add_argument("--delay", type=float, default=0)
    s.set_defaults(fn=cmd_restart)
    s = sub.add_parser("lan", help="phone access over your Wi-Fi: on | off | status")
    s.add_argument("action", nargs="?", default="status", choices=["on", "off", "status"]); s.set_defaults(fn=cmd_lan)
    s = sub.add_parser("remote", help="phone access when you're out, via Tailscale: on | off | status")
    s.add_argument("action", nargs="?", default="status", choices=["on", "off", "status"]); s.set_defaults(fn=cmd_remote)
    sub.add_parser("connect", help="pair a phone: shows a code + QR code").set_defaults(fn=cmd_connect)
    s = sub.add_parser("devices", help="list paired phones (--remove <#> to unpair one)")
    s.add_argument("--remove", type=int); s.set_defaults(fn=cmd_devices)
    s = sub.add_parser("logs", help="show the end of a log: agent | server | supervisor | panel | cli")
    s.add_argument("name", nargs="?", default="server", choices=["agent", "server", "supervisor", "panel", "cli"])
    s.add_argument("-n", type=int, default=40); s.set_defaults(fn=cmd_logs)
    s = sub.add_parser("backup", help="back up the database to data/backups (--list to see them)")
    s.add_argument("--keep", type=int, default=14); s.add_argument("--list", action="store_true")
    s.set_defaults(fn=cmd_backup)
    s = sub.add_parser("demo", help="seed | clear demo data (separate DB)")
    s.add_argument("action", choices=["seed", "clear"]); s.add_argument("--days", type=int, default=14)
    s.set_defaults(fn=cmd_demo)
    s = sub.add_parser("wa", help="WhatsApp: status | test (send a test message)")
    s.add_argument("action", choices=["status", "test"]); s.set_defaults(fn=cmd_wa)
    s = sub.add_parser("bot", help='chat with the bot from the terminal, e.g. workpulse bot today')
    s.add_argument("text", nargs="*", default=["help"])
    s.add_argument("--send", action="store_true", help="also send the reply to your WhatsApp")
    s.add_argument("--facts", action="store_true", help="show the facts the AI coach sees")
    s.set_defaults(fn=cmd_bot)
    s = sub.add_parser("report", help="preview (or --send) a morning | midday | night | weekly report")
    s.add_argument("kind", choices=["morning", "midday", "night", "weekly"]); s.add_argument("--send", action="store_true")
    s.set_defaults(fn=cmd_report)
    s = sub.add_parser("messages", help="recent WhatsApp messages (local log)")
    s.add_argument("-n", type=int, default=10); s.set_defaults(fn=cmd_messages)
    s = sub.add_parser("phone", help="phone screen time: show | token | import <file> | add | pull-android")
    s.add_argument("action", choices=["show", "token", "import", "add", "pull-android"], nargs="?", default="show")
    s.add_argument("arg", nargs="?", help="file to import")
    s.add_argument("--device"); s.add_argument("--date"); s.add_argument("--total"); s.add_argument("--pickups", type=int)
    s.add_argument("--app", action="append", help='"Name=1h10m" (repeatable)')
    s.set_defaults(fn=cmd_phone)
    s = sub.add_parser("export", help="export all sessions to CSV"); s.add_argument("--out"); s.set_defaults(fn=cmd_export)
    s = sub.add_parser("wipe", help="delete ALL tracked data"); s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_wipe)
    return p


def main(argv: list[str] | None = None) -> None:
    import logging
    args = build_parser().parse_args(argv)
    if args.demo:
        os.environ["WORKPULSE_DEMO"] = "1"
    try:
        args.fn(args)
    except KeyboardInterrupt:
        console.print("\n[dim]Stopped.[/]")
        sys.exit(130)
    except Exception as e:
        if args.debug:
            raise
        try:  # full traceback to the log; one friendly line on screen
            from workpulse.logs import setup_logging
            setup_logging(_cfg(), "cli", console=False)
            logging.getLogger("workpulse.cli").exception("command %r failed", args.cmd)
            where = "details in data/logs/cli.log"
        except Exception:
            where = "run again with --debug for details"
        console.print(f"[red]✗ {type(e).__name__}:[/] {e}\n[dim]({where} · `.\\workpulse doctor` checks your setup)[/]")
        sys.exit(1)


if __name__ == "__main__":
    main()
