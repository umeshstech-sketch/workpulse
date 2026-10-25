"""Phase 4 API: goals (linked to tracked time), roadmap, team/tasks/meetings, insights, and chatting with the coach."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import AfterValidator, BaseModel, Field

from workpulse.backend.deps import cfg, require_ui
from workpulse.config import CATEGORIES, Config
from workpulse.core.db import Goal, Meeting, Milestone, Task, TeamMember
from workpulse.core.insights import collaboration, compute_insights, profile, top
from workpulse.core.service import goal_progress
from workpulse.core.store import (HORIZONS, add_goal, add_meeting, add_member, add_milestone, add_task, delete_row,
                                  find_member, list_goals, list_meetings, list_members, list_milestones, list_tasks,
                                  log_message, recent_messages, update_row)

router = APIRouter(prefix="/api")
UI = [Depends(require_ui)]

Kind = Literal["daily", "weekly", "monthly", "long-term"]
Horizon = Literal["100d", "6m", "1y"]
Status = Literal["todo", "doing", "done"]
HORIZON_LABELS = {"100d": "Next 100 days", "6m": "6 months", "1y": "1 year"}


def _iso(v: str | None) -> str | None:
    if v in (None, ""):
        return None
    try:
        return date.fromisoformat(v).isoformat()
    except ValueError:
        raise ValueError("dates must be YYYY-MM-DD")


def _category(v: str | None) -> str | None:
    if v in (None, ""):
        return None
    if v not in CATEGORIES:
        raise ValueError(f"category must be one of {CATEGORIES}")
    return v


IsoDate = Annotated[str | None, AfterValidator(_iso)]
CategoryName = Annotated[str | None, AfterValidator(_category)]


# ---- goals -------------------------------------------------------------------------------------

class GoalIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    kind: Kind = "daily"
    category: CategoryName = None
    target_min: float | None = Field(None, gt=0, le=100000)
    deadline: IsoDate = None



class GoalPatch(BaseModel):
    text: str | None = Field(None, min_length=1, max_length=300)
    kind: Kind | None = None
    category: CategoryName = None
    target_min: float | None = Field(None, gt=0, le=100000)
    deadline: IsoDate = None
    done: bool | None = None
    manual_pct: float | None = Field(None, ge=0, le=100)



def _goal_dict(p) -> dict[str, Any]:
    g = p.goal
    return {"id": g.id, "text": g.text, "kind": g.kind, "category": g.category, "target_min": g.target_min,
            "deadline": g.deadline, "done": g.done, "manual_pct": g.manual_pct, "created_at": g.created_at,
            "tracked_min": p.minutes, "pct": p.pct, "summary": p.text}


@router.get("/goals")
def get_goals(include_done: bool = False, c: Config = Depends(cfg)) -> dict[str, Any]:
    goals = list_goals(c.db_path, include_done=include_done)
    return {"goals": [_goal_dict(p) for p in goal_progress(c, goals)], "categories": CATEGORIES,
            "kinds": ["daily", "weekly", "monthly", "long-term"]}


@router.post("/goals", dependencies=UI)
def create_goal(body: GoalIn, c: Config = Depends(cfg)) -> dict[str, Any]:
    g = add_goal(c.db_path, body.text, body.kind, body.category, body.target_min, body.deadline)
    return _goal_dict(goal_progress(c, [g])[0])


@router.patch("/goals/{goal_id}", dependencies=UI)
def patch_goal(goal_id: int, body: GoalPatch, c: Config = Depends(cfg)) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True)
    g = update_row(c.db_path, Goal, goal_id, fields,
                   {"text", "kind", "category", "target_min", "deadline", "done", "manual_pct"})
    if g is None:
        raise HTTPException(404, "no such goal")
    return _goal_dict(goal_progress(c, [g])[0])


@router.delete("/goals/{goal_id}", dependencies=UI)
def remove_goal(goal_id: int, c: Config = Depends(cfg)) -> dict[str, bool]:
    if not delete_row(c.db_path, Goal, goal_id):
        raise HTTPException(404, "no such goal")
    return {"deleted": True}


# ---- roadmap -----------------------------------------------------------------------------------

class MilestoneIn(BaseModel):
    horizon: Horizon
    text: str = Field(min_length=1, max_length=300)
    goal_id: int | None = None
    source: Literal["me", "coach"] = "me"


class MilestonePatch(BaseModel):
    horizon: Horizon | None = None
    text: str | None = Field(None, min_length=1, max_length=300)
    done: bool | None = None


def _ms_dict(m: Milestone) -> dict[str, Any]:
    return {"id": m.id, "goal_id": m.goal_id, "horizon": m.horizon, "text": m.text, "target_date": m.target_date,
            "done": m.done, "source": m.source}


@router.get("/roadmap")
def get_roadmap(c: Config = Depends(cfg)) -> dict[str, Any]:
    ms = list_milestones(c.db_path)
    today = date.today()
    goals = [g for g in list_goals(c.db_path) if g.kind == "long-term"]
    return {
        "horizons": [{"key": h, "label": HORIZON_LABELS[h], "until": (today + timedelta(days=d)).isoformat(),
                      "milestones": [_ms_dict(m) for m in ms if m.horizon == h]} for h, d in HORIZONS.items()],
        "long_term_goals": [{"id": g.id, "text": g.text, "deadline": g.deadline} for g in goals],
    }


@router.post("/roadmap/milestones", dependencies=UI)
def create_milestone(body: MilestoneIn, c: Config = Depends(cfg)) -> dict[str, Any]:
    return _ms_dict(add_milestone(c.db_path, body.horizon, body.text, body.goal_id, body.source))


@router.patch("/roadmap/milestones/{ms_id}", dependencies=UI)
def patch_milestone(ms_id: int, body: MilestonePatch, c: Config = Depends(cfg)) -> dict[str, Any]:
    m = update_row(c.db_path, Milestone, ms_id, body.model_dump(exclude_unset=True), {"horizon", "text", "done"})
    if m is None:
        raise HTTPException(404, "no such milestone")
    return _ms_dict(m)


@router.delete("/roadmap/milestones/{ms_id}", dependencies=UI)
def remove_milestone(ms_id: int, c: Config = Depends(cfg)) -> dict[str, bool]:
    if not delete_row(c.db_path, Milestone, ms_id):
        raise HTTPException(404, "no such milestone")
    return {"deleted": True}


class SuggestIn(BaseModel):
    goal_id: int


@router.post("/roadmap/suggest", dependencies=UI)
def suggest_milestones(body: SuggestIn, c: Config = Depends(cfg)) -> dict[str, Any]:
    """Coach-suggested milestones for a goal. Nothing is saved until you add the ones you like."""
    from workpulse.bot.roadmap import suggest
    g = next((g for g in list_goals(c.db_path, include_done=True) if g.id == body.goal_id), None)
    if g is None:
        raise HTTPException(404, "no such goal")
    items, source = suggest(c, g)
    return {"goal_id": g.id, "source": source, "suggestions": [{"horizon": h, "text": t} for h, t in items]}


# ---- team, tasks, meetings ---------------------------------------------------------------------

class MemberIn(BaseModel):
    name: str = Field(min_length=1, max_length=64, pattern=r"^[^\s@][^@]*$")
    role: str | None = Field(None, max_length=64)
    contact: str | None = Field(None, max_length=128)
    notes: str | None = Field(None, max_length=1000)


class MemberPatch(BaseModel):
    role: str | None = Field(None, max_length=64)
    contact: str | None = Field(None, max_length=128)
    notes: str | None = Field(None, max_length=1000)


class TaskIn(BaseModel):
    text: str = Field(min_length=1, max_length=300)
    owner: str = Field("me", min_length=1, max_length=64)
    due: IsoDate = None



class TaskPatch(BaseModel):
    text: str | None = Field(None, min_length=1, max_length=300)
    owner: str | None = Field(None, min_length=1, max_length=64)
    status: Status | None = None
    due: IsoDate = None



class MeetingIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    minutes: float = Field(gt=0, le=24 * 60)
    attendees: list[str] = Field(default_factory=list, max_length=50)
    when: str | None = None  # "YYYY-MM-DDTHH:MM" (local); default now
    notes: str | None = Field(None, max_length=2000)


def _member_dict(m: TeamMember, tasks: list[Task]) -> dict[str, Any]:
    return {"id": m.id, "name": m.name, "role": m.role, "contact": m.contact, "notes": m.notes,
            "open_tasks": sum(1 for t in tasks if t.owner.lower() == m.name.lower() and t.status != "done")}


def _task_dict(t: Task) -> dict[str, Any]:
    return {"id": t.id, "text": t.text, "owner": t.owner, "status": t.status, "due": t.due, "done_at": t.done_at}


def _meeting_dict(m: Meeting) -> dict[str, Any]:
    return {"id": m.id, "title": m.title, "start_ts": m.start_ts, "minutes": m.minutes,
            "attendees": [a.strip() for a in (m.attendees or "").split(",") if a.strip()], "notes": m.notes}


def _owner(c: Config, owner: str) -> str:
    """'me' stays 'me'; anyone else is matched to (or added to) the team, with consistent capitalisation."""
    owner = owner.strip().lstrip("@")
    if owner.lower() in ("me", "you", "myself"):
        return "me"
    m = find_member(c.db_path, owner) or add_member(c.db_path, owner)[0]
    return m.name


@router.get("/team")
def get_team(c: Config = Depends(cfg)) -> dict[str, Any]:
    tasks = list_tasks(c.db_path, include_done=True)
    recent_done_cutoff = datetime.now().timestamp() - 7 * 86400
    visible = [t for t in tasks if t.status != "done" or (t.done_at or 0) >= recent_done_cutoff]
    since = datetime.now().timestamp() - 30 * 86400
    return {
        "members": [_member_dict(m, tasks) for m in list_members(c.db_path)],
        "tasks": [_task_dict(t) for t in visible],
        "meetings": [_meeting_dict(m) for m in list_meetings(c.db_path, since)],
        "collaboration": collaboration(c),
    }


@router.post("/team/members", dependencies=UI)
def create_member(body: MemberIn, c: Config = Depends(cfg)) -> dict[str, Any]:
    m, created = add_member(c.db_path, body.name, body.role, body.contact, body.notes)
    if not created:
        raise HTTPException(409, f"{m.name} is already on the team")
    return _member_dict(m, [])


@router.patch("/team/members/{member_id}", dependencies=UI)
def patch_member(member_id: int, body: MemberPatch, c: Config = Depends(cfg)) -> dict[str, Any]:
    m = update_row(c.db_path, TeamMember, member_id, body.model_dump(exclude_unset=True), {"role", "contact", "notes"})
    if m is None:
        raise HTTPException(404, "no such member")
    return _member_dict(m, list_tasks(c.db_path))


@router.delete("/team/members/{member_id}", dependencies=UI)
def remove_member(member_id: int, c: Config = Depends(cfg)) -> dict[str, bool]:
    if not delete_row(c.db_path, TeamMember, member_id):
        raise HTTPException(404, "no such member")
    return {"deleted": True}


@router.post("/tasks", dependencies=UI)
def create_task(body: TaskIn, c: Config = Depends(cfg)) -> dict[str, Any]:
    return _task_dict(add_task(c.db_path, body.text, _owner(c, body.owner), body.due))


@router.patch("/tasks/{task_id}", dependencies=UI)
def patch_task(task_id: int, body: TaskPatch, c: Config = Depends(cfg)) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True)
    if "owner" in fields:
        fields["owner"] = _owner(c, fields["owner"])
    if "due" in fields:
        fields["reminded_at"] = None  # new due date -> remind again
    t = update_row(c.db_path, Task, task_id, fields, {"text", "owner", "status", "due", "reminded_at"})
    if t is None:
        raise HTTPException(404, "no such task")
    return _task_dict(t)


@router.delete("/tasks/{task_id}", dependencies=UI)
def remove_task(task_id: int, c: Config = Depends(cfg)) -> dict[str, bool]:
    if not delete_row(c.db_path, Task, task_id):
        raise HTTPException(404, "no such task")
    return {"deleted": True}


@router.post("/meetings", dependencies=UI)
def create_meeting(body: MeetingIn, c: Config = Depends(cfg)) -> dict[str, Any]:
    start = None
    if body.when:
        try:
            start = datetime.fromisoformat(body.when).timestamp()
        except ValueError:
            raise HTTPException(422, "when must be YYYY-MM-DDTHH:MM")
    attendees = [_owner(c, a) for a in body.attendees if a.strip() and a.strip().lower() != "me"]
    return _meeting_dict(add_meeting(c.db_path, body.title, body.minutes, attendees, start, body.notes))


@router.delete("/meetings/{meeting_id}", dependencies=UI)
def remove_meeting(meeting_id: int, c: Config = Depends(cfg)) -> dict[str, bool]:
    if not delete_row(c.db_path, Meeting, meeting_id):
        raise HTTPException(404, "no such meeting")
    return {"deleted": True}


# ---- insights ----------------------------------------------------------------------------------

@router.get("/insights")
def get_insights(days: int = Query(14, ge=7, le=60), c: Config = Depends(cfg)) -> dict[str, Any]:
    ins = compute_insights(c, days=days)
    return {
        "best": [{"text": i.text, "weight": round(i.weight, 1)} for i in top(ins, "best", 6)],
        "improve": [{"text": i.text, "weight": round(i.weight, 1)} for i in top(ins, "improve", 6)],
        "profile": profile(c, days=days),
    }


# ---- coach chat (same brain as WhatsApp) -------------------------------------------------------

class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


def _msg_dict(m) -> dict[str, Any]:
    return {"id": m.id, "ts": m.ts, "direction": m.direction, "kind": m.kind, "body": m.body,
            "status": m.status, "error": m.error}


@router.get("/messages")
def get_messages(limit: int = Query(60, ge=1, le=500), c: Config = Depends(cfg)) -> dict[str, Any]:
    return {"messages": [_msg_dict(m) for m in recent_messages(c.db_path, limit=limit)]}


@router.post("/chat", dependencies=UI)
def chat(body: ChatIn, request: Request, c: Config = Depends(cfg)) -> dict[str, Any]:
    """Talk to the bot from the dashboard or the phone app. Same commands + coach as WhatsApp; the reply is
    shown in the app (logged locally), not sent over WhatsApp."""
    from workpulse.bot.commands import SOURCE_STATUS, handle
    source = "phone" if getattr(request.state, "device_name", None) else "dashboard"
    reply = handle(c, body.text, source=source)
    log_message(c.db_path, "out", reply, kind="chat", status=SOURCE_STATUS.get(source, "local"))
    return {"reply": reply}
