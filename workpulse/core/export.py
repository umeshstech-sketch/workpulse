"""CSV export shared by the CLI and the dashboard."""
from __future__ import annotations

import csv
from datetime import datetime
from typing import TextIO

from workpulse.core.models import SessionRecord

HEADER = ["start", "end", "duration_s", "state", "app", "category", "title"]


def write_csv(rows: list[SessionRecord], f: TextIO) -> None:
    w = csv.writer(f)
    w.writerow(HEADER)
    for s in rows:
        w.writerow([datetime.fromtimestamp(s.start_ts).isoformat(timespec="seconds"),
                    datetime.fromtimestamp(s.end_ts).isoformat(timespec="seconds"),
                    round(s.duration), s.state, s.app or "", s.category, s.title or ""])
