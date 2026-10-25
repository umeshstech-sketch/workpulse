"""The tracking loop: sample every few seconds, merge into sessions, flush to storage in batches."""
from __future__ import annotations

import json
import logging
import os
import threading
import time

from workpulse.agent import control
from workpulse.agent.platforms.base import Platform, get_platform
from workpulse.agent.sinks import Sink, make_sink, record_payload
from workpulse.config import Config, config_mtime, load_config
from workpulse.core.categorize import scrub
from workpulse.core.models import Sample, SessionRecord
from workpulse.core.state import SessionTracker
from workpulse.logs import setup_logging  # noqa: F401  (re-exported for the CLI)

log = logging.getLogger("workpulse.agent")
RELOAD_CHECK_S = 10


class Agent:
    def __init__(self, cfg: Config, platform: Platform | None = None, sink: Sink | None = None,
                 tracking_overrides: dict | None = None) -> None:
        self.cfg = cfg
        self.platform = platform or get_platform()
        self.sink = sink or make_sink(cfg)
        self.overrides = tracking_overrides or {}  # CLI test flags survive config reloads
        self._apply_overrides()
        t = cfg.tracking
        self.tracker = SessionTracker(
            idle_after=t.idle_after_s, away_after=t.away_after_s,
            gap_tolerance=max(30.0, 4 * t.sample_interval_s), keep_titles=cfg.privacy.capture_titles,
        )
        self.pending: dict[str, SessionRecord] = {}  # closed sessions not yet persisted (buffer)
        self.stop_event = threading.Event()
        self._cfg_mtime = config_mtime()

    @property
    def outbox(self):
        return self.cfg.data_dir / "outbox.jsonl"

    def _apply_overrides(self) -> None:
        for k, v in self.overrides.items():
            setattr(self.cfg.tracking, k, v)

    def maybe_reload_config(self) -> None:
        """Pick up edits from config.yaml or the dashboard's Settings without restarting."""
        m = config_mtime()
        if m == self._cfg_mtime:
            return
        self._cfg_mtime = m
        try:
            new = load_config()
        except Exception:
            log.exception("config reload failed; keeping the old settings")
            return
        self.cfg = new
        self._apply_overrides()
        t = new.tracking
        self.tracker.idle_after, self.tracker.away_after = t.idle_after_s, t.away_after_s
        self.tracker.gap_tolerance = max(30.0, 4 * t.sample_interval_s)
        self.tracker.keep_titles = new.privacy.capture_titles
        log.info("config reloaded (idle=%ss away=%ss titles=%s)", t.idle_after_s, t.away_after_s,
                 new.privacy.capture_titles)

    def sample(self, now: float) -> Sample:
        raw_app, raw_title = self.platform.active_window()
        app, title, category = scrub(raw_app, raw_title, self.cfg.categories, self.cfg.privacy)
        return Sample(ts=now, idle_seconds=self.platform.idle_seconds(), locked=self.platform.is_locked(),
                      app=app, title=title, category=category)

    # ---- buffering: pending sessions survive a crash/restart via data/outbox.jsonl ----------------

    def load_outbox(self) -> None:
        if not self.outbox.exists():
            return
        for line in self.outbox.read_text(encoding="utf-8").splitlines():
            try:
                rec = SessionRecord(**json.loads(line))
                self.pending[rec.id] = rec
            except (ValueError, TypeError):
                continue
        log.info("loaded %d buffered sessions from outbox", len(self.pending))

    def _save_outbox(self, batch: list[SessionRecord]) -> None:
        tmp = self.outbox.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(record_payload(r)) + "\n" for r in batch), encoding="utf-8")
        tmp.replace(self.outbox)

    def flush(self) -> None:
        batch = list(self.pending.values())
        if self.tracker.current is not None:
            batch.append(self.tracker.current)
        if not batch:
            return
        try:
            self.sink.write(batch)
            self.pending.clear()
            for rec in batch:
                rec.saved = True
            self.outbox.unlink(missing_ok=True)
        except Exception as e:  # keep buffering; retried at the next flush
            log.warning("flush failed (%s); %d sessions buffered", e, len(batch))
            try:
                self._save_outbox(batch)
            except OSError:
                log.exception("could not write outbox")

    def _stop_requested(self) -> bool:
        return self.stop_event.is_set() or (self.cfg.data_dir / "stop.flag").exists()

    def run(self) -> None:
        cfg = self.cfg
        if (pid := control.running_pid(cfg)) and pid != os.getpid():
            log.warning("agent already running (pid %s); exiting", pid)
            return
        control.write_pid(cfg)
        (cfg.data_dir / "stop.flag").unlink(missing_ok=True)  # stale request from a crashed stop
        log.info("agent started on %s (sample=%ss idle=%ss away=%ss titles=%s sink=%s)", self.platform.name,
                 cfg.tracking.sample_interval_s, cfg.tracking.idle_after_s, cfg.tracking.away_after_s,
                 cfg.privacy.capture_titles, cfg.agent.mode)
        self.load_outbox()
        last_sample = last_flush = last_reload = 0.0
        was_paused = False
        last_state = None
        try:
            while not self._stop_requested():
                now = time.time()
                if now - last_reload >= RELOAD_CHECK_S:
                    self.maybe_reload_config()
                    last_reload = now
                if control.is_paused(self.cfg):
                    if not was_paused:
                        # Cut at the moment pause was requested, then persist immediately.
                        closed = self.tracker.close(control.paused_since(self.cfg) or now)
                        if closed:
                            self.pending[closed.id] = closed
                        self.flush()
                        log.info("tracking PAUSED")
                        was_paused, last_state = True, None
                    self.stop_event.wait(1)
                    continue
                if was_paused:
                    log.info("tracking RESUMED")
                    was_paused = False
                if now - last_sample >= self.cfg.tracking.sample_interval_s:
                    try:
                        for rec in self.tracker.feed(self.sample(now)):
                            self.pending[rec.id] = rec
                    except Exception:
                        log.exception("sample failed")
                    last_sample = now
                    cur = self.tracker.current
                    if cur and cur.state != last_state:
                        log.info("state -> %s (%s)", cur.state, cur.app or "-")
                        last_state = cur.state
                if now - last_flush >= self.cfg.tracking.flush_interval_s:
                    self.flush()
                    last_flush = now
                self.stop_event.wait(1)
        except KeyboardInterrupt:
            pass
        finally:
            closed = self.tracker.close(time.time())
            if closed:
                self.pending[closed.id] = closed
            self.flush()
            control.clear_pid(self.cfg)
            log.info("agent stopped")
