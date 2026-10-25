"""Realistic fake history so you can see the CLI/dashboard/reports before you have real data.

Demo rows are tagged source='demo' and can be removed with `workpulse demo clear`.
"""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta

from workpulse.core.models import SessionRecord

# (category, app, [titles]) — browser entries rely on titles, like real data.
ACTIVITIES = {
    "Coding": [("code", ["main.py - workpulse - Visual Studio Code", "model.ipynb - hackathon - Visual Studio Code"]),
               ("windowsterminal", ["PowerShell", "python train.py"]),
               ("chrome", ["openai/whisper · GitHub - Google Chrome", "python - Stack Overflow - Google Chrome"])],
    "Learning/AI": [("chrome", ["Neural Networks Explained - YouTube - Google Chrome", "Kaggle: Titanic - Google Chrome",
                                "Claude - Google Chrome", "Andrew Ng ML course - Coursera - Google Chrome"]),
                    ("obsidian", ["ML notes - Obsidian"])],
    "Design": [("figma", ["Startup landing page – Figma"])],
    "Content Creation": [("capcut", ["CapCut - reel_03"]), ("obs64", ["OBS 30 - Profile: Reels"])],
    "Communication": [("whatsapp.root", ["WhatsApp"]), ("discord", ["#hackathon-team - Discord"]),
                      ("chrome", ["Inbox (3) - Gmail - Google Chrome"])],
    "Browsing": [("chrome", ["Google - Google Chrome", "Amazon.in - Google Chrome"])],
    "Entertainment": [("chrome", ["lofi beats - YouTube - Google Chrome", "Instagram - Google Chrome", "Reddit - Google Chrome"]),
                      ("spotify", ["Spotify Premium"])],
}

# Relative weight of each category by part of day: the demo user peaks 6-9 PM and drifts to YouTube after lunch.
WEIGHTS = {
    "morning":   {"Coding": 3, "Learning/AI": 4, "Communication": 2, "Browsing": 1, "Entertainment": 1, "Design": 1},
    "afternoon": {"Coding": 2, "Learning/AI": 2, "Communication": 2, "Browsing": 2, "Entertainment": 4, "Content Creation": 1},
    "evening":   {"Coding": 6, "Learning/AI": 2, "Design": 1, "Content Creation": 2, "Communication": 1, "Entertainment": 1},
    "night":     {"Coding": 2, "Entertainment": 3, "Communication": 2, "Content Creation": 1},
}


def _part(hour: float) -> str:
    return "morning" if hour < 13 else "afternoon" if hour < 17 else "evening" if hour < 21.5 else "night"


def generate(days: int = 14, until: datetime | None = None, seed: int = 42) -> list[SessionRecord]:
    rng = random.Random(seed)
    until = until or datetime.now()
    out: list[SessionRecord] = []
    for back in range(days - 1, -1, -1):
        d: date = until.date() - timedelta(days=back)
        weekend = d.weekday() >= 5
        t = datetime.combine(d, time(hour=9 if not weekend else 11)) + timedelta(minutes=rng.randint(0, 70))
        end_of_day = datetime.combine(d, time(23, 15)) - timedelta(minutes=rng.randint(0, 90))
        lazy = rng.random() < 0.15  # some days are just worse, like real life
        while t < end_of_day and t < until:
            w = WEIGHTS[_part(t.hour + t.minute / 60)]
            if lazy:
                w = {**w, "Entertainment": w.get("Entertainment", 0) + 5}
            cat = rng.choices(list(w), weights=list(w.values()))[0]
            app, titles = rng.choice(ACTIVITIES[cat])
            minutes = rng.uniform(20, 95) if cat in ("Coding", "Learning/AI", "Design", "Content Creation") else rng.uniform(5, 35)
            # Split a block into a few title switches, sometimes with short (<3 min) interruptions.
            block_end = min(t + timedelta(minutes=minutes), until)
            while t < block_end:
                seg = min(t + timedelta(minutes=rng.uniform(6, 25)), block_end)
                out.append(SessionRecord(start_ts=t.timestamp(), end_ts=seg.timestamp(), state="active",
                                         app=app, title=rng.choice(titles), category=cat))
                t = seg
                if rng.random() < 0.15 and t < block_end:
                    gap = t + timedelta(minutes=rng.uniform(0.5, 2.5))
                    out.append(SessionRecord(start_ts=t.timestamp(), end_ts=gap.timestamp(), state="idle",
                                             app=app, title=None, category=cat))
                    t = gap
            if t >= until:
                break
            # Break between blocks: short idle, sometimes a long away (meals, classes, gym).
            r = rng.random()
            brk = rng.uniform(2, 9) if r < 0.6 else rng.uniform(15, 50) if r < 0.92 else rng.uniform(60, 120)
            b_end = min(t + timedelta(minutes=brk), until)
            state = "idle" if brk < 10 else "away"
            out.append(SessionRecord(start_ts=t.timestamp(), end_ts=b_end.timestamp(), state=state,
                                     app=app if state == "idle" else None, title=None,
                                     category=cat if state == "idle" else "Away"))
            t = b_end
    return out


