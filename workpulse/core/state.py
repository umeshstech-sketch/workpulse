"""The active / idle / away state machine and the sample -> session merger.

Pure logic (no OS calls), so it is fully unit-testable.
"""
from __future__ import annotations

from workpulse.core.models import Sample, SessionRecord, State


def classify(idle_seconds: float, locked: bool, idle_after: float, away_after: float) -> State:
    """active = input within `idle_after`; idle = up to `away_after`; away = longer, or screen locked."""
    if locked or idle_seconds >= away_after:
        return State.AWAY
    if idle_seconds >= idle_after:
        return State.IDLE
    return State.ACTIVE


class SessionTracker:
    """Turns a stream of samples into sessions (contiguous runs of the same state/app/category/title).

    Two subtleties:
    * Back-dating: "idle" is only detected 2 min after your last input, but you really stopped at the
      last input. On active->idle we end the active session at `ts - idle_seconds`, so active time
      isn't inflated by the idle threshold. Likewise idle->away is placed at `last_input + away_after`.
    * Gaps: if two samples are far apart (laptop slept, process was frozen), the gap is recorded as an
      `away` session instead of being smeared into whatever was running before.
    """

    def __init__(self, idle_after: float, away_after: float, gap_tolerance: float = 30.0,
                 keep_titles: bool = True) -> None:
        self.idle_after = idle_after
        self.away_after = away_after
        self.gap_tolerance = gap_tolerance
        self.keep_titles = keep_titles
        self.current: SessionRecord | None = None
        self.last_ts: float | None = None

    def _key(self, state: State, s: Sample) -> tuple:
        if state == State.AWAY:
            return (state.value, None, "Away", None)
        return (state.value, s.app, s.category, s.title if self.keep_titles else None)

    def _cur_key(self) -> tuple | None:
        c = self.current
        return None if c is None else (c.state, c.app, c.category, c.title)

    def _open(self, state: State, s: Sample, start: float) -> None:
        _, app, cat, title = self._key(state, s)
        self.current = SessionRecord(start_ts=start, end_ts=s.ts, state=state.value, app=app, title=title, category=cat)

    def feed(self, s: Sample) -> list[SessionRecord]:
        """Process one sample; return sessions that were closed by it (final, ready to persist)."""
        closed: list[SessionRecord] = []
        state = classify(s.idle_seconds, s.locked, self.idle_after, self.away_after)

        # Sleep / suspend / frozen process: close what was running at the last good sample, log the gap as away.
        if self.current is not None and self.last_ts is not None and s.ts - self.last_ts > self.gap_tolerance:
            self.current.end_ts = self.last_ts
            closed.append(self.current)
            gap = SessionRecord(start_ts=self.last_ts, end_ts=s.ts, state=State.AWAY.value, app=None, title=None, category="Away")
            closed.append(gap)
            self.current = None

        if self.current is None:
            self._open(state, s, s.ts)
        elif self._key(state, s) == self._cur_key():
            self.current.end_ts = s.ts
        else:
            prev = State(self.current.state)
            boundary = s.ts
            if s.locked:
                boundary = s.ts
            elif prev == State.ACTIVE and state != State.ACTIVE:
                boundary = s.ts - s.idle_seconds  # you actually stopped at your last input
            elif prev == State.IDLE and state == State.AWAY:
                boundary = s.ts - s.idle_seconds + self.away_after
            elif state == State.ACTIVE and prev != State.ACTIVE:
                boundary = s.ts - s.idle_seconds  # input happened somewhere since the last sample
            boundary = min(max(boundary, self.current.start_ts), s.ts)
            self.current.end_ts = boundary
            if self.current.duration > 0 or self.current.saved:
                closed.append(self.current)
            self._open(state, s, boundary)

        self.last_ts = s.ts
        return closed

    def close(self, ts: float | None = None) -> SessionRecord | None:
        """End the open session (pause / shutdown). `ts` lets pause cut at the exact moment it was requested."""
        cur, self.current = self.current, None
        self.last_ts = None
        if cur is None:
            return None
        if ts is not None:
            cur.end_ts = max(ts, cur.start_ts)
        return cur if cur.duration > 0 or cur.saved else None
