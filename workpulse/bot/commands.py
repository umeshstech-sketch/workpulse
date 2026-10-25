"""WhatsApp chat commands. `handle(cfg, text)` returns the reply text; free text goes to the AI coach."""
from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta

from workpulse.agent import control
from workpulse.bot import coach
from workpulse.config import CATEGORIES, Config
from workpulse.core.db import latest_session
from workpulse.core.insights import compute_insights, top
from workpulse.core.service import day_with_comparison, goal_progress, range_stats
from workpulse.core.stats import fmt_dur
from workpulse.core.db import Goal
from workpulse.core.insights import collaboration
from workpulse.core.store import (GOAL_KINDS, add_goal, add_meeting, add_member, add_task, complete_goal,
                                  complete_task, find_member, list_goals, list_members, list_milestones, list_tasks,
                                  log_message, update_row)
from workpulse.core.trends import find_streaks, trend_sentence, week_trend

HELP = """*WorkPulse commands* 🤖
- *status*: am I tracked, what am I doing
- *today* / *week*: summaries
- *best* / *improve*: specific wins and fixes
- *plan*: a plan for the rest of today
- *goals* · *goal add* [daily|weekly|monthly|long] <text> [#coding] [2h] · *goal done* <n> · *goal progress* <n> <%>
- *roadmap*: your 100-day / 6-month / 1-year milestones
- *team* · *team add* <name> <role> · *task* @name <text> [by fri] · *tasks* · *task done* <n>
- *meeting* <minutes> <title> [@names]: log a team meeting
- *phone*: laptop + phone = your digital day
- *pause* / *resume*: privacy switch
Anything else → your AI coach 💬"""

CATEGORY_ALIASES = {"code": "Coding", "coding": "Coding", "dev": "Coding", "learn": "Learning/AI", "learning": "Learning/AI",
                    "ai": "Learning/AI", "ml": "Learning/AI", "study": "Learning/AI", "design": "Design",
                    "content": "Content Creation", "video": "Content Creation", "comms": "Communication",
                    "communication": "Communication", "browsing": "Browsing", "entertainment": "Entertainment"}
WEEKDAY_FULL = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


# ---- small parsers -----------------------------------------------------------------------------

def parse_duration_min(tok: str) -> float | None:
    m = re.fullmatch(r"(\d+(?:\.\d+)?)(h|hr|hrs|m|min|mins)", tok.lower())
    if not m:
        return None
    v = float(m.group(1))
    return v * 60 if m.group(2).startswith("h") else v


def parse_due(word: str, today: date | None = None) -> str | None:
    """'today', 'tomorrow', 'fri', '2026-10-25', '25/10' -> YYYY-MM-DD (next occurrence for weekdays)."""
    today = today or date.today()
    w = word.lower().strip(".,")
    if w in ("today", "tonight", "eod"):
        return today.isoformat()
    if w in ("tomorrow", "tmrw", "tmr"):
        return (today + timedelta(days=1)).isoformat()
    for i, full in enumerate(WEEKDAY_FULL):
        if len(w) >= 3 and full.startswith(w):  # "fri", "frid", "friday"
            ahead = (i - today.weekday()) % 7 or 7  # next occurrence, never today
            return (today + timedelta(days=ahead)).isoformat()
    try:
        return date.fromisoformat(w).isoformat()
    except ValueError:
        pass
    m = re.fullmatch(r"(\d{1,2})[/-](\d{1,2})", w)  # day/month (Indian format)
    if m:
        try:
            d = date(today.year, int(m.group(2)), int(m.group(1)))
            return (d if d >= today else d.replace(year=today.year + 1)).isoformat()
        except ValueError:
            return None
    return None


def _cat(tok: str) -> str | None:
    t = tok.lstrip("#").lower()
    if t in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[t]
    for c in CATEGORIES:
        if c.lower().startswith(t):
            return c
    return None


# ---- commands ----------------------------------------------------------------------------------

def cmd_status(cfg: Config) -> str:
    if control.is_paused(cfg):
        return "⏸️ Tracking is *paused*. Nothing is being recorded. Send *resume* when you're ready."
    if not control.running_pid(cfg):
        return "😶 The tracker isn't running on your laptop. Run `workpulse start` there."
    s = latest_session(cfg.db_path)
    if not s or time.time() - s.end_ts > 120:
        return "🟢 Tracking is on, but nothing recent recorded. Is the laptop asleep? 💤"
    st, _ = day_with_comparison(cfg, date.today())
    if s.state == "away":
        now = "you're away from the laptop"
    elif s.state == "idle":
        now = f"idle on {cfg.alias(s.app)}"
    else:
        now = f"*{s.category}* in {cfg.alias(s.app)} for {fmt_dur(s.duration)}"
    return f"🟢 Tracking is on. Right now: {now}.\nToday: {fmt_dur(st.active_s)} active, focus score {st.focus_score}."


