"""SQLite storage. Schema is deliberately minimal: timestamps, state, app, optional title.

There is NO column for keystrokes, typed text, screenshots or screen contents — by design.
"""
from __future__ import annotations

import time
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import Boolean, Float, Index, Integer, String, create_engine, delete, event, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from workpulse.core.models import SessionRecord


class Base(DeclarativeBase):
    pass


class ActivitySession(Base):
    """One contiguous block of the same state + app (+ title)."""

    __tablename__ = "activity_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # uuid made by the agent (idempotent upserts)
    start_ts: Mapped[float] = mapped_column(Float, nullable=False)  # unix epoch seconds
    end_ts: Mapped[float] = mapped_column(Float, nullable=False)
    state: Mapped[str] = mapped_column(String(8), nullable=False)  # active | idle | away
    app: Mapped[str | None] = mapped_column(String(128))  # process name, e.g. "code"
    title: Mapped[str | None] = mapped_column(String(512))  # only if privacy.capture_titles
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="Other")
    device: Mapped[str] = mapped_column(String(16), nullable=False, default="laptop")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="agent")  # agent | demo
    updated_at: Mapped[float] = mapped_column(Float, nullable=False, default=time.time)

    __table_args__ = (Index("ix_sessions_range", "start_ts", "end_ts"),)

    def to_record(self) -> SessionRecord:
        return SessionRecord(
            id=self.id, start_ts=self.start_ts, end_ts=self.end_ts, state=self.state,
            app=self.app, title=self.title, category=self.category,
        )


class Goal(Base):
    __tablename__ = "goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(String(300), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False, default="daily")  # daily|weekly|monthly|long-term
    category: Mapped[str | None] = mapped_column(String(32))  # tracked time in this category counts toward it
    target_min: Mapped[float | None] = mapped_column(Float)
    deadline: Mapped[str | None] = mapped_column(String(10))  # YYYY-MM-DD
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    done_at: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[float] = mapped_column(Float, nullable=False, default=time.time)
    # For goals that tracked time can't measure ("launch my startup"): progress you set yourself, 0-100.
    manual_pct: Mapped[float | None] = mapped_column(Float)


class Milestone(Base):
    """A step on the roadmap (100 days / 6 months / 1 year), optionally under a long-term goal."""

    __tablename__ = "milestones"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    goal_id: Mapped[int | None] = mapped_column(Integer)
    horizon: Mapped[str] = mapped_column(String(4), nullable=False)  # 100d | 6m | 1y
    text: Mapped[str] = mapped_column(String(300), nullable=False)
    target_date: Mapped[str | None] = mapped_column(String(10))
    done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False, default="me")  # me | coach
    created_at: Mapped[float] = mapped_column(Float, nullable=False, default=time.time)


class Meeting(Base):
    """A logged team meeting (calls/standups often happen off the laptop, so they're logged by hand)."""

    __tablename__ = "meetings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    start_ts: Mapped[float] = mapped_column(Float, nullable=False, default=time.time)
    minutes: Mapped[float] = mapped_column(Float, nullable=False)
    attendees: Mapped[str | None] = mapped_column(String(300))  # comma-separated names
    notes: Mapped[str | None] = mapped_column(String(2000))


class PhoneDay(Base):
    """Daily phone screen time for one device. Phones only expose daily totals, so there's no timeline."""

    __tablename__ = "phone_days"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device: Mapped[str] = mapped_column(String(32), nullable=False, default="phone")
    day: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    total_s: Mapped[float] = mapped_column(Float, nullable=False)
    pickups: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(12), nullable=False, default="api")  # api|csv|adb|screenshot|manual|demo
    updated_at: Mapped[float] = mapped_column(Float, nullable=False, default=time.time)

    __table_args__ = (Index("ux_phone_days_device_day", "device", "day", unique=True),)


class PhoneApp(Base):
    __tablename__ = "phone_apps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device: Mapped[str] = mapped_column(String(32), nullable=False, default="phone")
    day: Mapped[str] = mapped_column(String(10), nullable=False)
    app: Mapped[str] = mapped_column(String(128), nullable=False)  # display name, e.g. "Instagram"
    package: Mapped[str | None] = mapped_column(String(160))  # e.g. com.instagram.android (Android only)
    category: Mapped[str] = mapped_column(String(32), nullable=False, default="Other")
    seconds: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (Index("ix_phone_apps_device_day", "device", "day"),)


class Device(Base):
    """A paired phone (mobile web app or Android app). Only a hash of its token is stored."""

    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False, default="web")  # web | android
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False, default=time.time)
    last_seen: Mapped[float | None] = mapped_column(Float)
    last_ip: Mapped[str | None] = mapped_column(String(45))


