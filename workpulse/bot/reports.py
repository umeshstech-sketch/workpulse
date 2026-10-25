"""Scheduled WhatsApp reports. The numbers are always computed (identical to CLI/dashboard); the coaching
lines come from the AI coach when available, else from templates."""
from __future__ import annotations

from datetime import datetime, timedelta

from workpulse.bot import coach
from workpulse.config import Config
from workpulse.core.insights import collaboration, compute_insights, top
from workpulse.core.service import day_with_comparison, goal_progress, range_stats
from workpulse.core.stats import fmt_dur
from workpulse.core.store import list_goals, list_tasks
from workpulse.core.trends import find_streaks, trend_sentence, week_trend

KINDS = ("morning", "midday", "night", "weekly")


def _hm(ts: float | None) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M") if ts else "--:--"


def morning(cfg: Config, now: datetime | None = None) -> str:
    now = now or datetime.now()
    y_day = now.date() - timedelta(days=1)
    y, ycmp = day_with_comparison(cfg, y_day)
    lines = ["☀️ *Good morning!*"]
    if y.active_s:
        top_cat = next(iter(y.per_category), "-")
        lines.append(f"Yesterday: {fmt_dur(y.active_s)} active, score *{y.focus_score}* (7-day avg {ycmp.avg7_score:.0f}), mostly {top_cat}.")
        if y.streak_category:
            lines.append(f"Best run: {fmt_dur(y.longest_streak_s)} of {y.streak_category} from {_hm(y.streak_start)} 🔥")
    else:
        lines.append("Yesterday: nothing tracked. New day, clean slate ✨")
    goals = [p for p in goal_progress(cfg, list_goals(cfg.db_path), now.date()) if p.goal.kind in ("daily", "weekly")]
    today_iso = now.date().isoformat()
    due = [t for t in list_tasks(cfg.db_path) if t.due and t.due <= today_iso]
    if goals:
        lines.append("\n🎯 *Goals*")
        lines += [f"- {p.text}" for p in goals[:4]]
    if due:
        lines.append("\n📝 *Due today*")
        lines += [f"- #{t.id} {'You' if t.owner == 'me' else t.owner}: {t.text}" for t in due[:4]]
    ai = coach.ask(cfg, "Write today's *Top 3 priorities* as 3 short bullets (each with a time slot or duration), "
                        "based on their goals, tasks due, yesterday and their best focus hours. Start with the line "
                        "'⚡ *Top 3 today*'. No greeting, no recap (already shown).", coach.build_facts(cfg, now))
    if ai:
        lines.append("\n" + ai)
    else:
        lines.append("\n⚡ *Top 3 today*")
        picks = [p.goal.text for p in goals[:2]] + [f"Task #{t.id}: {t.text}" for t in due[:2]]
        picks += [f"Task #{t.id}: {t.text}" for t in list_tasks(cfg.db_path) if t.owner == "me" and t.id not in {d.id for d in due}][:1]
        peak = next((i.text.split(":")[0].replace("Your focus peaks ", "") for i in top(compute_insights(cfg, now.date()), "best", 5)
                     if i.text.startswith("Your focus peaks")), None)
        picks.append(f"{cfg.scoring.daily_target_min / 60:.0f}h of deep work" + (f", ideally {peak} (your peak)" if peak else ""))
        picks.append("One 10-min walk away from screens 🚶")
        lines += [f"{i}. {p}" for i, p in enumerate(picks[:3], 1)]
    lines.append("\nReply *plan* anytime for a schedule 🗺️")
    return "\n".join(lines)


def midday(cfg: Config, now: datetime | None = None) -> str:
    now = now or datetime.now()
    st, cmp = day_with_comparison(cfg, now.date())
    if st.active_s == 0:
        return "🕐 Midday check: no laptop time yet today. Everything okay? Reply *plan* if you want a quick schedule."
    top_cat = next(iter(st.per_category), "-")
    msg = f"🕐 Midday check: *{fmt_dur(st.active_s)}* active, mostly {top_cat}. Score so far {st.focus_score}."
    left = cfg.scoring.daily_target_min * 60 - st.productive_s
    if left > 0:
        msg += f"\n{fmt_dur(left)} of productive time to hit today's target 🎯"
    else:
        msg += "\nTarget already hit. Anything now is bonus 🏆"
    if st.entertainment_s >= 45 * 60:
        msg += f"\n(Entertainment's at {fmt_dur(st.entertainment_s)}. Maybe park the tabs? 😉)"
    return msg


