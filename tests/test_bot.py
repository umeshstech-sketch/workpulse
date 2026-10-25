import re
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from workpulse.agent import control
from workpulse.backend.app import app
from workpulse.bot import commands, reports, scheduler
from workpulse.bot.commands import handle, parse_due, parse_duration_min
from workpulse.bot.providers import TwilioProvider, split_message
from workpulse.config import get_config
from workpulse.core.db import upsert_sessions
from workpulse.core.demo import generate
from workpulse.core.insights import compute_insights
from workpulse.core.models import SessionRecord
from workpulse.core.service import day_stats
from workpulse.core.stats import fmt_dur
from workpulse.core.store import list_goals, list_members, list_tasks, recent_messages

ME = "919876543210"


@pytest.fixture()
def demo(data_dir):
    cfg = get_config()
    # Demo history ending at 18:00 today, so "today" has data too.
    upsert_sessions(cfg.db_path, generate(days=14, until=datetime.combine(date.today(), datetime.min.time()) + timedelta(hours=18)))
    return cfg


# ---- parsing -----------------------------------------------------------------------------------

def test_parse_due():
    wed = date(2026, 10, 21)  # a Wednesday
    assert parse_due("today", wed) == "2026-10-21"
    assert parse_due("tomorrow", wed) == "2026-10-22"
    assert parse_due("fri", wed) == "2026-10-23"
    assert parse_due("friday", wed) == "2026-10-23"
    assert parse_due("wed", wed) == "2026-10-28"  # next week's, never today
    assert parse_due("25/10", wed) == "2026-10-25"
    assert parse_due("1/1", wed) == "2027-01-01"
    assert parse_due("2026-11-02", wed) == "2026-11-02"
    assert parse_due("someday", wed) is None


def test_parse_duration():
    assert parse_duration_min("2h") == 120 and parse_duration_min("45m") == 45 and parse_duration_min("1.5hrs") == 90
    assert parse_duration_min("two") is None


def test_split_message():
    body = "\n".join(f"line {i} " + "x" * 90 for i in range(40))
    parts = split_message(body, limit=500)
    assert all(len(p) <= 500 for p in parts) and "".join(parts).replace("\n", "") == body.replace("\n", "")


# ---- commands ----------------------------------------------------------------------------------

def test_goal_commands(data_dir):
    cfg = get_config()
    r = handle(cfg, "goal add weekly 10h #learning Finish the ML course")
    assert "Goal #1" in r and "weekly" in r
    g = list_goals(cfg.db_path)[0]
    assert (g.kind, g.category, g.target_min, g.text) == ("weekly", "Learning/AI", 600, "Finish the ML course")
    handle(cfg, "goal add long Launch my startup")
    assert list_goals(cfg.db_path)[1].kind == "long-term"
    assert "Finish the ML course" in handle(cfg, "goals")
    assert "done" in handle(cfg, "goal done 1").lower()
    assert len(list_goals(cfg.db_path)) == 1
    assert "can't find" in handle(cfg, "goal done 99")


def test_goal_progress_counts_tracked_time(demo):
    handle(demo, "goal add daily 2h #coding Code every day")
    st = day_stats(demo, date.today())
    reply = handle(demo, "goals")
    mins = st.per_category.get("Coding", 0) / 60
    assert f"{int(round(mins)) // 60}h{int(round(mins)) % 60:02d}" in reply or f"{int(round(mins))}m" in reply


def test_team_and_tasks(data_dir):
    cfg = get_config()
    assert "Added *Riya*" in handle(cfg, "team add Riya ML engineer")
    assert list_members(cfg.db_path)[0].role == "ML engineer"
    r = handle(cfg, "task @riya make the pitch deck by tomorrow")
    t = list_tasks(cfg.db_path)[0]
    assert t.owner == "Riya" and t.text == "make the pitch deck" and t.due == (date.today() + timedelta(days=1)).isoformat()
    assert "Task #1" in r
    handle(cfg, "task @Arjun fix the API")  # unknown person -> added to the team
    assert {m.name for m in list_members(cfg.db_path)} == {"Riya", "Arjun"}
    assert "Riya" in handle(cfg, "team") and "1 open task" in handle(cfg, "team")
    assert "pitch deck" in handle(cfg, "tasks")
    assert "done" in handle(cfg, "task done 1")
    assert len(list_tasks(cfg.db_path)) == 1


def test_pause_resume_via_whatsapp(data_dir):
    cfg = get_config()
    assert "Paused" in handle(cfg, "pause") and control.is_paused(cfg)
    assert "paused" in handle(cfg, "status").lower()
    assert "Resumed" in handle(cfg, "RESUME") and not control.is_paused(cfg)


