# Capture the Uma Musume window, save locally, and scp to the Pi inbox.
# Usually invoked from uma_capture_hotkeys.ahk. See README.md (Japanese).
#
#   powershell -File capture_upload.ps1 -Strategy nige
#   powershell -File capture_upload.ps1 -Strategy senkou -Tier recommended -Event 2026-07_CM
#   powershell -File capture_upload.ps1 -ResendOnly
#
# Event name: -Event arg, or current_event.txt next to this script.
# Requires SSH key auth to uma-pi for automatic upload.
#
# How it works:
#   1. Capture the window and encode it as PNG in memory.
#   2. If the PNG bytes equal the newest PNG already in the same
#      event/strategy/tier folder, nothing is saved (exit 3).
#   3. Otherwise save locally, add one line to the pending list
#      (%USERPROFILE%\uma-shots\pending_uploads.txt) and exit at once.
#   4. A separate hidden process (this script with -ResendOnly) sends every
#      file in the pending list and removes each line when its scp succeeds.
#      So a slow or dead network never delays the next capture, and files
#      that could not be sent are retried on the next capture / next start.
#
# Exit codes (capture):
#   0 = saved (upload handed to the background sender)
#   1 = unexpected error
#   3 = same picture as the previous capture in this folder (not saved)
#   4 = game window not found
#   5 = event name missing or invalid
# Exit codes (-ResendOnly):
#   0 = nothing left to send (or another sender is already running)
#   2 = some files are still waiting
#
# Sounds:
#   1200 Hz short      = saved locally
#   1600 Hz short      = uploaded (one per file; one long beep for 4+ files)
#   400 Hz long        = upload failed / error (local file is kept)
#   600 Hz short x2    = same picture as before (not saved)
#
# NOTE: keep this file ASCII-only. Windows PowerShell 5.1 misparses
# non-ASCII .ps1 files saved as UTF-8 without BOM.

param(
    [ValidateSet("nige", "senkou", "sashi", "oikomi")]
    [string]$Strategy,

    [ValidateSet("super", "recommended")]
    [string]$Tier = "super",

    [string]$Event = "",

    [string]$WindowTitle = "UmamusumePrettyDerby_Jpn",

    [string]$PiTarget = "katao@uma-pi",

    [string]$PiInbox = "/home/katao/uma-guide-data/screenshots/inbox",

    [switch]$NoUpload,

    [switch]$ResendOnly
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

$shotsRoot = Join-Path $env:USERPROFILE "uma-shots"
$pendingFile = Join-Path $shotsRoot "pending_uploads.txt"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

# Named mutexes shared by all copies of this script (same Windows session).
$listMutexName = "UmaCapturePendingListLock"
$workerMutexName = "UmaCaptureUploadWorkerLock"
$saveMutexName = "UmaCaptureSaveLock"

# ---------------------------------------------------------------- helpers

function Enter-NamedLock([string]$Name, [int]$TimeoutMs) {
    $m = New-Object System.Threading.Mutex($false, $Name)
    try {
        if ($m.WaitOne($TimeoutMs)) { return $m }
    } catch [System.Threading.AbandonedMutexException] {
        # The previous owner died while holding it. We own it now.
        return $m
    }
    $m.Dispose()
    return $null
}

function Exit-NamedLock($Mutex) {
    if ($Mutex) {
        try { $Mutex.ReleaseMutex() } catch { }
        try { $Mutex.Dispose() } catch { }
    }
}

function Invoke-WithRetry([scriptblock]$Action) {
    for ($i = 0; $i -lt 5; $i++) {
        try { return (& $Action) } catch { Start-Sleep -Milliseconds 100 }
    }
    return (& $Action)
}

function Read-PendingLines {
    if (-not (Test-Path -LiteralPath $pendingFile)) { return @() }
    $all = Invoke-WithRetry { [System.IO.File]::ReadAllLines($pendingFile, $utf8NoBom) }
    return @($all | Where-Object { $_ -and $_.Trim() -ne "" })
}

function Add-PendingLine([string]$Line) {
    New-Item -ItemType Directory -Force -Path $shotsRoot | Out-Null
    $lock = Enter-NamedLock $listMutexName 10000
    try {
        # Append even if the lock timed out: losing the line would be worse.
        Invoke-WithRetry { [System.IO.File]::AppendAllText($pendingFile, $Line + "`r`n", $utf8NoBom) }
    } finally {
        Exit-NamedLock $lock
    }
}

function Remove-PendingLine([string]$Line) {
    $lock = Enter-NamedLock $listMutexName 10000
    if (-not $lock) { return }   # keep the line; it is retried later
    try {
        $kept = @(Read-PendingLines | Where-Object { $_ -ne $Line })
        Invoke-WithRetry { [System.IO.File]::WriteAllLines($pendingFile, [string[]]$kept, $utf8NoBom) }
    } catch {
        Write-Warning "Could not update the pending list: $_"
    } finally {
        Exit-NamedLock $lock
    }
}

function Get-BytesHash([byte[]]$Bytes) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    try {
        return [System.BitConverter]::ToString($sha.ComputeHash($Bytes))
    } finally {
        $sha.Dispose()
    }
}