def cmd_today(cfg: Config) -> str:
    st, cmp = day_with_comparison(cfg, date.today())
    if st.active_s == 0:
        return "📭 Nothing tracked yet today. Fresh start! ✨"
    vs = ""
    if cmp.yesterday and cmp.yesterday.active_s:
        d = st.active_s - cmp.yesterday.active_s
        vs = f" ({'+' if d >= 0 else '-'}{fmt_dur(abs(d))} vs yesterday)"
    cats = ", ".join(f"{k} {fmt_dur(v)}" for k, v in list(st.per_category.items())[:4])
    apps = ", ".join(f"{cfg.alias(a)} {fmt_dur(v)}" for a, v in list(st.per_app.items())[:3])
    streak = f"\n🔥 Longest focus: {fmt_dur(st.longest_streak_s)} of {st.streak_category}" if st.streak_category else ""
    return (f"📊 *Today*: {fmt_dur(st.active_s)} active{vs}\n🎯 Focus score *{st.focus_score}*/100 (7-day avg {cmp.avg7_score:.0f})"
            f"{streak}\n🗂️ {cats}\n💻 {apps}\n☕ {st.breaks} breaks")


def cmd_week(cfg: Config) -> str:
    today = date.today()
    days = range_stats(cfg, today - timedelta(days=29), today)
    last7 = days[-7:]
    active = sum(d.active_s for d in last7)
    if active == 0:
        return "📭 No tracked time in the last 7 days yet."
    prod = sum(d.productive_s for d in last7)
    scored = [d for d in last7 if d.active_s > 0]
    best = max(scored, key=lambda d: (d.focus_score, d.active_s))
    trend = week_trend(days[-15:-1])
    streaks = find_streaks(days, cfg.scoring.productive_categories)
    bars = " ".join(f"{d.day:%a}:{d.active_s / 3600:.0f}h" for d in last7)
    out = (f"📅 *Last 7 days*: {fmt_dur(active)} active, {fmt_dur(prod)} productive\n"
           f"🎯 Avg focus {sum(d.focus_score for d in scored) / len(scored):.0f} · best {best.day:%a} ({best.focus_score})\n"
           f"📈 {trend_sentence(trend)}\n{bars}")
    if streaks:
        out += f"\n🔥 {streaks[0].text}"
    return out


def cmd_insights(cfg: Config, kind: str) -> str:
    items = top(compute_insights(cfg), kind, 3)
    if not items:
        return ("Not enough data yet for solid patterns. Give me a few days of tracking 📈" if kind == "best"
                else "Nothing obvious to fix yet. Either you're great or I need more data 😄")
    head = "🏆 *What you're doing best*" if kind == "best" else "🛠️ *What to improve*"
    return head + "\n" + "\n".join(f"- {i.text}" for i in items)


def cmd_goals(cfg: Config) -> str:
    progress = goal_progress(cfg, list_goals(cfg.db_path))
    if not progress:
        return "🎯 No goals yet. Try: *goal add daily 2h #coding Ship the API*"
    lines = ["🎯 *Your goals*"]
    for p in progress:
        mark = "✅" if p.pct is not None and p.pct >= 100 else "▫️"
        lines.append(f"{mark} #{p.goal.id} _{p.goal.kind}_ {p.text}")
    return "\n".join(lines) + "\nDone with one? *goal done <n>*"


def cmd_goal_add(cfg: Config, rest: str) -> str:
    toks = rest.split()
    kind, category, target = "daily", None, None
    if toks and toks[0].lower() in GOAL_KINDS + ("long", "longterm"):
        k = toks.pop(0).lower()
        kind = "long-term" if k.startswith("long") else k
    words = []
    for t in toks:
        if t.startswith("#") and _cat(t):
            category = _cat(t)
        elif target is None and parse_duration_min(t):
            target = parse_duration_min(t)
        else:
            words.append(t)
    text = " ".join(words).strip()
    if not text:
        return "Tell me the goal 🙂 e.g. *goal add weekly 10h #learning Finish the ML course*"
    if target and not category:
        category = "Coding" if re.search(r"\b(code|coding|build|ship|api)\b", text, re.I) else None
    g = add_goal(cfg.db_path, text, kind=kind, category=category, target_min=target)
    link = f" · counts {g.category} time" + (f" toward {fmt_dur(target * 60)}" if target else "") if g.category else ""
    return f"🎯 Goal #{g.id} added ({kind}){link}: {g.text}\nYou've got this 💪"


