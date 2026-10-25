import types
from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from workpulse.backend.app import app
from workpulse.backend.phone_api import PHONE_TOKEN_HEADER, phone_token
from workpulse.bot.commands import handle
from workpulse.bot import reports
from workpulse.config import get_config
from workpulse.core import phone
from workpulse.core.db import upsert_sessions
from workpulse.core.models import SessionRecord

UI = {"X-WorkPulse-UI": "1"}
TODAY = date.today().isoformat()


@pytest.fixture()
def client(data_dir):
    return TestClient(app)


def tok():
    return {PHONE_TOKEN_HEADER: phone_token(get_config())}


# ---- parsing -----------------------------------------------------------------------------------

@pytest.mark.parametrize("raw,secs", [
    ("1h 20m", 4800), ("1 hr 5 min", 3900), ("01:20:00", 4800), ("1:20", 4800), ("80", 4800),
    ("45m", 2700), ("30s", 30), ("2 hours", 7200), (90, 5400), ("", None), ("soon", None),
])
def test_parse_duration(raw, secs):
    assert phone.parse_duration(raw) == secs


def test_parse_day():
    assert phone.parse_day("2026-10-20") == "2026-10-20"
    assert phone.parse_day("20/10/2026") == "2026-10-20"
    assert phone.parse_day("2026-10-20T08:00:00") == "2026-10-20"
    assert phone.parse_day(None) == TODAY
    with pytest.raises(ValueError):
        phone.parse_day("yesterday-ish")


def test_categorize_and_package_names(data_dir):
    cfg = get_config()
    assert phone.categorize_app(cfg, "Instagram") == "Entertainment"
    assert phone.categorize_app(cfg, "Yt", "com.google.android.youtube") == "Entertainment"
    assert phone.categorize_app(cfg, "YouTube Studio") == "Content Creation"  # specific rule beats generic
    assert phone.categorize_app(cfg, "WhatsApp") == "Communication"
    assert phone.categorize_app(cfg, "Duolingo") == "Learning/AI"
    assert phone.categorize_app(cfg, "Some Random App") == "Other"
    assert phone.pretty_package("com.instagram.android") == "Instagram"
    assert phone.pretty_package("com.google.android.youtube") == "Youtube"


def test_csv_import_tolerant_headers(data_dir):
    cfg = get_config()
    csv_text = ("﻿Date,App Name,Usage Time,Pickups\n"
                "20/10/2026,Instagram,1h 10m,40\n20/10/2026,WhatsApp,45m,30\n"
                "21/10/2026,com.instagram.android,30m,\n21/10/2026,Total,2h,\n")
    days = phone.from_csv(cfg, csv_text)
    by_day = {d.day: d for d in days}
    assert by_day["2026-10-20"].pickups == 70 and len(by_day["2026-10-20"].apps) == 2
    d21 = by_day["2026-10-21"]
    assert d21.total_s == 7200 and d21.apps[0].app == "Instagram" and d21.apps[0].package == "com.instagram.android"
    minutes_csv = "day,app,minutes\n2026-10-20,YouTube,90\n"
    assert phone.from_csv(cfg, minutes_csv)[0].apps[0].seconds == 5400
    with pytest.raises(ValueError):
        phone.from_csv(cfg, "foo,bar\n1,2\n")


def test_save_is_idempotent_and_validated(data_dir):
    cfg = get_config()
    d = phone.PhoneDayData(day="2026-10-20", apps=[phone.PhoneAppUsage("Instagram", 3600), phone.PhoneAppUsage("WhatsApp", 1800)])
    phone.save_day(cfg, d, "manual")
    phone.save_day(cfg, d, "manual")  # re-import replaces, doesn't double
    days, apps = phone.load_days(cfg, date(2026, 10, 20), date(2026, 10, 20))
    assert len(days) == 1 and days[0].total_s == 5400 and len(apps) == 2
    assert {a.category for a in apps} == {"Entertainment", "Communication"}
    # a reported total smaller than its apps is raised to the apps' sum
    phone.save_day(cfg, phone.PhoneDayData(day="2026-10-20", total_s=60, apps=d.apps), "manual")
    assert phone.load_days(cfg, date(2026, 10, 20), date(2026, 10, 20))[0][0].total_s == 5400
    with pytest.raises(ValueError, match="24h"):
        phone.save_day(cfg, phone.PhoneDayData(day="2026-10-20", total_s=90000), "manual")
    with pytest.raises(ValueError):
        phone.save_day(cfg, phone.PhoneDayData(day="2026-10-20"), "manual")


