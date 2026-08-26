# Capture the Uma Musume window, save locally, and scp to the Pi inbox.
# Usually invoked from uma_capture_hotkeys.ahk. See README.md (Japanese).
#
#   powershell -File capture_upload.ps1 -Strategy nige
#   powershell -File capture_upload.ps1 -Strategy senkou -Event 2026-07_CM
#
# Event name: -Event arg, or current_event.txt next to this script.
# Requires SSH key auth to uma-pi for automatic upload.
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 misparses
# non-ASCII .ps1 files saved as UTF-8 without BOM.

param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("nige", "senkou", "sashi", "oikomi")]
    [string]$Strategy,

    [ValidateSet("super", "recommended")]
    [string]$Tier = "super",

    [string]$Event = "",

    [string]$WindowTitle = "UmamusumePrettyDerby_Jpn",

    [string]$PiTarget = "katao@uma-pi",

    [string]$PiInbox = "/home/katao/uma-guide-data/screenshots/inbox",

    [switch]$NoUpload
)

$ErrorActionPreference = "Stop"

$strategyDirs = @{
    nige   = "1_nige"
    senkou = "2_senkou"
    sashi  = "3_sashi"
    oikomi = "4_oikomi"
}

$tierDirs = @{
    super       = "super"
    recommended = "recommended"
}

# Resolve event name
if (-not $Event) {
    $eventFile = Join-Path $PSScriptRoot "current_event.txt"
    if (Test-Path $eventFile) {
        $Event = (Get-Content $eventFile -Raw).Trim()
    }
}
if (-not $Event) {
    Write-Error "Event name missing. Pass -Event or create current_event.txt (e.g. 2026-07_CM)."
    exit 1
}

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class Win32 {
    [DllImport("user32.dll")] public static extern IntPtr FindWindow(string cls, string title);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT rect);
    [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
    public struct RECT { public int Left, Top, Right, Bottom; }
}
"@
[void][Win32]::SetProcessDPIAware()

# Find the game window
$hwnd = [Win32]::FindWindow($null, $WindowTitle)
if ($hwnd -eq [IntPtr]::Zero) {
    $proc = Get-Process | Where-Object { $_.MainWindowTitle -like "*$WindowTitle*" } | Select-Object -First 1
    if ($proc) { $hwnd = $proc.MainWindowHandle }
}
if ($hwnd -eq [IntPtr]::Zero) {
    [console]::beep(400, 400)
    Write-Error "Window '$WindowTitle' not found. Start the game first."
    exit 1
}

$rect = New-Object Win32+RECT
[void][Win32]::GetWindowRect($hwnd, [ref]$rect)
$width = $rect.Right - $rect.Left
$height = $rect.Bottom - $rect.Top
if ($width -le 0 -or $height -le 0) {
    [console]::beep(400, 400)
    Write-Error "Could not get window size."
    exit 1
}

# Capture
Add-Type -AssemblyName System.Drawing
$bitmap = New-Object System.Drawing.Bitmap($width, $height)
$graphics = [System.Drawing.Graphics]::FromImage($bitmap)
$graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)
$graphics.Dispose()

# Save locally
$strategyDir = $strategyDirs[$Strategy]
$tierDir = $tierDirs[$Tier]
$localDir = Join-Path $env:USERPROFILE "uma-shots\$Event\$strategyDir\$tierDir"
New-Item -ItemType Directory -Force -Path $localDir | Out-Null
$fileName = "{0:yyyyMMdd_HHmmss_fff}.png" -f (Get-Date)
$localPath = Join-Path $localDir $fileName
$bitmap.Save($localPath, [System.Drawing.Imaging.ImageFormat]::Png)
$bitmap.Dispose()
Write-Host "Saved: $localPath"

# Beep = capture OK
[console]::beep(1200, 120)

# Upload to the Pi
if (-not $NoUpload) {
    $remoteDir = "$PiInbox/$Event/$strategyDir/$tierDir"
    ssh -o BatchMode=yes $PiTarget "mkdir -p '$remoteDir'" 2>$null
    scp -q -o BatchMode=yes $localPath "${PiTarget}:$remoteDir/" 2>$null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Uploaded: ${PiTarget}:$remoteDir/$fileName"
        [console]::beep(1600, 120)
    } else {
        Write-Warning "Upload failed (local file kept). Check SSH key auth to uma-pi."
        [console]::beep(400, 400)
    }
}