def cmd_goal_done(cfg: Config, rest: str) -> str:
    m = re.search(r"\d+", rest)
    if not m:
        return "Which one? e.g. *goal done 2* (see *goals*)"
    g = complete_goal(cfg.db_path, int(m.group()))
    if not g:
        return f"I can't find goal #{m.group()} 🤔 Send *goals* to see the list."
    return f"✅ Goal #{g.id} done: {g.text}\nThat's a win. Frame it 🖼️🎉"


def cmd_goal_progress(cfg: Config, rest: str) -> str:
    m = re.match(r"\s*#?(\d+)\s+(\d{1,3})\s*%?\s*$", rest)
    if not m or int(m.group(2)) > 100:
        return "Use *goal progress <n> <0-100>*, e.g. *goal progress 2 40*"
    g = update_row(cfg.db_path, Goal, int(m.group(1)), {"manual_pct": float(m.group(2))}, {"manual_pct"})
    if g is None:
        return f"I can't find goal #{m.group(1)} 🤔"
    note = " (this goal is measured from tracked time, so I'll keep showing that)" if g.category else ""
    return f"📍 Goal #{g.id} at *{int(m.group(2))}%*: {g.text}{note}"


def cmd_roadmap(cfg: Config) -> str:
    ms = [m for m in list_milestones(cfg.db_path) if not m.done]
    if not ms:
        return ("🗺️ No roadmap yet. Add a long-term goal (*goal add long Launch my startup*), then open the "
                "dashboard's Goals tab and hit *Suggest milestones*.")
    lines = ["🗺️ *Your roadmap*"]
    for h, label in (("100d", "Next 100 days"), ("6m", "6 months"), ("1y", "1 year")):
        items = [m for m in ms if m.horizon == h]
        if items:
            lines.append(f"\n*{label}*")
            lines += [f"▫️ {m.text}" + (f" _(by {date.fromisoformat(m.target_date):%d %b %Y})_" if m.target_date else "")
                      for m in items[:4]]
    return "\n".join(lines)


def cmd_meeting(cfg: Config, rest: str) -> str:
    toks = rest.split()
    if not toks:
        return "Log it like: *meeting 45 standup @Riya @Arjun*"
    minutes = parse_duration_min(toks[0]) or (float(toks[0]) if re.fullmatch(r"\d+(\.\d+)?", toks[0]) else None)
    if not minutes:
        return "Start with the length: *meeting 45 standup @Riya* (or *meeting 1h pitch prep*)"
    names = [t[1:] for t in toks[1:] if t.startswith("@") and len(t) > 1]
    title = " ".join(t for t in toks[1:] if not t.startswith("@")) or "Team meeting"
    attendees = []
    for n in names:
        member = find_member(cfg.db_path, n) or add_member(cfg.db_path, n)[0]
        attendees.append(member.name)
    add_meeting(cfg.db_path, title, minutes, attendees)
    share = collaboration(cfg)["share"]
    who = f" with {', '.join(attendees)}" if attendees else ""
    return f"🤝 Logged *{title}* ({fmt_dur(minutes * 60)}){who}.\nCollaboration this week: {share:.0%} of your time."


def cmd_phone(cfg: Config) -> str:
    from workpulse.core.phone import digital_day
    dd = digital_day(cfg, date.today())
    if not dd["has_phone_data"]:
        y = digital_day(cfg, date.today() - timedelta(days=1))
        if not y["has_phone_data"]:
            return ("📱 No phone screen time yet. Add it from the dashboard (Digital day tab: screenshot, CSV or "
                    "manual), or let Tasker/Shortcuts post it. See README → Phone.")
        dd, label = y, "Yesterday"
    else:
        label = "Today"
    apps = ", ".join(f"{a['app']} {fmt_dur(a['seconds'])}" for a in dd["phone_top_apps"][:3])
    lines = [f"📱 *{label}'s digital day*: {fmt_dur(dd['total_s'])}",
             f"💻 Laptop {fmt_dur(dd['laptop_active_s'])} · 📱 Phone {fmt_dur(dd['phone_s'])} ({dd['phone_share']:.0%})"]
    if apps:
        lines.append(f"Top phone apps: {apps}")
    if dd["pickups"]:
        lines.append(f"🔓 {dd['pickups']} pickups")
    if dd["phone_entertainment_s"] >= 3600:
        lines.append(f"🎮 {fmt_dur(dd['phone_entertainment_s'])} of phone Entertainment. Phone in another room for the next focus block?")
    return "\n".join(lines)