ADB_SAMPLE = """
user 0:
  In-memory daily stats
  timeRange="10/21/2026, 00:00 – 10/21/2026, 18:00"
  packages
    package=com.instagram.android totalTimeUsed="1:02:03" lastTimeUsed="2026-10-21 17:59:00" totalTimeVisible="1:05:00"
    package=com.whatsapp totalTimeUsed="20:11" lastTimeUsed="2026-10-21 17:00:00"
    package=com.android.launcher3 totalTimeUsed="05:00" lastTimeUsed="2026-10-21 17:00:00"
    package=com.android.settings totalTimeUsed="00:20" lastTimeUsed="2026-10-21 12:00:00"
  In-memory weekly stats
    package=com.instagram.android totalTimeUsed="9:00:00"
"""


def test_adb_parser_reads_daily_block_only():
    d = phone.parse_adb_usagestats(ADB_SAMPLE, day="2026-10-21")
    secs = {a.package: a.seconds for a in d.apps}
    assert secs == {"com.instagram.android": 3723, "com.whatsapp": 1211}  # launcher + <1 min skipped, weekly ignored
    with pytest.raises(ValueError):
        phone.parse_adb_usagestats("nothing here")


# ---- digital day -------------------------------------------------------------------------------

def test_digital_day_combines_laptop_and_phone(data_dir):
    cfg = get_config()
    t = datetime.combine(date.today(), datetime.min.time())
    upsert_sessions(cfg.db_path, [SessionRecord(start_ts=(t + timedelta(hours=0)).timestamp(), end_ts=(t + timedelta(hours=2)).timestamp(),
                                                state="active", app="code", title=None, category="Coding")])
    phone.save_day(cfg, phone.PhoneDayData(day=TODAY, pickups=50, apps=[phone.PhoneAppUsage("Instagram", 3600),
                                                                          phone.PhoneAppUsage("Duolingo", 1800)]), "manual")
    dd = phone.digital_day(cfg, date.today())
    assert dd["laptop_active_s"] == 7200 and dd["phone_s"] == 5400 and dd["total_s"] == 12600
    assert dd["productive_s"] == 7200 + 1800  # Duolingo counts as Learning/AI
    assert dd["phone_share"] == pytest.approx(5400 / 12600) and dd["pickups"] == 50
    cats = {c["name"]: (c["laptop_s"], c["phone_s"]) for c in dd["categories"]}
    assert cats["Coding"] == (7200, 0) and cats["Entertainment"] == (0, 3600)
    assert phone.digital_range(cfg, date.today(), 7)[-1]["phone_s"] == 5400


# ---- API ---------------------------------------------------------------------------------------

def test_ingest_requires_phone_token(client):
    body = {"day": TODAY, "total": "2h", "apps": [{"name": "Instagram", "minutes": 70}]}
    assert client.post("/api/phone/ingest", json=body).status_code == 401
    assert client.post("/api/phone/ingest", json=body, headers={PHONE_TOKEN_HEADER: "nope"}).status_code == 401
    r = client.post("/api/phone/ingest", json=body, headers=tok())
    assert r.status_code == 200 and r.json()["stored"][0]["total_s"] == 7200
    assert client.post("/api/phone/ingest", json={"day": "garbage"}, headers=tok()).status_code == 422


def test_ingest_accepts_shortcut_friendly_apps_text(client):
    r = client.post("/api/phone/ingest", headers=tok(),
                    json={"total_minutes": 200, "pickups": "75", "apps_text": "Instagram=70m, WhatsApp=40\nYouTube = 1h"})
    assert r.status_code == 200
    d = client.get(f"/api/digital?date={TODAY}").json()
    assert d["phone_s"] == 12000 and d["pickups"] == 75
    assert {a["app"]: a["seconds"] for a in d["phone_top_apps"]} == {"Instagram": 4200, "YouTube": 3600, "WhatsApp": 2400}


def test_ingest_reachable_through_tunnel_but_token_still_required(client):
    tunnel = {"Host": "abc.ngrok-free.app", "X-Forwarded-For": "1.2.3.4", "X-Forwarded-Proto": "https"}
    body = [{"day": TODAY, "apps": [{"name": "WhatsApp", "time": "30m"}]}]
    assert client.post("/api/phone/ingest", json=body, headers=tunnel).status_code == 401
    assert client.post("/api/phone/ingest", json=body, headers={**tunnel, **tok()}).status_code == 200
    assert client.get("/api/phone/setup", headers=tunnel).status_code in (400, 403)  # token page stays local-only
    assert client.get("/api/digital", headers=tunnel).status_code in (400, 403)


