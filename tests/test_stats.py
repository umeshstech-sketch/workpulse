from datetime import date, datetime, timedelta

import pytest

from workpulse.config import ScoringConfig
from workpulse.core.models import SessionRecord
from workpulse.core.stats import compare, compute_day, focus_score

D = date(2026, 10, 20)
CFG = ScoringConfig()


def at(h, m=0, day=D):
    return datetime(day.year, day.month, day.day, h, m).timestamp()


def rec(h1, m1, h2, m2, cat="Coding", state="active", app="code", day=D):
    return SessionRecord(start_ts=at(h1, m1, day), end_ts=at(h2, m2, day), state=state, app=app, title=None, category=cat)


def test_totals_and_categories():
    st = compute_day([
        rec(9, 0, 10, 0),
        rec(10, 0, 10, 30, cat="Entertainment", app="chrome"),
        rec(10, 30, 10, 45, state="idle"),
        rec(10, 45, 11, 15, cat="Learning/AI", app="chrome"),
    ], D, CFG)
    assert st.active_s == 2 * 3600
    assert st.productive_s == 1.5 * 3600
    assert st.entertainment_s == 1800
    assert st.idle_s == 900
    assert st.per_category == {"Coding": 3600, "Entertainment": 1800, "Learning/AI": 1800}
    assert st.per_app == {"code": 3600, "chrome": 3600}
    assert st.first_activity == at(9) and st.last_activity == at(11, 15)


def test_streak_tolerates_short_interruptions_only():
    st = compute_day([
        rec(9, 0, 9, 40),
        rec(9, 40, 9, 42, cat="Communication", app="whatsapp"),  # 2-min WhatsApp check: streak continues
        rec(9, 42, 10, 30),
        rec(10, 30, 10, 40, cat="Entertainment"),  # 10 min: breaks the streak
        rec(10, 40, 11, 0),
    ], D, CFG)
    assert st.longest_streak_s == (40 + 48) * 60  # interruption itself isn't counted
    assert st.streak_category == "Coding" and st.streak_start == at(9)


def test_breaks_count_gaps_of_at_least_min_break():
    st = compute_day([rec(9, 0, 10, 0), rec(10, 3, 11, 0), rec(11, 20, 12, 0), rec(13, 0, 14, 0)], D, CFG)
    assert st.breaks == 2  # 3-min gap ignored; 20 min and 60 min count


def test_sessions_crossing_midnight_are_clipped():
    prev = D - timedelta(days=1)
    s = SessionRecord(start_ts=at(23, 30, prev), end_ts=at(0, 30), state="active", app="code", title=None, category="Coding")
    assert compute_day([s], D, CFG).active_s == 1800
    assert compute_day([s], prev, CFG).active_s == 1800


def test_focus_score_formula():
    # 4h productive of 5h active, 90-min streak, 30 min entertainment.
    score, parts = focus_score(5 * 3600, 4 * 3600, 90 * 60, 30 * 60, CFG)
    assert parts == {"deep_work": 40.0, "focus_ratio": 20.0, "streak": 20.0, "low_distraction": 12.0}
    assert score == 92
    assert focus_score(0, 0, 0, 0, CFG)[0] == 0
    # All entertainment: only... nothing.
    assert focus_score(3600, 0, 0, 3600, CFG)[0] == 0


def test_focus_score_bounds():
    for args in [(1, 1, 1, 0), (36000, 36000, 36000, 0), (3600, 0, 0, 0)]:
        s, _ = focus_score(*args, CFG)
        assert 0 <= s <= 100


def test_compare_yesterday_avg_best():
    days = [compute_day([rec(9, 0, 9 + i, 0, day=D - timedelta(days=i))], D - timedelta(days=i), CFG) for i in range(1, 9)]
    today = compute_day([rec(9, 0, 12, 0)], D, CFG)
    c = compare(today, days)
    assert c.yesterday.day == D - timedelta(days=1) and c.yesterday.active_s == 3600
    assert c.avg7_active_s == pytest.approx(sum(range(1, 8)) / 7 * 3600)
    assert c.best.day == D - timedelta(days=8)  # longest day has the best score
