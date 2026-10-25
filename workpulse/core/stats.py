"""Daily stats and the focus score. Pure functions over SessionRecords so the CLI, dashboard
and WhatsApp reports all compute identical numbers.

Focus score (0-100), documented in README:
    deep_work   40 * min(productive_min / daily_target_min, 1)
    focus_ratio 25 * productive_min / active_min
    streak      20 * min(longest_streak_min / streak_target_min, 1)
    low_distraction 15 * (1 - min(2 * entertainment_min / active_min, 1))
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta

from workpulse.config import ScoringConfig
from workpulse.core.models import SessionRecord, State


def day_bounds(d: date) -> tuple[float, float]:
    """Local-midnight to local-midnight as epoch seconds."""
    start = datetime.combine(d, time.min)
    return start.timestamp(), (start + timedelta(days=1)).timestamp()


def clip(sessions: list[SessionRecord], start: float, end: float) -> list[SessionRecord]:
    out = []
    for s in sessions:
        a, b = max(s.start_ts, start), min(s.end_ts, end)
        if b > a:
            out.append(SessionRecord(id=s.id, start_ts=a, end_ts=b, state=s.state, app=s.app, title=s.title, category=s.category))
    return sorted(out, key=lambda s: s.start_ts)


def _merge_intervals(intervals: list[tuple[float, float]], tolerance: float) -> list[tuple[float, float, float]]:
    """Merge intervals whose gaps are <= tolerance. Returns (start, end, covered_seconds)."""
    merged: list[list[float]] = []
    for a, b in sorted(intervals):
        if merged and a - merged[-1][1] <= tolerance:
            merged[-1][1] = max(merged[-1][1], b)
            merged[-1][2] += b - a
        else:
            merged.append([a, b, b - a])
    return [(a, b, c) for a, b, c in merged]


@dataclass
class DayStats:
    day: date
    active_s: float = 0.0
    idle_s: float = 0.0
    productive_s: float = 0.0
    entertainment_s: float = 0.0
    per_category: dict[str, float] = field(default_factory=dict)
    per_app: dict[str, float] = field(default_factory=dict)
    longest_streak_s: float = 0.0
    streak_category: str | None = None
    streak_start: float | None = None
    first_activity: float | None = None
    last_activity: float | None = None
    breaks: int = 0
    focus_score: int = 0
    score_breakdown: dict[str, float] = field(default_factory=dict)
    sessions: list[SessionRecord] = field(default_factory=list, repr=False)

    def to_dict(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "sessions"}
        d["day"] = self.day.isoformat()
        return d


def focus_score(active_s: float, productive_s: float, streak_s: float, entertainment_s: float,
                cfg: ScoringConfig) -> tuple[int, dict[str, float]]:
    if active_s <= 0:
        return 0, {"deep_work": 0, "focus_ratio": 0, "streak": 0, "low_distraction": 0}
    m = 60.0
    parts = {
        "deep_work": 40 * min(productive_s / m / cfg.daily_target_min, 1.0),
        "focus_ratio": 25 * min(productive_s / active_s, 1.0),
        "streak": 20 * min(streak_s / m / cfg.streak_target_min, 1.0),
        "low_distraction": 15 * (1 - min(2 * entertainment_s / active_s, 1.0)),
    }
    parts = {k: round(v, 1) for k, v in parts.items()}
    return round(sum(parts.values())), parts


def compute_day(sessions: list[SessionRecord], d: date, cfg: ScoringConfig) -> DayStats:
    start, end = day_bounds(d)
    ss = clip(sessions, start, end)
    st = DayStats(day=d, sessions=ss)
    productive = set(cfg.productive_categories)
    per_cat: dict[str, float] = defaultdict(float)
    per_app: dict[str, float] = defaultdict(float)
    active_by_cat: dict[str, list[tuple[float, float]]] = defaultdict(list)
    active_intervals: list[tuple[float, float]] = []

    for s in ss:
        if s.state == State.IDLE.value:
            st.idle_s += s.duration
        if s.state != State.ACTIVE.value:
            continue
        st.active_s += s.duration
        per_cat[s.category] += s.duration
        per_app[s.app or "-"] += s.duration
        active_by_cat[s.category].append((s.start_ts, s.end_ts))
        active_intervals.append((s.start_ts, s.end_ts))
        if s.category in productive:
            st.productive_s += s.duration
        if s.category == "Entertainment":
            st.entertainment_s += s.duration

    if active_intervals:
        st.first_activity = min(a for a, _ in active_intervals)
        st.last_activity = max(b for _, b in active_intervals)

    # Longest streak: time in ONE productive category, where interruptions <= tolerance don't break it.
    tol = cfg.streak_break_tolerance_min * 60
    for cat, ivs in active_by_cat.items():
        if cat not in productive:
            continue
        for a, _b, covered in _merge_intervals(ivs, tol):
            if covered > st.longest_streak_s:
                st.longest_streak_s, st.streak_category, st.streak_start = covered, cat, a

    # Breaks: gaps between any active time that are at least min_break_min long.
    blocks = _merge_intervals(active_intervals, 0)
    min_break = cfg.min_break_min * 60
    st.breaks = sum(1 for (_, b1, _), (a2, _, _) in zip(blocks, blocks[1:]) if a2 - b1 >= min_break)

    st.per_category = dict(sorted(per_cat.items(), key=lambda kv: -kv[1]))
    st.per_app = dict(sorted(per_app.items(), key=lambda kv: -kv[1]))
    st.focus_score, st.score_breakdown = focus_score(st.active_s, st.productive_s, st.longest_streak_s, st.entertainment_s, cfg)
    return st


@dataclass
class Comparison:
    yesterday: DayStats | None
    avg7_active_s: float
    avg7_score: float
    best: DayStats | None  # best focus score in history (excluding today)


def compare(today: DayStats, history: list[DayStats]) -> Comparison:
    """`history` = previous days (any order), today excluded. Days with no activity are skipped for averages."""
    by_day = {h.day: h for h in history}
    yesterday = by_day.get(today.day - timedelta(days=1))
    last7 = [h for h in history if 0 < (today.day - h.day).days <= 7 and h.active_s > 0]
    avg_active = sum(h.active_s for h in last7) / len(last7) if last7 else 0.0
    avg_score = sum(h.focus_score for h in last7) / len(last7) if last7 else 0.0
    active_days = [h for h in history if h.active_s > 0]
    best = max(active_days, key=lambda h: (h.focus_score, h.active_s)) if active_days else None
    return Comparison(yesterday=yesterday, avg7_active_s=avg_active, avg7_score=avg_score, best=best)


def fmt_dur(seconds: float) -> str:
    m = int(round(seconds / 60))
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"
