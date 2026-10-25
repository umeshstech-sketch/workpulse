# Commands

[← Back to README](../README.md)

## All commands

| Command | What it does |
|---|---|
| `.\workpulse today` | Today's stats, timeline strip, categories, top apps (`--yesterday`, `--date 2026-10-20`) |
| `.\workpulse status` | Is tracking on, what am I doing right now |
| `.\workpulse start` / `stop` | Start/stop the tracker + dashboard in the background (`start --agent-only` = tracker only) |
| `.\workpulse dashboard` | Open the dashboard in your browser |
| `.\workpulse serve` | Run the API + dashboard in this terminal (`--port 8788` to pick a port) |
| `.\workpulse pause` / `resume` | Privacy switch: pausing stops recording **immediately** |
| `.\workpulse remote on\|off\|status` | Phone access when you're out, over Tailscale (separate from `lan`) |
| `.\workpulse autostart on\|off\|status` | Start tracker + dashboard at login and keep them running (per-user, no admin). `on --panel` also opens the side panel |
| `.\workpulse panel` | Open the dashboard docked to the side of the screen. `--left`/`--right`, `--width N`, `--float`/`--dock` (remembered), `--close` |
| `.\workpulse supervise` | The keep-alive process auto-start runs (restarts the tracker/dashboard if they stop) |
| `.\workpulse agent` | Run the tracker in the terminal with live logs (Ctrl+C to stop) |
| `.\workpulse doctor` | Health check of everything with a fix for each problem, then live readings of what the tracker sees (`-n 5` for 5 readings) |
| `.\workpulse lan on\|off\|status` | Let paired phones on your Wi-Fi connect (mobile app), or turn it off |
| `.\workpulse connect` | Show a pairing code + QR code for your phone |
| `.\workpulse devices` | List paired phones (`--remove <#>` to cut one off) |
| `.\workpulse restart` | Restart the tracker + dashboard (`--server-only`) |
| `.\workpulse logs [agent\|server\|cli]` | Show the end of a log (`-n 100` for more lines) |
| `.\workpulse backup` | Back up the database to `data/backups` (`--list` shows backups; the dashboard server also backs up daily) |
| `.\workpulse export` | Export all sessions to CSV |
| `.\workpulse wipe --yes` | Delete all tracked data |
| `.\workpulse demo seed\|clear` | Fake 14-day history in a separate DB; add `--demo` to any command to view it |
| `.\workpulse wa status\|test` | WhatsApp config check / send a test message |
| `.\workpulse bot <message>` | Talk to the bot in the terminal (`--send` also sends the reply, `--facts` shows the coach's fact sheet) |
| `.\workpulse report morning\|midday\|night\|weekly` | Preview a report (`--send` sends it now) |
| `.\workpulse messages -n 20` | Recent WhatsApp messages (local log, shows dry-run/failed status) |
| `.\workpulse phone [show]` | Laptop + phone digital day (`--date 2026-10-20`) |
| `.\workpulse phone add --total 3h --app "Instagram=1h10m"` | Add a phone day by hand (`--date`, `--pickups`, `--device`) |
| `.\workpulse phone import usage.csv` | Import a CSV/JSON export |
| `.\workpulse phone pull-android` | Experimental: read today's usage from an Android phone over ADB |
| `.\workpulse phone token` | Show the phone ingest endpoint + token |

`.\workpulse` is a tiny shim in the project folder. Add the folder to your PATH if you want plain `workpulse` everywhere. Add `--demo` before any command to use the demo database, and `--debug` to see full error tracebacks (normally they go to `data/logs/cli.log`).

WhatsApp chat commands are listed in [whatsapp.md](whatsapp.md#chat-commands).
