"""FastAPI backend: ingest from the agent, stats for the dashboard, settings, export, pause.

Runs on 127.0.0.1 only. Every number comes from workpulse.core.stats, the same code the CLI uses,
so the dashboard and `workpulse today` can't disagree.
"""
from __future__ import annotations

import io
import json
import logging
import mimetypes
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import date, timedelta
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse, PlainTextResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, ValidationError

from workpulse import __version__
from workpulse.agent import control
from workpulse.agent.sinks import TOKEN_HEADER, agent_token
from workpulse.backend.deps import cfg, require_local, require_ui
from workpulse.backend.pairing_api import router as pairing_router
from workpulse.backend.phone_api import router as phone_router
from workpulse.backend.planning import router as planning_router
from workpulse.config import CATEGORIES, ROOT, Config, get_config, save_settings
from workpulse.core.db import delete_sessions, latest_session, sessions_between, upsert_sessions
from workpulse.core.export import write_csv
from workpulse.core.models import SessionRecord
from workpulse.core.service import range_stats
from workpulse.core.stats import DayStats, compare
from workpulse.core.trends import find_streaks, trend_sentence, week_trend

DASHBOARD = ROOT / "dashboard"
UI_HEADER = "X-WorkPulse-UI"  # custom header => browsers block cross-site requests (CORS preflight)
log = logging.getLogger("workpulse.server")

# The ONLY paths reachable through a tunnel (ngrok/cloudflared). Each one authenticates every request:
# WhatsApp webhooks by the provider's signature, phone ingest by data/phone.token.
WEBHOOK_PATHS = {"/api/whatsapp/twilio", "/api/whatsapp/meta", "/api/phone/ingest"}
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}
# Reachable from your Wi-Fi WITHOUT a device token: the mobile app's static files (no data in them), pairing,
# and a ping so the app can tell "laptop unreachable" from "not paired".
LAN_PUBLIC_PREFIXES = ("/m/", "/assets/")
LAN_PUBLIC_PATHS = {"/", "/m", "/api/pair", "/api/ping", "/favicon.ico"}
TUNNEL_HEADERS = ("x-forwarded-for", "x-forwarded-host", "cf-connecting-ip", "forwarded", "ngrok-trace-id")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    c = get_config()
    try:  # never-log list may have grown since phone data was stored
        from workpulse.core.phone import apply_privacy_to_stored
        if n := apply_privacy_to_stored(c):
            log.info("privacy: hid %d stored phone app rows matching the never-log list", n)
    except Exception:
        log.exception("privacy clean-up of phone data failed")
    sched = None
    if not c.demo and os.environ.get("WORKPULSE_NO_SCHEDULER") != "1":  # reports (if WhatsApp on) + daily backups
        from workpulse.bot.scheduler import BotScheduler
        try:
            sched = BotScheduler(c)
            sched.start()
        except Exception:
            log.exception("could not start the WhatsApp scheduler")
            sched = None
    yield
    if sched:
        sched.shutdown()


app = FastAPI(title="WorkPulse", version=__version__, docs_url="/api/docs", redoc_url=None, lifespan=lifespan)
app.include_router(planning_router)
app.include_router(phone_router)
app.include_router(pairing_router)


@app.exception_handler(Exception)
async def unexpected_error(request: Request, exc: Exception):
    """Anything unexpected: full traceback to data/logs/server.log, a short readable message to the caller."""
    import sqlite3

    from fastapi.responses import JSONResponse
    from sqlalchemy.exc import OperationalError
    if isinstance(exc, (OperationalError, sqlite3.OperationalError)) and "locked" in str(exc).lower():
        log.warning("database busy on %s %s", request.method, request.url.path)
        return JSONResponse({"detail": "The database is busy for a moment. Try again."}, status_code=503)
    log.exception("unexpected error on %s %s", request.method, request.url.path)
    return JSONResponse({"detail": f"Something went wrong ({type(exc).__name__}). Details are in data/logs/server.log."},
                        status_code=500)


def _host_of(request: Request) -> str:
    host = (request.headers.get("host") or "").lower()
    return host[1:].split("]")[0] if host.startswith("[") else host.rsplit(":", 1)[0]


