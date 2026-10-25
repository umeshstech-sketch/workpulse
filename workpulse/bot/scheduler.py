"""Background jobs inside the backend process: scheduled reports, nudges and task reminders.

Robust to a laptop that sleeps and restarts:
- every send is deduped per kind per day (messages table), so a restart never double-sends;
- missed reports run when the server comes back, if still within CATCH_UP_H hours of the scheduled time;
- nothing proactive while tracking is paused; nudges respect quiet hours.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import date, datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from workpulse.agent import control
from workpulse.bot import reports
from workpulse.bot.messenger import Messenger
from workpulse.config import Config, get_config
from workpulse.core.db import latest_session
from workpulse.core.service import day_stats
from workpulse.core.stats import fmt_dur
from workpulse.core.store import mark_reminded, sent_today, tasks_due_for_reminder

log = logging.getLogger("workpulse.bot")
CATCH_UP_H = 2
_send_lock = threading.Lock()  # catch-up and a cron firing in the same minute must not both send
DOW = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def parse_hm(s: str) -> tuple[int, int] | None:
    try:
        h, m = s.strip().split(":")
        return int(h), int(m)
    except (ValueError, AttributeError):
        return None


def parse_weekly(s: str) -> tuple[int, int, int] | None:
    """'sun 19:00' -> (6, 19, 0)."""
    try:
        d, hm = s.strip().lower().split()
        h, m = parse_hm(hm)  # type: ignore[misc]
        return DOW[d[:3]], h, m
    except (ValueError, KeyError, TypeError):
        return None


def in_window(now: datetime, start: str, end: str) -> bool:
    """Is now within [start, end) local time? Handles windows that cross midnight."""
    a, b = parse_hm(start), parse_hm(end)
    if not a or not b:
        return False
    cur, s, e = now.hour * 60 + now.minute, a[0] * 60 + a[1], b[0] * 60 + b[1]
    return s <= cur < e if s <= e else (cur >= s or cur < e)


def send_report(kind: str, cfg: Config | None = None, force: bool = False) -> bool:
    """Build + send one report unless it already went out today."""
    cfg = cfg or get_config()
    if cfg.demo:
        return False
    with _send_lock:
        return _send_report_locked(kind, cfg, force)


def _send_report_locked(kind: str, cfg: Config, force: bool) -> bool:
    if not force and sent_today(cfg.db_path, kind):
        log.info("report %s already sent today; skipping", kind)
        return False
    if not force and control.is_paused(cfg) and kind != "morning":
        log.info("tracking paused; skipping %s report", kind)
        return False
    try:
        body = reports.build(cfg, kind)
    except Exception:
        log.exception("building %s report failed", kind)
        return False
    return Messenger(cfg).send(body, kind=kind)


def _nudge_once(cfg: Config, kind: str, body: str) -> None:
    if not sent_today(cfg.db_path, kind):
        Messenger(cfg).send(body, kind=kind)


def check_nudges(cfg: Config | None = None, now: datetime | None = None) -> None:
    cfg = cfg or get_config()
    n = cfg.whatsapp.nudges
    now = now or datetime.now()
    if cfg.demo or not n.enabled or control.is_paused(cfg) or in_window(now, *n.quiet_hours):
        return

    # Task reminders (one message listing everything newly due soon).
    due = tasks_due_for_reminder(cfg.db_path, n.task_reminder_hours, now)
    if due:
        today = now.date().isoformat()
        lines = ["⏰ *Task reminder*"]
        for t in due:
            when = "overdue!" if t.due < today else ("today" if t.due == today else f"due {date.fromisoformat(t.due):%a %d %b}")
            lines.append(f"- #{t.id} {'You' if t.owner == 'me' else t.owner}: {t.text} ({when})")
        lines.append("Done? Reply *task done <n>*")
        if Messenger(cfg).send("\n".join(lines), kind="reminder"):
            mark_reminded(cfg.db_path, [t.id for t in due])

    st = day_stats(cfg, now.date())
    # Entertainment: once per threshold crossed (1h, 2h, ...), per day.
    if n.entertainment_min > 0 and st.entertainment_s >= n.entertainment_min * 60:
        level = int(st.entertainment_s // (n.entertainment_min * 60))
        _nudge_once(cfg, f"nudge-ent{level}",
                    f"🎮 Gentle nudge: {fmt_dur(st.entertainment_s)} of Entertainment today. "
                    f"Fun is good! Want to switch to a 25-min focus sprint? Reply *plan* for ideas 🚀")

    # Idle: laptop on (agent running, recent samples) but no input for a long stretch, in work hours.
    if n.idle_min > 0 and in_window(now, *n.work_hours) and control.running_pid(cfg):
        s = latest_session(cfg.db_path)
        if s and s.state in ("idle", "away") and time.time() - s.end_ts < 120 and s.duration >= n.idle_min * 60:
            _nudge_once(cfg, "nudge-idle",
                        f"👋 Your laptop has been idle for {fmt_dur(s.duration)}. Taking a break, or stuck? "
                        f"Reply *plan* and I'll suggest a restart 🔄")


def daily_backup(cfg: Config, only_if_older_h: float | None = None) -> None:
    from workpulse.core.maintenance import backup, list_backups
    try:
        existing = list_backups(cfg)
        if only_if_older_h and existing and time.time() - existing[-1].stat().st_mtime < only_if_older_h * 3600:
            return
        log.info("backed up database to %s", backup(cfg))
    except Exception:
        log.exception("daily backup failed")


class BotScheduler:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.sched = BackgroundScheduler(job_defaults={"coalesce": True, "misfire_grace_time": CATCH_UP_H * 3600})

    def _daily_times(self) -> dict[str, tuple[int, int]]:
        s = self.cfg.whatsapp.schedule
        return {k: hm for k in ("morning", "midday", "night") if (hm := parse_hm(getattr(s, k)))}

    def start(self) -> None:
        if self.cfg.whatsapp.enabled:
            for kind, (h, m) in self._daily_times().items():
                self.sched.add_job(send_report, CronTrigger(hour=h, minute=m), args=[kind], id=kind, replace_existing=True)
            if wk := parse_weekly(self.cfg.whatsapp.schedule.weekly):
                d, h, m = wk
                self.sched.add_job(send_report, CronTrigger(day_of_week=d, hour=h, minute=m), args=["weekly"], id="weekly",
                                   replace_existing=True)
            self.sched.add_job(check_nudges, "interval", minutes=10, id="nudges", replace_existing=True,
                               next_run_time=datetime.now() + timedelta(minutes=1))
        self.sched.add_job(daily_backup, CronTrigger(hour=3, minute=30), args=[self.cfg], id="backup", replace_existing=True)
        self.sched.start()
        log.info("scheduler started: %s", ", ".join(f"{j.id} -> {j.next_run_time:%a %H:%M}" for j in self.sched.get_jobs()))
        if self.cfg.whatsapp.enabled:
            self.catch_up()
        daily_backup(self.cfg, only_if_older_h=24)  # laptop was off at 03:30? catch up

    def catch_up(self, now: datetime | None = None) -> list[str]:
        """Send reports whose time passed within the last CATCH_UP_H hours while the server was down/asleep."""
        now = now or datetime.now()
        due = []
        for kind, (h, m) in self._daily_times().items():
            t = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if t <= now < t + timedelta(hours=CATCH_UP_H):
                due.append(kind)
        if wk := parse_weekly(self.cfg.whatsapp.schedule.weekly):
            d, h, m = wk
            t = now.replace(hour=h, minute=m, second=0, microsecond=0)
            if now.weekday() == d and t <= now < t + timedelta(hours=CATCH_UP_H):
                due.append("weekly")
        for kind in due:
            send_report(kind, self.cfg)  # deduped inside
        return due

    def shutdown(self) -> None:
        self.sched.shutdown(wait=False)
