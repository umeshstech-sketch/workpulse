"""Linux/X11 implementation (best-effort). Needs `xprintidle` and `xdotool` installed.
Wayland sessions generally don't expose the focused window to other apps."""
from __future__ import annotations

import subprocess

import psutil

from workpulse.agent.platforms.base import Platform


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


class LinuxPlatform(Platform):
    name = "linux"

    def idle_seconds(self) -> float:
        out = _run(["xprintidle"])
        return int(out) / 1000.0 if out.isdigit() else 0.0

    def active_window(self) -> tuple[str | None, str | None]:
        title = _run(["xdotool", "getactivewindow", "getwindowname"]) or None
        pid = _run(["xdotool", "getactivewindow", "getwindowpid"])
        app = None
        if pid.isdigit():
            try:
                app = psutil.Process(int(pid)).name()
            except psutil.Error:
                pass
        return app, title

    def is_locked(self) -> bool:
        out = _run(["loginctl", "show-session", "self", "-p", "LockedHint"])
        return out.strip().endswith("yes")