def night(cfg: Config, now: datetime | None = None) -> str:
    now = now or datetime.now()
    st, cmp = day_with_comparison(cfg, now.date())
    if st.active_s == 0:
        return "🌙 No laptop time tracked today. Rest days count too 😌 Reply *plan* tomorrow morning."
    vs = ""
    if cmp.yesterday and cmp.yesterday.active_s:
        d = st.active_s - cmp.yesterday.active_s
        vs = f" ({'+' if d >= 0 else '-'}{fmt_dur(abs(d))} vs yesterday)"
    apps = ", ".join(f"{cfg.alias(a)} {fmt_dur(v)}" for a, v in list(st.per_app.items())[:3])
    lines = [
        "🌙 *Daily report*",
        f"⏱️ {fmt_dur(st.active_s)} active{vs} · {fmt_dur(st.productive_s)} productive",
        f"🎯 Focus score *{st.focus_score}*/100 (7-day avg {cmp.avg7_score:.0f}" + (f", best {cmp.best.focus_score}" if cmp.best else "") + ")",
        f"💻 Top apps: {apps}",
    ]
    if st.streak_category:
        lines.append(f"🔥 Best moment: {fmt_dur(st.longest_streak_s)} of {st.streak_category} from {_hm(st.streak_start)}")
    from workpulse.core.phone import digital_day
    dd = digital_day(cfg, now.date())
    if dd["has_phone_data"]:
        top_app = dd["phone_top_apps"][0] if dd["phone_top_apps"] else None
        lines.append(f"📱 Phone {fmt_dur(dd['phone_s'])}" + (f" (top: {top_app['app']} {fmt_dur(top_app['seconds'])})" if top_app else "")
                     + f" → digital day {fmt_dur(dd['total_s'])}")
    ins = compute_insights(cfg, now.date())
    imp = top(ins, "improve", 1)
    ai = coach.ask(cfg, "Write the end-of-day coaching for today's report, below stats already shown. Exactly 3 parts, "
                        "each 1-2 lines: '👍 *Win:*' (what went best today), '🛠️ *Improve:*' (one specific fix with numbers), "
                        "'🗓️ *Tomorrow:*' (a concrete plan: first focus block with a time, plus the main goal/task).",
                   coach.build_facts(cfg, now))
    if ai:
        lines.append("\n" + ai)
    else:
        if imp:
            lines.append(f"\n🛠️ *Improve:* {imp[0].text}")
        nxt = [p.goal.text for p in goal_progress(cfg, list_goals(cfg.db_path), now.date()) if p.goal.kind == "daily"][:1]
        lines.append(f"🗓️ *Tomorrow:* start with a 50-min block on {nxt[0] if nxt else 'your top goal'} before opening chats.")
    lines.append("\nSleep well, champ 😴")
    return "\n".join(lines)


def weekly(cfg: Config, now: datetime | None = None) -> str:
    now = now or datetime.now()
    today = now.date()
    days = range_stats(cfg, today - timedelta(days=29), today)
    last7 = days[-7:]
    active = sum(d.active_s for d in last7)
    if active == 0:
        return "📅 Weekly review: nothing tracked this week. Next week is a fresh page 📖"
    prod = sum(d.productive_s for d in last7)
    scored = [d for d in last7 if d.active_s > 0]
    best = max(scored, key=lambda d: (d.focus_score, d.active_s))
    trend = week_trend(days[-14:])
    streaks = find_streaks(days, cfg.scoring.productive_categories)
    ins = compute_insights(cfg, today, days=7)
    lines = [
        "📅 *Weekly review*",
        f"⏱️ {fmt_dur(active)} active · {fmt_dur(prod)} productive · avg score {sum(d.focus_score for d in scored) / len(scored):.0f}",
        f"📈 {trend_sentence(trend)}",
        f"🏆 Best day: {best.day:%A} (score {best.focus_score}, {fmt_dur(best.active_s)})",
    ]
    if streaks:
        lines.append(f"🔥 {streaks[0].text}")
    from workpulse.core.phone import digital_range
    week_phone = sum(d["phone_s"] for d in digital_range(cfg, today, 7))
    if week_phone:
        lines.append(f"📱 Phone: {fmt_dur(week_phone)} this week ({fmt_dur(week_phone / 7)}/day)")
    collab = collaboration(cfg, today)
    if collab["meeting_s"] or collab["communication_s"]:
        lines.append(f"🤝 Collaboration: {collab['share']:.0%} of your week (meetings {fmt_dur(collab['meeting_s'])}, "
                     f"chat apps {fmt_dur(collab['communication_s'])})")
    wins, problems = top(ins, "best", 2), top(ins, "improve", 2)
    if wins:
        lines.append("\n✅ *Wins*")
        lines += [f"- {i.text}" for i in wins]
    if problems:
        lines.append("\n⚠️ *Problems*")
        lines += [f"- {i.text}" for i in problems]
    ai = coach.ask(cfg, "Propose ONE small, specific experiment for next week that targets their biggest problem "
                        "(what, when, how to measure it with WorkPulse). Start with '🧪 *Experiment:*'. Max 3 lines.",
                   coach.build_facts(cfg, now))
    if ai:
        lines.append("\n" + ai)
    elif problems:
        lines.append(f"\n🧪 *Experiment:* for the next 7 days, fix the first problem above with one rule "
                     f"(e.g. no YouTube until your first 50-min focus block is done). I'll show you the numbers next Sunday.")
    else:
        lines.append("\n🧪 *Experiment:* add one extra 50-min focus block on your weakest day. Let's see if the score moves.")
    return "\n".join(lines)


def build(cfg: Config, kind: str, now: datetime | None = None) -> str:
    return {"morning": morning, "midday": midday, "night": night, "weekly": weekly}[kind](cfg, now)