class PairingCode(Base):
    """Short-lived 6-digit code shown on the laptop; a phone trades it for a device token."""

    __tablename__ = "pairing_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[float] = mapped_column(Float, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class TeamMember(Base):
    __tablename__ = "team_members"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    role: Mapped[str | None] = mapped_column(String(64))
    contact: Mapped[str | None] = mapped_column(String(128))
    notes: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[float] = mapped_column(Float, nullable=False, default=time.time)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(String(300), nullable=False)
    owner: Mapped[str] = mapped_column(String(64), nullable=False, default="me")
    status: Mapped[str] = mapped_column(String(8), nullable=False, default="todo")  # todo|doing|done
    due: Mapped[str | None] = mapped_column(String(10))  # YYYY-MM-DD
    reminded_at: Mapped[float | None] = mapped_column(Float)
    done_at: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[float] = mapped_column(Float, nullable=False, default=time.time)


class Message(Base):
    """WhatsApp messages to/from YOUR number only (kept locally for the coach's short-term memory)."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[float] = mapped_column(Float, nullable=False, default=time.time)
    direction: Mapped[str] = mapped_column(String(3), nullable=False)  # in|out
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="chat")  # chat|morning|night|nudge|...
    day: Mapped[str] = mapped_column(String(10), nullable=False)  # local YYYY-MM-DD (dedupes scheduled sends)
    body: Mapped[str] = mapped_column(String(4000), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False, default="sent")  # sent|failed|dry-run|received
    error: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (Index("ix_messages_kind_day", "kind", "day"),)


@lru_cache(maxsize=4)
def get_engine(db_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"timeout": 15})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _):  # WAL lets the agent write while the CLI/dashboard read
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

    Base.metadata.create_all(engine)
    _add_missing_columns(engine)
    return engine


def _add_missing_columns(engine: Engine) -> None:
    """Tiny forward-only migration: new nullable/defaulted columns get added to existing tables, so upgrading
    WorkPulse never needs a manual step or loses data."""
    from sqlalchemy import inspect, text
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name in existing or not (col.nullable or col.default is not None):
                    continue
                ddl = f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {col.type.compile(engine.dialect)}'
                if not col.nullable and col.default is not None and col.default.is_scalar:
                    arg = int(col.default.arg) if isinstance(col.default.arg, bool) else col.default.arg
                    ddl += f" NOT NULL DEFAULT {arg!r}"
                conn.execute(text(ddl))


@contextmanager
def session_scope(db_path: Path) -> Iterator[Session]:
    factory = sessionmaker(bind=get_engine(db_path), expire_on_commit=False)
    s = factory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def upsert_sessions(db_path: Path, records: Iterable[SessionRecord], source: str = "agent") -> int:
    """Insert or update sessions by id. Zero-length records mean "this session no longer exists"."""
    records = list(records)
    empty_ids = [r.id for r in records if r.end_ts <= r.start_ts]
    if empty_ids:
        with session_scope(db_path) as s:
            s.execute(delete(ActivitySession).where(ActivitySession.id.in_(empty_ids)))
    records = [r for r in records if r.end_ts > r.start_ts]
    rows = [
        dict(id=r.id, start_ts=r.start_ts, end_ts=r.end_ts, state=r.state, app=r.app,
             title=r.title, category=r.category, source=source, device="laptop", updated_at=time.time())
        for r in records
    ]
    with session_scope(db_path) as s:
        for i in range(0, len(rows), 500):  # stay under SQLite's bound-parameter limit
            stmt = sqlite_insert(ActivitySession).values(rows[i : i + 500])
            stmt = stmt.on_conflict_do_update(
                index_elements=["id"],
                set_={c: stmt.excluded[c] for c in ("start_ts", "end_ts", "state", "app", "title", "category", "updated_at")},
            )
            s.execute(stmt)
    return len(rows)


def sessions_between(db_path: Path, start_ts: float, end_ts: float) -> list[SessionRecord]:
    """All sessions overlapping [start_ts, end_ts), oldest first."""
    with session_scope(db_path) as s:
        q = (
            select(ActivitySession)
            .where(ActivitySession.end_ts > start_ts, ActivitySession.start_ts < end_ts)
            .order_by(ActivitySession.start_ts)
        )
        return [row.to_record() for row in s.scalars(q)]


def latest_session(db_path: Path) -> SessionRecord | None:
    with session_scope(db_path) as s:
        row = s.scalars(select(ActivitySession).order_by(ActivitySession.end_ts.desc()).limit(1)).first()
        return row.to_record() if row else None


def delete_sessions(db_path: Path, source: str | None = None) -> int:
    with session_scope(db_path) as s:
        q = delete(ActivitySession)
        if source:
            q = q.where(ActivitySession.source == source)
        return s.execute(q).rowcount or 0
