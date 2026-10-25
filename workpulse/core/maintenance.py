"""Housekeeping: database backups and the `workpulse doctor` health check."""
from __future__ import annotations

import os
import socket
import sqlite3
import sys
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from workpulse.config import Config, config_path, load_config, settings_path


# ---- backups -----------------------------------------------------------------------------------

def backup(cfg: Config, keep: int = 14) -> Path:
    """Consistent copy of the DB using SQLite's online backup API (safe while the tracker is writing).
    Keeps the newest `keep` backups."""
    dest_dir = cfg.data_dir / "backups"
    dest_dir.mkdir(exist_ok=True)
    stem = cfg.db_path.stem
    dest = dest_dir / f"{stem}-{datetime.now():%Y%m%d-%H%M%S}.db"
    src = sqlite3.connect(cfg.db_path, timeout=30)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    old = sorted(dest_dir.glob(f"{stem}-*.db"))[:-keep] if keep > 0 else []
    for p in old:
        p.unlink(missing_ok=True)
    return dest


def list_backups(cfg: Config) -> list[Path]:
    return sorted((cfg.data_dir / "backups").glob(f"{cfg.db_path.stem}-*.db"))


# ---- doctor ------------------------------------------------------------------------------------

@dataclass
class Check:
    name: str
    status: str  # ok | warn | fail
    detail: str
    fix: str = ""


def _port_free(host: str, port: int) -> bool:
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) != 0


def run_checks(cfg: Config) -> list[Check]:
    from workpulse.agent import control
    from workpulse.bot.providers import get_provider, my_number
    from workpulse.core.db import latest_session

    out: list[Check] = []
    v = sys.version_info
    out.append(Check("Python", "ok" if v >= (3, 11) else "fail", f"{v.major}.{v.minor}.{v.micro}",
                     "" if v >= (3, 11) else "Install Python 3.11+ and re-run scripts\\install.cmd"))

    try:
        load_config(config_path())
        detail = "config.yaml OK" + (" + data/settings.yaml" if settings_path().exists() else "")
        load_config()
        out.append(Check("Config", "ok", detail))
    except Exception as e:
        out.append(Check("Config", "fail", f"invalid: {str(e).splitlines()[0]}",
                         "Fix the value in config.yaml, or delete data/settings.yaml to undo dashboard changes"))

    try:
        probe = cfg.data_dir / ".write-test"
        probe.write_text("ok")
        probe.unlink()
        con = sqlite3.connect(cfg.db_path, timeout=10)
        res = con.execute("PRAGMA quick_check").fetchone()[0]
        size = sum(p.stat().st_size for p in (cfg.db_path, cfg.db_path.with_name(cfg.db_path.name + "-wal")) if p.exists()) / 1e6
        con.close()
        out.append(Check("Database", "ok" if res == "ok" else "fail", f"{cfg.db_path.name} · {size:.1f} MB · integrity {res}",
                         "" if res == "ok" else "Restore the newest file from data/backups (see docs/troubleshooting.md)"))
    except Exception as e:
        out.append(Check("Database", "fail", str(e), "Check that the data folder isn't read-only or synced by OneDrive"))

    backups = list_backups(cfg)
    if backups:
        age_h = (time.time() - backups[-1].stat().st_mtime) / 3600
        out.append(Check("Backups", "ok" if age_h < 48 else "warn", f"{len(backups)} kept, newest {age_h:.0f}h ago",
                         "" if age_h < 48 else "Run: .\\workpulse backup  (the dashboard server also backs up daily)"))
    else:
        out.append(Check("Backups", "warn", "none yet", "Run: .\\workpulse backup  (the dashboard server backs up daily at 03:30)"))

    agent = control.running_pid(cfg, "agent")
    if control.is_paused(cfg):
        out.append(Check("Tracker", "warn", "paused", "Resume with: .\\workpulse resume"))
    elif agent:
        s = latest_session(cfg.db_path)
        age = time.time() - s.end_ts if s else None
        ok = age is not None and age < cfg.tracking.flush_interval_s * 4
        out.append(Check("Tracker", "ok" if ok else "warn", f"running (pid {agent})" + (f", last data {age:.0f}s ago" if age is not None else ""),
                         "" if ok else "If this persists, check data\\logs\\agent.log"))
    else:
        out.append(Check("Tracker", "fail", "not running", "Start it: .\\workpulse start"))

    server = control.running_pid(cfg, "server")
    if server:
        try:
            with urllib.request.urlopen(f"{cfg.server.url}/api/status", timeout=3) as r:
                out.append(Check("Dashboard", "ok", f"{cfg.server.url} (pid {server}, HTTP {r.status})"))
        except Exception as e:
            out.append(Check("Dashboard", "fail", f"process up but not answering ({e})", "See data\\logs\\server.log"))
    elif not _port_free(cfg.server.host, cfg.server.port):
        out.append(Check("Dashboard", "fail", f"port {cfg.server.port} is used by another program",
                         "Set server.port in config.yaml (e.g. 8790), then .\\workpulse start"))
    else:
        out.append(Check("Dashboard", "warn", "not running", "Start it: .\\workpulse start"))

    out.append(Check("Auto-start", "ok" if control.autostart_status() else "warn",
                     "on" if control.autostart_status() else "off", "" if control.autostart_status() else "Enable: .\\workpulse autostart on"))

    p = get_provider(cfg.whatsapp.provider)
    if not cfg.whatsapp.enabled:
        out.append(Check("WhatsApp", "warn", "disabled in config.yaml"))
    elif p.configured():
        out.append(Check("WhatsApp", "ok", f"{cfg.whatsapp.provider} configured, sending to +{my_number()[:4]}…{my_number()[-3:]}"))
    else:
        missing = "MY_WHATSAPP_NUMBER" if not my_number() else f"{cfg.whatsapp.provider} credentials"
        out.append(Check("WhatsApp", "warn", f"not configured ({missing} missing): messages are dry-run logged",
                         "Follow docs/whatsapp.md, then .\\workpulse wa test"))

    from workpulse.core.devices import list_devices
    n_dev = len(list_devices(cfg))
    if not cfg.server.lan:
        out.append(Check("Phone app", "ok" if not n_dev else "warn", "Wi-Fi access off (laptop only)",
                         "" if not n_dev else "Paired phones can't connect until you run .\\workpulse lan on"))
    else:
        from workpulse.backend.pairing_api import lan_status
        st = lan_status(cfg)
        out.append(Check("Phone app", "warn" if st["warnings"] else "ok",
                         f"Wi-Fi access on · {st['url'] or 'no Wi-Fi address'} · {n_dev} phone(s) paired",
                         " / ".join(st["warnings"]) or ("" if n_dev else "Pair your phone: .\\workpulse connect")))

    if cfg.server.remote:
        from workpulse.backend.pairing_api import remote_status
        rs = remote_status(cfg)
        out.append(Check("Away access", "warn" if rs["warnings"] else "ok",
                         f"on via Tailscale · {rs['url'] or 'no Tailscale address'}", " / ".join(rs["warnings"])))

    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    out.append(Check("AI coach", "ok" if has_key else "warn",
                     f"ANTHROPIC_API_KEY set · model {cfg.coach.model}" if has_key else "no ANTHROPIC_API_KEY: using templates",
                     "" if has_key else "Optional: add ANTHROPIC_API_KEY to .env and restart"))
    return out
