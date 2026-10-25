# Setup, upgrades & maintenance

[← Back to README](../README.md)

## Install

```bat
scripts\install.cmd
```
Creates `.venv`, installs everything, runs a self-check, and asks whether to start at login.

```bat
scripts\run.cmd
```
Starts the tracker **and** the dashboard in the background (no windows), prints today's stats and opens **http://127.0.0.1:8787**.

Want to see it with data right away?
```bat
.\workpulse demo seed
.\workpulse --demo today
.\workpulse --demo serve --port 8788
```
Then open http://127.0.0.1:8788. Demo data lives in a separate `data/demo.db`, so your real data is never touched, and the demo dashboard can run next to the real one.

The installer also adds a **WorkPulse Dashboard** shortcut to the Start Menu and starts WorkPulse when it's done.
Flags: `-Autostart` / `-NoAutostart`, `-NoShortcuts`, `-NoStart`.

If the install fails because the folder path is too long, move the project somewhere short like `C:\Users\<you>\workpulse` (Windows' 260-character path limit; the installer checks for this).

## Auto-start

`.\workpulse autostart on` puts a `WorkPulse.lnk` shortcut in your Startup folder (Task Manager → Startup apps lists it). At login it runs `pythonw -m workpulse supervise` (hidden), the **supervisor**:

- it starts the tracker and the dashboard, then checks every 15 s and restarts whichever has stopped (crash, killed, update);
- if one keeps dying (5 restarts in 10 min) it pauses restarts for 10 min and logs why (`.\workpulse logs supervisor`);
- `.\workpulse stop` stops the supervisor first, so stopping on purpose sticks until the next login or `.\workpulse start`.

No admin rights needed. `autostart off` removes the shortcut. Versions before 1.2 used the `HKCU\...\Run` registry list; `autostart on` migrates away from it because other programs can rewrite that list (that's how WorkPulse once failed to start after a reboot). macOS (LaunchAgent) and Linux (systemd `--user`) also launch the supervisor; both are written but untested.

## Side panel (dashboard docked to the screen edge)

`.\workpulse panel` opens the mobile dashboard in a slim Microsoft Edge app window on the right edge of the screen. It's docked like the taskbar: the edge is reserved, so maximized windows stop at it instead of covering it. Minimize it and the space comes back; restore it and it docks again. Close it with its X or `.\workpulse panel --close`. The Start Menu has a "WorkPulse Panel" shortcut.

- `--left` / `--right`, `--width 480` (320–900 points), `--float` (an ordinary window, no reserved edge) / `--dock`. Options are remembered.
- `.\workpulse autostart on --panel` opens it at every login too; `--no-panel` turns that off.
- On the laptop the panel needs no pairing; it's the same app the phone uses, at `http://127.0.0.1:8787/m/`.
- Windows only. On macOS/Linux open that address in a narrow browser window (or as an installed web app) instead.

## Upgrade

Re-run `scripts\install.cmd`. It detects the existing install, stops WorkPulse, updates the packages, and restarts whatever was running. Database changes are applied automatically on start, and existing data is kept.

## Backups

- The dashboard server backs up `data/workpulse.db` every day at 03:30, and on start if the newest backup is older than 24 h (laptop asleep at night). The newest 14 are kept in `data/backups/`.
- Make one any time: `.\workpulse backup`. List them: `.\workpulse backup --list`.
- Backups use SQLite's online backup, so they're consistent even while the tracker is writing.
- **Restore:** `.\workpulse stop`, copy a backup over `data\workpulse.db`, `.\workpulse start`.

## Logs & health check

- `.\workpulse doctor`: checks everything and prints a fix for each problem.
- `.\workpulse logs agent|server|cli`: the end of each log. Files live in `data/logs/`, rotate at 1 MB and keep 3 old copies.
- More detail: set `WORKPULSE_LOG_LEVEL=DEBUG` in `.env` and restart.

## Uninstall

```bat
scripts\uninstall.cmd
```
Stops WorkPulse and removes auto-start, the Start Menu shortcut and `.venv`. **Your data stays** in `data\` unless you add `-RemoveData` (asks for confirmation; `-Yes` skips it). The project folder itself is left for you to delete.
