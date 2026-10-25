# Future ideas

[← Back to README](../README.md)

Roughly in order of how much they'd help day to day.

## Tracking
- **Phone timeline.** The Android app already reads per-app sessions; sending them (not just daily totals) would put the phone on the same timeline as the laptop.
- **HTTPS on the home network** (self-signed certificate pinned by the Android app), so Wi-Fi traffic is encrypted too.
- **Tray icon.** A system-tray icon showing tracking on / paused, with Pause / Resume / Open dashboard in its menu (e.g. with `pystray`). Today the switch lives in the CLI, the dashboard and WhatsApp.
- **"Passive" time.** Detect when a video or call is playing (Windows media session / audio activity) so a 30-minute lecture doesn't count as idle. Idle sessions already keep the app and category, so the data is there to reclassify.
- **Sleep estimate.** Last activity at night and first in the morning (laptop + phone pickups) give a rough sleep window; flag short nights in the morning report.
- **Mac and Linux.** The platform code is written (`agent/platforms/macos.py`, `linux.py`) but untested; test it and add launchd/systemd install steps to the installer.

## Coach & planning
- **Calendar integration.** Read Google Calendar to log meetings automatically (collaboration share without typing), and let `plan` write focus blocks straight into the calendar.
- **Focus mode.** `focus 50` on WhatsApp starts a timer, mutes nudges, optionally blocks distracting sites, and reports how the block went.
- **Mood / energy check-ins.** A one-tap 1–5 reply to the midday message, correlated with focus score in the weekly review.
- **Outcome tracking.** GitHub commits, LeetCode/Kaggle progress, or video uploads counting toward goals alongside tracked time.
- **Hackathon mode.** Countdown, checklist, team task board and a "submission in X hours" nudge for a hackathon weekend.

## Team
- **Opt-in weekly team digest.** Send each teammate a short summary of shared tasks and meetings (only what you choose to share).
- **Task sync** with Notion / GitHub Issues / Trello.

## Packaging & reliability
- **Play-store-free updates for the Android app** (the app checks the laptop for a newer APK).
- **Single-file installer.** `winget` / MSI / PyInstaller build, so no Python install is needed.
- **Offline dashboard.** Bundle Chart.js instead of loading it from a CDN.
- **Encrypted backups to your own cloud drive** (opt-in), plus a one-click restore in the dashboard.
- **WhatsApp production setup.** Meta Cloud API with approved message templates, so scheduled reports work beyond WhatsApp's 24-hour window without the sandbox's limits.
- **Better ADB parsing** across Android versions, tested against real devices.

## Content creation
- **Creator stats.** YouTube / Instagram channel numbers next to Content Creation time: "3h editing → 1 reel → 2.1k views".
