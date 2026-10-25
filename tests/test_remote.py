"""Away-from-home access over Tailscale: who gets in, pairing links with every address, the phone's host list."""
import pytest
from fastapi.testclient import TestClient

from workpulse.backend import pairing_api
from workpulse.backend.app import app
from workpulse.config import save_settings
from workpulse.core import devices

UI = {"X-WorkPulse-UI": "1"}
TS_PHONE = ("100.88.1.2", 40000)
TS_HOST = {"Host": "100.101.102.103:8787"}


@pytest.fixture()
def laptop(data_dir, monkeypatch):
    monkeypatch.setattr(devices, "tailscale_addresses", lambda: ["100.101.102.103"])
    monkeypatch.setattr(devices, "tailscale_info", lambda: {"installed": True, "running": True, "dns_name": "my-laptop.tail1234.ts.net"})
    monkeypatch.setattr(devices, "lan_addresses", lambda: [{"interface": "Wi-Fi", "ip": "192.168.1.20", "likely_vpn": False}])
    monkeypatch.setattr(pairing_api, "network_profiles", lambda: [])
    return TestClient(app)


@pytest.fixture()
def ts_phone(data_dir):
    return TestClient(app, client=TS_PHONE, headers=TS_HOST)


def pair(laptop, phone):
    code = laptop.post("/api/pairing/start", headers=UI).json()["code"]
    r = phone.post("/api/pair", json={"code": code, "name": "Away Phone", "kind": "android"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}", **UI}


@pytest.mark.parametrize("ip,expected", [("100.64.0.1", True), ("100.127.255.254", True), ("100.128.0.1", False),
                                         ("192.168.1.5", False), ("fd7a:115c:a1e0::1", True), ("8.8.8.8", False), (None, False)])
def test_is_tailscale(ip, expected):
    assert devices.is_tailscale(ip) is expected


def test_tailscale_phone_refused_while_remote_is_off(laptop, ts_phone):
    save_settings({"server": {"lan": True}})  # Wi-Fi access alone doesn't open Tailscale
    r = ts_phone.get("/m/")
    assert r.status_code == 403 and "remote on" in r.text


def test_tailscale_phone_pairs_and_needs_its_token(laptop, ts_phone):
    save_settings({"server": {"remote": True}})
    assert ts_phone.get("/m/").status_code == 200
    assert ts_phone.get("/api/day").status_code == 401
    auth = pair(laptop, ts_phone)
    assert ts_phone.get("/api/day", headers=auth).status_code == 200
    assert ts_phone.put("/api/remote", headers=auth, json={"enabled": False}).status_code == 403  # laptop-only


def test_remote_on_does_not_open_the_home_wifi(laptop):
    save_settings({"server": {"remote": True, "lan": False}})
    wifi_phone = TestClient(app, client=("192.168.1.50", 5000), headers={"Host": "192.168.1.20:8787"})
    assert wifi_phone.get("/m/").status_code == 403


def test_public_internet_is_still_refused(laptop):
    save_settings({"server": {"remote": True, "lan": True}})
    stranger = TestClient(app, client=("8.8.4.4", 5000), headers={"Host": "8.8.4.4:8787"})
    assert stranger.get("/m/").status_code == 403


@pytest.mark.parametrize("host,code", [("my-laptop.tail1234.ts.net:8787", 200), ("evil.example.com:8787", 400)])
def test_host_header_over_tailscale(laptop, host, code):
    save_settings({"server": {"remote": True}})
    c = TestClient(app, client=TS_PHONE, headers={"Host": host})
    assert c.get("/api/ping").status_code == code  # MagicDNS name ok; any other domain = DNS rebinding → refused


def test_pairing_link_and_whoami_carry_every_address(laptop, ts_phone):
    save_settings({"server": {"remote": True, "lan": True}})
    r = laptop.post("/api/pairing/start", headers=UI).json()
    assert r["hosts"] == ["192.168.1.20:8787", "100.101.102.103:8787", "my-laptop.tail1234.ts.net:8787"]
    assert r["app_url"].startswith("workpulse://pair?host=192.168.1.20%3A8787&code=")
    assert "&alt=100.101.102.103%3A8787%2Cmy-laptop.tail1234.ts.net%3A8787" in r["app_url"]
    auth = pair(laptop, ts_phone)
    assert ts_phone.get("/api/whoami", headers=auth).json()["hosts"] == r["hosts"]


def test_remote_only_pairing_uses_the_tailscale_address(laptop):
    save_settings({"server": {"remote": True, "lan": False}})
    r = laptop.post("/api/pairing/start", headers=UI).json()
    assert r["web_url"].startswith("http://100.101.102.103:8787/m/#pair=")


def test_remote_status_explains_missing_tailscale(data_dir, monkeypatch):
    monkeypatch.setattr(devices, "tailscale_addresses", lambda: [])
    monkeypatch.setattr(devices, "tailscale_info", lambda: {"installed": False, "running": False, "dns_name": None})
    st = pairing_api.remote_status(save_settings({"server": {"remote": True}}))
    assert st["url"] is None and "tailscale.com/download" in st["warnings"][0]


def test_bind_host_opens_for_either_mode(data_dir):
    assert save_settings({"server": {"lan": False, "remote": False}}).server.bind_host == "127.0.0.1"
    assert save_settings({"server": {"remote": True}}).server.bind_host == "0.0.0.0"


def test_server_sees_settings_written_by_another_process(data_dir):
    import os
    import time

    from workpulse.config import get_config, settings_path
    assert get_config().server.remote is False
    settings_path().write_text("server:\n  remote: true\n", encoding="utf-8")  # like the CLI, from outside
    future = time.time() + 5
    os.utime(settings_path(), (future, future))
    assert get_config().server.remote is True


def test_apk_is_served_as_an_android_app(data_dir):
    from workpulse.backend import app as app_module
    apk = app_module.DASHBOARD / "m" / "workpulse.apk"
    if not apk.exists():
        pytest.skip("APK not built")
    r = TestClient(app).get("/m/workpulse.apk")
    assert r.headers["content-type"] == "application/vnd.android.package-archive"
    assert "WorkPulse.apk" in r.headers["content-disposition"]
