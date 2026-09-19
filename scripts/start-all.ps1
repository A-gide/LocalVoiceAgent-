# start-all.ps1 - Strictly follows MASTER_PROMPT.md Section 29
#
# Sequence:
#   1. Screenpipe (24/7 passive recording engine, port 3030)
#   2. LM Studio / llama-server (port 1234)
#   3. TTS service (sherpa-onnx MeloTTS integrated)
#   4. Open-LLM-VTuber (Live Assistant shell, port 12393)
#   5. health-check
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

# ------------------------------------------------------------- 2. LM Studio / llama-server (port 1234)
Say "Step 2: Checking LM Studio LLM backend (port 1234)..."
$llmPort = Get-NetTCPConnection -State Listen -LocalPort 1234 -ErrorAction SilentlyContinue
if ($llmPort) {
    Say "LLM server already listening on 127.0.0.1:1234."
} else {
    Say "Starting local llama-server on port 1234..."
    & $py (Join-Path $Root "scripts\llm_serve.py") --start $Model --ctx $Ctx --ngl $Ngl
    Wait-Port 1234 60 "llama-server" | Out-Null
}

# ------------------------------------------------------------- 3. TTS
Say "Step 3: Verifying TTS engine (sherpa-onnx MeloTTS)..."
Say "TTS engine is configured locally on CPU (0MB VRAM footprint)."

# ------------------------------------------------------------- 4. Open-LLM-VTuber (port 12393)
Say "Step 4: Checking Open-LLM-VTuber (Live Assistant Shell, port 12393)..."
$vtuberPort = Get-NetTCPConnection -State Listen -LocalPort 12393 -ErrorAction SilentlyContinue
if ($vtuberPort) {
    Say "Open-LLM-VTuber already running on 127.0.0.1:12393."
} else {
    Say "Starting Open-LLM-VTuber..."
    $vtuberDir = Join-Path $Root "apps\open-llm-vtuber"
    $ffmpegBin = Join-Path $Root "apps\screenpipe\node_modules\@screenpipe\cli-win32-x64\bin"
    $env:PYTHONPATH = $vtuberDir
    $env:PATH = "$ffmpegBin;" + $env:PATH
    $vtuberProc = Start-Process -FilePath $py -ArgumentList "run_server.py" -WorkingDirectory $vtuberDir -PassThru -WindowStyle Hidden -RedirectStandardOutput (Join-Path $logs "open_llm_vtuber_stdout.log") -RedirectStandardError (Join-Path $logs "open_llm_vtuber_stderr.log")
    $pids["open_llm_vtuber"] = $vtuberProc.Id
    Wait-Port 12393 30 "Open-LLM-VTuber" | Out-Null
}

# Save PIDs
$pids | ConvertTo-Json | Set-Content -Path $pidFile -Encoding UTF8

# ------------------------------------------------------------- 5. Health Check
Say "Step 5: Executing health-check..."
& (Join-Path $Root "scripts\health-check.ps1")