def test_summaries_use_the_same_numbers(demo):
    st = day_stats(demo, date.today())
    r = handle(demo, "today")
    assert fmt_dur(st.active_s) in r and f"*{st.focus_score}*" in r
    assert "Last 7 days" in handle(demo, "week")
    assert "doing best" in handle(demo, "best")
    assert "improve" in handle(demo, "improve").lower()


def test_freetext_falls_back_without_ai(data_dir):
    cfg = get_config()
    r = handle(cfg, "how do I stop doomscrolling?")
    assert "help" in r and "ANTHROPIC_API_KEY" in r


def test_freetext_uses_ai_with_history(data_dir, monkeypatch):
    cfg = get_config()
    seen = {}

    def fake_ask(cfg, task, facts, history=None):
        seen.update(task=task, facts=facts, history=history)
        return "Try a 25-min sprint 🚀"

    monkeypatch.setattr(commands.coach, "ask", fake_ask)
    handle(cfg, "hello there")  # greeting -> help, but logged
    assert handle(cfg, "I feel stuck") == "Try a 25-min sprint 🚀"
    assert "I feel stuck" in seen["task"] and "today so far" in seen["facts"]
    assert ("user", "hello there") in seen["history"]  # earlier chat is passed as memory, current one isn't duplicated
    assert ("user", "I feel stuck") not in seen["history"]


def test_plan_fallback(demo):
    r = handle(demo, "plan")
    assert "Plan for the rest of today" in r


# ---- insights + reports ------------------------------------------------------------------------

def test_insights_are_specific_and_numeric(demo):
    ins = compute_insights(demo)
    kinds = {i.kind for i in ins}
    assert kinds == {"best", "improve"}
    for i in ins:
        assert re.search(r"\d", i.text), i.text  # every insight carries a number
    assert any(re.search(r"\d+ (AM|PM)", i.text) for i in ins)  # names a time window


def test_reports_build_with_exact_numbers(demo):
    st = day_stats(demo, date.today())
    night = reports.build(demo, "night")
    assert fmt_dur(st.active_s) in night and f"*{st.focus_score}*" in night and "Tomorrow" in night
    morning = reports.build(demo, "morning")
    assert "Good morning" in morning and "Top 3 today" in morning and morning.count("\n1. ") == 1
    assert "Midday" in reports.build(demo, "midday")
    weekly = reports.build(demo, "weekly")
    assert "Weekly review" in weekly and "Experiment" in weekly


def test_report_dedupe_pause_and_demo(demo, monkeypatch):
    assert scheduler.send_report("night", demo) is True
    assert scheduler.send_report("night", demo) is False  # already sent today
    out = [m for m in recent_messages(demo.db_path, 10) if m.kind == "night"]
    assert len(out) == 1 and out[0].status == "dry-run"  # no Twilio creds -> logged, not sent
    control.pause(demo)
    assert scheduler.send_report("midday", demo) is False
    control.resume(demo)
    monkeypatch.setenv("WORKPULSE_DEMO", "1")
    assert scheduler.send_report("weekly", get_config()) is False


def test_catch_up_window(demo):
    bs = scheduler.BotScheduler(demo)
    t = datetime.now().replace(hour=21, minute=45)
    assert "night" in bs.catch_up(t)
    assert bs.catch_up(datetime.now().replace(hour=23, minute=59)) == []  # > 2h late: skip


def test_in_window():
    assert scheduler.in_window(datetime(2026, 1, 1, 23, 30), "23:00", "07:30")
    assert scheduler.in_window(datetime(2026, 1, 1, 6, 0), "23:00", "07:30")
    assert not scheduler.in_window(datetime(2026, 1, 1, 12, 0), "23:00", "07:30")
    assert scheduler.in_window(datetime(2026, 1, 1, 12, 0), "10:00", "20:00")


def test_nudges_entertainment_and_reminders(data_dir):
    cfg = get_config()
    now = datetime.combine(date.today(), datetime.min.time()) + timedelta(hours=15)
    t0 = now - timedelta(hours=1, minutes=10)
    upsert_sessions(cfg.db_path, [SessionRecord(start_ts=t0.timestamp(), end_ts=now.timestamp(), state="active",
                                                app="chrome", title="x - YouTube", category="Entertainment")])
    handle(cfg, "task finish slides by today")
    scheduler.check_nudges(cfg, now)
    scheduler.check_nudges(cfg, now)  # second run: nothing new
    kinds = [m.kind for m in recent_messages(cfg.db_path, 20) if m.direction == "out"]
    assert kinds.count("nudge-ent1") == 1 and kinds.count("reminder") == 1
    assert list_tasks(cfg.db_path)[0].reminded_at is not None


def test_nudges_respect_quiet_hours_and_pause(data_dir):
    cfg = get_config()
    handle(cfg, "task finish slides by today")
    scheduler.check_nudges(cfg, datetime.now().replace(hour=23, minute=30))
    control.pause(cfg)
    scheduler.check_nudges(cfg, datetime.now().replace(hour=15))
    assert not [m for m in recent_messages(cfg.db_path, 20) if m.direction == "out"]


