"""Multi-day views: week summaries, day-streaks ("5 days in a row over 4h of Coding") and week-over-week trends."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from workpulse.core.stats import DayStats, fmt_dur

STREAK_THRESHOLDS_H = [6, 5, 4, 3, 2, 1]


@dataclass
class Streak:
    label: str  # e.g. "Coding" or "Productive" or "Active"
    hours: int  # threshold
    days: int  # consecutive days meeting it, ending today (or yesterday if today isn't there yet)

    @property
    def text(self) -> str:
        return f"{self.days} days in a row with {self.hours}h+ of {self.label}"


def _metric(d: DayStats, label: str) -> float:
    if label == "Active":
        return d.active_s
    if label == "Productive":
        return d.productive_s
    return d.per_category.get(label, 0.0)


def _run_length(days: list[DayStats], label: str, threshold_s: float) -> int:
    """Consecutive days at the END of `days` meeting threshold. Today may still be in progress, so if today
    doesn't meet it yet we count the streak ending yesterday (it's still alive)."""
    seq = list(days)
    if seq and _metric(seq[-1], label) < threshold_s:
        seq = seq[:-1]
    n = 0
    for d in reversed(seq):
        if _metric(d, label) >= threshold_s:
            n += 1
        else:
            break
    return n


def find_streaks(days: list[DayStats], productive: list[str], min_days: int = 2) -> list[Streak]:
    """For each metric, the highest threshold with a live streak of at least `min_days`. `days` = oldest..today."""
    out: list[Streak] = []
    for label in ["Productive", *productive, "Active"]:
        for h in STREAK_THRESHOLDS_H:
            n = _run_length(days, label, h * 3600)
            if n >= min_days:
                out.append(Streak(label=label, hours=h, days=n))
                break
    return sorted(out, key=lambda s: (-s.days, -s.hours))


@dataclass
class WeekTrend:
    active_s: float
    prev_active_s: float
    score_avg: float
    prev_score_avg: float
    productive_s: float
    prev_productive_s: float

    @staticmethod
    def _pct(cur: float, prev: float) -> float | None:
        return None if prev <= 0 else round(100 * (cur - prev) / prev, 1)

    def to_dict(self) -> dict:
        return {
            "active_s": self.active_s, "prev_active_s": self.prev_active_s,
            "active_change_pct": self._pct(self.active_s, self.prev_active_s),
            "productive_s": self.productive_s, "prev_productive_s": self.prev_productive_s,
            "productive_change_pct": self._pct(self.productive_s, self.prev_productive_s),
            "score_avg": round(self.score_avg, 1), "prev_score_avg": round(self.prev_score_avg, 1),
        }


def week_trend(days: list[DayStats]) -> WeekTrend:
    """`days` = the last 14 days, oldest first. Compares the last 7 with the 7 before."""
    cur, prev = days[-7:], days[-14:-7]

    def avg_score(ds: list[DayStats]) -> float:
        act = [d for d in ds if d.active_s > 0]
        return sum(d.focus_score for d in act) / len(act) if act else 0.0

    return WeekTrend(
        active_s=sum(d.active_s for d in cur), prev_active_s=sum(d.active_s for d in prev),
        score_avg=avg_score(cur), prev_score_avg=avg_score(prev),
        productive_s=sum(d.productive_s for d in cur), prev_productive_s=sum(d.productive_s for d in prev),
    )


def trend_sentence(t: WeekTrend) -> str:
    pct = t._pct(t.productive_s, t.prev_productive_s)
    if pct is None:
        return f"{fmt_dur(t.productive_s)} productive this week."
    arrow = "up" if pct >= 0 else "down"
    return f"Productive time {arrow} {abs(pct):.0f}% vs last week ({fmt_dur(t.productive_s)} vs {fmt_dur(t.prev_productive_s)})."


def days_back(end: date, n: int) -> tuple[date, date]:
    return end - timedelta(days=n - 1), end