def test_import_manual_delete_and_digital_endpoint(client):
    csv_bytes = b"date,app,time\n" + f"{TODAY},Instagram,1h\n{TODAY},WhatsApp,30m\n".encode()
    r = client.post("/api/phone/import", headers=UI, files={"file": ("usage.csv", csv_bytes, "text/csv")})
    assert r.status_code == 200 and r.json()["stored"][0]["source"] == "csv"
    assert client.post("/api/phone/import", files={"file": ("u.csv", csv_bytes, "text/csv")}).status_code == 403
    r = client.post("/api/phone/manual", headers=UI, json={"day": TODAY, "device": "ipad", "total": "1h 30m",
                                                           "apps": [{"name": "Kindle", "time": "50m"}]})
    assert r.json()["stored"][0] == {"device": "ipad", "day": TODAY, "total_s": 5400, "pickups": None, "source": "manual"}
    d = client.get(f"/api/digital?date={TODAY}").json()
    assert d["phone_s"] == 5400 + 5400 and len(d["phone_devices"]) == 2 and len(d["week"]) == 7
    assert client.delete(f"/api/phone/day?date={TODAY}&device=ipad", headers=UI).json() == {"deleted": 1}
    assert client.get(f"/api/digital?date={TODAY}").json()["phone_s"] == 5400
    assert client.post("/api/phone/manual", headers=UI, json={"day": TODAY, "apps": [{"name": "X", "time": "lots"}]}).status_code == 422


def test_screenshot_endpoint_reads_numbers_without_saving(client, monkeypatch):
    import anthropic
    seen = {}

    class FakeMessages:
        def create(self, **kw):
            seen.update(kw)
            text = '```json\n{"period":"day","date":null,"relative":"yesterday","total_minutes":205,"pickups":91,' \
                   '"apps":[{"name":"Instagram","minutes":83},{"name":"WhatsApp","minutes":41},{"name":"","minutes":5}]}\n```'
            return types.SimpleNamespace(stop_reason="end_turn", content=[types.SimpleNamespace(type="text", text=text)])

    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: types.SimpleNamespace(beta=types.SimpleNamespace(messages=FakeMessages())))
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 100
    r = client.post("/api/phone/screenshot", headers=UI, files={"file": ("st.png", png, "image/png")})
    assert r.status_code == 200
    out = r.json()
    assert out["day"] == (date.today() - timedelta(days=1)).isoformat() and out["total_minutes"] == 205
    assert [a["name"] for a in out["apps"]] == ["Instagram", "WhatsApp"]  # blank rows dropped
    img = seen["messages"][0]["content"][0]
    assert img["type"] == "image" and img["source"]["media_type"] == "image/png"
    assert client.get(f"/api/digital?date={out['day']}").json()["has_phone_data"] is False  # nothing saved
    assert client.post("/api/phone/screenshot", headers=UI, files={"file": ("x.txt", b"hi", "text/plain")}).status_code == 422


def test_screenshot_without_api_key_explains(client):
    r = client.post("/api/phone/screenshot", headers=UI, files={"file": ("st.png", b"\x89PNG....", "image/png")})
    assert r.status_code == 422 and "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_setup_endpoint(client):
    s = client.get("/api/phone/setup").json()
    assert s["token"] == phone_token(get_config()) and s["path"] == "/api/phone/ingest"


# ---- bot ---------------------------------------------------------------------------------------

def test_bot_phone_command_and_night_report(data_dir):
    cfg = get_config()
    assert "No phone screen time yet" in handle(cfg, "phone")
    phone.save_day(cfg, phone.PhoneDayData(day=TODAY, pickups=60, apps=[phone.PhoneAppUsage("Instagram", 4000)]), "manual")
    r = handle(cfg, "phone")
    assert "digital day" in r and "Instagram 1h 07m" in r and "60 pickups" in r and "Phone in another room" in r
    t = datetime.combine(date.today(), datetime.min.time())
    upsert_sessions(cfg.db_path, [SessionRecord(start_ts=t.timestamp(), end_ts=(t + timedelta(hours=1)).timestamp(),
                                                state="active", app="code", title=None, category="Coding")])
    assert "📱 Phone 1h 07m (top: Instagram 1h 07m)" in reports.build(cfg, "night")
