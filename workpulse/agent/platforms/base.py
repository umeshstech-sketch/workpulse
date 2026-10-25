"""OS abstraction. Each platform answers three questions and nothing more:
how long since the last input, which window is in front, and is the screen locked."""
from __future__ import annotations

import sys
from abc import ABC, abstractmethod


class Platform(ABC):
    name = "base"

    @abstractmethod
    def idle_seconds(self) -> float:
        """Seconds since last keyboard/mouse input, from the OS. Never reads WHICH key/what was typed."""

    @abstractmethod
    def active_window(self) -> tuple[str | None, str | None]:
        """(process name, window title) of the foreground window."""

    def is_locked(self) -> bool:
        return False


def get_platform() -> Platform:
    if sys.platform == "win32":
        from workpulse.agent.platforms.windows import WindowsPlatform
        return WindowsPlatform()
    if sys.platform == "darwin":
        from workpulse.agent.platforms.macos import MacPlatform
        return MacPlatform()
    from workpulse.agent.platforms.linux import LinuxPlatform
    return LinuxPlatform()
