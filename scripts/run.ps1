# Start the tracker + dashboard in the background (no windows), print today's stats, open the dashboard.
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$wp = Join-Path $Root ".venv\Scripts\workpulse.exe"
if (-not (Test-Path $wp)) { throw "Not installed yet. Run scripts\install.cmd first." }
& $wp start
Start-Sleep -Seconds 2
& $wp today
& $wp dashboard