# Send one file. Returns $true on success. $MadeDirs remembers remote dirs
# already created in this run so mkdir is not repeated for every file.
function Send-OneFile([string]$LocalPath, [string]$RemoteDir, [hashtable]$MadeDirs) {
    # Native stderr must not become a terminating error here.
    $ErrorActionPreference = "Continue"
    try {
        if (-not $MadeDirs.ContainsKey($RemoteDir)) {
            & ssh -o BatchMode=yes -o ConnectTimeout=8 $PiTarget "mkdir -p '$RemoteDir'" 2>$null | Out-Null
            if ($LASTEXITCODE -ne 0) { return $false }
            $MadeDirs[$RemoteDir] = $true
        }
        & scp -q -o BatchMode=yes -o ConnectTimeout=8 $LocalPath "${PiTarget}:$RemoteDir/" 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

# Send everything in the pending list. Only one sender runs at a time.
# Returns the number of lines still waiting (0 if another sender is running).
function Invoke-PendingUploads {
    $worker = Enter-NamedLock $workerMutexName 0
    if (-not $worker) {
        Write-Host "Another sender is already running."
        return 0
    }
    $attempted = @{}
    try {
        while ($true) {
            # Decide under the list lock whether there is new work. When there
            # is none, the worker lock is released BEFORE the list lock, so a
            # capture that adds a line right after this can start a new sender.
            $lock = Enter-NamedLock $listMutexName 10000
            $lines = @()
            try {
                $lines = @(Read-PendingLines)
                $fresh = @($lines | Where-Object { -not $attempted.ContainsKey($_) })
                if ($fresh.Count -eq 0) {
                    Exit-NamedLock $worker
                    $worker = $null
                    break
                }
            } finally {
                Exit-NamedLock $lock
            }

            foreach ($l in $lines) { $attempted[$l] = $true }
            $madeDirs = @{}
            $sent = 0
            $many = ($lines.Count -gt 3)
            foreach ($line in $lines) {
                $parts = $line.Split("`t")
                if ($parts.Count -ne 2 -or $parts[1] -notmatch '^/[A-Za-z0-9_./-]+$') {
                    Write-Warning "Dropped a broken line from the pending list: $line"
                    Remove-PendingLine $line
                    continue
                }
                $localPath = $parts[0]
                $remoteDir = $parts[1]
                if (-not (Test-Path -LiteralPath $localPath)) {
                    Write-Warning "Local file is gone, dropped from the pending list: $localPath"
                    Remove-PendingLine $line
                    continue
                }
                if (Send-OneFile $localPath $remoteDir $madeDirs) {
                    Remove-PendingLine $line
                    $sent++
                    Write-Host "Uploaded: $localPath -> ${PiTarget}:$remoteDir/"
                    if (-not $many) { [console]::beep(1600, 120) }
                } else {
                    # Most likely the network or the Pi is down, so the rest
                    # would fail too. Stop this pass; lines stay in the list.
                    Write-Warning "Upload failed (local file kept, will retry later): $localPath"
                    break
                }
            }
            if ($many -and $sent -gt 0) { [console]::beep(1600, 400) }
        }
    } finally {
        Exit-NamedLock $worker
    }

    $left = @(Read-PendingLines).Count
    if ($left -gt 0) { [console]::beep(400, 400) }
    return $left
}

function Start-BackgroundSender {
    $argList = @(
        "-NoProfile", "-ExecutionPolicy", "Bypass",
        "-File", "`"$PSCommandPath`"",
        "-ResendOnly",
        "-PiTarget", "`"$PiTarget`"",
        "-PiInbox", "`"$PiInbox`""
    )
    Start-Process -FilePath "powershell.exe" -ArgumentList $argList -WindowStyle Hidden | Out-Null
}

# ---------------------------------------------------------------- resend only

if ($ResendOnly) {
    $left = 0
    try {
        $left = Invoke-PendingUploads
    } catch {
        Write-Host "Resend failed: $_"
        exit 1
    }
    if ($left -gt 0) {
        Write-Host "Still waiting: $left file(s)."
        exit 2
    }
    exit 0
}

# ---------------------------------------------------------------- capture

if (-not $Strategy) {
    Write-Host "Pass -Strategy (nige/senkou/sashi/oikomi) or -ResendOnly."
    exit 1
}

# Resolve event name
if (-not $Event) {
    $eventFile = Join-Path $PSScriptRoot "current_event.txt"
    if (Test-Path -LiteralPath $eventFile) {
        $Event = ("" + (Get-Content -LiteralPath $eventFile -Raw)).Trim()
    }
}
if (-not $Event -or $Event -notmatch '^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$') {
    [console]::beep(400, 400)
    Write-Host "Event name missing or invalid. Pass -Event or fix current_event.txt (e.g. 2026-07_CM)."
    exit 5
}

try {
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
        Write-Host "Window '$WindowTitle' not found. Start the game first."
        exit 4
    }

    $rect = New-Object Win32+RECT
    [void][Win32]::GetWindowRect($hwnd, [ref]$rect)
    $width = $rect.Right - $rect.Left
    $height = $rect.Bottom - $rect.Top
    if ($width -le 0 -or $height -le 0) {
        [console]::beep(400, 400)
        Write-Host "Could not get window size."
        exit 4
    }

    # Capture, and encode as PNG in memory
    Add-Type -AssemblyName System.Drawing
    $bitmap = New-Object System.Drawing.Bitmap($width, $height)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.CopyFromScreen($rect.Left, $rect.Top, 0, 0, $bitmap.Size)
    $graphics.Dispose()
    $stream = New-Object System.IO.MemoryStream
    $bitmap.Save($stream, [System.Drawing.Imaging.ImageFormat]::Png)
    $bitmap.Dispose()
    [byte[]]$newBytes = $stream.ToArray()
    $stream.Dispose()

    $strategyDir = $strategyDirs[$Strategy]
    $tierDir = $tierDirs[$Tier]
    $localDir = Join-Path $shotsRoot "$Event\$strategyDir\$tierDir"
    New-Item -ItemType Directory -Force -Path $localDir | Out-Null

    # Duplicate check + save, one capture at a time.
    $isDuplicate = $false
    $localPath = ""
    $saveLock = Enter-NamedLock $saveMutexName 5000
    try {
        $previous = Get-ChildItem -LiteralPath $localDir -Filter "*.png" -File |
            Sort-Object Name | Select-Object -Last 1
        if ($previous -and $previous.Length -eq $newBytes.Length) {
            [byte[]]$oldBytes = [System.IO.File]::ReadAllBytes($previous.FullName)
            if ((Get-BytesHash $oldBytes) -eq (Get-BytesHash $newBytes)) {
                $isDuplicate = $true
            }
        }
        if (-not $isDuplicate) {
            do {
                $fileName = "{0:yyyyMMdd_HHmmss_fff}.png" -f (Get-Date)
                $localPath = Join-Path $localDir $fileName
                if (Test-Path -LiteralPath $localPath) { Start-Sleep -Milliseconds 2 }
            } while (Test-Path -LiteralPath $localPath)
            [System.IO.File]::WriteAllBytes($localPath, $newBytes)
        }
    } finally {
        Exit-NamedLock $saveLock
    }

    if ($isDuplicate) {
        Write-Host "Same picture as the previous capture ($($previous.Name)). Not saved."
        [console]::beep(600, 150)
        [console]::beep(600, 150)
        exit 3
    }

    Write-Host "Saved: $localPath"
    # Beep = capture OK
    [console]::beep(1200, 120)
} catch {
    try { [console]::beep(400, 400) } catch { }
    Write-Host "Capture failed: $_"
    exit 1
}

# Upload to the Pi: queue the file, then let a separate hidden process send
# the whole pending list. The local file is already saved at this point.
if (-not $NoUpload) {
    try {
        $remoteDir = "$PiInbox/$Event/$strategyDir/$tierDir"
        Add-PendingLine ($localPath + "`t" + $remoteDir)
        Start-BackgroundSender
    } catch {
        Write-Host "Could not start the upload (local file kept): $_"
    }
}
exit 0
