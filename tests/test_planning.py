import sqlite3
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from workpulse.backend.app import app
from workpulse.bot import roadmap
from workpulse.bot.commands import handle
from workpulse.config import get_config
from workpulse.core.db import get_engine, upsert_sessions
from workpulse.core.demo import generate
from workpulse.core.insights import collaboration
from workpulse.core.models import SessionRecord

UI = {"X-WorkPulse-UI": "1"}


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def at(h, m=0, d=None):
    d = d or date.today()
    return datetime(d.year, d.month, d.day, h, m).timestamp()


# ---- goals -------------------------------------------------------------------------------------

def test_goal_crud_and_tracked_progress(client):
    cfg = get_config()
    upsert_sessions(cfg.db_path, [SessionRecord(start_ts=at(0, 10), end_ts=at(1, 10), state="active", app="code",
                                                title=None, category="Coding")])
    r = client.post("/api/goals", headers=UI, json={"text": "Code daily", "kind": "daily", "category": "Coding", "target_min": 120})
    assert r.status_code == 200
    g = r.json()
    assert g["tracked_min"] == pytest.approx(60) and g["pct"] == pytest.approx(50)
    gid = g["id"]
    r = client.patch(f"/api/goals/{gid}", headers=UI, json={"target_min": 60, "deadline": "2026-12-31"})
    assert r.json()["pct"] == pytest.approx(100) and r.json()["deadline"] == "2026-12-31"
    client.patch(f"/api/goals/{gid}", headers=UI, json={"done": True})
    assert client.get("/api/goals").json()["goals"] == []
    assert client.get("/api/goals?include_done=true").json()["goals"][0]["done"] is True
    assert client.delete(f"/api/goals/{gid}", headers=UI).json() == {"deleted": True}
    assert client.delete(f"/api/goals/{gid}", headers=UI).status_code == 404


def test_goal_validation_and_manual_progress(client):
    assert client.post("/api/goals", headers=UI, json={"text": "x", "category": "Gaming"}).status_code == 422
    assert client.post("/api/goals", headers=UI, json={"text": "x", "deadline": "next week"}).status_code == 422
    assert client.post("/api/goals", headers=UI, json={"text": "x", "kind": "yearly"}).status_code == 422
    assert client.post("/api/goals", json={"text": "x"}).status_code == 403  # dashboard header required
    g = client.post("/api/goals", headers=UI, json={"text": "Launch my startup", "kind": "long-term"}).json()
    assert g["pct"] is None
    g = client.patch(f"/api/goals/{g['id']}", headers=UI, json={"manual_pct": 35}).json()
    assert g["pct"] == 35 and "35% done" in g["summary"]
    assert client.patch(f"/api/goals/{g['id']}", headers=UI, json={"manual_pct": 140}).status_code == 422


# ---- roadmap -----------------------------------------------------------------------------------

def test_roadmap_milestones_and_suggestions(client):
    g = client.post("/api/goals", headers=UI, json={"text": "Launch my startup", "kind": "long-term"}).json()
    rm = client.get("/api/roadmap").json()
    assert [h["key"] for h in rm["horizons"]] == ["100d", "6m", "1y"] and rm["long_term_goals"][0]["id"] == g["id"]
    s = client.post("/api/roadmap/suggest", headers=UI, json={"goal_id": g["id"]}).json()
    assert s["source"] == "template" and {x["horizon"] for x in s["suggestions"]} == {"100d", "6m", "1y"}
    assert client.get("/api/roadmap").json()["horizons"][0]["milestones"] == []  # suggestions aren't saved
    m = client.post("/api/roadmap/milestones", headers=UI, json={"horizon": "100d", "text": s["suggestions"][0]["text"],
                                                                "goal_id": g["id"], "source": "coach"}).json()
    assert m["target_date"] == (date.today() + timedelta(days=100)).isoformat()
    assert client.patch(f"/api/roadmap/milestones/{m['id']}", headers=UI, json={"done": True}).json()["done"] is True
    assert client.post("/api/roadmap/milestones", headers=UI, json={"horizon": "5y", "text": "x"}).status_code == 422
    client.delete(f"/api/goals/{g['id']}", headers=UI)  # deleting the goal removes its milestones
    assert all(not h["milestones"] for h in client.get("/api/roadmap").json()["horizons"])


def test_roadmap_parses_ai_lines(data_dir, monkeypatch):
    cfg = get_config()
    from workpulse.core.store import add_goal
    g = add_goal(cfg.db_path, "Build my first AI model", "long-term")
    monkeypatch.setattr(roadmap.coach, "ask", lambda *a, **k: "Sure!\n100d: Train a CNN on CIFAR-10\n- 6m: Publish a Kaggle notebook\n1y – Ship a model API\nrandom line")
    items, source = roadmap.suggest(cfg, g)
    assert source == "coach"
    assert items == [("100d", "Train a CNN on CIFAR-10"), ("6m", "Publish a Kaggle notebook"), ("1y", "Ship a model API")]
    monkeypatch.setattr(roadmap.coach, "ask", lambda *a, **k: "no structure here")
    assert roadmap.suggest(cfg, g)[1] == "template"


# ---- team, tasks, meetings ---------------------------------------------------------------------

