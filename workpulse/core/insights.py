"""'What you're doing best' / 'what to improve': specific, numeric findings from the last two weeks.

Each finding carries a weight so callers can show the strongest few. Phase 4 builds the dashboard
Insights tab on top of this.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from workpulse.config import Config
from workpulse.core.db import sessions_between
from workpulse.core.models import SessionRecord
from workpulse.core.stats import DayStats, compute_day, day_bounds, fmt_dur

# Sites/apps worth naming when they eat time. Matched against window titles (if stored) then app names.
DISTRACTION_SOURCES = ["YouTube", "Instagram", "Reddit", "Netflix", "Twitter", "X.com", "Facebook", "Hotstar",
                       "Prime Video", "Twitch", "Spotify", "WhatsApp", "Discord", "LinkedIn"]
WEEKDAYS = ["Mondays", "Tuesdays", "Wednesdays", "Thursdays", "Fridays", "Saturdays", "Sundays"]


@dataclass
class Insight:
    kind: str  # "best" | "improve"
    text: str
    weight: float  # higher = more noteworthy


def _window_label(start_h: int, width: int) -> str:
    a, b = start_h % 24, (start_h + width) % 24
    sa, sb = ("AM" if a < 12 else "PM"), ("AM" if b < 12 else "PM")
    left = f"{a % 12 or 12}" if sa == sb else f"{a % 12 or 12} {sa}"
    return f"{left}–{b % 12 or 12} {sb}"


def _by_hour(sessions: list[SessionRecord], pred) -> list[float]:
    """Seconds per hour-of-day (0..23) for active sessions matching pred, split exactly at hour edges."""
    hours = [0.0] * 24
    for s in sessions:
        if s.state != "active" or not pred(s):
            continue
        t = s.start_ts
        while t < s.end_ts:
            dt = datetime.fromtimestamp(t)
            edge = (dt.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).timestamp()
            seg_end = min(edge, s.end_ts)
            hours[dt.hour] += seg_end - t
            t = seg_end
    return hours


def _best_window(hours: list[float], width: int) -> tuple[int, float]:
    best_h, best_v = 0, -1.0
    for h in range(24):
        v = sum(hours[(h + i) % 24] for i in range(width))
        if v > best_v:
            best_h, best_v = h, v
    return best_h, best_v


def _source(s: SessionRecord, cfg: Config) -> str:
    """Name the site/app behind a session: a known distraction, else the site from a browser title."""
    t = (s.title or "").lower()
    for name in DISTRACTION_SOURCES:
        if name.lower() in t:
            return name
    if s.app in cfg.categories.browsers:
        parts = [x.strip() for x in (s.title or "").split(" - ") if x.strip()]
        if len(parts) >= 2:  # "Amazon.in - Google Chrome" -> "Amazon.in"
            return parts[-2][:40]
        return f"Browsing ({cfg.alias(s.app)})"
    return cfg.alias(s.app)


def compute_insights(cfg: Config, end: date | None = None, days: int = 14) -> list[Insight]:
    end = end or date.today()
    first = end - timedelta(days=days - 1)
    start_ts, _ = day_bounds(first)
    _, end_ts = day_bounds(end)
    sessions = sessions_between(cfg.db_path, start_ts, end_ts)
    stats: list[DayStats] = []
    d = first
    while d <= end:
        stats.append(compute_day(sessions, d, cfg.scoring))
        d += timedelta(days=1)
    sessions = [x for st in stats for x in st.sessions]  # clipped to the period, day by day
    active_days = [s for s in stats if s.active_s > 0]
    if not active_days:
        return []
    productive = set(cfg.scoring.productive_categories)
    out: list[Insight] = []
    total_active = sum(s.active_s for s in stats)
    total_prod = sum(s.productive_s for s in stats)

    # ---- best ----
    prod_hours = _by_hour(sessions, lambda s: s.category in productive)
    if total_prod >= 2 * 3600:
        h, v = _best_window(prod_hours, 3)
        share = v / total_prod
        out.append(Insight("best", f"Your focus peaks {_window_label(h, 3)}: {share:.0%} of your productive time lands there. Guard that slot 🛡️",
                           50 + 50 * share))

    by_wd: dict[int, list[float]] = defaultdict(list)
    for s in active_days:  # days with no laptop use (or today, not started yet) would drag averages down
        by_wd[s.day.weekday()].append(s.productive_s)
    wd_avg = {wd: sum(v) / len(v) for wd, v in by_wd.items() if v}
    if len(wd_avg) >= 5 and total_prod > 0:
        wd, avg = max(wd_avg.items(), key=lambda kv: kv[1])
        overall = total_prod / len(active_days)
        if avg > overall * 1.2:
            out.append(Insight("best", f"{WEEKDAYS[wd]} are your power days: {fmt_dur(avg)} productive on average vs {fmt_dur(overall)} overall 💪",
                               40 + 20 * min(avg / max(overall, 1) - 1, 1)))

    best_streak = max(stats, key=lambda s: s.longest_streak_s)
    if best_streak.longest_streak_s >= 30 * 60:
        out.append(Insight("best", f"Best focus run: {fmt_dur(best_streak.longest_streak_s)} of {best_streak.streak_category} on {best_streak.day:%a %d %b} 🔥",
                           45 + min(best_streak.longest_streak_s / 3600, 3) * 10))

    cur, prev = stats[-7:], stats[-14:-7]
    if prev:
        growth = {}
        for cat in productive:
            a = sum(s.per_category.get(cat, 0) for s in cur)
            b = sum(s.per_category.get(cat, 0) for s in prev)
            growth[cat] = (a - b, a, b)
        cat, (diff, a, b) = max(growth.items(), key=lambda kv: kv[1][0])
        if diff >= 30 * 60:
            out.append(Insight("best", f"{cat} is up {fmt_dur(diff)} vs last week ({fmt_dur(a)} vs {fmt_dur(b)}) 📈", 40 + min(diff / 3600, 5) * 6))

    strong_days = sum(1 for s in stats if s.productive_s >= 3 * 3600)
    if strong_days >= 3:
        out.append(Insight("best", f"{strong_days} of the last {days} days had 3h+ of productive work. That's consistency ✅", 30 + strong_days * 3))

    # ---- improve ----
    total_ent = sum(s.entertainment_s for s in stats)
    if total_ent >= 30 * 60:
        ent_hours = _by_hour(sessions, lambda s: s.category == "Entertainment")
        h, v = _best_window(ent_hours, 2)
        share = v / total_ent
        if share >= 0.3:
            out.append(Insight("improve", f"{share:.0%} of your Entertainment time happens {_window_label(h, 2)} ({fmt_dur(total_ent / len(active_days))}/day on average). Plan something there 🎯",
                               50 + 40 * share))

    distract = [s for s in sessions if s.state == "active" and s.category in ("Entertainment", "Browsing")]
    distract_total = sum(s.duration for s in distract)
    if distract_total >= 45 * 60:
        per_src: dict[str, float] = defaultdict(float)
        for s in distract:
            per_src[_source(s, cfg)] += s.duration
        src, secs = max(per_src.items(), key=lambda kv: kv[1])
        share = secs / distract_total
        if share >= 0.25:
            out.append(Insight("improve", f"{src} is {share:.0%} of your Browsing + Entertainment time ({fmt_dur(secs)} in {days} days) 👀",
                               45 + 40 * share))

    if total_active >= 3600:
        switches = 0
        prev_app = None
        for s in sorted((s for s in sessions if s.state == "active"), key=lambda s: s.start_ts):
            if prev_app is not None and s.app != prev_app:
                switches += 1
            prev_app = s.app
        per_hour = switches / (total_active / 3600)
        if per_hour >= 20:
            out.append(Insight("improve", f"You switch apps ~{per_hour:.0f} times per active hour. Try batching chats and notifications 🔕",
                               35 + min(per_hour, 60) / 2))

    late = 0
    for s in stats[1:]:
        s0, _ = day_bounds(s.day)
        if any(x.state == "active" and s0 <= x.start_ts < s0 + 4 * 3600 for x in s.sessions):  # 00:00–04:00
            late += 1
    if late >= 2:
        out.append(Insight("improve", f"{late} of the last {days} nights you were on the laptop after midnight. Sleep is a productivity tool too 😴",
                           35 + late * 4))

    if total_active >= 2 * 3600:
        ratio = total_prod / total_active
        if ratio < 0.5:
            out.append(Insight("improve", f"Only {ratio:.0%} of your active time is productive. Small change: start each session in a focus app 🧠",
                               40 + (0.5 - ratio) * 60))

    if prev:
        prev_active = [s for s in prev if s.active_s > 0]
        cur_active = [s for s in cur if s.active_s > 0]
        if prev_active and cur_active:
            a = sum(s.focus_score for s in cur_active) / len(cur_active)
            b = sum(s.focus_score for s in prev_active) / len(prev_active)
            if b - a >= 8:
                out.append(Insight("improve", f"Focus score slipped to {a:.0f} this week from {b:.0f}. Let's win it back 📉➡️📈", 40 + (b - a)))

    return sorted(out, key=lambda i: -i.weight)


def top(insights: list[Insight], kind: str, n: int = 3) -> list[Insight]:
    return [i for i in insights if i.kind == kind][:n]


def profile(cfg: Config, end: date | None = None, days: int = 14) -> dict:
    """Chart data for the Insights tab: when you focus, which days, where time leaks, and consistency."""
    end = end or date.today()
    first = end - timedelta(days=days - 1)
    start_ts, _ = day_bounds(first)
    _, end_ts = day_bounds(end)
    raw = sessions_between(cfg.db_path, start_ts, end_ts)
    stats = []
    d = first
    while d <= end:
        stats.append(compute_day(raw, d, cfg.scoring))
        d += timedelta(days=1)
    sessions = [x for st in stats for x in st.sessions]
    productive = set(cfg.scoring.productive_categories)
    n_active = max(1, sum(1 for s in stats if s.active_s > 0))
    prod_h = _by_hour(sessions, lambda s: s.category in productive)
    ent_h = _by_hour(sessions, lambda s: s.category == "Entertainment")
    by_wd: dict[int, list[float]] = defaultdict(list)
    for s in stats:
        if s.active_s > 0:
            by_wd[s.day.weekday()].append(s.productive_s)
    per_src: dict[str, float] = defaultdict(float)
    for s in sessions:
        if s.state == "active" and s.category in ("Entertainment", "Browsing"):
            per_src[_source(s, cfg)] += s.duration
    month = range_days(cfg, end, 30)
    return {
        "days": days,
        "hours": [{"hour": h, "productive_min": prod_h[h] / 60 / n_active, "entertainment_min": ent_h[h] / 60 / n_active}
                  for h in range(24)],
        "weekdays": [{"weekday": WEEKDAYS[wd][:3], "avg_productive_s": (sum(v) / len(v)) if v else 0.0}
                     for wd, v in sorted(by_wd.items())],
        "sources": [{"name": k, "seconds": v} for k, v in sorted(per_src.items(), key=lambda kv: -kv[1])[:8]],
        "calendar": [{"date": s.day.isoformat(), "productive_s": s.productive_s, "active_s": s.active_s,
                      "focus_score": s.focus_score} for s in month],
    }


def range_days(cfg: Config, end: date, days: int) -> list[DayStats]:
    first = end - timedelta(days=days - 1)
    start_ts, _ = day_bounds(first)
    _, end_ts = day_bounds(end)
    raw = sessions_between(cfg.db_path, start_ts, end_ts)
    return [compute_day(raw, first + timedelta(days=i), cfg.scoring) for i in range(days)]


def collaboration(cfg: Config, end: date | None = None, days: int = 7) -> dict:
    """Share of your week spent collaborating = (logged meetings + Communication apps) / (laptop active + meetings).

    Meetings are often off-laptop (calls, in person), so they're added on top of tracked laptop time.
    """
    from workpulse.core.store import list_meetings
    end = end or date.today()
    stats = range_days(cfg, end, days)
    start_ts, _ = day_bounds(end - timedelta(days=days - 1))
    _, end_ts = day_bounds(end)
    meeting_s = sum(m.minutes * 60 for m in list_meetings(cfg.db_path, start_ts) if m.start_ts < end_ts)
    comm_s = sum(s.per_category.get("Communication", 0.0) for s in stats)
    active_s = sum(s.active_s for s in stats)
    total = active_s + meeting_s
    return {"days": days, "meeting_s": meeting_s, "communication_s": comm_s, "active_s": active_s,
            "share": (meeting_s + comm_s) / total if total else 0.0}
