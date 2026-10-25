from workpulse.core.models import Sample, State
from workpulse.core.state import SessionTracker, classify

IDLE, AWAY = 120, 600


def s(ts, idle=0.0, app="code", cat="Coding", title="main.py", locked=False):
    return Sample(ts=ts, idle_seconds=idle, locked=locked, app=app, title=title, category=cat)


def test_classify_thresholds():
    assert classify(0, False, IDLE, AWAY) == State.ACTIVE
    assert classify(119.9, False, IDLE, AWAY) == State.ACTIVE
    assert classify(120, False, IDLE, AWAY) == State.IDLE
    assert classify(599, False, IDLE, AWAY) == State.IDLE
    assert classify(600, False, IDLE, AWAY) == State.AWAY
    assert classify(0, True, IDLE, AWAY) == State.AWAY  # locked screen is always away


def run(samples, **kw):
    t = SessionTracker(IDLE, AWAY, gap_tolerance=30, **kw)
    closed = []
    for x in samples:
        closed += t.feed(x)
    return t, closed


def test_continuous_activity_is_one_session():
    t, closed = run([s(i * 5) for i in range(100)])
    assert closed == []
    assert t.current.state == "active" and t.current.start_ts == 0 and t.current.end_ts == 495


def test_app_switch_splits_session():
    t, closed = run([s(0), s(5), s(10, app="chrome", cat="Browsing", title="Google")])
    assert [c.app for c in closed] == ["code"]
    assert t.current.app == "chrome"


def test_active_to_idle_is_backdated_to_last_input():
    # Last input at t=100; samples keep coming with growing idle time; idle detected at t=220.
    samples = [s(ts) for ts in range(0, 101, 5)]
    samples += [s(ts, idle=ts - 100) for ts in range(105, 230, 5)]
    t, closed = run(samples)
    active = closed[0]
    assert active.state == "active" and active.end_ts == 100  # not 220
    assert t.current.state == "idle" and t.current.start_ts == 100


def test_idle_to_away_and_back_to_active():
    samples = [s(0), s(5)]
    samples += [s(ts, idle=ts - 5) for ts in range(10, 700, 5)]  # no input after t=5
    samples += [s(700, idle=1)]
    t, closed = run(samples)
    states = [c.state for c in closed]
    assert states == ["active", "idle", "away"]
    idle, away = closed[1], closed[2]
    assert idle.start_ts == 5 and idle.end_ts == 5 + AWAY  # away begins at last input + away threshold
    assert away.start_ts == 605 and away.end_ts == 699
    assert t.current.state == "active"


def test_lock_screen_goes_away_immediately():
    t, closed = run([s(0), s(5), s(10, locked=True)])
    assert closed[0].state == "active" and closed[0].end_ts == 10
    assert t.current.state == "away" and t.current.app is None


def test_sleep_gap_recorded_as_away():
    # Laptop slept between t=10 and t=3610.
    t, closed = run([s(0), s(5), s(10), s(3610, idle=2)])
    assert [c.state for c in closed] == ["active", "away"]
    assert closed[0].end_ts == 10
    assert closed[1].start_ts == 10 and closed[1].end_ts == 3610
    assert t.current.state == "active" and t.current.start_ts == 3610


def test_titles_dropped_when_disabled():
    t, _ = run([s(0, title="secret.txt")], keep_titles=False)
    assert t.current.title is None


def test_close_cuts_at_pause_time():
    t, _ = run([s(0), s(5), s(10)])
    rec = t.close(7.5)
    assert rec.end_ts == 7.5 and t.current is None
    # After a pause, the next sample starts fresh without inventing an away gap.
    closed = t.feed(s(500))
    assert closed == [] and t.current.start_ts == 500