def test_team_tasks_meetings(client):
    assert client.post("/api/team/members", headers=UI, json={"name": "Riya", "role": "ML"}).status_code == 200
    assert client.post("/api/team/members", headers=UI, json={"name": "riya"}).status_code == 409
    assert client.post("/api/team/members", headers=UI, json={"name": "@bad"}).status_code == 422
    t = client.post("/api/tasks", headers=UI, json={"text": "Pitch deck", "owner": "RIYA", "due": "2026-10-30"}).json()
    assert t["owner"] == "Riya" and t["status"] == "todo"
    t2 = client.post("/api/tasks", headers=UI, json={"text": "Fix API", "owner": "Arjun"}).json()  # new person auto-added
    assert t2["owner"] == "Arjun"
    assert client.patch(f"/api/tasks/{t['id']}", headers=UI, json={"status": "doing"}).json()["status"] == "doing"
    assert client.patch(f"/api/tasks/{t['id']}", headers=UI, json={"status": "blocked"}).status_code == 422
    client.patch(f"/api/tasks/{t2['id']}", headers=UI, json={"status": "done"})
    m = client.post("/api/meetings", headers=UI, json={"title": "Standup", "minutes": 30, "attendees": ["riya", "me"]}).json()
    assert m["attendees"] == ["Riya"]
    team = client.get("/api/team").json()
    assert {x["name"]: x["open_tasks"] for x in team["members"]} == {"Arjun": 0, "Riya": 1}
    assert {x["status"] for x in team["tasks"]} == {"doing", "done"}  # recently done tasks stay visible
    assert team["collaboration"]["meeting_s"] == 1800
    assert client.delete(f"/api/meetings/{m['id']}", headers=UI).json() == {"deleted": True}
    assert client.post("/api/meetings", headers=UI, json={"title": "x", "minutes": 0}).status_code == 422


def test_collaboration_share(data_dir):
    cfg = get_config()
    upsert_sessions(cfg.db_path, [
        SessionRecord(start_ts=at(0, 0), end_ts=at(3, 0), state="active", app="code", title=None, category="Coding"),
        SessionRecord(start_ts=at(3, 0), end_ts=at(4, 0), state="active", app="discord", title=None, category="Communication"),
    ])
    handle(cfg, "meeting 1h pitch prep @Riya")
    c = collaboration(cfg)
    assert c["meeting_s"] == 3600 and c["communication_s"] == 3600 and c["active_s"] == 4 * 3600
    assert c["share"] == pytest.approx(2 / 5)  # (1h meeting + 1h chat) / (4h laptop + 1h meeting)


# ---- bot commands ------------------------------------------------------------------------------

def test_bot_meeting_roadmap_progress(data_dir):
    cfg = get_config()
    r = handle(cfg, "meeting 45 standup @Riya @arjun")
    assert "Logged *standup*" in r and "Riya, arjun" in r and "Collaboration this week" in r
    assert "Start with the length" in handle(cfg, "meeting standup")
    assert "No roadmap yet" in handle(cfg, "roadmap")
    handle(cfg, "goal add long Launch my startup")
    from workpulse.core.store import add_milestone
    add_milestone(cfg.db_path, "6m", "First 10 paying users", goal_id=1)
    r = handle(cfg, "roadmap")
    assert "*6 months*" in r and "First 10 paying users" in r and "\n" in r
    assert "*40%*" in handle(cfg, "goal progress 1 40")
    assert "Use *goal progress" in handle(cfg, "goal progress 1 400")


# ---- insights, chat, migration -----------------------------------------------------------------

def test_insights_endpoint(client):
    upsert_sessions(get_config().db_path, generate(days=14))
    r = client.get("/api/insights").json()
    assert r["best"] and r["improve"]
    p = r["profile"]
    assert len(p["hours"]) == 24 and len(p["calendar"]) == 30 and p["weekdays"] and p["sources"]
    assert sum(h["productive_min"] for h in p["hours"]) > 0


def test_chat_endpoint_uses_bot_brain(client):
    r = client.post("/api/chat", headers=UI, json={"text": "goal add weekly 5h #learning ML course"})
    assert "Goal #1" in r.json()["reply"]
    msgs = client.get("/api/messages").json()["messages"]
    assert [(m["direction"], m["status"]) for m in msgs] == [("in", "local"), ("out", "local")]
    assert client.post("/api/chat", json={"text": "hi"}).status_code == 403


def test_migration_adds_new_columns_to_old_db(tmp_path):
    db = tmp_path / "old.db"
    con = sqlite3.connect(db)  # a goals table as Phase 3 created it (no manual_pct)
    con.execute("CREATE TABLE goals (id INTEGER PRIMARY KEY, text VARCHAR(300) NOT NULL, kind VARCHAR(12) NOT NULL, "
                "category VARCHAR(32), target_min FLOAT, deadline VARCHAR(10), done BOOLEAN NOT NULL, done_at FLOAT, "
                "created_at FLOAT NOT NULL)")
    con.execute("INSERT INTO goals (text, kind, done, created_at) VALUES ('old goal', 'daily', 0, 1)")
    con.commit()
    con.close()
    get_engine(db)
    con = sqlite3.connect(db)
    cols = {r[1] for r in con.execute("PRAGMA table_info(goals)")}
    assert "manual_pct" in cols
    assert con.execute("SELECT text, manual_pct FROM goals").fetchall() == [("old goal", None)]  # data kept
