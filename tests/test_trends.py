from datetime import date, timedelta

from workpulse.core.stats import DayStats
from workpulse.core.trends import find_streaks, week_trend

PROD = ["Coding", "Learning/AI", "Design", "Content Creation"]
TODAY = date(2026, 10, 21)


def day(back, coding_h, other_h=0.0, score=50):
    s = coding_h * 3600
    return DayStats(day=TODAY - timedelta(days=back), active_s=s + other_h * 3600, productive_s=s,
                    per_category={"Coding": s, "Browsing": other_h * 3600}, focus_score=score)


def test_streak_counts_consecutive_days_at_highest_threshold():
    days = [day(6, 1), day(5, 4.5), day(4, 4.2), day(3, 5), day(2, 4.1), day(1, 4.6), day(0, 4.3)]
    s = {x.label: x for x in find_streaks(days, PROD)}
    assert s["Coding"].hours == 4 and s["Coding"].days == 6
    assert s["Coding"].text == "6 days in a row with 4h+ of Coding"


def test_today_in_progress_does_not_break_streak():
    days = [day(3, 0), day(2, 3), day(1, 3.5), day(0, 0.5)]  # today only 30 min so far
    s = {x.label: x for x in find_streaks(days, PROD)}
    assert s["Coding"].hours == 3 and s["Coding"].days == 2


def test_no_streak_when_single_day():
    assert find_streaks([day(1, 0), day(0, 5)], PROD) == []


def test_week_trend_compares_last_7_with_prior_7():
    days = [day(13 - i, 2 if i < 7 else 3, score=40 if i < 7 else 60) for i in range(14)]
    t = week_trend(days).to_dict()
    assert t["productive_change_pct"] == 50.0
    assert t["score_avg"] == 60 and t["prev_score_avg"] == 40
