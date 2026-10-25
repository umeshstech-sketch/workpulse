"""Plain data types shared by the agent, stats and storage (no DB / OS dependencies)."""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from enum import Enum


class State(str, Enum):
    ACTIVE = "active"
    IDLE = "idle"
    AWAY = "away"


@dataclass(frozen=True)
class Sample:
    """One 5-second observation. Note: no keys, no text, no pixels — just these fields."""

    ts: float
    idle_seconds: float  # seconds since the last keyboard/mouse input (from the OS)
    locked: bool
    app: str | None  # process name, lowercase, no .exe
    title: str | None  # window title (may be dropped before storage)
    category: str


@dataclass
class SessionRecord:
    start_ts: float
    end_ts: float
    state: str
    app: str | None
    title: str | None
    category: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    # Set once the record has been written to storage. A saved session that later shrinks to zero
    # length (back-dating) must still be emitted so storage can drop its stale row.
    saved: bool = field(default=False, compare=False, repr=False)

    @property
    def duration(self) -> float:
        return max(0.0, self.end_ts - self.start_ts)
