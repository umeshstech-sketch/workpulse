"""Phone screen time: storage, categorizing, importers (JSON/CSV/ADB) and the combined laptop + phone "digital day".

Phones only give daily totals (no timeline). Re-importing a device's day replaces it, so imports are idempotent.
"""
from __future__ import annotations

import csv
import io
import json
import re
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import delete, select

from workpulse.config import Config
from workpulse.core.db import PhoneApp, PhoneDay, session_scope
from workpulse.core.service import day_stats, range_stats


@dataclass
class PhoneAppUsage:
    app: str
    seconds: float
    package: str | None = None
    category: str = "Other"
    hint: str | None = None  # Android's own app category (game, video, social, ...), used when config.yaml has no rule


@dataclass
class PhoneDayData:
    day: str  # YYYY-MM-DD
    device: str = "phone"
    total_s: float | None = None  # if None, the sum of apps
    pickups: int | None = None
    apps: list[PhoneAppUsage] = field(default_factory=list)


# ---- parsing helpers ---------------------------------------------------------------------------

def parse_duration(v) -> float | None:
    """Seconds from '1h 20m', '1 hr 5 min', '01:20:00', '1:20', '80' (minutes), '45m', '30s', 4800 (int = minutes)."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v) * 60
    s = str(v).strip().lower()
    if not s:
        return None
    if re.fullmatch(r"\d+(\.\d+)?", s):
        return float(s) * 60
    m = re.fullmatch(r"(\d+):(\d{1,2})(?::(\d{1,2}))?", s)
    if m:
        h, mi, se = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        return h * 3600 + mi * 60 + se if m.group(3) is not None else h * 3600 + mi * 60
    total, found = 0.0, False
    for num, unit in re.findall(r"(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes|s|sec|secs|seconds)\b", s):
        found = True
        n = float(num)
        total += n * 3600 if unit.startswith("h") else n * 60 if unit.startswith("m") else n
    return total if found else None


def parse_day(v, default: date | None = None) -> str:
    if v in (None, ""):
        return (default or date.today()).isoformat()
    s = str(v).strip()[:10]
    try:
        return date.fromisoformat(s).isoformat()
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})", s)
    if m:  # DD/MM/YYYY (Indian/European order)
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        return date(y + 2000 if y < 100 else y, mo, d).isoformat()
    raise ValueError(f"can't read date {v!r} (use YYYY-MM-DD)")


def pretty_package(pkg: str) -> str:
    """com.instagram.android -> Instagram; com.google.android.youtube -> Youtube."""
    parts = [p for p in pkg.split(".") if p not in ("com", "org", "net", "in", "android", "app", "apps", "mobile", "google", "co")]
    return (parts[-1] if parts else pkg).replace("_", " ").title()


# Android's ApplicationInfo category -> WorkPulse category (only used when config.yaml's phone.apps has no rule).
ANDROID_HINTS = {"game": "Entertainment", "video": "Entertainment", "audio": "Entertainment",
                 "social": "Entertainment", "news": "Browsing"}


def categorize_app(cfg: Config, name: str, package: str | None = None, hint: str | None = None) -> str:
    hay = f"{name} {package or ''}".lower()
    for key, cat in cfg.phone.apps.items():
        if key.lower() in hay:
            return cat
    return ANDROID_HINTS.get((hint or "").lower(), "Other")


def is_private(cfg: Config, name: str, package: str | None = None) -> bool:
    """The same never-log list as laptop windows (privacy.exclude_apps / exclude_keywords), on the app name AND package."""
    from workpulse.core.categorize import normalize_app
    excluded = {normalize_app(a) for a in cfg.privacy.exclude_apps}
    if normalize_app(name) in excluded or (package and package.lower() in excluded):
        return True
    hay = f"{name} {package or ''}".lower()
    return any(k.lower() in hay for k in cfg.privacy.exclude_keywords)


def apply_privacy_to_stored(cfg: Config) -> int:
    """Re-check stored phone apps against the never-log list (e.g. after you add a keyword): matching rows are
    merged into "(private)" so the day's total stays right but the app isn't named. Returns rows changed."""
    from workpulse.core.categorize import PRIVATE_APP
    changed = 0
    with session_scope(cfg.db_path) as s:
        rows = list(s.scalars(select(PhoneApp).where(PhoneApp.app != PRIVATE_APP)))
        hidden: dict[tuple[str, str], float] = {}
        for r in rows:
            if is_private(cfg, r.app, r.package):
                hidden[(r.device, r.day)] = hidden.get((r.device, r.day), 0.0) + r.seconds
                s.delete(r)
                changed += 1
        for (device, day), secs in hidden.items():
            existing = s.scalars(select(PhoneApp).where(PhoneApp.device == device, PhoneApp.day == day,
                                                        PhoneApp.app == PRIVATE_APP)).first()
            if existing:
                existing.seconds += secs
            else:
                s.add(PhoneApp(device=device, day=day, app=PRIVATE_APP, package=None, category=cfg.categories.default, seconds=secs))
    return changed


# ---- storage -----------------------------------------------------------------------------------

def save_day(cfg: Config, data: PhoneDayData, source: str) -> PhoneDay:
    """Insert or replace one device-day (apps included). Returns the stored day."""
    from workpulse.core.categorize import PRIVATE_APP
    apps: dict[str, PhoneAppUsage] = {}
    for a in data.apps:
        if a.seconds is None or a.seconds <= 0 or not a.app.strip():
            continue
        key, package = a.app.strip()[:128], a.package
        if is_private(cfg, key, package):  # banking, password managers, ...: time counted, name never stored
            key, package, category = PRIVATE_APP, None, cfg.categories.default
        else:
            category = a.category if a.category != "Other" else categorize_app(cfg, key, package, a.hint)
        if key in apps:
            apps[key].seconds += a.seconds
        else:
            apps[key] = PhoneAppUsage(key, a.seconds, package, category)
    # A reported total can't be less than the apps it contains; without one, the apps are the total.
    screen = max(data.total_s or 0.0, sum(a.seconds for a in apps.values()))
    if screen <= 0 and not apps:
        raise ValueError("no screen time in this import")
    if screen > 86400:
        raise ValueError("more than 24h of screen time in one day; check the units (minutes vs seconds)")
    with session_scope(cfg.db_path) as s:
        s.execute(delete(PhoneApp).where(PhoneApp.device == data.device, PhoneApp.day == data.day))
        row = s.scalars(select(PhoneDay).where(PhoneDay.device == data.device, PhoneDay.day == data.day)).first()
        if row is None:
            row = PhoneDay(device=data.device, day=data.day, total_s=screen)
            s.add(row)
        row.total_s, row.pickups, row.source, row.updated_at = screen, data.pickups, source, time.time()
        for a in apps.values():
            s.add(PhoneApp(device=data.device, day=data.day, app=a.app, package=a.package, category=a.category, seconds=a.seconds))
        s.flush()
        return row


def delete_day(cfg: Config, day: str, device: str | None = None) -> int:
    with session_scope(cfg.db_path) as s:
        q1, q2 = delete(PhoneDay).where(PhoneDay.day == day), delete(PhoneApp).where(PhoneApp.day == day)
        if device:
            q1, q2 = q1.where(PhoneDay.device == device), q2.where(PhoneApp.device == device)
        s.execute(q2)
        return s.execute(q1).rowcount or 0


def delete_all(cfg: Config) -> int:
    with session_scope(cfg.db_path) as s:
        s.execute(delete(PhoneApp))
        return s.execute(delete(PhoneDay)).rowcount or 0


def load_days(cfg: Config, first: date, last: date) -> tuple[list[PhoneDay], list[PhoneApp]]:
    a, b = first.isoformat(), last.isoformat()
    with session_scope(cfg.db_path) as s:
        days = list(s.scalars(select(PhoneDay).where(PhoneDay.day >= a, PhoneDay.day <= b)))
        apps = list(s.scalars(select(PhoneApp).where(PhoneApp.day >= a, PhoneApp.day <= b)))
    return days, apps


# ---- importers ---------------------------------------------------------------------------------

def from_json(cfg: Config, payload: dict | list) -> list[PhoneDayData]:
    """{"day": "...", "device": "...", "total": "3h20m" | total_minutes/total_s, "pickups": 80,
        "apps": [{"name": "Instagram", "package": "...", "minutes": 70} | {"name":..., "time": "1h10m"}]}  (or a list of these)"""
    items = payload if isinstance(payload, list) else [payload]
    out = []
    for it in items:
        if not isinstance(it, dict):
            raise ValueError("each entry must be an object")
        apps = []
        for a in it.get("apps") or []:
            name = (a.get("name") or a.get("app") or (pretty_package(a["package"]) if a.get("package") else "")).strip()
            secs = (float(a["seconds"]) if "seconds" in a else float(a["minutes"]) * 60 if "minutes" in a
                    else parse_duration(a.get("time") or a.get("duration")))
            if name and secs:
                apps.append(PhoneAppUsage(name, secs, a.get("package"), hint=a.get("category_hint")))
        # Shortcut-friendly flat form: "Instagram=70m, WhatsApp=40m" (comma or newline separated)
        for part in re.split(r"[,\n;]", it.get("apps_text") or ""):
            name, sep, t = part.partition("=")
            secs = parse_duration(t) if sep else None
            if name.strip() and secs:
                apps.append(PhoneAppUsage(name.strip(), secs))
        total = (float(it["total_s"]) if "total_s" in it else float(it["total_minutes"]) * 60 if "total_minutes" in it
                 else parse_duration(it.get("total") or it.get("screen_time")))
        out.append(PhoneDayData(day=parse_day(it.get("day") or it.get("date")),
                                device=(it.get("device") or cfg.phone.default_device)[:32], total_s=total,
                                pickups=int(it["pickups"]) if it.get("pickups") not in (None, "") else None, apps=apps))
    return out


HEADER_ALIASES = {
    "day": {"date", "day", "usage date"},
    "app": {"app", "app name", "application", "name", "package", "package name"},
    "duration": {"duration", "time", "usage", "usage time", "screen time", "total time", "time used", "foreground time"},
    "minutes": {"minutes", "mins", "usage (min)", "duration (min)", "time (min)", "minutes used"},
    "seconds": {"seconds", "secs", "duration (s)", "duration (sec)"},
    "ms": {"milliseconds", "ms", "duration (ms)", "totaltimeinforeground"},
    "pickups": {"pickups", "unlocks", "launches", "opens"},
    "device": {"device"},
}


def from_csv(cfg: Config, text: str, device: str | None = None) -> list[PhoneDayData]:
    """Long format CSV: one row per app per day. Column names are matched loosely (see HEADER_ALIASES);
    a row whose app is 'total'/'screen time' sets the day total."""
    reader = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not reader.fieldnames:
        raise ValueError("empty CSV")
    cols: dict[str, str] = {}
    for f in reader.fieldnames:
        key = f.strip().lower()
        for role, names in HEADER_ALIASES.items():
            if key in names and role not in cols:
                cols[role] = f
    if "app" not in cols or not ({"duration", "minutes", "seconds", "ms"} & set(cols)):
        raise ValueError(f"need an app column and a time column; found {reader.fieldnames}")
    days: dict[tuple[str, str], PhoneDayData] = {}
    for row in reader:
        app = (row.get(cols["app"]) or "").strip()
        if not app:
            continue
        if "seconds" in cols:
            secs = float(row[cols["seconds"]] or 0)
        elif "ms" in cols:
            secs = float(row[cols["ms"]] or 0) / 1000
        elif "minutes" in cols:
            secs = float(row[cols["minutes"]] or 0) * 60
        else:
            secs = parse_duration(row[cols["duration"]]) or 0
        dev = (row.get(cols["device"]) if "device" in cols else None) or device or cfg.phone.default_device
        day = parse_day(row.get(cols["day"]) if "day" in cols else None)
        d = days.setdefault((dev, day), PhoneDayData(day=day, device=dev[:32]))
        if "pickups" in cols and (row.get(cols["pickups"]) or "").strip().isdigit():
            d.pickups = (d.pickups or 0) + int(row[cols["pickups"]])
        if app.lower() in ("total", "screen time", "total screen time", "all apps"):
            d.total_s = secs
            continue
        pkg = app if re.fullmatch(r"[a-z][\w]*(\.[\w]+)+", app) else None
        d.apps.append(PhoneAppUsage(pretty_package(app) if pkg else app, secs, pkg))
    if not days:
        raise ValueError("no usable rows")
    return list(days.values())


# Example lines in `adb shell dumpsys usagestats` output (format varies by Android version):
#   package=com.instagram.android totalTimeUsed="1:02:03" lastTimeUsed="2026-10-21 18:00:00" ...
#   package=com.whatsapp totalTime="20:11" lastTime=...
ADB_LINE = re.compile(r'package=([\w.]+)\s.*?totalTime(?:Used|InForeground)?="?([\d:]+)"?')


def parse_adb_usagestats(text: str, day: str | None = None, device: str = "phone") -> PhoneDayData:
    """Best-effort parse of the first 'daily' stats block from `dumpsys usagestats` (experimental)."""
    block = text
    m = re.search(r"In-memory daily stats(.*?)(In-memory weekly stats|$)", text, re.S)
    if m:
        block = m.group(1)
    apps: dict[str, float] = {}
    for pkg, t in ADB_LINE.findall(block):
        if ":" in t:  # dumpsys prints h:mm:ss or mm:ss
            parts = [int(p) for p in t.split(":")]
            secs = float(sum(v * 60 ** i for i, v in enumerate(reversed(parts))))
        else:
            secs = float(t) / 1000  # milliseconds
        if secs and secs >= 60:  # skip launcher blips
            apps[pkg] = max(apps.get(pkg, 0.0), secs)
    if not apps:
        raise ValueError("couldn't find per-app totals in the dumpsys output")
    return PhoneDayData(day=day or date.today().isoformat(), device=device,
                        apps=[PhoneAppUsage(pretty_package(p), s, p) for p, s in apps.items()
                              if not p.endswith((".launcher", ".launcher3", "systemui"))])


# ---- digital day -------------------------------------------------------------------------------

def digital_day(cfg: Config, d: date) -> dict:
    """Laptop + phone for one day. Category minutes are combined; phone has no idle/away concept."""
    st = day_stats(cfg, d)
    days, apps = load_days(cfg, d, d)
    phone_s = sum(x.total_s for x in days)
    pickups = sum(x.pickups or 0 for x in days) if any(x.pickups for x in days) else None
    phone_cat: dict[str, float] = {}
    phone_apps: dict[str, float] = {}
    for a in apps:
        phone_cat[a.category] = phone_cat.get(a.category, 0) + a.seconds
        phone_apps[a.app] = phone_apps.get(a.app, 0) + a.seconds
    productive = set(cfg.scoring.productive_categories)
    phone_prod = sum(v for k, v in phone_cat.items() if k in productive)
    cats = sorted(set(st.per_category) | set(phone_cat), key=lambda c: -(st.per_category.get(c, 0) + phone_cat.get(c, 0)))
    return {
        "date": d.isoformat(),
        "laptop_active_s": st.active_s, "laptop_productive_s": st.productive_s,
        "phone_s": phone_s, "phone_productive_s": phone_prod, "pickups": pickups,
        "total_s": st.active_s + phone_s,
        "productive_s": st.productive_s + phone_prod,
        "phone_share": phone_s / (st.active_s + phone_s) if (st.active_s + phone_s) else 0.0,
        "phone_entertainment_s": phone_cat.get("Entertainment", 0.0),
        "categories": [{"name": c, "laptop_s": st.per_category.get(c, 0.0), "phone_s": phone_cat.get(c, 0.0)} for c in cats],
        "phone_top_apps": [{"app": k, "seconds": v} for k, v in sorted(phone_apps.items(), key=lambda kv: -kv[1])[:10]],
        "phone_devices": [{"device": x.device, "total_s": x.total_s, "source": x.source} for x in days],
        "has_phone_data": bool(days),
    }


def digital_range(cfg: Config, end: date, n: int = 7) -> list[dict]:
    first = end - timedelta(days=n - 1)
    laptop = range_stats(cfg, first, end)
    days, _ = load_days(cfg, first, end)
    phone: dict[str, float] = {}
    for x in days:
        phone[x.day] = phone.get(x.day, 0) + x.total_s
    return [{"date": s.day.isoformat(), "laptop_active_s": s.active_s, "phone_s": phone.get(s.day.isoformat(), 0.0)} for s in laptop]


def read_file(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def import_file(cfg: Config, path: Path, device: str | None = None) -> list[PhoneDay]:
    text = read_file(path)
    if path.suffix.lower() == ".json":
        items = from_json(cfg, json.loads(text))
        if device:
            for it in items:
                it.device = device
        src = "api"
    else:
        items, src = from_csv(cfg, text, device), "csv"
    return [save_day(cfg, it, src) for it in items]
