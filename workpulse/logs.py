"""Logging: one rotating file per process (agent.log, server.log, cli.log) in data/logs, plus the console
when there is one. Set WORKPULSE_LOG_LEVEL=DEBUG in .env for more detail."""
from __future__ import annotations

import logging
import os
import sys
from collections import deque
from logging.handlers import RotatingFileHandler

from workpulse.config import Config

LOG_NAMES = ("agent", "server", "cli")


def setup_logging(cfg: Config, name: str = "agent", console: bool = True) -> None:
    root = logging.getLogger("workpulse")
    if root.handlers:
        return
    level = getattr(logging, os.environ.get("WORKPULSE_LOG_LEVEL", "INFO").upper(), logging.INFO)
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = RotatingFileHandler(cfg.log_dir / f"{name}.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if console and sys.stderr is not None:  # pythonw has no console
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)


def tail(cfg: Config, name: str, n: int = 40) -> list[str]:
    path = cfg.log_dir / f"{name}.log"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", errors="replace") as f:
        return list(deque(f, maxlen=n))