def cmd_team(cfg: Config) -> str:
    members = list_members(cfg.db_path)
    if not members:
        return "👥 No teammates yet. Try: *team add Riya ML-engineer*"
    tasks = list_tasks(cfg.db_path)
    lines = ["👥 *Your team*"]
    for m in members:
        n = sum(1 for t in tasks if t.owner.lower() == m.name.lower())
        lines.append(f"- *{m.name}*{' · ' + m.role if m.role else ''}{f' · {n} open task(s)' if n else ''}")
    mine = sum(1 for t in tasks if t.owner == "me")
    if mine:
        lines.append(f"- *You* · {mine} open task(s)")
    return "\n".join(lines)


def cmd_team_add(cfg: Config, rest: str) -> str:
    parts = rest.split(maxsplit=1)
    if not parts:
        return "Who? e.g. *team add Arjun cofounder*"
    name, role = parts[0].lstrip("@"), (parts[1] if len(parts) > 1 else None)
    m, created = add_member(cfg.db_path, name, role)
    return f"👥 {'Added' if created else 'Updated'} *{m.name}*{' as ' + m.role if m.role else ''}. Assign work with *task @{m.name} <text>*"


def cmd_task(cfg: Config, rest: str) -> str:
    m = re.match(r"@(\S+)\s+(.+)", rest.strip())
    owner, text = ("me", rest.strip()) if not m else (m.group(1), m.group(2))
    if not text:
        return "What's the task? e.g. *task @Riya make the pitch deck by fri*"
    due = None
    dm = re.search(r"\s+(?:by|due)\s+(\S+)\s*$", text, re.I)
    if dm and (parsed := parse_due(dm.group(1))):
        due, text = parsed, text[: dm.start()]
    if owner.lower() != "me":
        member = find_member(cfg.db_path, owner)
        if member is None:
            member, _ = add_member(cfg.db_path, owner)
        owner = member.name
    t = add_task(cfg.db_path, text, owner=owner, due=due)
    when = f" · due {date.fromisoformat(due):%a %d %b}" if due else ""
    who = "you" if owner == "me" else f"*{owner}*"
    return f"📝 Task #{t.id} for {who}: {t.text}{when}\nI'll remind you before it's due ⏰"


def cmd_tasks(cfg: Config) -> str:
    tasks = list_tasks(cfg.db_path)
    if not tasks:
        return "📝 No open tasks. Add one: *task @name <text> by fri*"
    today = date.today().isoformat()
    lines = ["📝 *Open tasks*"]
    for t in tasks[:15]:
        flag = "🔴" if t.due and t.due < today else ("🟠" if t.due == today else "▫️")
        due = f" · {date.fromisoformat(t.due):%a %d %b}" if t.due else ""
        lines.append(f"{flag} #{t.id} {'You' if t.owner == 'me' else t.owner}: {t.text}{due}")
    return "\n".join(lines) + "\nFinished one? *task done <n>*"


def cmd_task_done(cfg: Config, rest: str) -> str:
    m = re.search(r"\d+", rest)
    if not m:
        return "Which one? e.g. *task done 3*"
    t = complete_task(cfg.db_path, int(m.group()))
    return f"✅ Task #{t.id} done: {t.text} 🙌" if t else f"I can't find open task #{m.group()} 🤔"


def cmd_pause(cfg: Config) -> str:
    control.pause(cfg)
    return "⏸️ Paused. Nothing is recorded until you send *resume*. 🔒"


def cmd_resume(cfg: Config) -> str:
    control.resume(cfg)
    extra = "" if control.running_pid(cfg) else "\n(Heads up: the tracker isn't running. Run `workpulse start` on the laptop.)"
    return "▶️ Resumed. Back to work, legend 🚀" + extra