# ---- webhook -----------------------------------------------------------------------------------

def _signed(url, params, token="tok123"):
    return {"X-Twilio-Signature": TwilioProvider.signature(token, url, params)}


@pytest.fixture()
def twilio_env(data_dir, monkeypatch):
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok123")
    return TestClient(app)


def test_signature_roundtrip(monkeypatch):
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "tok123")
    url, params = "https://abc.ngrok-free.app/api/whatsapp/twilio", {"From": "whatsapp:+1", "Body": "hi"}
    sig = TwilioProvider.signature("tok123", url, params)
    p = TwilioProvider()
    assert p.verify(url, params, sig)
    assert not p.verify(url, {**params, "Body": "tampered"}, sig)
    assert not p.verify(url, params, None)


def test_webhook_replies_to_my_number(twilio_env):
    url = "http://testserver/api/whatsapp/twilio"
    form = {"From": f"whatsapp:+{ME}", "Body": "goal add Ship v1"}
    r = twilio_env.post("/api/whatsapp/twilio", data=form, headers=_signed(url, form))
    assert r.status_code == 200 and "<Response>" in r.text
    msgs = recent_messages(get_config().db_path, 10)
    assert [(m.direction, m.status) for m in msgs] == [("in", "received"), ("out", "dry-run")]
    assert "Goal #1" in msgs[1].body


def test_webhook_rejects_bad_signature_and_strangers(twilio_env):
    form = {"From": f"whatsapp:+{ME}", "Body": "status"}
    assert twilio_env.post("/api/whatsapp/twilio", data=form, headers={"X-Twilio-Signature": "nope"}).status_code == 403
    url = "http://testserver/api/whatsapp/twilio"
    stranger = {"From": "whatsapp:+15550001111", "Body": "status"}
    r = twilio_env.post("/api/whatsapp/twilio", data=stranger, headers=_signed(url, stranger))
    assert r.status_code == 200
    assert recent_messages(get_config().db_path, 10) == []  # stranger's text isn't even stored


def test_tunnel_reaches_webhook_but_not_dashboard(twilio_env):
    tunnel = {"Host": "abc.ngrok-free.app", "X-Forwarded-Proto": "https", "X-Forwarded-For": "1.2.3.4"}
    form = {"From": f"whatsapp:+{ME}", "Body": "help"}
    sig = _signed("https://abc.ngrok-free.app/api/whatsapp/twilio", form)
    assert twilio_env.post("/api/whatsapp/twilio", data=form, headers={**tunnel, **sig}).status_code == 200
    assert twilio_env.get("/api/status", headers=tunnel).status_code in (400, 403)  # foreign Host
    spoofed = {"Host": "127.0.0.1", "X-Forwarded-For": "1.2.3.4"}
    assert twilio_env.get("/api/status", headers=spoofed).status_code == 403  # came through a proxy
    assert twilio_env.post("/api/wipe", headers={**spoofed, "X-WorkPulse-UI": "1"}, json={"confirm": "DELETE"}).status_code == 403


# ---- the coach's API call ----------------------------------------------------------------------

def test_coach_request_shape_and_refusal(monkeypatch):
    import importlib
    import types

    import anthropic

    import workpulse.bot.coach as real_coach
    real_coach = importlib.reload(real_coach)  # undo the autouse stub for this module object
    calls = []

    class FakeMessages:
        def __init__(self, stop):
            self.stop = stop

        def create(self, **kw):
            calls.append(kw)
            return types.SimpleNamespace(stop_reason=self.stop, stop_details=None,
                                         content=[types.SimpleNamespace(type="thinking", thinking=""),
                                                  types.SimpleNamespace(type="text", text="  Hi champ 👋 ")])

    def fake_client(stop):
        return lambda **kw: types.SimpleNamespace(beta=types.SimpleNamespace(messages=FakeMessages(stop)))

    cfg = get_config()
    monkeypatch.setattr(anthropic, "Anthropic", fake_client("end_turn"))
    real_coach._unavailable_until = 0
    assert real_coach.ask(cfg, "task", "facts", [("assistant", "old"), ("user", "hey")]) == "Hi champ 👋"
    kw = calls[-1]
    assert kw["model"] == "claude-opus-5-5" and kw["fallbacks"] == "default"
    assert kw["betas"] == ["server-side-fallback-2026-07-01"] and kw["output_config"] == {"effort": "low"}
    assert kw["messages"][0] == {"role": "user", "content": "hey"}  # history can't start with assistant
    assert "<facts>" in kw["messages"][-1]["content"]
    monkeypatch.setattr(anthropic, "Anthropic", fake_client("refusal"))
    assert real_coach.ask(cfg, "task", "facts") is None
