"""Phone access over the home Wi-Fi: pairing, device tokens, what a phone may and may not do."""
import time

import pytest
from fastapi.testclient import TestClient

from workpulse.backend.app import app
from workpulse.config import get_config, save_settings
from workpulse.core import devices
from workpulse.core.db import PairingCode, session_scope

UI = {"X-WorkPulse-UI": "1"}
PHONE_IP = ("192.168.1.50", 51515)
LAN_HOST = {"Host": "192.168.1.20:8787"}


@pytest.fixture()
def laptop(data_dir):
    return TestClient(app)


@pytest.fixture()
def phone(data_dir):
    return TestClient(app, client=PHONE_IP, headers=LAN_HOST)


def lan_on():
    save_settings({"server": {"lan": True}})


def pair(laptop, phone, kind="web"):
    code = laptop.post("/api/pairing/start", headers=UI).json()["code"]
    r = phone.post("/api/pair", json={"code": code, "name": "Test Phone", "kind": kind})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}", **UI}


def test_phone_is_refused_while_wifi_access_is_off(laptop, phone):
    r = phone.get("/api/day")
    assert r.status_code == 403 and "lan on" in r.text
    assert phone.get("/m/").status_code == 403


def test_pairing_and_authenticated_access(laptop, phone):
    lan_on()
    assert phone.get("/m/").status_code == 200  # the app shell is public on the LAN (no data in it)
    assert phone.get("/api/ping").json()["app"] == "workpulse"
    assert phone.get("/api/day").status_code == 401  # data needs a token
    auth = pair(laptop, phone)
    assert phone.get("/api/day", headers=auth).status_code == 200
    assert phone.get("/api/whoami", headers=auth).json()["device"] == "Test Phone"
    assert phone.post("/api/pause", headers=auth).json()["tracking"] == "paused"  # privacy switch works from the phone
    assert phone.post("/api/chat", headers=auth, json={"text": "goal add Ship v1"}).json()["reply"].startswith("🎯")
    dev = laptop.get("/api/devices").json()["devices"][0]
    assert dev["name"] == "Test Phone" and dev["last_ip"] == PHONE_IP[0]


def test_laptop_only_actions_are_refused_from_a_paired_phone(laptop, phone):
    lan_on()
    auth = pair(laptop, phone)
    assert phone.put("/api/settings", headers=auth, json={"tracking": {"idle_after_s": 300}}).status_code == 403
    assert phone.post("/api/wipe", headers=auth, json={"confirm": "DELETE"}).status_code == 403
    assert phone.get("/api/phone/setup", headers=auth).status_code == 403
    assert phone.post("/api/pairing/start", headers=auth).status_code == 403  # a phone can't invite more phones
    assert phone.get("/api/devices", headers=auth).status_code == 403
    assert phone.put("/api/lan", headers=auth, json={"enabled": False}).status_code == 403


def test_codes_are_single_use_expire_and_lock_after_wrong_tries(laptop, phone):
    lan_on()
    code = laptop.post("/api/pairing/start", headers=UI).json()["code"]
    assert phone.post("/api/pair", json={"code": code}).status_code == 200
    assert phone.post("/api/pair", json={"code": code}).status_code == 403  # used
    code = laptop.post("/api/pairing/start", headers=UI).json()["code"]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(4):
        assert "tries left" in phone.post("/api/pair", json={"code": wrong}).json()["detail"]
    assert "Too many" in phone.post("/api/pair", json={"code": wrong}).json()["detail"]
    assert phone.post("/api/pair", json={"code": code}).status_code == 403  # locked now, even with the right code
    code = laptop.post("/api/pairing/start", headers=UI).json()["code"]
    with session_scope(get_config().db_path) as s:
        for pc in s.query(PairingCode).all():
            pc.expires_at = time.time() - 1
    assert phone.post("/api/pair", json={"code": code}).status_code == 403  # expired


def test_revoked_or_bogus_tokens_stop_working(laptop, phone):
    lan_on()
    auth = pair(laptop, phone)
    dev_id = laptop.get("/api/devices").json()["devices"][0]["id"]
    assert laptop.delete(f"/api/devices/{dev_id}", headers=UI).json() == {"removed": True}
    assert phone.get("/api/day", headers=auth).status_code == 401
    assert phone.get("/api/day", headers={"Authorization": "Bearer nope"}).status_code == 401


def test_dns_rebinding_and_public_clients_are_refused(data_dir):
    lan_on()
    rebind = TestClient(app, client=PHONE_IP, headers={"Host": "evil.example:8787"})
    assert rebind.get("/m/").status_code == 400
    internet = TestClient(app, client=("8.8.8.8", 5000), headers=LAN_HOST)
    assert internet.get("/m/").status_code == 403
    assert internet.post("/api/pair", json={"code": "123456"}).status_code == 403


def test_android_app_syncs_phone_usage_with_its_device_token(laptop, phone):
    lan_on()
    auth = pair(laptop, phone, kind="android")
    payload = [{"day": "2026-10-20", "apps": [{"name": "Instagram", "package": "com.instagram.android", "seconds": 3600}],
                "pickups": 70}]
    r = phone.post("/api/phone/ingest", headers=auth, json=payload)
    assert r.status_code == 200
    assert r.json()["stored"][0]["device"] == "Test Phone"  # filed under the phone's name
    assert phone.post("/api/phone/ingest", json=payload).status_code == 401


def test_lan_addresses_prefer_wifi_over_vpn(monkeypatch):
    import types

    snic = lambda ip: types.SimpleNamespace(family=types.SimpleNamespace(name="AF_INET"), address=ip)  # noqa: E731
    monkeypatch.setattr(devices.psutil, "net_if_addrs", lambda: {"ProTUN": [snic("10.2.0.2")], "WiFi 3": [snic("192.168.1.20")],
                                                                "Loopback": [snic("127.0.0.1")]})
    monkeypatch.setattr(devices.psutil, "net_if_stats", lambda: {k: types.SimpleNamespace(isup=True) for k in ("ProTUN", "WiFi 3", "Loopback")})
    addrs = devices.lan_addresses()
    assert [a["ip"] for a in addrs] == ["192.168.1.20", "10.2.0.2"] and addrs[1]["likely_vpn"]
