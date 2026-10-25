"""macOS implementation (best-effort, untested on real hardware yet).

Idle time comes from IOKit's HIDIdleTime; the front app via AppleScript (needs Accessibility permission
for window titles)."""
from __future__ import annotations

import re
import subprocess

from workpulse.agent.platforms.base import Platform


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=3).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ""


class MacPlatform(Platform):
    name = "macos"

    def idle_seconds(self) -> float:
        m = re.search(r'"HIDIdleTime" = (\d+)', _run(["ioreg", "-c", "IOHIDSystem"]))
        return int(m.group(1)) / 1e9 if m else 0.0

    def active_window(self) -> tuple[str | None, str | None]:
        script = (
            'tell application "System Events" to set p to first application process whose frontmost is true\n'
            'set n to name of p\n'
            'try\n set t to name of front window of p\non error\n set t to ""\nend try\n'
            'return n & "\\n" & t'
        )
        out = _run(["osascript", "-e", script]).split("\n", 1)
        app = out[0] or None
        title = out[1] if len(out) > 1 and out[1] else None
        return app, title

    def is_locked(self) -> bool:
        # The key only appears in IOConsoleUsers while the screen is locked.
        return '"CGSSessionScreenIsLocked"=Yes' in _run(["ioreg", "-n", "Root", "-d1"]).replace(" ", "")