@app.middleware("http")
async def access_control(request: Request, call_next):
    """Who may talk to WorkPulse:

    * The laptop itself (loopback): everything, as long as the Host is localhost. This blocks DNS-rebinding
      attacks from websites you visit.
    * Requests that came through a tunnel (forwarding headers): only the webhook paths, which check their own
      signature or token. So exposing the WhatsApp webhook never exposes your data.
    * Phones on your home Wi-Fi (private IP), only when `server.lan` is on, and phones on your Tailscale network
      (100.64.0.0/10), only when `server.remote` is on: the mobile app's static files and pairing; every other
      /api call needs a paired device's `Authorization: Bearer` token.
    * Anything else: refused.
    """
    from fastapi.responses import JSONResponse

    from workpulse.core.devices import is_loopback, is_private_lan, is_tailscale, verify
    path = request.url.path
    if path in WEBHOOK_PATHS:
        return await call_next(request)
    client = request.client.host if request.client else None
    tunneled = any(h in request.headers for h in TUNNEL_HEADERS)
    host = _host_of(request)
    if is_loopback(client) and not tunneled:
        if host not in LOCAL_HOSTS:
            return PlainTextResponse("Invalid host header", status_code=400)
        return await call_next(request)
    c = get_config()
    on_wifi = is_private_lan(client) and c.server.lan
    on_tailscale = is_tailscale(client) and c.server.remote
    if (on_wifi or on_tailscale) and not tunneled:
        # Host must be an IP address (what the phone typed or scanned) or your Tailscale name, never another
        # domain name: DNS rebinding again.
        if not (host in LOCAL_HOSTS or is_private_lan(host) or is_tailscale(host) or (on_tailscale and host.endswith(".ts.net"))):
            return PlainTextResponse("Invalid host header", status_code=400)
        if path in LAN_PUBLIC_PATHS or path.startswith(LAN_PUBLIC_PREFIXES):
            return await call_next(request)
        auth = request.headers.get("authorization", "")
        device = verify(c, auth[7:].strip() if auth.lower().startswith("bearer ") else None, client)
        if device is None:
            return JSONResponse({"detail": "This phone isn't paired (or was removed). Pair it again in the app."}, status_code=401)
        request.state.device_name = device.name
        return await call_next(request)
    if is_private_lan(client) and not tunneled:
        return PlainTextResponse("Wi-Fi access is off. On the laptop run: .\\workpulse lan on", status_code=403)
    if is_tailscale(client) and not tunneled:
        return PlainTextResponse("Away-from-home access is off. On the laptop run: .\\workpulse remote on", status_code=403)
    return PlainTextResponse("WorkPulse is local-only", status_code=403)


def require_agent(c: Config = Depends(cfg), x_workpulse_token: str | None = Header(default=None)) -> None:
    if not x_workpulse_token or not secrets.compare_digest(x_workpulse_token, agent_token(c)):
        raise HTTPException(401, f"bad or missing {TOKEN_HEADER}")


# ---- helpers -----------------------------------------------------------------------------------

def _day_payload(c: Config, st: DayStats, history: list[DayStats]) -> dict[str, Any]:
    cmp = compare(st, history)
    d = st.to_dict()
    d["top_apps"] = [{"app": a, "name": c.alias(a), "seconds": s} for a, s in list(st.per_app.items())[:10]]
    d["categories"] = [{"name": k, "seconds": v} for k, v in st.per_category.items()]
    d["timeline"] = [
        {"start": s.start_ts, "end": s.end_ts, "state": s.state, "category": s.category,
         "app": c.alias(s.app) if s.app else None, "title": s.title}
        for s in st.sessions
    ]
    d["comparison"] = {
        "yesterday_active_s": cmp.yesterday.active_s if cmp.yesterday else None,
        "yesterday_score": cmp.yesterday.focus_score if cmp.yesterday else None,
        "avg7_active_s": cmp.avg7_active_s,
        "avg7_score": round(cmp.avg7_score, 1),
        "best_day": cmp.best.day.isoformat() if cmp.best else None,
        "best_score": cmp.best.focus_score if cmp.best else None,
        "best_active_s": cmp.best.active_s if cmp.best else None,
    }
    return d


def _parse_day(s: str | None) -> date:
    if not s:
        return date.today()
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise HTTPException(400, "date must be YYYY-MM-DD")


# ---- read endpoints ----------------------------------------------------------------------------

@app.get("/api/status")
def status(c: Config = Depends(cfg)) -> dict[str, Any]:
    s = latest_session(c.db_path)
    paused = control.is_paused(c)
    agent_pid = control.running_pid(c, "agent")
    current = None
    if s and not paused and time.time() - s.end_ts < c.tracking.flush_interval_s * 3:
        current = {"state": s.state, "category": s.category, "app": c.alias(s.app) if s.app else None,
                   "since": s.start_ts, "duration_s": s.duration}
    return {
        "tracking": "paused" if paused else ("on" if agent_pid else "off"),
        "agent_running": bool(agent_pid),
        "paused_since": control.paused_since(c),
        "current": current,
        "last_seen": s.end_ts if s else None,
        "demo": c.demo,
        "version": __version__,
        "server_time": time.time(),
    }


@app.get("/api/day")
def day(date_: str | None = Query(None, alias="date"), c: Config = Depends(cfg)) -> dict[str, Any]:
    d = _parse_day(date_)
    days = range_stats(c, d - timedelta(days=60), d)
    return _day_payload(c, days[-1], days[:-1])