def plan_fallback(cfg: Config, now: datetime | None = None) -> str:
    now = now or datetime.now()
    st, _ = day_with_comparison(cfg, now.date())
    left_min = max(0, cfg.scoring.daily_target_min - st.productive_s / 60)
    hours_left = max(0.0, 23 - now.hour - now.minute / 60)
    goals = [p for p in goal_progress(cfg, list_goals(cfg.db_path)) if p.goal.kind == "daily"]
    tasks = [t for t in list_tasks(cfg.db_path) if t.owner == "me"][:2]
    lines = [f"🗺️ *Plan for the rest of today* ({hours_left:.0f}h left)"]
    if left_min > 0:
        blocks = max(1, round(left_min / 50))
        lines.append(f"- {blocks} × 50-min focus block{'s' if blocks > 1 else ''} to hit your {cfg.scoring.daily_target_min:.0f}-min target ({fmt_dur(left_min * 60)} to go)")
    else:
        lines.append("- Target already hit 🎉 One light block, then rest")
    for p in goals[:2]:
        lines.append(f"- Goal: {p.text}")
    for t in tasks:
        lines.append(f"- Task #{t.id}: {t.text}")
    lines.append("- 10-min break between blocks, phone in another room 📵")
    return "\n".join(lines)


def cmd_plan(cfg: Config) -> str:
    facts = coach.build_facts(cfg)
    ai = coach.ask(cfg, "Write a realistic plan for the REST of today (from the current time in the facts). "
                        "3-5 time-boxed bullets with start times, using their goals/tasks and remaining productive target. "
                        "Put their strongest focus window to work if it's still ahead. End with one short motivating line.", facts)
    return ai or plan_fallback(cfg)


def cmd_freetext(cfg: Config, text: str, history: list[tuple[str, str]]) -> str:
    ai = coach.ask(cfg, f"Their message: {text}\n\nReply as their coach. Keep it short.", coach.build_facts(cfg), history)
    return ai or ("🤔 I didn't catch that as a command. Send *help* for the list.\n"
                  "_(The free-chat coach needs ANTHROPIC_API_KEY in .env on your laptop.)_")


SOURCE_STATUS = {"whatsapp": "received", "phone": "app"}  # anything else (dashboard, cli) -> "local"


def handle(cfg: Config, text: str, source: str = "whatsapp") -> str:
    """Route one inbound message (WhatsApp, a paired phone, the laptop dashboard or the CLI) and log it locally.
    The reply is logged by whoever delivers it (the Messenger for WhatsApp)."""
    raw = (text or "").strip()
    history = coach.chat_history(cfg)
    log_message(cfg.db_path, "in", raw, kind="chat", status=SOURCE_STATUS.get(source, "local"))
    low = raw.lower()
    first, _, rest = raw.partition(" ")
    f = first.lower()
    if low in ("help", "hi", "hello", "hey", "menu", "?", "commands"):
        return HELP
    if low == "status":
        return cmd_status(cfg)
    if low == "today":
        return cmd_today(cfg)
    if low == "week":
        return cmd_week(cfg)
    if low == "best":
        return cmd_insights(cfg, "best")
    if low == "improve":
        return cmd_insights(cfg, "improve")
    if low == "plan":
        return cmd_plan(cfg)
    if low == "goals":
        return cmd_goals(cfg)
    if low == "tasks":
        return cmd_tasks(cfg)
    if low == "team":
        return cmd_team(cfg)
    if low == "roadmap":
        return cmd_roadmap(cfg)
    if low in ("phone", "digital", "screen time"):
        return cmd_phone(cfg)
    if low in ("pause", "stop tracking"):
        return cmd_pause(cfg)
    if low in ("resume", "start tracking"):
        return cmd_resume(cfg)
    if f == "goal":
        sub, _, arg = rest.partition(" ")
        if sub.lower() == "add":
            return cmd_goal_add(cfg, arg)
        if sub.lower() in ("done", "complete"):
            return cmd_goal_done(cfg, arg)
        if sub.lower() == "progress":
            return cmd_goal_progress(cfg, arg)
        return "Try *goal add <text>* or *goal done <n>* 🎯"
    if f == "team" and rest.lower().startswith("add"):
        return cmd_team_add(cfg, rest[3:].strip())
    if f in ("meeting", "meet"):
        return cmd_meeting(cfg, rest)
    if f == "task":
        if rest.lower().startswith("done"):
            return cmd_task_done(cfg, rest[4:])
        return cmd_task(cfg, rest)
    return cmd_freetext(cfg, raw, history)
