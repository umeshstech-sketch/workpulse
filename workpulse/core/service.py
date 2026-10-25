"""Read-side helpers: load sessions from the DB and turn them into DayStats. Used by CLI + (later) API."""
from __future__ import annotations

from datetime import date, timedelta

from workpulse.config import Config
from workpulse.core.db import sessions_between
from workpulse.core.stats import Comparison, DayStats, compare, compute_day, day_bounds


def day_stats(cfg: Config, d: date) -> DayStats:
    start, end = day_bounds(d)
    return compute_day(sessions_between(cfg.db_path, start, end), d, cfg.scoring)


def range_stats(cfg: Config, first: date, last: date) -> list[DayStats]:
    """Stats for every day in [first, last], one DB query."""
    start, _ = day_bounds(first)
    _, end = day_bounds(last)
    sessions = sessions_between(cfg.db_path, start, end)
    out, d = [], first
    while d <= last:
        out.append(compute_day(sessions, d, cfg.scoring))
        d += timedelta(days=1)
    return out


def goal_progress(cfg: Config, goals: list, today: date | None = None) -> list:
    """Tracked minutes toward each goal linked to a category, over the goal's period."""
    from datetime import datetime

    from workpulse.core.store import GoalProgress, period_start
    today = today or date.today()
    out = []
    cache: dict[date, list[DayStats]] = {}
    for g in goals:
        if not g.category:
            out.append(GoalProgress(g, None, g.manual_pct))
            continue
        start = period_start(g.kind, today) or datetime.fromtimestamp(g.created_at).date()
        if start not in cache:
            cache[start] = range_stats(cfg, start, today)
        minutes = sum(d.per_category.get(g.category, 0.0) for d in cache[start]) / 60
        pct = min(100.0, 100 * minutes / g.target_min) if g.target_min else None
        out.append(GoalProgress(g, minutes, pct))
    return out


def day_with_comparison(cfg: Config, d: date, history_days: int = 60) -> tuple[DayStats, Comparison]:
    days = range_stats(cfg, d - timedelta(days=history_days), d)
    today, history = days[-1], days[:-1]
    return today, compare(today, history)
