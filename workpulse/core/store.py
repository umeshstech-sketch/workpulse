"""CRUD for goals, roadmap milestones, team, tasks, meetings and the message log (bot + dashboard)."""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select

from workpulse.core.db import Goal, Meeting, Message, Milestone, Task, TeamMember, session_scope

GOAL_KINDS = ("daily", "weekly", "monthly", "long-term")
HORIZONS = {"100d": 100, "6m": 182, "1y": 365}  # roadmap horizon -> days
TASK_STATUSES = ("todo", "doing", "done")


# ---- generic update / delete (whitelisted fields only) ------------------------------------------

def update_row(db: Path, model, row_id: int, fields: dict, allowed: set[str]):
    """Set `fields` (only keys in `allowed`) on one row. Returns the row, or None if it doesn't exist."""
    with session_scope(db) as s:
        row = s.get(model, row_id)
        if row is None:
            return None
        for k, v in fields.items():
            if k in allowed:
                setattr(row, k, v)
        if model is Goal and "done" in fields:
            row.done_at = time.time() if fields["done"] else None
        if model is Task and "status" in fields:
            row.done_at = time.time() if fields["status"] == "done" else None
        s.flush()
        return row


def delete_row(db: Path, model, row_id: int) -> bool:
    with session_scope(db) as s:
        row = s.get(model, row_id)
        if row is None:
            return False
        s.delete(row)
        if model is Goal:  # its roadmap steps go with it
            for m in s.scalars(select(Milestone).where(Milestone.goal_id == row_id)):
                s.delete(m)
        return True


# ---- goals -------------------------------------------------------------------------------------

def add_goal(db: Path, text: str, kind: str = "daily", category: str | None = None,
             target_min: float | None = None, deadline: str | None = None) -> Goal:
    with session_scope(db) as s:
        g = Goal(text=text.strip()[:300], kind=kind, category=category, target_min=target_min, deadline=deadline)
        s.add(g)
        s.flush()
        s.refresh(g)
        return g


def list_goals(db: Path, include_done: bool = False) -> list[Goal]:
    with session_scope(db) as s:
        q = select(Goal).order_by(Goal.done, Goal.id)
        if not include_done:
            q = q.where(Goal.done.is_(False))
        return list(s.scalars(q))


def complete_goal(db: Path, goal_id: int) -> Goal | None:
    with session_scope(db) as s:
        g = s.get(Goal, goal_id)
        if g is not None and not g.done:
            g.done, g.done_at = True, time.time()
        return g


# ---- team + tasks ------------------------------------------------------------------------------

def find_member(db: Path, name: str) -> TeamMember | None:
    with session_scope(db) as s:
        return s.scalars(select(TeamMember).where(func.lower(TeamMember.name) == name.strip().lower())).first()


def add_member(db: Path, name: str, role: str | None = None, contact: str | None = None,
               notes: str | None = None) -> tuple[TeamMember, bool]:
    """Returns (member, created). Re-adding an existing name updates the role."""
    with session_scope(db) as s:
        m = s.scalars(select(TeamMember).where(func.lower(TeamMember.name) == name.strip().lower())).first()
        if m:
            if role:
                m.role = role
            return m, False
        m = TeamMember(name=name.strip()[:64], role=role, contact=contact, notes=notes)
        s.add(m)
        s.flush()
        s.refresh(m)
        return m, True


def list_members(db: Path) -> list[TeamMember]:
    with session_scope(db) as s:
        return list(s.scalars(select(TeamMember).order_by(TeamMember.name)))


def add_task(db: Path, text: str, owner: str = "me", due: str | None = None) -> Task:
    with session_scope(db) as s:
        t = Task(text=text.strip()[:300], owner=owner, due=due)
        s.add(t)
        s.flush()
        s.refresh(t)
        return t


def list_tasks(db: Path, include_done: bool = False) -> list[Task]:
    with session_scope(db) as s:
        q = select(Task).order_by(Task.due.is_(None), Task.due, Task.id)
        if not include_done:
            q = q.where(Task.status != "done")
        return list(s.scalars(q))


def complete_task(db: Path, task_id: int) -> Task | None:
    with session_scope(db) as s:
        t = s.get(Task, task_id)
        if t is None or t.status == "done":
            return None
        t.status, t.done_at = "done", time.time()
        return t


