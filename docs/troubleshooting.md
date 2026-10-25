# Troubleshooting

[← Back to README](../README.md)

**Start here:** `.\workpulse doctor` checks everything (Python, config, database, backups, tracker, dashboard, port, auto-start, WhatsApp, AI key) and prints a fix for each problem. Logs: `.\workpulse logs agent`, `.\workpulse logs server`, `.\workpulse logs cli`.

- **Install fails with "No such file or directory … site-packages\pip\…":** the project folder's path is too long for Windows' 260-character limit. Move the folder somewhere short like `C:\Users\<you>\workpulse`. The installer checks for this and tells you.

- **`workpulse` isn't recognized:** use `.\workpulse` from the project folder, or `.venv\Scripts\workpulse`.
- **"agent not running":** `.\workpulse start`, then check `data\logs\agent.log`.
- **Dashboard won't open / port in use:** check `data\logs\server.log`. If port 8787 is taken, set `server.port` in `config.yaml`, then `.\workpulse stop` and `.\workpulse start`.
- **Dashboard says "Tracker off":** the dashboard is running but the tracker isn't: `.\workpulse start`.
- **`wa test` says "not configured":** `.env` is missing `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN` or `MY_WHATSAPP_NUMBER`, or the server wasn't restarted after editing it.
- **Bot doesn't reply:** is the tunnel running, and does the Twilio webhook URL match it (step 6)? `data\logs\server.log` shows "bad signature" (wrong token or URL: set `whatsapp.public_url`) or "unknown number" (check `MY_WHATSAPP_NUMBER`).
- **Error 63016 / 63015 in `.\workpulse messages`:** the WhatsApp 24-hour window closed or you left the sandbox. Send any message (or your `join` code) to the bot.
- **Coach replies are plain templates:** no `ANTHROPIC_API_KEY`, or the API was unreachable. The server log says which.
- **Upgrading:** re-run `scripts\install.cmd`. It stops WorkPulse, updates, and restarts it; new database tables/columns are added automatically and your data is kept.
- **Watching a video counts as idle:** the agent only sees input, so a 20-minute lecture with no mouse movement becomes idle. The app/category is still stored on idle sessions so this can be counted as "passive" time later.
- **Wrong category:** run `.\workpulse doctor -n 5` to see the process name, then add it under `categories.apps` in `config.yaml`.
- **Something broke after editing settings:** delete `data\settings.yaml` (it only holds dashboard changes) and restart.
- **Database damaged (doctor says integrity isn't ok):** stop WorkPulse, copy the newest file from `data\backups\` over `data\workpulse.db`, start again. Backups are made daily by the dashboard server and whenever you run `.\workpulse backup`.
- **A command printed an error:** the one-line message says what failed; the full traceback is in `data\logs\cli.log` (or re-run with `--debug`).
