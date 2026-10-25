"""Pause/resume flag, single-instance PID file, background start/stop and login auto-start."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import psutil

from workpulse.config import ROOT, Config

AUTOSTART_NAME = "WorkPulseAgent"


# ---- pause -------------------------------------------------------------------------------------
# A flag file is used (not the DB) so pausing works instantly even if the DB is busy or the backend
# is down. The agent checks it every second and cuts the open session at the flag's mtime.

def is_paused(cfg: Config) -> bool:
    return cfg.pause_flag.exists()


def pause(cfg: Config) -> None:
    cfg.pause_flag.write_text("paused\n", encoding="utf-8")


def resume(cfg: Config) -> None:
    cfg.pause_flag.unlink(missing_ok=True)


def paused_since(cfg: Config) -> float | None:
    try:
        return cfg.pause_flag.stat().st_mtime
    except FileNotFoundError:
        return None


# ---- single instance / background processes ----------------------------------------------------
# Background processes: "agent" (tracking), "server" (API + dashboard), "supervisor" (keeps those two alive)
# and "panel" (the docked side panel's window watcher). Each writes its own pid file.

SUBCOMMANDS = {"agent": "agent", "server": "serve", "supervisor": "supervise", "panel": "panel"}
HOLD_FILE = "supervise.hold"  # while fresh, the supervisor doesn't restart anything (a restart is in progress)


def hold_supervisor(cfg: Config) -> None:
    (cfg.data_dir / HOLD_FILE).write_text("hold", encoding="utf-8")


def release_supervisor(cfg: Config) -> None:
    (cfg.data_dir / HOLD_FILE).unlink(missing_ok=True)


def _pid_file(cfg: Config, name: str) -> Path:
    # A demo dashboard (`workpulse --demo serve`) can run next to the real one.
    suffix = "-demo" if name == "server" and cfg.demo else ""
    return cfg.data_dir / f"{name}{suffix}.pid"


def running_pid(cfg: Config, name: str = "agent") -> int | None:
    try:
        pid = int(_pid_file(cfg, name).read_text().strip())
    except (FileNotFoundError, ValueError):
        return None
    try:
        cmd = " ".join(psutil.Process(pid).cmdline()).lower()
        if "workpulse" in cmd and SUBCOMMANDS[name] in cmd:
            return pid
    except psutil.Error:
        pass
    return None


def write_pid(cfg: Config, name: str = "agent") -> None:
    _pid_file(cfg, name).write_text(str(os.getpid()), encoding="utf-8")


def clear_pid(cfg: Config, name: str = "agent") -> None:
    if running_pid(cfg, name) in (None, os.getpid()):
        _pid_file(cfg, name).unlink(missing_ok=True)


def _pythonw() -> str:
    exe = Path(sys.executable)
    if sys.platform == "win32":
        w = exe.with_name("pythonw.exe")
        if w.exists():
            return str(w)
    return str(exe)


def command(name: str = "agent", *extra: str) -> list[str]:
    return [_pythonw(), "-m", "workpulse", SUBCOMMANDS[name], *extra]


def spawn_detached(cmd: list[str]) -> int:
    kwargs: dict = dict(cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    return subprocess.Popen(cmd, **kwargs).pid


def start_background(cfg: Config, name: str = "agent", *extra: str) -> int:
    if pid := running_pid(cfg, name):
        return pid
    return spawn_detached(command(name, *extra))


def stop_background(cfg: Config, name: str = "agent") -> bool:
    pid = running_pid(cfg, name)
    if not pid:
        return False
    stop_flag = cfg.data_dir / ("stop.flag" if name == "agent" else f"{name}.stop")
    if name in ("agent", "supervisor"):
        # Ask nicely via a stop flag so the agent flushes its open session; force after a timeout.
        stop_flag.write_text("stop", encoding="utf-8")
    try:
        p = psutil.Process(pid)
        if name not in ("agent", "supervisor"):
            p.terminate()
        p.wait(timeout=8)
    except psutil.TimeoutExpired:
        psutil.Process(pid).kill()
    except psutil.NoSuchProcess:
        pass
    stop_flag.unlink(missing_ok=True)
    _pid_file(cfg, name).unlink(missing_ok=True)
    return True


def restart_server_later(delay: float = 1.5) -> None:
    """Spawn a detached helper that stops and restarts the dashboard server (used after Wi-Fi access changes)."""
    spawn_detached([_pythonw(), "-m", "workpulse", "restart", "--server-only", "--delay", str(delay)])


# ---- shortcuts (Windows) -------------------------------------------------------------------------

def _shell_folder(*parts: str) -> Path:
    return Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / Path(*parts)


def startup_shortcut() -> Path:
    return _shell_folder("Startup", "WorkPulse.lnk")


def make_shortcut(path: Path, target: str, args: str, description: str, icon: str | None = None) -> None:
    """Create a .lnk with the Windows Script Host (built into Windows, no admin needed)."""
    def q(v: str) -> str:  # PowerShell single-quoted string
        return "'" + v.replace("'", "''") + "'"
    path.parent.mkdir(parents=True, exist_ok=True)
    ps = (f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut({q(str(path))}); "
          f"$s.TargetPath = {q(target)}; $s.Arguments = {q(args)}; $s.WorkingDirectory = {q(str(ROOT))}; "
          f"$s.Description = {q(description)}; " + (f"$s.IconLocation = {q(icon)}; " if icon else "") + "$s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps], check=True, capture_output=True, timeout=30)


def make_panel_shortcut() -> Path:
    """Start Menu "WorkPulse Panel": opens the docked side panel."""
    lnk = _shell_folder("WorkPulse Panel.lnk")
    icon = ROOT / "dashboard" / "m" / "icon.ico"
    make_shortcut(lnk, _pythonw(), "-m workpulse panel", "WorkPulse dashboard docked to the side of the screen",
                  str(icon) if icon.exists() else None)
    return lnk


# ---- auto-start at login -----------------------------------------------------------------------
# Windows: a shortcut in the per-user Startup folder (no admin needed; visible in Task Manager → Startup apps).
# It launches the supervisor, which starts the tracker + dashboard and restarts them if they ever stop.
# (Older versions used the HKCU "Run" registry list; other apps can rewrite that list, so it's migrated away.)
# macOS: a LaunchAgent plist. Linux: a systemd --user unit.

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _remove_legacy_run_value() -> None:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, AUTOSTART_NAME)
    except FileNotFoundError:
        pass


def _legacy_run_value_exists() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, AUTOSTART_NAME)
            return True
    except FileNotFoundError:
        return False


def autostart_status() -> bool:
    if sys.platform == "win32":
        return startup_shortcut().exists() or _legacy_run_value_exists()
    if sys.platform == "darwin":
        return _launchd_plist().exists()
    return _systemd_unit().exists()


def autostart_enable() -> str:
    if sys.platform == "win32":
        lnk = startup_shortcut()
        make_shortcut(lnk, _pythonw(), "-m workpulse supervise", "WorkPulse: keeps the tracker and dashboard running",
                      str(ROOT / "dashboard" / "m" / "icon.ico") if (ROOT / "dashboard" / "m" / "icon.ico").exists() else None)
        _remove_legacy_run_value()  # one launcher only, never two
        return f"Added {lnk.name} to your Startup folder (starts WorkPulse hidden at every login and keeps it running)"
    if sys.platform == "darwin":
        p = _launchd_plist()
        p.parent.mkdir(parents=True, exist_ok=True)
        args = "".join(f"<string>{a}</string>" for a in command("supervisor"))
        p.write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
            '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0"><dict>'
            f"<key>Label</key><string>com.workpulse.agent</string><key>ProgramArguments</key><array>{args}</array>"
            f"<key>WorkingDirectory</key><string>{ROOT}</string><key>RunAtLoad</key><true/><key>KeepAlive</key><true/>"
            "</dict></plist>\n", encoding="utf-8")
        subprocess.run(["launchctl", "load", str(p)], check=False)
        return f"Installed {p}"
    u = _systemd_unit()
    u.parent.mkdir(parents=True, exist_ok=True)
    u.write_text(
        "[Unit]\nDescription=WorkPulse activity agent\n\n[Service]\n"
        f"WorkingDirectory={ROOT}\nExecStart={' '.join(command('supervisor'))}\nRestart=on-failure\n\n"
        "[Install]\nWantedBy=default.target\n", encoding="utf-8")
    subprocess.run(["systemctl", "--user", "enable", "--now", "workpulse.service"], check=False)
    return f"Installed {u}"


def autostart_disable() -> str:
    if sys.platform == "win32":
        startup_shortcut().unlink(missing_ok=True)
        _remove_legacy_run_value()
        return "Removed WorkPulse from your Startup folder"
    if sys.platform == "darwin":
        p = _launchd_plist()
        subprocess.run(["launchctl", "unload", str(p)], check=False)
        p.unlink(missing_ok=True)
        return "Removed LaunchAgent"
    subprocess.run(["systemctl", "--user", "disable", "--now", "workpulse.service"], check=False)
    _systemd_unit().unlink(missing_ok=True)
    return "Removed systemd user unit"


def _launchd_plist() -> Path:
    return Path.home() / "Library/LaunchAgents/com.workpulse.agent.plist"


def _systemd_unit() -> Path:
    return Path.home() / ".config/systemd/user/workpulse.service"