def tasks_due_for_reminder(db: Path, within_hours: float, now: datetime | None = None) -> list[Task]:
    """Open tasks due (end of their due day) within `within_hours`, or overdue, not yet reminded."""
    now = now or datetime.now()
    limit = now + timedelta(hours=within_hours)
    out = []
    for t in list_tasks(db):
        if not t.due or t.reminded_at:
            continue
        due_end = datetime.combine(date.fromisoformat(t.due), datetime.max.time())
        if due_end <= limit:
            out.append(t)
    return out


def mark_reminded(db: Path, ids: list[int]) -> None:
    with session_scope(db) as s:
        for t in s.scalars(select(Task).where(Task.id.in_(ids))):
            t.reminded_at = time.time()


# ---- meetings ----------------------------------------------------------------------------------

def add_meeting(db: Path, title: str, minutes: float, attendees: list[str] | None = None,
                start_ts: float | None = None, notes: str | None = None) -> Meeting:
    with session_scope(db) as s:
        m = Meeting(title=title.strip()[:200], minutes=minutes, start_ts=start_ts or time.time(),
                    attendees=", ".join(a.strip() for a in attendees or [] if a.strip()) or None, notes=notes)
        s.add(m)
        s.flush()
        s.refresh(m)
        return m


def list_meetings(db: Path, since_ts: float = 0) -> list[Meeting]:
    with session_scope(db) as s:
        return list(s.scalars(select(Meeting).where(Meeting.start_ts >= since_ts).order_by(Meeting.start_ts.desc())))


# ---- roadmap milestones ------------------------------------------------------------------------

def add_milestone(db: Path, horizon: str, text: str, goal_id: int | None = None, source: str = "me",
                  target_date: str | None = None) -> Milestone:
    if horizon not in HORIZONS:
        raise ValueError(f"horizon must be one of {list(HORIZONS)}")
    target_date = target_date or (date.today() + timedelta(days=HORIZONS[horizon])).isoformat()
    with session_scope(db) as s:
        m = Milestone(horizon=horizon, text=text.strip()[:300], goal_id=goal_id, source=source, target_date=target_date)
        s.add(m)
        s.flush()
        s.refresh(m)
        return m


def list_milestones(db: Path) -> list[Milestone]:
    with session_scope(db) as s:
        return list(s.scalars(select(Milestone).order_by(Milestone.done, Milestone.target_date, Milestone.id)))


# ---- message log -------------------------------------------------------------------------------

def log_message(db: Path, direction: str, body: str, kind: str = "chat", status: str = "sent",
                error: str | None = None) -> None:
    with session_scope(db) as s:
        s.add(Message(direction=direction, body=body[:4000], kind=kind, status=status, error=error,
                      day=date.today().isoformat()))


def sent_today(db: Path, kind: str, day: date | None = None) -> bool:
    """Was a scheduled message of this kind successfully sent (or dry-run logged) today? Prevents double sends."""
    d = (day or date.today()).isoformat()
    with session_scope(db) as s:
        q = select(func.count()).select_from(Message).where(
            Message.kind == kind, Message.day == d, Message.direction == "out", Message.status != "failed")
        return (s.scalar(q) or 0) > 0


def recent_messages(db: Path, limit: int = 10, kinds: tuple[str, ...] | None = None) -> list[Message]:
    with session_scope(db) as s:
        q = select(Message).order_by(Message.ts.desc()).limit(limit)
        if kinds:
            q = q.where(Message.kind.in_(kinds))
        return list(reversed(list(s.scalars(q))))


# ---- goal progress -----------------------------------------------------------------------------

@dataclass
class GoalProgress:
    goal: Goal
    minutes: float | None  # tracked minutes in the goal's category over its period (None if not linked)
    pct: float | None  # from tracked time vs target, else the manual percentage, else None

    @property
    def text(self) -> str:
        g = self.goal
        bits = [f"{g.text}"]
        if self.minutes is not None and g.target_min:
            bits.append(f"{_m(self.minutes)}/{_m(g.target_min)} {g.category} ({self.pct:.0f}%)")
        elif g.category:
            bits.append(f"{_m(self.minutes or 0)} {g.category}")
        elif self.pct is not None:
            bits.append(f"{self.pct:.0f}% done")
        if g.deadline:
            bits.append(f"due {g.deadline}")
        return " · ".join(bits)


def _m(minutes: float) -> str:
    m = int(round(minutes))
    return f"{m // 60}h{m % 60:02d}" if m >= 60 else f"{m}m"


def period_start(kind: str, today: date) -> date | None:
    if kind == "daily":
        return today
    if kind == "weekly":
        return today - timedelta(days=today.weekday())  # since Monday
    if kind == "monthly":
        return today.replace(day=1)
    return None
