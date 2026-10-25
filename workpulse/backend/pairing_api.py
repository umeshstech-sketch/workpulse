"""Phone pairing + Wi-Fi access endpoints (mobile web app and Android app)."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from typing import Any, Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from workpulse import __version__
from workpulse.backend.deps import cfg, require_local, require_ui
from workpulse.config import Config, save_settings
from workpulse.core import devices

router = APIRouter(prefix="/api")
LOCAL_UI = [Depends(require_local), Depends(require_ui)]
_profiles_cache: tuple[float, list[dict]] = (0.0, [])


def network_profiles() -> list[dict]:
    """Windows network profiles (Public networks block incoming connections from phones by default)."""
    global _profiles_cache
    if sys.platform != "win32":
        return []
    if time.time() - _profiles_cache[0] < 60:
        return _profiles_cache[1]
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-NetConnectionProfile | Select-Object Name,InterfaceAlias,@{n='Category';e={[string]$_.NetworkCategory}} | ConvertTo-Json"],
                             capture_output=True, text=True, timeout=10).stdout.strip()
        data = json.loads(out) if out else []
        data = data if isinstance(data, list) else [data]
        profiles = [{"name": d.get("Name"), "interface": d.get("InterfaceAlias"), "category": d.get("Category")} for d in data]
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        profiles = []
    _profiles_cache = (time.time(), profiles)
    return profiles


def lan_status(c: Config) -> dict[str, Any]:
    addrs = devices.lan_addresses()
    profiles = network_profiles()
    primary = next((a for a in addrs if not a["likely_vpn"]), addrs[0] if addrs else None)
    warnings = []
    if primary:
        prof = next((p for p in profiles if p["interface"] == primary["interface"]), None)
        if prof and prof["category"] == "Public":
            warnings.append(f"Windows marks the Wi-Fi '{prof['name']}' as Public, which blocks phones. Settings → Network & internet → "
                            "Wi-Fi → (your network) → Network profile type: Private. Then allow Python when Windows asks.")
    if any(a["likely_vpn"] for a in addrs):
        warnings.append("A VPN is on. If the phone can't connect, enable 'Allow LAN connections' in the VPN app (or pause it).")
    return {"enabled": c.server.lan, "port": c.server.port, "addresses": addrs, "primary_ip": primary["ip"] if primary else None,
            "url": f"http://{primary['ip']}:{c.server.port}/m/" if primary else None, "profiles": profiles, "warnings": warnings}


def remote_status(c: Config) -> dict[str, Any]:
    """Away-from-home access over Tailscale."""
    info = devices.tailscale_info()
    ips = devices.tailscale_addresses()
    warnings = []
    if not info["installed"] and not ips:
        warnings.append("Tailscale isn't installed on this laptop. Get it free from tailscale.com/download, sign in, "
                        "and install the Tailscale app on your phone with the same account.")
    elif not ips:
        warnings.append("Tailscale is installed but not connected. Open Tailscale (tray icon) and log in / connect.")
    else:
        prof = next((p for p in network_profiles() if "tailscale" in (p["interface"] or "").lower()), None)
        if prof and prof["category"] == "Public":
            warnings.append("Windows marks the Tailscale network as Public, which can block the phone. If it can't connect, "
                            "allow Python on Public networks in Windows Firewall, or set that network to Private.")
    hosts = [f"{ip}:{c.server.port}" for ip in ips]
    return {"enabled": c.server.remote, "installed": info["installed"] or bool(ips), "connected": bool(ips),
            "addresses": ips, "dns_name": info["dns_name"], "port": c.server.port,
            "url": f"http://{hosts[0]}/m/" if hosts else None, "warnings": warnings}


def phone_hosts(c: Config) -> list[str]:
    """Addresses a phone can use to reach this laptop, home Wi-Fi first, then Tailscale (only those turned on)."""
    hosts = []
    if c.server.lan and (ip := lan_status(c)["primary_ip"]):
        hosts.append(f"{ip}:{c.server.port}")
    if c.server.remote:
        hosts += [f"{ip}:{c.server.port}" for ip in devices.tailscale_addresses()]
        if name := devices.tailscale_info()["dns_name"]:
            hosts.append(f"{name}:{c.server.port}")
    return hosts


def qr_svg(data: str) -> str:
    import qrcode
    import qrcode.image.svg
    img = qrcode.make(data, image_factory=qrcode.image.svg.SvgPathImage, box_size=8, border=2)
    return img.to_string(encoding="unicode")


@router.get("/ping")
def ping() -> dict[str, str]:
    return {"app": "workpulse", "version": __version__}


@router.get("/whoami")
def whoami(request: Request, c: Config = Depends(cfg)) -> dict[str, Any]:
    # `hosts`: the Android app refreshes its list of laptop addresses from this after every sync, so turning on
    # away-from-home access later doesn't need re-pairing.
    return {"device": getattr(request.state, "device_name", None) or "laptop", "version": __version__,
            "hosts": phone_hosts(c)}


@router.get("/lan", dependencies=[Depends(require_local)])
def get_lan(c: Config = Depends(cfg)) -> dict[str, Any]:
    return lan_status(c)


class LanIn(BaseModel):
    enabled: bool


@router.put("/lan", dependencies=LOCAL_UI)
def put_lan(body: LanIn, c: Config = Depends(cfg)) -> dict[str, Any]:
    """Turn Wi-Fi access on/off. The server restarts itself a moment later to listen on the new address."""
    from workpulse.agent import control
    new = save_settings({"server": {"lan": body.enabled}})
    restarting = control.running_pid(c, "server") is not None and new.server.bind_host != c.server.bind_host
    if restarting:
        control.restart_server_later()
    return {**lan_status(new), "restarting": restarting}


@router.get("/remote", dependencies=[Depends(require_local)])
def get_remote(c: Config = Depends(cfg)) -> dict[str, Any]:
    return remote_status(c)


@router.put("/remote", dependencies=LOCAL_UI)
def put_remote(body: LanIn, c: Config = Depends(cfg)) -> dict[str, Any]:
    """Turn away-from-home (Tailscale) access on/off. The server restarts itself to listen on the new address."""
    from workpulse.agent import control
    new = save_settings({"server": {"remote": body.enabled}})
    restarting = control.running_pid(c, "server") is not None and new.server.bind_host != c.server.bind_host
    if restarting:
        control.restart_server_later()
    return {**remote_status(new), "restarting": restarting}


@router.post("/pairing/start", dependencies=LOCAL_UI)
def pairing_start(c: Config = Depends(cfg)) -> dict[str, Any]:
    code, expires = devices.new_code(c)
    st = lan_status(c)
    hosts = phone_hosts(c)
    out: dict[str, Any] = {"code": code, "expires_at": expires, "lan": st, "hosts": hosts}
    if hosts:
        web = f"http://{hosts[0]}/m/#pair={code}"
        # The app gets every address: it pairs over whichever works and later switches between them by itself.
        app = f"workpulse://pair?host={quote(hosts[0])}&code={code}" + (f"&alt={quote(','.join(hosts[1:]))}" if hosts[1:] else "")
        out.update(web_url=web, app_url=app, web_qr=qr_svg(web), app_qr=qr_svg(app))
    return out


class PairIn(BaseModel):
    code: str = Field(min_length=6, max_length=12)
    name: str = Field("My phone", max_length=64)
    kind: Literal["web", "android"] = "web"


@router.post("/pair")
def pair(body: PairIn, request: Request, c: Config = Depends(cfg)) -> dict[str, Any]:
    try:
        token, dev = devices.redeem(c, body.code, body.name, body.kind, request.client.host if request.client else None)
    except devices.PairingError as e:
        raise HTTPException(403, str(e))
    return {"token": token, "device_id": dev.id, "name": dev.name, "version": __version__}


@router.get("/devices", dependencies=[Depends(require_local)])
def get_devices(c: Config = Depends(cfg)) -> dict[str, Any]:
    return {"devices": [{"id": d.id, "name": d.name, "kind": d.kind, "created_at": d.created_at, "last_seen": d.last_seen,
                         "last_ip": d.last_ip} for d in devices.list_devices(c)]}


@router.delete("/devices/{device_id}", dependencies=LOCAL_UI)
def delete_device(device_id: int, c: Config = Depends(cfg)) -> dict[str, bool]:
    if not devices.revoke(c, device_id):
        raise HTTPException(404, "no such device")
    return {"removed": True}
