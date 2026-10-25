# Build the WorkPulse Android app (android/) into dashboard\m\workpulse.apk, so your phone can download it from
# the laptop (mobile app → More → Get the Android app).
#
# First run downloads a private toolchain (~1.5 GB, no admin needed) into %LOCALAPPDATA%\WorkPulse-android:
#   Microsoft Build of OpenJDK 17, Android SDK command-line tools + platform 35, Gradle 8.10.2.
# Usage:  powershell -ExecutionPolicy Bypass -File scripts\build-android.ps1
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$Tool = Join-Path $env:LOCALAPPDATA "WorkPulse-android"
$Dl = Join-Path $Tool "downloads"
New-Item -ItemType Directory -Force $Tool, $Dl | Out-Null
function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Fetch($url, $file) {
    $out = Join-Path $Dl $file
    if (-not (Test-Path $out)) {
        Step "Downloading $file"
        & curl.exe -L --fail --retry 3 -o "$out.part" $url
        if ($LASTEXITCODE -ne 0) { throw "Download failed: $url" }
        Move-Item "$out.part" $out
    }
    return $out
}

# --- JDK 17 ---
$jdk = Get-ChildItem $Tool -Directory -Filter "jdk-17*" -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $jdk) {
    $zip = Fetch "https://aka.ms/download-jdk/microsoft-jdk-17-windows-x64.zip" "jdk17.zip"
    Step "Extracting JDK"
    Expand-Archive $zip $Tool -Force
    $jdk = Get-ChildItem $Tool -Directory -Filter "jdk-17*" | Select-Object -First 1
}
$env:JAVA_HOME = $jdk.FullName
$env:Path = "$($jdk.FullName)\bin;$env:Path"

# --- Android SDK ---
$Sdk = Join-Path $Tool "sdk"
$sdkmanager = Join-Path $Sdk "cmdline-tools\latest\bin\sdkmanager.bat"
if (-not (Test-Path $sdkmanager)) {
    $zip = Fetch "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip" "cmdline-tools.zip"
    Step "Extracting Android command-line tools"
    $tmp = Join-Path $Tool "cmdline-tmp"
    Expand-Archive $zip $tmp -Force
    New-Item -ItemType Directory -Force (Join-Path $Sdk "cmdline-tools") | Out-Null
    Move-Item (Join-Path $tmp "cmdline-tools") (Join-Path $Sdk "cmdline-tools\latest")
    Remove-Item -Recurse -Force $tmp
}
$env:ANDROID_HOME = $Sdk
if (-not (Test-Path (Join-Path $Sdk "licenses\android-sdk-license"))) {
    # Agreeing to Google's Android SDK licenses is your decision: they're shown and you answer y/N yourself.
    Step "The Android SDK needs you to accept its license agreements (https://developer.android.com/studio/terms)"
    cmd /c "`"$sdkmanager`" --sdk_root=`"$Sdk`" --licenses"
    if (-not (Test-Path (Join-Path $Sdk "licenses\android-sdk-license"))) { throw "The Android SDK licenses weren't accepted, so the app can't be built." }
}
if (-not (Test-Path (Join-Path $Sdk "platforms\android-35"))) {
    Step "Installing Android platform 35 + build tools"
    cmd /c "`"$sdkmanager`" --sdk_root=`"$Sdk`" platform-tools platforms;android-35 build-tools;34.0.0"
    if ($LASTEXITCODE -ne 0) { throw "sdkmanager failed" }
}

# --- Gradle ---
$gradleHome = Join-Path $Tool "gradle-8.10.2"
if (-not (Test-Path $gradleHome)) {
    $zip = Fetch "https://services.gradle.org/distributions/gradle-8.10.2-bin.zip" "gradle-8.10.2.zip"
    Step "Extracting Gradle"
    Expand-Archive $zip $Tool -Force
}
$gradle = Join-Path $gradleHome "bin\gradle.bat"

# --- Signing key ---
# Android only installs an update if it's signed with the same key as the installed app. Gradle signs debug builds
# with %USERPROFILE%\.android\debug.keystore; keep a copy next to the toolchain and restore it if it ever goes missing.
$keystore = Join-Path $env:USERPROFILE ".android\debug.keystore"
$keyBackup = Join-Path $Tool "debug.keystore.backup"
if (-not (Test-Path $keystore) -and (Test-Path $keyBackup)) {
    Step "Restoring the app-signing key from backup"
    New-Item -ItemType Directory -Force (Split-Path $keystore) | Out-Null
    Copy-Item $keyBackup $keystore
}

# --- Build ---
$android = Join-Path $Root "android"
Set-Content -Path (Join-Path $android "local.properties") -Encoding ASCII -Value ("sdk.dir=" + ($Sdk -replace "\\", "/"))
Push-Location $android
try {
    if (-not (Test-Path "gradlew.bat")) { Step "Creating Gradle wrapper"; & $gradle wrapper --gradle-version 8.10.2 --no-daemon -q }
    Step "Building the app (first build downloads libraries; a few minutes)"
    & .\gradlew.bat assembleDebug --no-daemon
    if ($LASTEXITCODE -ne 0) { throw "Gradle build failed" }
} finally { Pop-Location }

if ((Test-Path $keystore) -and -not (Test-Path $keyBackup)) { Copy-Item $keystore $keyBackup; Step "Backed up the app-signing key to $keyBackup" }

$apk = Join-Path $android "app\build\outputs\apk\debug\app-debug.apk"
$dest = Join-Path $Root "dashboard\m\workpulse.apk"
Copy-Item $apk $dest -Force
Write-Host ""
Write-Host "Built: $dest ($([math]::Round((Get-Item $dest).Length / 1MB, 1)) MB)" -ForegroundColor Green
Write-Host "On your phone: open the mobile app (http://<laptop-ip>:8787/m/) → More → Get the Android app."