PHONE_APPS = [("Instagram", "com.instagram.android", 25, 80), ("WhatsApp", "com.whatsapp", 20, 60),
              ("YouTube", "com.google.android.youtube", 15, 70), ("Chrome", "com.android.chrome", 10, 35),
              ("Spotify", "com.spotify.music", 5, 40), ("Duolingo", "com.duolingo", 0, 15),
              ("ChatGPT", "com.openai.chatgpt", 0, 20), ("Discord", "com.discord", 0, 25)]


def generate_phone(days: int = 14, until: datetime | None = None, seed: int = 7):
    """Daily phone totals per app (phones don't give timelines). Returns PhoneDayData for core.phone.save_day."""
    from workpulse.core.phone import PhoneAppUsage, PhoneDayData
    rng = random.Random(seed)
    until = until or datetime.now()
    out = []
    for back in range(days - 1, -1, -1):
        d = until.date() - timedelta(days=back)
        scale = 1.0 if back else min(1.0, max(0.05, (until.hour - 7) / 16))  # today is only partly over
        weekend = 1.3 if d.weekday() >= 5 else 1.0
        apps = [PhoneAppUsage(name, rng.uniform(lo, hi) * 60 * scale * weekend, pkg) for name, pkg, lo, hi in PHONE_APPS]
        apps = [a for a in apps if a.seconds >= 60]
        if not apps:
            continue
        out.append(PhoneDayData(day=d.isoformat(), device="phone", pickups=int(rng.uniform(60, 130) * scale),
                                total_s=sum(a.seconds for a in apps) * rng.uniform(1.05, 1.15), apps=apps))
    return out


def seed_planning(cfg) -> None:
    """Sample goals, roadmap, team, tasks and meetings for the DEMO database (replaces any there)."""
    from sqlalchemy import delete

    from workpulse.core.db import Goal, Meeting, Milestone, Task, TeamMember, session_scope
    from workpulse.core.store import (add_goal, add_meeting, add_member, add_milestone, add_task, update_row)
    with session_scope(cfg.db_path) as s:
        for model in (Goal, Milestone, TeamMember, Task, Meeting):
            s.execute(delete(model))
    today = date.today()
    add_goal(cfg.db_path, "Code every day", "daily", "Coding", 120)
    add_goal(cfg.db_path, "Finish the ML course module", "weekly", "Learning/AI", 600)
    startup = add_goal(cfg.db_path, "Launch my startup", "long-term", deadline=(today + timedelta(days=300)).isoformat())
    model = add_goal(cfg.db_path, "Build my first AI model", "long-term")
    update_row(cfg.db_path, Goal, startup.id, {"manual_pct": 20}, {"manual_pct"})
    update_row(cfg.db_path, Goal, model.id, {"manual_pct": 35}, {"manual_pct"})
    for horizon, text, gid, src in [
        ("100d", "Ship a landing page + waitlist with 50 sign-ups", startup.id, "coach"),
        ("6m", "First 10 paying users", startup.id, "coach"),
        ("1y", "Pitch at a pre-seed demo day", startup.id, "me"),
        ("100d", "Train a CNN on CIFAR-10 to 85%+ accuracy", model.id, "coach"),
        ("6m", "Publish a Kaggle notebook with 50 upvotes", model.id, "coach"),
        ("1y", "Ship a model behind a public API", model.id, "me"),
    ]:
        m = add_milestone(cfg.db_path, horizon, text, gid, src)
        if text.startswith("Train a CNN"):
            update_row(cfg.db_path, Milestone, m.id, {"done": True}, {"done"})
    add_member(cfg.db_path, "Riya", "ML engineer")
    add_member(cfg.db_path, "Arjun", "Cofounder", "arjun@example.com")
    add_member(cfg.db_path, "Sana", "Designer")
    add_task(cfg.db_path, "Pitch deck v2", "Arjun", (today + timedelta(days=1)).isoformat())
    add_task(cfg.db_path, "Landing page copy", "Sana", (today - timedelta(days=1)).isoformat())
    add_task(cfg.db_path, "Record the demo video", "me", (today + timedelta(days=3)).isoformat())
    doing = add_task(cfg.db_path, "Fix the training script", "me")
    done = add_task(cfg.db_path, "Book hackathon venue", "Riya")
    update_row(cfg.db_path, Task, doing.id, {"status": "doing"}, {"status"})
    update_row(cfg.db_path, Task, done.id, {"status": "done"}, {"status"})
    now = datetime.now()
    add_meeting(cfg.db_path, "Hackathon standup", 40, ["Riya", "Arjun"], (now - timedelta(days=1)).timestamp())
    add_meeting(cfg.db_path, "Pitch practice", 60, ["Arjun"], (now - timedelta(days=3)).timestamp())
