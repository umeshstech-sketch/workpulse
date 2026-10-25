"""Roadmap milestones (100 days / 6 months / 1 year): the coach suggests, you decide what to keep."""
from __future__ import annotations

import re

from workpulse.bot import coach
from workpulse.config import Config
from workpulse.core.db import Goal

LINE = re.compile(r"^\s*[-*•]?\s*(100d|6m|1y)\s*[:\-–]\s*(.+?)\s*$", re.I | re.M)


def template(goal_text: str) -> list[tuple[str, str]]:
    g = goal_text.strip().rstrip(".")
    return [
        ("100d", f"Define the smallest real version of “{g}” and ship a v0 people can see"),
        ("100d", f"Put 1–2 focused hours a day toward “{g}” (link a daily goal so WorkPulse tracks it)"),
        ("6m", f"Get outside proof for “{g}”: 10 real users, a hackathon demo, or a public write-up"),
        ("6m", "Find one mentor or teammate who's done this before and review progress with them monthly"),
        ("1y", f"“{g}” done and shown publicly, with a post on what you learned"),
    ]


def parse(text: str) -> list[tuple[str, str]]:
    return [(h.lower(), t.strip()[:300]) for h, t in LINE.findall(text or "") if t.strip()]


def suggest(cfg: Config, goal: Goal) -> tuple[list[tuple[str, str]], str]:
    """Returns ([(horizon, text)], source) where source is 'coach' (AI) or 'template'."""
    ai = coach.ask(cfg,
                   f"Suggest roadmap milestones for this long-term goal: “{goal.text}”"
                   f"{' (deadline ' + goal.deadline + ')' if goal.deadline else ''}. "
                   "Give 2 milestones for each horizon (100 days, 6 months, 1 year). Each must be concrete and "
                   "checkable (a thing shipped, a number reached, an event entered), fitting a CSE student who "
                   "codes, does hackathons and builds a startup. Output ONLY lines in exactly this format, no other text:\n"
                   "100d: <milestone>\n100d: <milestone>\n6m: <milestone>\n6m: <milestone>\n1y: <milestone>\n1y: <milestone>",
                   coach.build_facts(cfg))
    items = parse(ai) if ai else []
    if len(items) >= 3:
        return items[:9], "coach"
    return template(goal.text), "template"
