from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from workpulse.agent.sinks import TOKEN_HEADER, agent_token
from workpulse.backend.app import app
from workpulse.config import config_path, get_config
from workpulse.core.demo import generate
from workpulse.core.service import day_stats

UI = {"X-WorkPulse-UI": "1"}


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def ts(h, m=0, d=None):
    d = d or date.today()
    return datetime(d.year, d.month, d.day, h, m).timestamp()


def sess(i, h1, m1, h2, m2, state="active", app="code", cat="Coding", title="main.py", d=None):
    return {"id": f"test-{i:04d}-session", "start_ts": ts(h1, m1, d), "end_ts": ts(h2, m2, d), "state": state,
            "app": app, "title": title, "category": cat}


def ingest(client, sessions):
    return client.post("/api/ingest/sessions", json={"sessions": sessions},
                       headers={TOKEN_HEADER: agent_token(get_config())})


def test_ingest_requires_token(client):
    r = client.post("/api/ingest/sessions", json={"sessions": []})
    assert r.status_code == 401
    r = client.post("/api/ingest/sessions", json={"sessions": []}, headers={TOKEN_HEADER: "wrong"})
    assert r.status_code == 401


def test_dashboard_numbers_match_cli(client):
    """Acceptance check: the API returns exactly what `workpulse today` computes."""
    ingest(client, [sess(1, 0, 10, 1, 0), sess(2, 1, 0, 1, 20, app="chrome", cat="Entertainment"),
                    sess(3, 1, 20, 1, 30, state="idle"), sess(4, 1, 30, 2, 15, app="chrome", cat="Learning/AI")])
    api = client.get(f"/api/day?date={date.today()}").json()
    cli = day_stats(get_config(), date.today())
    for k in ("active_s", "productive_s", "idle_s", "longest_streak_s", "breaks", "focus_score", "first_activity", "last_activity"):
        assert api[k] == getattr(cli, k), k
    assert api["per_category"] == cli.per_category
    assert api["active_s"] == (50 + 20 + 45) * 60
    assert [a["name"] for a in api["top_apps"]] == ["Chrome", "VS Code"]  # aliases applied
    assert len(api["timeline"]) == 4


def test_ingest_upsert_and_zero_length_delete(client):
    ingest(client, [sess(1, 0, 10, 0, 20)])
    s = sess(1, 0, 10, 0, 10)  # same id, shrunk to nothing
    ingest(client, [s])
    assert client.get("/api/day").json()["active_s"] == 0


def test_ingest_validation(client):
    bad = sess(1, 0, 10, 0, 20)
    bad["state"] = "typing"
    assert ingest(client, [bad]).status_code == 422


def test_server_drops_titles_when_capture_disabled(client):
    client.put("/api/settings", json={"privacy": {"capture_titles": False}}, headers=UI)
    ingest(client, [sess(1, 0, 10, 0, 20, title="secret plans.docx")])
    assert client.get("/api/day").json()["timeline"][0]["title"] is None


def test_pause_resume_need_ui_header(client, data_dir):
    assert client.post("/api/pause").status_code == 403
    r = client.post("/api/pause", headers=UI)
    assert r.json()["tracking"] == "paused" and (data_dir / "paused.flag").exists()
    r = client.post("/api/resume", headers=UI)
    assert r.json()["tracking"] == "off" and not (data_dir / "paused.flag").exists()


def test_settings_roundtrip_and_validation(client, data_dir):
    before = config_path().read_text(encoding="utf-8")
    r = client.put("/api/settings", headers=UI, json={"tracking": {"idle_after_s": 180}, "categories": {"apps": {"notion": "Content Creation"}}})
    assert r.status_code == 200
    s = client.get("/api/settings").json()
    assert s["tracking"]["idle_after_s"] == 180 and s["categories"]["apps"]["notion"] == "Content Creation"
    assert s["categories"]["apps"]["code"] == "Coding"  # merged, not replaced
    assert config_path().read_text(encoding="utf-8") == before  # config.yaml untouched
    assert (data_dir / "settings.yaml").exists()
    assert client.put("/api/settings", headers=UI, json={"tracking": {"idle_after_s": -5}}).status_code == 422
    assert client.put("/api/settings", headers=UI, json={"server": {"host": "0.0.0.0"}}).status_code == 400
    assert client.put("/api/settings", json={"tracking": {"idle_after_s": 200}}).status_code == 403


def test_wipe_requires_confirmation(client):
    ingest(client, [sess(1, 0, 10, 0, 20)])
    assert client.post("/api/wipe", headers=UI, json={"confirm": "yes"}).status_code == 400
    assert client.post("/api/wipe", headers=UI, json={"confirm": "DELETE"}).json() == {"deleted": 1}


def test_rejects_foreign_host_header(client):
    """DNS-rebinding protection: a page on evil.example resolving to 127.0.0.1 gets nothing."""
    assert client.get("/api/status", headers={"Host": "evil.example"}).status_code == 400


def test_week_endpoint_with_demo_history(client):
    from workpulse.core.db import upsert_sessions
    upsert_sessions(get_config().db_path, generate(days=14), source="demo")
    w = client.get("/api/week").json()
    assert len(w["days"]) == 7 and w["days"][-1]["date"] == date.today().isoformat()
    assert w["trend"]["prev_active_s"] > 0 and w["trend_text"]
    assert sum(w["category_totals"].values()) == pytest.approx(sum(d["active_s"] for d in w["days"]))
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    assert client.get(f"/api/day?date={yesterday}").json()["active_s"] > 0


def test_export_and_index(client):
    ingest(client, [sess(1, 0, 10, 0, 20)])
    r = client.get("/api/export.csv")
    assert r.status_code == 200 and r.text.splitlines()[0].startswith("start,end,duration_s")
    assert len(r.text.strip().splitlines()) == 2
    assert "WorkPulse" in client.get("/").text
    assert client.get("/assets/app.js").status_code == 200


def test_demo_server_refuses_ingest(client, monkeypatch):
    monkeypatch.setenv("WORKPULSE_DEMO", "1")
    assert ingest(client, [sess(1, 0, 10, 0, 20)]).status_code == 409


def test_bad_date(client):
    assert client.get("/api/day?date=yesterday").status_code == 400
