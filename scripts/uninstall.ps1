# WorkPulse uninstaller for Windows.
#   scripts\uninstall.cmd               stop WorkPulse, remove auto-start + shortcut + .venv (KEEPS your data)
#   scripts\uninstall.cmd -RemoveData   also delete data\ (your tracked history, goals, messages, backups)
#   -Yes                                don't ask for confirmation
param([switch]$RemoveData, [switch]$Yes)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
function Step($msg) { Write-Host "==> $msg" -ForegroundColor Cyan }

$what = "stop WorkPulse, remove auto-start, the Start Menu shortcut and .venv"
if ($RemoveData) { $what += ", and PERMANENTLY DELETE data\ (all tracked history, goals, messages and backups)" }
if (-not $Yes) {
    $answer = Read-Host "This will $what. Continue? [y/N]"
    if ($answer -notmatch '^[yY]') { Write-Host "Nothing changed."; exit 0 }
}

$vpy = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $vpy) {
    Step "Stopping tracker + dashboard"
    & $vpy -m workpulse stop | Out-Null
    Step "Removing auto-start"
    & $vpy -m workpulse autostart off | Out-Null
} else {
    # No venv: still remove the Run key if an old install left one.
    Remove-ItemProperty -Path "HKCU:\Software\Microsoft\Windows\CurrentVersion\Run" -Name "WorkPulseAgent" -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\Startup\WorkPulse.lnk") -ErrorAction SilentlyContinue
}

$lnk = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\WorkPulse Dashboard.url"
if (Test-Path $lnk) { Step "Removing Start Menu shortcut"; Remove-Item $lnk }
$panelLnk = Join-Path $env:APPDATA "Microsoft\Windows\Start Menu\Programs\WorkPulse Panel.lnk"
if (Test-Path $panelLnk) { Remove-Item $panelLnk }

if (Test-Path ".venv") { Step "Removing .venv"; Remove-Item -Recurse -Force ".venv" }

if ($RemoveData -and (Test-Path "data")) {
    Step "Deleting data\"
    Remove-Item -Recurse -Force "data"
}

Write-Host ""
Write-Host "WorkPulse is uninstalled." -ForegroundColor Green
if (-not $RemoveData -and (Test-Path "data")) { Write-Host "  Your data is still in $Root\data (delete the folder yourself, or re-run with -RemoveData)." }
Write-Host "  The project folder itself is untouched; delete it whenever you like. Reinstall with scripts\install.cmd"
