# Privacy

[← Back to README](../README.md)

## What is and isn't recorded

- Everything is stored locally in `data/workpulse.db` (SQLite). Nothing is uploaded.
- **No keylogging, no screenshots, no screen contents.** The agent doesn't install keyboard or mouse hooks at all: it asks Windows *"how many ms since the last input?"* (`GetLastInputInfo`), which can't tell which key was pressed.
- Stored per session: start, end, state, app (process name), category, and the window title **only if** `privacy.capture_titles: true`. With titles off, the title is still used in memory to pick a category, then thrown away.
- `privacy.exclude_apps` / `exclude_keywords` (banking, payment apps, incognito, password managers, …) are stored only as app `(private)` with no title, on the laptop **and for phone apps** (matched on app name and package). Adding a keyword also cleans phone data that's already stored.
- `workpulse pause` takes effect within 1 second and cuts the current session at the exact moment you paused.
- **Phone data** is daily totals per app only (no messages, no content), stored locally like everything else.
- Proof: `grep -ri "keystroke\|pynput\|keyboard\|ImageGrab" workpulse/` finds only comments saying we don't do it. The only `screenshot` code is the opt-in phone Screen Time importer (`workpulse/bot/vision.py`): you upload the image, it's read in memory and discarded, and no table has a column for images. The full schema is in [`workpulse/core/db.py`](../workpulse/core/db.py), and `tests/test_db.py` fails if any column name looks like keys, screens or images.

## What leaves your laptop (only if you set it up)

| Feature | What is sent | Where |
|---|---|---|
| WhatsApp reports & replies | The message text (stats summaries, goals, tasks you mention) | Twilio / Meta, to **your** number only |
| AI coach | A fact sheet: aggregated stats, app names, site names in insights, goals/tasks/team names, recent bot chat. Never full window titles | Anthropic API |
| Phone screenshot import | The screenshot you upload, once, to read the numbers (not stored anywhere) | Anthropic API |

Without `.env` keys, nothing is sent anywhere: messages are only logged locally and the coach uses templates.

## Deleting your data
- Everything: dashboard → Settings → *Delete all data…*, or `.\workpulse wipe --yes` (tracked activity), or `scripts\uninstall.cmd -RemoveData` (the whole `data` folder, including backups).
- One phone day: Digital day tab → ✕ next to the device.
- Export first if you want a copy: `.\workpulse export` (CSV).
