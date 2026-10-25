"""Phone pairing over the home Wi-Fi (and, optionally, over Tailscale when you're out).

Flow: the laptop shows a 6-digit code (valid 10 minutes, one use, 5 wrong tries max). The phone sends the code
once and gets a long random device token, which it sends as `Authorization: Bearer <token>` from then on.
Only a SHA-256 hash of the token is stored, so a copy of the database can't be used to impersonate a phone.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
import secrets

import psutil
from sqlalchemy import delete, or_, select

from workpulse.config import Config
from workpulse.core.db import Device, PairingCode, session_scope

CODE_TTL_S = 10 * 60
MAX_ATTEMPTS = 5
# Tailscale gives every device a fixed address in these ranges, reachable only by your own devices.
TAILSCALE_NETS = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))
VPN_HINTS = ("tun", "tap", "vpn", "wireguard", "wg", "zerotier", "tailscale", "hamachi", "virtual", "vethernet", "loopback")


def _hash(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


# ---- pairing codes -----------------------------------------------------------------------------

def new_code(cfg: Config) -> tuple[str, float]:
    """Create a fresh code (older unused codes are invalidated so only one is live at a time)."""
    code = f"{secrets.randbelow(1_000_000):06d}"
    expires = time.time() + CODE_TTL_S
    with session_scope(cfg.db_path) as s:
        # Only one live code at a time; old ones (used, expired or replaced) are deleted, not kept forever.
        s.execute(delete(PairingCode).where(or_(PairingCode.used.is_(True), PairingCode.expires_at <= time.time())))
        for old in s.scalars(select(PairingCode)):
            old.used = True
        s.add(PairingCode(code_hash=_hash(code), expires_at=expires))
    return code, expires


class PairingError(ValueError):
    pass


def redeem(cfg: Config, code: str, name: str, kind: str = "web", ip: str | None = None) -> tuple[str, Device]:
    """Trade a valid code for a new device token. Raises PairingError with a user-facing message."""
    code = (code or "").strip().replace(" ", "")
    error = None
    # The failed-attempt counter must be COMMITTED before we raise (raising inside session_scope rolls back),
    # otherwise wrong guesses would never count and the 5-try limit wouldn't stop brute force.
    with session_scope(cfg.db_path) as s:
        live = s.scalars(select(PairingCode).where(PairingCode.used.is_(False), PairingCode.expires_at > time.time())).first()
        if live is None:
            error = "No pairing code is active. On the laptop: Settings → Connect a phone (or .\\workpulse connect)."
        elif not secrets.compare_digest(live.code_hash, _hash(code)):
            live.attempts += 1
            if live.attempts >= MAX_ATTEMPTS:
                live.used = True
                error = "Too many wrong codes. Make a new code on the laptop."
            else:
                error = f"Wrong code ({MAX_ATTEMPTS - live.attempts} tries left)."
    if error:
        raise PairingError(error)
    with session_scope(cfg.db_path) as s:
        live = s.scalars(select(PairingCode).where(PairingCode.used.is_(False), PairingCode.expires_at > time.time())).first()
        if live is None or not secrets.compare_digest(live.code_hash, _hash(code)):  # lost a race with another phone
            raise PairingError("That code was just used. Make a new code on the laptop.")
        live.used = True
        token = secrets.token_urlsafe(32)
        dev = Device(name=(name or "My phone").strip()[:64] or "My phone", kind=kind if kind in ("web", "android") else "web",
                     token_hash=_hash(token), last_seen=time.time(), last_ip=ip)
        s.add(dev)
        s.flush()
        s.refresh(dev)
        return token, dev


# ---- device tokens -----------------------------------------------------------------------------

def verify(cfg: Config, token: str | None, ip: str | None = None) -> Device | None:
    if not token:
        return None
    with session_scope(cfg.db_path) as s:
        dev = s.scalars(select(Device).where(Device.token_hash == _hash(token))).first()
        if dev is None:
            return None
        if not dev.last_seen or time.time() - dev.last_seen > 60:  # throttle writes
            dev.last_seen, dev.last_ip = time.time(), ip
        return dev


def list_devices(cfg: Config) -> list[Device]:
    with session_scope(cfg.db_path) as s:
        return list(s.scalars(select(Device).order_by(Device.created_at)))


def revoke(cfg: Config, device_id: int) -> bool:
    with session_scope(cfg.db_path) as s:
        dev = s.get(Device, device_id)
        if dev is None:
            return False
        s.delete(dev)
        return True


# ---- network helpers ---------------------------------------------------------------------------

def is_loopback(ip: str | None) -> bool:
    if ip in ("testclient", "testserver"):  # FastAPI's TestClient
        return True
    try:
        return ipaddress.ip_address(ip or "").is_loopback
    except ValueError:
        return False


def is_private_lan(ip: str | None) -> bool:
    try:
        a = ipaddress.ip_address(ip or "")
    except ValueError:
        return False
    return a.is_private and not a.is_loopback and not a.is_link_local


def is_tailscale(ip: str | None) -> bool:
    try:
        a = ipaddress.ip_address(ip or "")
    except ValueError:
        return False
    return any(a in net for net in TAILSCALE_NETS)


def tailscale_addresses() -> list[str]:
    """This laptop's Tailscale IPv4 address(es) (empty if Tailscale isn't installed or not connected)."""
    stats = psutil.net_if_stats()
    return [a.address for name, addrs in psutil.net_if_addrs().items() if not (name in stats and not stats[name].isup)
            for a in addrs if a.family.name == "AF_INET" and is_tailscale(a.address)]


def tailscale_exe() -> str | None:
    found = shutil.which("tailscale")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base and (p := Path(base) / "Tailscale" / "tailscale.exe").exists():
            return str(p)
    return None


_ts_cache: tuple[float, dict] = (0.0, {})


def tailscale_info() -> dict:
    """{"installed", "running", "dns_name"} from `tailscale status --json`, cached for a minute."""
    global _ts_cache
    if time.time() - _ts_cache[0] < 60:
        return _ts_cache[1]
    exe = tailscale_exe()
    info = {"installed": exe is not None, "running": False, "dns_name": None}
    if exe:
        try:
            out = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=8).stdout
            st = json.loads(out or "{}")
            info["running"] = st.get("BackendState") == "Running"
            info["dns_name"] = ((st.get("Self") or {}).get("DNSName") or "").rstrip(".") or None
        except (OSError, subprocess.TimeoutExpired, ValueError):
            pass
    _ts_cache = (time.time(), info)
    return info


def lan_addresses() -> list[dict]:
    """Private IPv4 addresses of this laptop, best guess first (Wi-Fi/Ethernet before VPN-looking adapters)."""
    out = []
    stats = psutil.net_if_stats()
    for name, addrs in psutil.net_if_addrs().items():
        if name in stats and not stats[name].isup:
            continue
        for a in addrs:
            if a.family.name != "AF_INET" or not is_private_lan(a.address):
                continue
            vpnish = any(h in name.lower() for h in VPN_HINTS)
            score = (0 if not vpnish else 2) + (0 if a.address.startswith("192.168.") else 1)
            out.append({"interface": name, "ip": a.address, "likely_vpn": vpnish, "_score": score})
    out.sort(key=lambda x: x["_score"])
    for x in out:
        x.pop("_score")
    return out
