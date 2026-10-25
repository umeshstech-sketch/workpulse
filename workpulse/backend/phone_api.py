"""Phase 5 API: phone screen time in (ingest/import/manual/screenshot) and the combined digital-day view out."""
from __future__ import annotations

import json
import secrets
from datetime import date, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field

from workpulse.backend.deps import cfg, require_local, require_ui
from workpulse.config import Config
from workpulse.core.phone import delete_day, digital_day, digital_range, from_csv, from_json, save_day

router = APIRouter(prefix="/api")
UI = [Depends(require_ui)]
PHONE_TOKEN_HEADER = "X-WorkPulse-Phone-Token"
MAX_UPLOAD = 5 * 1024 * 1024


def phone_token(c: Config) -> str:
    """Separate from the agent token: it can ONLY add phone screen time, so it's safe to put in Tasker/Shortcuts."""
    p = c.data_dir / "phone.token"
    if not p.exists():
        p.write_text(secrets.token_urlsafe(24), encoding="utf-8")
    return p.read_text(encoding="utf-8").strip()


def _day_dict(row) -> dict[str, Any]:
    return {"device": row.device, "day": row.day, "total_s": row.total_s, "pickups": row.pickups, "source": row.source}


def _save_all(c: Config, items, source: str) -> list[dict[str, Any]]:
    try:
        return [_day_dict(save_day(c, it, source)) for it in items]
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/phone/ingest")
async def phone_ingest(request: Request, c: Config = Depends(cfg),
                       x_workpulse_phone_token: str | None = Header(default=None)) -> dict[str, Any]:
    """For the Android app (paired device token), Tasker / Shortcuts / scripts (phone token), locally, over your
    Wi-Fi or through your tunnel. The token is checked before the body is even read."""
    from workpulse.core.devices import verify
    auth = request.headers.get("authorization", "")
    device = verify(c, auth[7:].strip(), request.client.host if request.client else None) if auth.lower().startswith("bearer ") else None
    phone_ok = bool(x_workpulse_phone_token) and secrets.compare_digest(x_workpulse_phone_token or "", phone_token(c))
    if device is None and not phone_ok:
        raise HTTPException(401, f"bad or missing {PHONE_TOKEN_HEADER} / device token")
    if c.demo:
        raise HTTPException(409, "server is in demo mode")
    raw = await request.body()
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "payload over 5 MB")
    try:
        items = from_json(c, json.loads(raw or b"null"))
    except (ValueError, KeyError, TypeError) as e:
        raise HTTPException(422, f"couldn't read payload: {e}")
    if device is not None:  # the Android app's numbers are filed under the paired phone's name
        for it in items:
            if it.device == c.phone.default_device:
                it.device = device.name[:32]
    return {"stored": _save_all(c, items, "api")}


@router.post("/phone/import", dependencies=UI)
async def phone_import(file: UploadFile = File(...), device: str = Form(""), c: Config = Depends(cfg)) -> dict[str, Any]:
    raw = await file.read(MAX_UPLOAD + 1)
    if len(raw) > MAX_UPLOAD:
        raise HTTPException(413, "file over 5 MB")
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        if (file.filename or "").lower().endswith(".json") or text.lstrip().startswith(("{", "[")):
            items = from_json(c, json.loads(text))
            if device:
                for it in items:
                    it.device = device[:32]
            src = "api"
        else:
            items, src = from_csv(c, text, device[:32] or None), "csv"
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
        raise HTTPException(422, f"couldn't read {file.filename}: {e}")
    return {"stored": _save_all(c, items, src)}


class AppIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    time: str = Field(min_length=1, max_length=32)  # "1h 10m", "70", "1:10"


class ManualIn(BaseModel):
    day: str | None = None
    device: str | None = Field(None, max_length=32)
    total: str | None = Field(None, max_length=32)
    pickups: int | None = Field(None, ge=0, le=5000)
    apps: list[AppIn] = Field(default_factory=list, max_length=200)
    source: Literal["manual", "screenshot"] = "manual"


@router.post("/phone/manual", dependencies=UI)
def phone_manual(body: ManualIn, c: Config = Depends(cfg)) -> dict[str, Any]:
    payload = {"day": body.day, "device": body.device, "total": body.total, "pickups": body.pickups,
               "apps": [{"name": a.name, "time": a.time} for a in body.apps]}
    try:
        items = from_json(c, payload)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"stored": _save_all(c, items, body.source)}


@router.post("/phone/screenshot", dependencies=UI)
async def phone_screenshot(file: UploadFile = File(...), c: Config = Depends(cfg)) -> dict[str, Any]:
    """Reads a Screen Time / Digital Wellbeing screenshot with the AI and returns the numbers for you to
    confirm. The image is never saved (it only lives in memory for this request)."""
    from workpulse.bot.vision import VisionError, read_screen_time
    raw = await file.read(MAX_UPLOAD + 1)
    try:
        data = read_screen_time(c, raw, file.content_type or "")
    except VisionError as e:
        raise HTTPException(422, str(e))
    finally:
        del raw
    day = data.get("date")
    if not day:
        day = (date.today() - timedelta(days=1 if data.get("relative") == "yesterday" else 0)).isoformat()
    return {"day": day, "period": data.get("period", "unknown"), "total_minutes": data.get("total_minutes"),
            "pickups": data.get("pickups"), "apps": data["apps"]}


@router.get("/phone/setup", dependencies=[Depends(require_local)])
def phone_setup(c: Config = Depends(cfg)) -> dict[str, Any]:
    return {
        "token": phone_token(c), "header": PHONE_TOKEN_HEADER, "path": "/api/phone/ingest",
        "local_url": f"{c.server.url}/api/phone/ingest", "default_device": c.phone.default_device,
        "example": {"day": date.today().isoformat(), "device": c.phone.default_device, "total": "3h 20m", "pickups": 85,
                    "apps": [{"name": "Instagram", "minutes": 70}, {"name": "WhatsApp", "time": "45m"}]},
    }


@router.delete("/phone/day", dependencies=UI)
def phone_delete(date_: str = Query(..., alias="date"), device: str | None = None, c: Config = Depends(cfg)) -> dict[str, int]:
    return {"deleted": delete_day(c, date_, device)}


@router.get("/digital")
def get_digital(date_: str | None = Query(None, alias="date"), c: Config = Depends(cfg)) -> dict[str, Any]:
    try:
        d = date.fromisoformat(date_) if date_ else date.today()
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")
    out = digital_day(c, d)
    out["week"] = digital_range(c, d, 7)
    return out
