# Regenerate docs/screenshots/*.png from the DEMO dashboard (never your real data).
# Needs Microsoft Edge (preinstalled on Windows). Usage: powershell -ExecutionPolicy Bypass -File scripts\screenshots.ps1
param([int]$Port = 8788)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$wp = Join-Path $Root ".venv\Scripts\workpulse.exe"
$edge = @("${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe", "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe") |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $edge) { throw "Microsoft Edge not found." }
$out = Join-Path $Root "docs\screenshots"
New-Item -ItemType Directory -Force $out | Out-Null
$edgeProfile = Join-Path $env:TEMP "workpulse-shots-profile"  # throwaway browser profile

& $wp demo seed | Out-Null
$server = $null
try { Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/api/status" -TimeoutSec 2 | Out-Null } catch {
    $server = Start-Process -PassThru -WindowStyle Hidden -FilePath $wp -ArgumentList "--demo", "serve", "--port", "$Port"
    Start-Sleep -Seconds 6
}
$day = (Get-Date).AddDays(-1).ToString("yyyy-MM-dd")
$shots = @(
    @{ name = "today";    tab = "today";    h = 830 },
    @{ name = "week";     tab = "week";     h = 1300 },
    @{ name = "digital";  tab = "digital";  h = 1150 },
    @{ name = "goals";    tab = "goals";    h = 980 },
    @{ name = "team";     tab = "team";     h = 1000 },
    @{ name = "insights"; tab = "insights"; h = 1500 },
    @{ name = "coach";    tab = "coach";    h = 900 }
)
foreach ($s in $shots) {
    $file = Join-Path $out "$($s.name).png"
    $edgeArgs = @("--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run", "--user-data-dir=`"$edgeProfile`"",
              "--window-size=1280,$($s.h)", "--virtual-time-budget=6000", "--screenshot=`"$file`"",
              "`"http://127.0.0.1:$Port/?date=$day#$($s.tab)`"")
    Start-Process -FilePath $edge -ArgumentList $edgeArgs -Wait -WindowStyle Hidden
    if (Test-Path $file) { Write-Host "saved $file" } else { Write-Warning "no screenshot for $($s.name)" }
}
if ($server) { Stop-Process -Id $server.Id -Force -ErrorAction SilentlyContinue }
Remove-Item -Recurse -Force $edgeProfile -ErrorAction SilentlyContinue
