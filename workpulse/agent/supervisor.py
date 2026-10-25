"""Keeps the tracker and the dashboard running ("always on").

Started at login (Startup folder) or by `workpulse start`. Every CHECK_S seconds it starts whichever of the
two isn't running. If one keeps dying it backs off (5 restarts in 10 minutes → wait 10 minutes) instead of
spinning. `workpulse stop` stops the supervisor first, so stopping on purpose is respected.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque

from workpulse.agent import control
from workpulse.config import Config, get_config

log = logging.getLogger("workpulse.supervisor")
CHECK_S = 15
WINDOW_S = 600
MAX_RESTARTS = 5
HOLD_MAX_AGE_S = 60
MANAGED = ("agent", "server")


class Supervisor:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.starts: dict[str, deque[float]] = {n: deque() for n in MANAGED}
        self.gave_up: dict[str, bool] = dict.fromkeys(MANAGED, False)
        self.stop_event = threading.Event()
        self.first_pass = True

    def _held(self) -> bool:
        hold = self.cfg.data_dir / control.HOLD_FILE
        try:
            return time.time() - hold.stat().st_mtime < HOLD_MAX_AGE_S
        except FileNotFoundError:
            return False

    def _stop_requested(self) -> bool:
        return self.stop_event.is_set() or (self.cfg.data_dir / "supervisor.stop").exists()

    def check_once(self, now: float | None = None) -> list[str]:
        """Start anything that isn't running. Returns the names started (for tests/logs)."""
        now = now or time.time()
        if self._held():
            return []
        started = []
        for name in MANAGED:
            if control.running_pid(self.cfg, name):
                self.gave_up[name] = False
                continue
            recent = self.starts[name]
            while recent and now - recent[0] > WINDOW_S:
                recent.popleft()
            if len(recent) >= MAX_RESTARTS:
                if not self.gave_up[name]:
                    log.error("%s keeps stopping (%d starts in %d min); pausing restarts. See .\\workpulse logs %s",
                              name, len(recent), WINDOW_S // 60, "agent" if name == "agent" else "server")
                    self.gave_up[name] = True
                continue
            log.info("%s %s", "starting" if self.first_pass else "restarting (it had stopped)", name)
            control.start_background(self.cfg, name)
            recent.append(now)
            started.append(name)
        return started

    def run(self) -> None:
        cfg = self.cfg
        if (pid := control.running_pid(cfg, "supervisor")) and pid != os.getpid():
            log.info("supervisor already running (pid %s)", pid)
            return
        control.write_pid(cfg, "supervisor")
        (cfg.data_dir / "supervisor.stop").unlink(missing_ok=True)
        log.info("supervisor started")
        try:
            while not self._stop_requested():
                try:
                    self.check_once()
                except Exception:
                    log.exception("supervisor check failed")
                if self.first_pass:
                    self.first_pass = False
                    if cfg.startup.panel:
                        time.sleep(5)  # give the dashboard a moment to come up
                        control.start_background(cfg, "panel", "--watch")
                for _ in range(CHECK_S):
                    if self._stop_requested():
                        break
                    self.stop_event.wait(1)
        finally:
            control.clear_pid(cfg, "supervisor")
            log.info("supervisor stopped")


def main() -> None:
    from workpulse.logs import setup_logging
    cfg = get_config()
    setup_logging(cfg, "supervisor")
    Supervisor(cfg).run()
