import re

from sqlalchemy import inspect

from workpulse.core.db import get_engine, sessions_between, upsert_sessions
from workpulse.core.models import Sample
from workpulse.core.state import SessionTracker


def test_upsert_is_idempotent_and_updates(tmp_path):
    db = tmp_path / "t.db"
    t = SessionTracker(120, 600)
    t.feed(Sample(0, 0, False, "code", "a", "Coding"))
    t.feed(Sample(5, 0, False, "code", "a", "Coding"))
    upsert_sessions(db, [t.current])
    t.feed(Sample(10, 0, False, "code", "a", "Coding"))
    upsert_sessions(db, [t.current])
    rows = sessions_between(db, 0, 100)
    assert len(rows) == 1 and rows[0].end_ts == 10


def test_saved_session_backdated_to_zero_is_removed(tmp_path):
    """Regression: an active session flushed to the DB, then back-dated to zero length when idle is detected,
    used to leave a stale row overlapping the idle session."""
    db = tmp_path / "t.db"
    t = SessionTracker(120, 600, gap_tolerance=1000)  # sparse samples here aren't a sleep gap
    t.feed(Sample(0, 0, False, "code", "a", "Coding"))  # last input at t=0
    t.feed(Sample(60, 60, False, "code", "a", "Coding"))
    upsert_sessions(db, [t.current])
    t.current.saved = True
    closed = t.feed(Sample(125, 125, False, "code", "a", "Coding"))  # idle detected; active shrinks to [0, 0]
    assert closed and closed[0].duration == 0
    upsert_sessions(db, closed + [t.current])
    rows = sessions_between(db, 0, 1000)
    assert [r.state for r in rows] == ["idle"] and rows[0].start_ts == 0


def test_schema_has_no_keystroke_or_screenshot_columns(tmp_path):
    insp = inspect(get_engine(tmp_path / "t.db"))
    activity = {c["name"] for c in insp.get_columns("activity_sessions")}
    assert activity == {"id", "start_ts", "end_ts", "state", "app", "title", "category", "device", "source", "updated_at"}
    assert set(insp.get_table_names()) == {"activity_sessions", "goals", "milestones", "team_members", "tasks",
                                           "meetings", "messages", "phone_days", "phone_apps", "devices", "pairing_codes"}
    banned = re.compile(r"key|stroke|typed|keyboard|screen|image|pixel|clipboard|url", re.I)
    for table in insp.get_table_names():
        for c in insp.get_columns(table):
            assert not banned.search(c["name"]), f"{table}.{c['name']}"
