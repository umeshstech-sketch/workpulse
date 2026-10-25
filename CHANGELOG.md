# Changelog

## Android app 2.2.0 (2026-10-23)

- The AI coach now uses **Google Gemini** with your own Gemini API key (new `AQ.` keys and older `AIza` keys both work), instead of Claude. Commands are unchanged and still work offline. The Anthropic SDK was removed, so the app is back to ~2.5 MB.

## Android app 2.1.0 (2026-10-23)

- **Coach tab:** the laptop's chat, on the phone. Commands (today, week, best, improve, plan, apps, score, limit, goal, focus, stop, bedtime, habits) are answered on the phone, offline; quick-reply buttons for the common ones.
- **AI coach (optional):** free-form questions answered by Claude with your own Anthropic API key (More → AI coach), using a short summary of your stats; server-side fallback enabled. Without a key, commands still work.

## Android app 2.0.0 (2026-10-23)

The Android app is now a **standalone phone tracker**: everything is computed and stored on the phone, with no laptop or account needed, so anyone can install it. Laptop sync is still there, optional, under More.
- **Today:** screen time vs goal, transparent balance score, pickups, first pickup, longest stretch, focus time, hour-by-hour chart, categories, insights, apps with opens and limits; browse earlier days.
- **Trends:** 7/30-day history vs goal, period comparison, best day, categories, top apps.
- **Focus timer** with a notification at the end and a report of distracting apps opened during the session; streaks.
- **Goals:** daily screen-time and pickup goals, per-app limits with 80%/100% nudges, bedtime reminder, habits with streaks.
- **Privacy:** private-apps list (banking/payment by default) stored only as "Private apps"; CSV export; delete everything.
- Per-app details: 14-day history, change category, set a limit.

## 1.3.0 (2026-10-22)

- **Phone access when you're out, via Tailscale.** `workpulse remote on` (or Settings → Connect a phone) lets paired phones on your own Tailscale network reach the laptop from anywhere. Nothing is exposed to the internet: only Tailscale addresses are let in, separate from home Wi-Fi access, and every request still needs the phone's token. Doctor checks Tailscale.
- **Android app 1.1.0:** remembers every laptop address (home Wi-Fi, Tailscale IP, Tailscale name), uses whichever answers, and learns new addresses at each sync. After time out of reach, it catches up on every missed day (up to a week), not just yesterday.
- Pairing QR codes carry all of the laptop's addresses.

## 1.2.0 (2026-10-22)

- **Always on.** New supervisor (`workpulse supervise`) keeps the tracker and the dashboard running and restarts either one within ~15 s if it stops, with back-off if something keeps crashing. Auto-start now uses a Startup-folder shortcut that launches the supervisor, replacing the `HKCU\...\Run` entry, which Windows skipped after a reboot (another program was rewriting that list). `workpulse start` / `stop` / `restart` work through the supervisor.
- **Side panel.** `workpulse panel` docks the mobile dashboard to the side of the screen as an app bar (the edge is reserved like the taskbar; it gives the space back when minimized or closed). Options for side, width and floating; `autostart on --panel` opens it at login; Start Menu "WorkPulse Panel" shortcut.
- The mobile app opened on the laptop itself needs no pairing.

## 1.1.1 (2026-10-21)

Fixes from a full review of the project:
- **Privacy:** the never-log list (banking, payment apps, password managers…) now applies to phone apps too, by app name and package. Matches are stored only as "(private)". Already-stored phone data is cleaned on start and whenever privacy settings change. Added Indian payment apps (IPPB, BHIM, YONO, GPay…) to the default list.
- **Android app 1.0.1:** no longer hidden behind the status/navigation bars on Android 15; sends Android's own app category so games/video/social apps are sorted without config rules; pickups fall back to screen-ons on phones that don't report unlocks.
- Coach messages typed on the phone are labelled "phone app" (not "this laptop"); the full dashboard's Settings page is read-only on a paired phone; `workpulse connect` refuses when the dashboard isn't running.
- Old pairing codes are deleted; the server ignores forwarded client-address headers; the build script backs up and restores the app-signing key; `config.yaml` explains that `lan` lives in `data/settings.yaml`; screenshot script no longer reuses PowerShell's `$args`/`$profile`.

## 1.1.0 (2026-10-21)

- **Mobile app over Wi-Fi.** Phone-first web app at `/m/` (Home digital day, Coach, Phone, Plan, More), served by the laptop. Opt-in Wi-Fi access (`workpulse lan on`), one-time pairing with a 6-digit code / QR, per-phone hashed tokens, laptop-only admin actions, DNS-rebinding and public-IP protection.
- **Android app** (`android/`, built with `scripts/build-android.ps1`): pairs by QR or code, shows the mobile dashboard, and syncs phone usage (per-app foreground time + unlocks from Android usage stats) to the laptop every 15 minutes. Download it from the laptop at `/m/workpulse.apk`.
- Dashboard **Settings → Connect a phone**; `connect`, `devices`, `lan`, `restart` commands; doctor checks for Public network profiles and VPNs.

## 1.0.0 (2026-10-21)

First complete version, built in six phases.

- **Phase 1: tracker + CLI.** Windows agent using OS idle time and the foreground window (no keyboard hooks), active/idle/away state machine with back-dating and sleep-gap detection, privacy filters, app/title categorization, SQLite storage, `workpulse today` with a timeline strip, pause/resume, login auto-start, demo data.
- **Phase 2: backend + dashboard.** Local FastAPI server (localhost-only, Host-checked, token-protected ingest), dark/light dashboard with Today and Week views, settings that hot-reload into the tracker, CSV export, delete-all; the agent syncs over HTTP with a local fallback and an outbox.
- **Phase 3: WhatsApp + AI coach.** Twilio sandbox (pluggable, with Meta Cloud API and dry-run providers), signed webhook, scheduled morning/midday/night/weekly reports, nudges, task reminders, chat commands, Claude-powered coaching with template fallbacks, numeric insights.
- **Phase 4: goals, team, insights.** Goals linked to tracked time, 100-day / 6-month / 1-year roadmap with coach-suggested milestones, team task board, meeting log and collaboration share, Insights tab, Coach chat tab, automatic DB migrations.
- **Phase 5: phone.** Phone screen time via screenshot (AI-read, never stored), manual entry, CSV/JSON import, experimental ADB pull and a token-protected ingest API; combined "digital day" view.
- **Phase 6: polish.** Friendly CLI/server/dashboard errors with logs, `doctor` health check, `logs` and `backup` commands, daily automatic backups, installer that also upgrades, Start Menu shortcut, uninstaller, `?date=` dashboard links, docs split into guides with screenshots, future ideas, acceptance report.
