"""Regression tests for the issues found in the full-folder review (1.1.1)."""
from fastapi.testclient import TestClient

from workpulse import cli
from workpulse.backend.app import app
from workpulse.config import get_config, save_settings
from workpulse.core import devices, phone
from workpulse.core.categorize import PRIVATE_APP
from workpulse.core.db import PairingCode, PhoneApp, session_scope
from workpulse.core.store import recent_messages

UI = {"X-WorkPulse-UI": "1"}
DAY = "2026-10-21"


def apps_for(cfg, day=DAY):
    _, apps = phone.load_days(cfg, phone.date.fromisoformat(day), phone.date.fromisoformat(day))
    return {a.app: (a.seconds, a.category, a.package) for a in apps}


def test_never_log_list_applies_to_phone_apps(data_dir):
    """Review #1: a banking app synced from the phone was stored by name."""
    cfg = get_config()
    phone.save_day(cfg, phone.PhoneDayData(day=DAY, apps=[
        phone.PhoneAppUsage("IPPB Mobile", 120, "com.iexceed.appzillon.ippbMB"),
        phone.PhoneAppUsage("My Bank", 60, "com.example.mybank"),        # keyword in the package
        phone.PhoneAppUsage("Instagram", 3600, "com.instagram.android"),
    ]), "api")
    stored = apps_for(cfg)
    assert set(stored) == {PRIVATE_APP, "Instagram"}
    assert stored[PRIVATE_APP] == (180, "Other", None)  # time still counted, identity gone
    assert phone.load_days(cfg, phone.date(2026, 10, 21), phone.date(2026, 10, 21))[0][0].total_s == 3780


def test_existing_phone_rows_are_scrubbed_when_the_list_grows(data_dir):
    cfg = get_config()
    phone.save_day(cfg, phone.PhoneDayData(day=DAY, apps=[phone.PhoneAppUsage("Dr. Driving", 300, "com.ansangha.drdriving"),
                                                         phone.PhoneAppUsage("WhatsApp", 600, "com.whatsapp")]), "api")
    assert "Dr. Driving" in apps_for(cfg)
    new = save_settings({"privacy": {"exclude_keywords": [*cfg.privacy.exclude_keywords, "driving"]}})
    assert phone.apply_privacy_to_stored(new) == 1
    stored = apps_for(new)
    assert set(stored) == {PRIVATE_APP, "WhatsApp"} and stored[PRIVATE_APP][0] == 300
    assert phone.apply_privacy_to_stored(new) == 0  # idempotent


def test_privacy_settings_change_from_dashboard_scrubs_phone_data(data_dir):
    cfg = get_config()
    phone.save_day(cfg, phone.PhoneDayData(day=DAY, apps=[phone.PhoneAppUsage("Secret Diary", 300)]), "api")
    r = TestClient(app).put("/api/settings", headers=UI, json={"privacy": {"exclude_keywords": ["diary"]}})
    assert r.status_code == 200
    assert set(apps_for(get_config())) == {PRIVATE_APP}


def test_android_category_hints_fill_gaps(data_dir):
    """Review #5: games fell into Other."""
    cfg = get_config()
    assert phone.categorize_app(cfg, "Dr. Driving", "com.ansangha.drdriving", "game") == "Entertainment"
    assert phone.categorize_app(cfg, "WhatsApp", "com.whatsapp", "social") == "Communication"  # config.yaml wins
    assert phone.categorize_app(cfg, "Gallery", "com.coloros.gallery3d", "image") == "Other"
    items = phone.from_json(cfg, {"day": DAY, "apps": [{"name": "Dr. Driving", "seconds": 600, "category_hint": "game"}]})
    phone.save_day(cfg, items[0], "api")
    assert apps_for(cfg)["Dr. Driving"][1] == "Entertainment"


def test_phone_chat_is_labelled_as_phone(data_dir):
    """Review #6: messages typed on the phone showed up as 'this laptop'."""
    save_settings({"server": {"lan": True}})
    laptop = TestClient(app)
    phone_client = TestClient(app, client=("192.168.1.50", 5000), headers={"Host": "192.168.1.20:8787"})
    code = laptop.post("/api/pairing/start", headers=UI).json()["code"]
    token = phone_client.post("/api/pair", json={"code": code, "name": "Test Phone"}).json()["token"]
    phone_client.post("/api/chat", headers={**UI, "Authorization": f"Bearer {token}"}, json={"text": "help"})
    laptop.post("/api/chat", headers=UI, json={"text": "help"})
    statuses = [(m.direction, m.status) for m in recent_messages(get_config().db_path, 10)]
    assert statuses == [("in", "app"), ("out", "app"), ("in", "local"), ("out", "local")]


def test_old_pairing_codes_are_deleted(data_dir):
    """Review #9: used codes piled up."""
    cfg = get_config()
    for _ in range(5):
        code, _ = devices.new_code(cfg)
    devices.redeem(cfg, code, "phone")
    devices.new_code(cfg)
    with session_scope(cfg.db_path) as s:
        assert s.query(PairingCode).count() <= 2


def test_connect_refuses_when_dashboard_is_not_running(data_dir, capsys):
    """Review #8: a code was printed even though nothing could accept it."""
    save_settings({"server": {"lan": True}})
    cli.main(["connect"])
    out = capsys.readouterr().out
    assert "isn't running" in out and "workpulse start" in out
    with session_scope(get_config().db_path) as s:
        assert s.query(PairingCode).count() == 0


def test_config_yaml_phone_keywords_cover_indian_payment_apps():
    from workpulse.config import ROOT, load_config
    cfg = load_config(ROOT / "config.yaml")
    for name, pkg in [("IPPB Mobile", "com.iexceed.appzillon.ippbMB"), ("BHIM", "in.org.npci.upiapp"),
                      ("Google Pay", "com.google.android.apps.nbu.paisa.user"), ("YONO SBI", "com.sbi.lotusintouch")]:
        assert phone.is_private(cfg, name, pkg), name
    for name in ("Instagram", "Stupid Zombies", "Cupid"):
        assert not phone.is_private(cfg, name), name  # no over-eager keywords


def test_phone_app_rows_never_hold_private_names(data_dir):
    cfg = get_config()
    phone.save_day(cfg, phone.PhoneDayData(day=DAY, apps=[phone.PhoneAppUsage("PhonePe", 50, "com.phonepe.app")]), "api")
    with session_scope(cfg.db_path) as s:
        assert [r.app for r in s.query(PhoneApp).all()] == [PRIVATE_APP]
