"""Where the agent sends sessions. Phase 2 default is `auto`: POST to the local backend, and if it isn't
running write straight into the SQLite DB (same machine), so data never gets stuck."""
from __future__ import annotations

import json
import logging
import secrets
import urllib.error
import urllib.request
from dataclasses import asdict
from typing import Protocol

from workpulse.config import Config
from workpulse.core.db import upsert_sessions
from workpulse.core.models import SessionRecord

log = logging.getLogger("workpulse.agent")
TOKEN_HEADER = "X-WorkPulse-Token"


class Sink(Protocol):
    def write(self, records: list[SessionRecord]) -> None: ...


def agent_token(cfg: Config) -> str:
    """Shared secret between agent and backend so nothing else on the machine can inject activity."""
    p = cfg.data_dir / "agent.token"
    if not p.exists():
        p.write_text(secrets.token_urlsafe(24), encoding="utf-8")
    return p.read_text(encoding="utf-8").strip()


def record_payload(r: SessionRecord) -> dict:
    d = asdict(r)
    d.pop("saved", None)
    return d


class DbSink:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg

    def write(self, records: list[SessionRecord]) -> None:
        upsert_sessions(self.cfg.db_path, records)


class HttpSink:
    def __init__(self, cfg: Config, timeout: float = 3.0) -> None:
        self.url = f"{cfg.server.url}/api/ingest/sessions"
        self.token = agent_token(cfg)
        self.timeout = timeout

    def write(self, records: list[SessionRecord]) -> None:
        body = json.dumps({"sessions": [record_payload(r) for r in records]}).encode()
        req = urllib.request.Request(self.url, data=body, method="POST",
                                     headers={"Content-Type": "application/json", TOKEN_HEADER: self.token})
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            if resp.status != 200:
                raise RuntimeError(f"backend returned {resp.status}")


class AutoSink:
    def __init__(self, cfg: Config) -> None:
        self.http, self.db = HttpSink(cfg), DbSink(cfg)
        self.using_http: bool | None = None

    def write(self, records: list[SessionRecord]) -> None:
        try:
            self.http.write(records)
            ok = True
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError):
            self.db.write(records)
            ok = False
        if ok != self.using_http:
            log.info("sending sessions via %s", "backend" if ok else "local DB (backend not running)")
            self.using_http = ok


def make_sink(cfg: Config) -> Sink:
    return {"auto": AutoSink, "http": HttpSink, "direct": DbSink}[cfg.agent.mode](cfg)
