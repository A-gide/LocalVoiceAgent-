# start-all.ps1 - Strictly follows MASTER_PROMPT.md Section 29
#
# Sequence:
#   1. Screenpipe (24/7 passive recording engine, port 3030)
#   2. llama.cpp-hub runtime backend (port 8080, external/adopted service)
#   3. TTS service (sherpa-onnx MeloTTS integrated, in-process)
#   4. LVA Core is NOT started here -- Tauri owns it (see below)
#   5. health-check
#
# v1.2.1 note: LVA Core is a `Spawned` child of the Tauri shell, launched with a
# one-shot pipe bootstrap handshake (token + nonce, ephemeral port).  Starting it
# from this script would mean a fixed port and no token, which violates hard
# constraint 5.  Launch the desktop shell instead; this script only brings up the
# external services and then checks health.
#
[CmdletBinding()]
param(
    [string]$Root = "E:\AI\LocalVoiceAgent",
    [string]$Model = "spark-x2.5-4b-q8-0",
    [int]$Ctx = 8192,
    [int]$Ngl = 99
)

$ErrorActionPreference = "Continue"
$py = Join-Path $Root "venv\Scripts\python.exe"
$logs = Join-Path $Root "logs"
$data = Join-Path $Root "data"
$screenpipeData = Join-Path $Root "screenpipe-data"
New-Item -ItemType Directory -Force -Path $logs, $data, $screenpipeData | Out-Null

$pidFile = Join-Path $data "pids.json"
$pids = @{}
if (Test-Path $pidFile) {
    try { $pids = Get-Content $pidFile -Raw | ConvertFrom-Json -AsHashtable } catch { $pids = @{} }
}

function Say($msg, $level = "INFO") {
    Write-Host ("[{0}] {1}" -f $level, $msg)
}

function Wait-Port($port, $seconds, $what) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue) {
            Say "$what is listening on 127.0.0.1:$port"
            return $true
        }
        Start-Sleep -Milliseconds 600
    }
    Say "$what did not come up on port $port within ${seconds}s" "WARN"
    return $false
}

Say "=== Starting Local Voice Agent Stack (MASTER_PROMPT) ==="

# ------------------------------------------------------------- 1. Screenpipe (port 3030)
Say "Step 1: Checking Screenpipe (Passive 24/7 Audio Recorder)..."
$spPort = Get-NetTCPConnection -State Listen -LocalPort 3030 -ErrorAction SilentlyContinue
if ($spPort) {
    Say "Screenpipe is already running on port 3030."
} else {
    $spBin = Join-Path $Root "apps\screenpipe\node_modules\@screenpipe\cli-win32-x64\bin\screenpipe.exe"
    if (-not (Test-Path $spBin)) {
        $spBin = Join-Path $Root "apps\screenpipe\screenpipe.exe"
    }
    if (Test-Path $spBin) {
        Say "Starting Screenpipe with audio-only, local data-dir, telemetry disabled..."
        $spArgs = @(
            "record",
            "--disable-vision",
            "--disable-telemetry",
            "--data-dir", $screenpipeData,
            "--port", "3030",
            "--audio-transcription-engine", "disabled",
            "--api-auth", "false"
        )
        $spProc = Start-Process -FilePath $spBin -ArgumentList $spArgs -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs "screenpipe_stdout.log") -RedirectStandardError (Join-Path $logs "screenpipe_stderr.log")
        $pids["screenpipe"] = $spProc.Id
        Wait-Port 3030 15 "Screenpipe" | Out-Null
    } else {
        Say "Screenpipe binary not found!" "WARN"
    }
}

# ------------------------------------------------------------- 2. llama.cpp-hub (port 8080)
Say "Step 2: Checking llama.cpp-hub runtime backend (port 8080)..."
$hubPort = Get-NetTCPConnection -State Listen -LocalPort 8080 -ErrorAction SilentlyContinue
if ($hubPort) {
    Say "llama.cpp-hub already listening on 127.0.0.1:8080."
} else {
    Say "llama.cpp-hub not listening on port 8080 (External/Adopted service)." "WARN"
}

# ------------------------------------------------------------- 3. LVA Core (owned by Tauri)
# Deliberately not started from here.  Core must be spawned by the Tauri shell so
# it receives its token/nonce over the bootstrap pipe and binds an ephemeral
# port; a standalone start would be unauthenticated on a well-known port.
Say "Step 3: LVA Core is started by the Tauri desktop shell (bootstrap pipe handshake)."
Say "        Launch apps/desktop-shell (lva-pet.exe) to bring Core up; skipping here." "INFO"

# Save PIDs (external services only; Core is tracked by the Tauri shell)
$pids | ConvertTo-Json | Set-Content -Path $pidFile -Encoding UTF8

# ------------------------------------------------------------- 4. Health Check
Say "Step 4: Executing health-check..."
& (Join-Path $Root "scripts\health-check.ps1")
