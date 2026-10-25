# Acceptance checks

[← Back to README](../README.md)

The checks from the original brief, how each was verified, and the result. "Live" means run on the real Windows 11 laptop, not just in tests.

| # | Check | How it was verified | Result |
|---|---|---|---|
| 1 | Agent runs 10+ minutes and flips active / idle / away correctly | **Live:** a 10-minute run with normal thresholds; the log shows active → idle → active transitions, and active time was back-dated to the last real input. **Live stress test:** 3 minutes with short thresholds (idle 20 s / away 60 s) showed all three states. Plus unit tests for every transition. | ✅ |
| 1b | Survives sleep / resume | **Live, simulated:** the agent process was frozen for 50 s (what sleep looks like to it); the gap was recorded as `away` and tracking resumed. Unit tests cover the gap logic. A real lid-close sleep wasn't tested. | ✅ (simulated) |
| 2 | Pausing stops all recording immediately | **Live:** `workpulse pause` cut the session at the exact second, and no new data appeared for 20 s; `resume` started recording again. Also verified from the dashboard's Pause button (agent paused within a second) and with the WhatsApp `pause` command (tests). | ✅ |
| 3 | Dashboard numbers match the CLI | **Live:** API vs CLI for the same day matched to the decimal (active 427.57 s, productive 397.33 s, score 40, breaks 1, streak 185.85 s). An automated test asserts they're equal, and both call the same `core/stats.py`. | ✅ |
| 4 | A test WhatsApp message arrives; `status`, `today`, `goal add` work | Commands are verified by tests that post **signed** Twilio webhooks from your number (and that strangers / bad signatures are rejected), plus live runs through the CLI and the dashboard's Coach tab. **Real delivery to your phone needs your Twilio sandbox credentials in `.env`**: run `.\workpulse wa test` after following [whatsapp.md](whatsapp.md). | ⏳ waiting on your Twilio setup |
| 5 | No keystrokes or screenshots stored anywhere | `grep` over `workpulse/` and `dashboard/` finds no keyboard hooks, key-state calls or screen capture, only comments saying we don't do it. The tracker uses `GetLastInputInfo` (a timestamp only). `tests/test_db.py` fails if any column name looks like keys, typed text, screens or images. The only screenshot code is the opt-in phone Screen Time importer: the image you upload is read in memory and never stored. | ✅ |

**Mobile (1.1.x):** pairing, token checks, laptop-only actions and device removal were verified live through the laptop's Wi-Fi address; the mobile web app was clicked through at phone size; the Android APK builds and `aapt` confirms its package, SDK levels and permissions. **On a real Android phone:** the APK installed, paired, and synced two days of per-app usage and unlocks to the laptop, with apps correctly categorized. That real data is also what revealed the phone privacy gap fixed in 1.1.1.

**Automated tests:** 128 passing (`.venv\Scripts\python -m pytest -q`), covering the state machine, categorizer, stats and focus score, DB and migrations, API (including the security checks), agent sinks and outbox, the WhatsApp bot (commands, signed webhook, scheduler, coach request shape), goals, roadmap, team, insights, phone importers, and maintenance.

**Not verified (needs your accounts or devices):** real WhatsApp delivery, real AI coach replies and screenshot reading (needs `ANTHROPIC_API_KEY`), ADB pull on a real Android phone, macOS / Linux.