@app.get("/api/week")
def week(end: str | None = None, c: Config = Depends(cfg)) -> dict[str, Any]:
    e = _parse_day(end)
    days = range_stats(c, e - timedelta(days=29), e)  # 30 days: this week, last week, streaks
    last7 = days[-7:]
    totals: dict[str, float] = {}
    for d in last7:
        for k, v in d.per_category.items():
            totals[k] = totals.get(k, 0) + v
    active_days = [d for d in last7 if d.active_s > 0]
    best = max(active_days, key=lambda d: (d.focus_score, d.active_s)) if active_days else None
    # Today is still in progress, so comparing it would always look like a drop: trend uses full days only.
    partial = e == date.today()
    trend = week_trend(days[-15:-1] if partial else days[-14:])
    return {
        "end": e.isoformat(),
        "trend_full_days_only": partial,
        "days": [{"date": d.day.isoformat(), "active_s": d.active_s, "productive_s": d.productive_s,
                  "focus_score": d.focus_score, "longest_streak_s": d.longest_streak_s,
                  "per_category": d.per_category} for d in last7],
        "category_totals": dict(sorted(totals.items(), key=lambda kv: -kv[1])),
        "trend": trend.to_dict(),
        "trend_text": trend_sentence(trend),
        "streaks": [{"label": s.label, "hours": s.hours, "days": s.days, "text": s.text}
                    for s in find_streaks(days, c.scoring.productive_categories)],
        "best_day": {"date": best.day.isoformat(), "score": best.focus_score, "active_s": best.active_s} if best else None,
    }


@app.get("/api/export.csv")
def export_csv(c: Config = Depends(cfg)) -> StreamingResponse:
    buf = io.StringIO()
    write_csv(sessions_between(c.db_path, 0, time.time() + 86400), buf)
    name = f"workpulse-export-{date.today()}.csv"
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


# ---- agent ingest ------------------------------------------------------------------------------

class SessionIn(BaseModel):
    id: str = Field(min_length=8, max_length=36)
    start_ts: float
    end_ts: float
    state: str = Field(pattern="^(active|idle|away)$")
    app: str | None = Field(None, max_length=128)
    title: str | None = Field(None, max_length=512)
    category: str = Field(max_length=32)


class IngestIn(BaseModel):
    sessions: list[SessionIn] = Field(max_length=5000)


@app.post("/api/ingest/sessions", dependencies=[Depends(require_agent)])
def ingest(body: IngestIn, c: Config = Depends(cfg)) -> dict[str, int]:
    if c.demo:  # never mix real activity into demo.db; the agent's auto mode then writes to the real DB
        raise HTTPException(409, "server is in demo mode")
    keep_titles = c.privacy.capture_titles  # enforced again server-side
    recs = [SessionRecord(id=s.id, start_ts=s.start_ts, end_ts=s.end_ts, state=s.state, app=s.app,
                          title=s.title if keep_titles else None, category=s.category) for s in body.sessions]
    return {"stored": upsert_sessions(c.db_path, recs)}


# ---- controls (dashboard) ----------------------------------------------------------------------

@app.post("/api/pause", dependencies=[Depends(require_ui)])
def pause(c: Config = Depends(cfg)) -> dict[str, Any]:
    control.pause(c)
    return status(c)


@app.post("/api/resume", dependencies=[Depends(require_ui)])
def resume(c: Config = Depends(cfg)) -> dict[str, Any]:
    control.resume(c)
    return status(c)


def _settings_view(c: Config) -> dict[str, Any]:
    return {
        "tracking": c.tracking.model_dump(),
        "privacy": c.privacy.model_dump(),
        "scoring": c.scoring.model_dump(),
        "categories": {"apps": c.categories.apps},
        "category_names": CATEGORIES,
    }


@app.get("/api/settings")
def get_settings(c: Config = Depends(cfg)) -> dict[str, Any]:
    return _settings_view(c)


EDITABLE = {"tracking", "privacy", "scoring", "categories"}


@app.put("/api/settings", dependencies=[Depends(require_ui), Depends(require_local)])
def put_settings(changes: dict[str, Any]) -> dict[str, Any]:
    unknown = set(changes) - EDITABLE
    if unknown:
        raise HTTPException(400, f"not editable here: {sorted(unknown)}")
    if "categories" in changes and set(changes["categories"]) - {"apps"}:
        raise HTTPException(400, "only categories.apps is editable from the dashboard")
    try:
        new = save_settings(changes)
    except ValidationError as e:
        raise HTTPException(422, e.errors(include_url=False, include_context=False))
    if "privacy" in changes:
        from workpulse.core.phone import apply_privacy_to_stored
        apply_privacy_to_stored(new)
    return _settings_view(new)


