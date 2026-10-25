# Dashboard, focus score & goals

[← Back to README](../README.md)

## Tabs

| Tab | What's there |
|---|---|
| **Today** | Live status + pause button, KPI tiles (active, focus score, longest focus, productive, breaks, first→last) with deltas vs yesterday / 7-day avg / best day, a Gantt-style timeline of the day (hover any block for app + title), category donut with a value table, top apps, focus-score breakdown. ‹ › or the date picker browse other days. |
| **Week** | Active time per day stacked by category, focus score per day, week-over-week trend (full days only, so a half-finished today doesn't look like a slump), live streaks ("6 days in a row with 4h+ of Coding"), best day, a per-category table. |
| **Digital day** | Laptop + phone together: total digital day, laptop active vs phone screen time, pickups, a 7-day stacked chart, categories side by side (laptop / phone / total), phone top apps, and every way to add phone data (screenshot, file, manual, automatic). |
| **Goals** | Daily / weekly / monthly / long-term goals with deadline and progress. Link a category + target (e.g. 2h of Coding a day) and tracked time fills the progress bar automatically; for goals time can't measure ("launch my startup") drag a progress slider. Below: the **roadmap** (next 100 days / 6 months / 1 year). Hit **✨ Suggest milestones** on a long-term goal and the coach proposes concrete steps; add the ones you like and tick them off. |
| **Team** | People (role, contact), a task board (To do → Doing → Done, overdue in red, owner + due date), a meeting log, and **collaboration share**: how much of your week went to meetings + chat apps. |
| **Insights** | "Doing best" / "improve" with real numbers, when you focus (productive vs entertainment by hour), productive time by weekday, where browsing/entertainment time goes (YouTube, Instagram…), and a 30-day consistency heatmap. |
| **Coach** | The bot conversation: WhatsApp chats, reports, nudges and reminders (including dry-run ones), and a chat box that talks to the same brain. Messages typed here stay on the laptop. |
| **Settings** | Idle/away thresholds, title capture, never-log apps/keywords, scoring targets, productive categories, app → category mapping, CSV export, delete all data. Saved changes reach the running tracker within ~10 s, no restart. |

Dark by default (◐ toggles light). Works at phone width too, but it only listens on `127.0.0.1`, so it's reachable from this laptop only. Charts load Chart.js from a CDN; offline, the numbers and tables still work.

Tip: add `?date=2026-10-20` to the dashboard URL to open a specific day.

## Focus score (0–100)

| Part | Points | Formula |
|---|---|---|
| Deep work | 40 | `40 × min(productive_min / 240, 1)` |
| Focus ratio | 25 | `25 × productive_min / active_min` |
| Longest streak | 20 | `20 × min(streak_min / 90, 1)` |
| Low distraction | 15 | `15 × (1 − min(2 × entertainment_min / active_min, 1))` |

- *Productive* = Coding, Learning/AI, Design, Content Creation (configurable).
- *Longest focus streak* = longest run of active time in **one** productive category, where interruptions ≤ 3 min don't break it (the interruption itself isn't counted).
- *Breaks* = gaps of ≥ 5 min between active time.
- Targets (240 min, 90 min, 3 min, 5 min) are in `config.yaml → scoring`.

## How goals count tracked time

| Goal type | Progress counts tracked time in its category… |
|---|---|
| daily | today |
| weekly | since Monday |
| monthly | since the 1st |
| long-term | since you added it (or use the manual progress slider when it isn't about laptop time) |

**Collaboration share** = (logged meetings + Communication-app time) ÷ (laptop active time + logged meetings), over the last 7 days. Meetings are added on top because calls and in-person meetings often happen away from the laptop.
