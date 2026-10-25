# WorkPulse installer / upgrader for Windows.
#   scripts\install.cmd                 install, or upgrade an existing install (safe to re-run)
# Flags:
#   -Autostart / -NoAutostart   enable start-at-login without asking / skip the question
#   -NoShortcuts                don't create the Start Menu shortcut
#   -NoStart                    don't start WorkPulse at the end
param([switch]$Autostart, [switch]$NoAutostart, [switch]$NoShortcuts, [switch]$NoStart)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

# pip writes files ~110 chars deep inside .venv; past Windows' 260-char limit it fails with "No such file".
$longPaths = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem" -ErrorAction SilentlyContinue).LongPathsEnabled
if ($Root.Length -gt 140 -and $longPaths -ne 1) {
    throw "This folder's path is $($Root.Length) characters long, which breaks pip on Windows. Move the project somewhere shorter (e.g. $env:USERPROFILE\workpulse) and run this again."
}

Step "Looking for Python 3.11+"
$py = $null
foreach ($cand in @("py -3", "python", "python3")) {
    $exe, $arg = $cand -split " ", 2
    if (Get-Command $exe -ErrorAction SilentlyContinue) {
        $ver = & $exe $arg -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>$null
        if ($ver -and [version]$ver -ge [version]"3.11") { $py = $cand; break }
    }
}
if (-not $py) { throw "Python 3.11+ not found. Install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this again." }
Write-Host "    using: $py ($ver)"

$vpy = Join-Path $Root ".venv\Scripts\python.exe"
$upgrading = Test-Path $vpy
$wasRunning = $false
if ($upgrading) {
    Step "Existing install found: upgrading"
    # Stop the background processes so pip can replace files they have open; restarted at the end.
    $status = & $vpy -m workpulse status 2>$null | Out-String
    $wasRunning = $status -match "tracking ON|dashboard http"
    if ($wasRunning) { & $vpy -m workpulse stop | Out-Null }
} else {
    Step "Creating virtual env (.venv)"
    $exe, $arg = $py -split " ", 2
    & $exe $arg -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Couldn't create the virtual env." }
}

Step "Installing dependencies (a minute or two the first time)"
& $vpy -m pip install --upgrade pip --quiet --disable-pip-version-check
& $vpy -m pip install -e ".[dev]" --quiet --disable-pip-version-check
if ($LASTEXITCODE -ne 0) { throw "pip install failed. Check your internet connection and run this again." }

if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Step "Created .env from .env.example (add WhatsApp / AI keys there later)" }

$url = (& $vpy -c "from workpulse.config import load_config; print(load_config().server.url)").Trim()
if (-not $NoShortcuts) {
    $programs = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs"
    $lnk = Join-Path $programs "WorkPulse Dashboard.url"
    Set-Content -Path $lnk -Encoding ASCII -Value "[InternetShortcut]`r`nURL=$url/`r`n"
    Step "Start Menu shortcut: 'WorkPulse Dashboard' -> $url"
    & $vpy -c "from workpulse.agent.control import make_panel_shortcut; make_panel_shortcut()"
    Step "Start Menu shortcut: 'WorkPulse Panel' (the dashboard docked to the side of the screen)"
}

Step "Health check"
& $vpy -m workpulse doctor

if (-not $NoAutostart) {
    $enable = $Autostart
    if (-not $Autostart) { $enable = (Read-Host "Start WorkPulse automatically when you log in? [Y/n]") -notmatch '^[nN]' }
    if ($enable) { & $vpy -m workpulse autostart on }
}

if (-not $NoStart -or $wasRunning) {
    Step "Starting WorkPulse"
    & $vpy -m workpulse start
}

Write-Host ""
Write-Host ($(if ($upgrading) { "Upgrade complete!" } else { "Install complete!" })) -ForegroundColor Green
Write-Host "  Dashboard:  $url$(if (-not $NoShortcuts) { "   (Start Menu: 'WorkPulse Dashboard')" })"
Write-Host "  .\workpulse today            stats in the terminal"
Write-Host "  .\workpulse pause / resume   privacy switch"
Write-Host "  .\workpulse doctor           check everything"
Write-Host "  WhatsApp + AI coach setup:   docs\whatsapp.md"