class WipeIn(BaseModel):
    confirm: str


@app.post("/api/wipe", dependencies=[Depends(require_ui), Depends(require_local)])
def wipe(body: WipeIn, c: Config = Depends(cfg)) -> dict[str, int]:
    if body.confirm != "DELETE":
        raise HTTPException(400, 'send {"confirm": "DELETE"}')
    return {"deleted": delete_sessions(c.db_path)}


# ---- WhatsApp webhooks (public via your tunnel; signature-verified; your number only) -----------

def _reply_in_background(text: str) -> None:
    """Runs after the webhook has returned (Twilio wants an answer within 15 s; the AI coach may take longer)."""
    from workpulse.bot.commands import handle
    from workpulse.bot.messenger import Messenger
    c = get_config()
    try:
        reply = handle(c, text)
    except Exception:
        log.exception("handling WhatsApp message failed")
        reply = "😵 Something broke on my side. Check data/logs/server.log on the laptop."
    Messenger(c).send(reply, kind="chat")


def _public_url(request: Request, c: Config) -> str:
    """The exact URL Twilio signed: your configured public_url, else rebuilt from the tunnel's forwarded headers."""
    path = request.url.path + (f"?{request.url.query}" if request.url.query else "")
    if c.whatsapp.public_url:
        return c.whatsapp.public_url.rstrip("/") + path
    proto = request.headers.get("x-forwarded-proto", request.url.scheme).split(",")[0].strip()
    host = request.headers.get("x-forwarded-host") or request.headers.get("host", "")
    return f"{proto}://{host}{path}"


EMPTY_TWIML = '<?xml version="1.0" encoding="UTF-8"?><Response></Response>'


@app.post("/api/whatsapp/twilio", include_in_schema=False)
async def twilio_webhook(request: Request, background: BackgroundTasks) -> Response:
    from workpulse.bot.providers import TwilioProvider, digits, my_number
    c = get_config()
    form = {k: str(v) for k, v in (await request.form()).items()}
    if not TwilioProvider().verify(_public_url(request, c), form, request.headers.get("x-twilio-signature")):
        log.warning("rejected Twilio webhook: bad signature (check TWILIO_AUTH_TOKEN / whatsapp.public_url)")
        raise HTTPException(403, "bad signature")
    sender = digits(form.get("From", ""))
    if not my_number() or sender != my_number():
        log.warning("ignored WhatsApp message from an unknown number (ending %s)", sender[-4:])
        return Response(EMPTY_TWIML, media_type="text/xml")
    if c.demo:
        return Response(EMPTY_TWIML, media_type="text/xml")
    background.add_task(_reply_in_background, form.get("Body", ""))
    return Response(EMPTY_TWIML, media_type="text/xml")


@app.get("/api/whatsapp/meta", include_in_schema=False)
def meta_verify(request: Request) -> PlainTextResponse:
    """Meta's one-time webhook verification handshake."""
    from workpulse.bot.providers import MetaProvider
    q = request.query_params
    token = MetaProvider().verify_token
    if q.get("hub.mode") == "subscribe" and token and secrets.compare_digest(q.get("hub.verify_token", ""), token):
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403, "verification failed")


@app.post("/api/whatsapp/meta", include_in_schema=False)
async def meta_webhook(request: Request, background: BackgroundTasks) -> dict[str, str]:
    from workpulse.bot.providers import MetaProvider, my_number
    raw = await request.body()
    p = MetaProvider()
    if not p.verify(raw, request.headers.get("x-hub-signature-256")):
        raise HTTPException(403, "bad signature")
    if get_config().demo:
        return {"status": "ignored"}
    for sender, text in p.parse(json.loads(raw or b"{}")):
        if my_number() and sender == my_number():
            background.add_task(_reply_in_background, text)
        else:
            log.warning("ignored WhatsApp message from an unknown number (ending %s)", sender[-4:])
    return {"status": "ok"}


# ---- dashboard ---------------------------------------------------------------------------------

@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(DASHBOARD / "index.html", headers={"Cache-Control": "no-cache"})


# Windows doesn't know .apk, so it would be served as a generic file, which Android browsers refuse to install.
mimetypes.add_type("application/vnd.android.package-archive", ".apk")


@app.get("/m/workpulse.apk", include_in_schema=False)
def android_apk() -> FileResponse:
    apk = DASHBOARD / "m" / "workpulse.apk"
    if not apk.exists():
        raise HTTPException(404, "the Android app hasn't been built yet: scripts\\build-android.ps1")
    return FileResponse(apk, media_type="application/vnd.android.package-archive", filename="WorkPulse.apk")


app.mount("/m", StaticFiles(directory=DASHBOARD / "m", html=True), name="mobile")  # phone app (PWA)
app.mount("/assets", StaticFiles(directory=DASHBOARD), name="assets")
