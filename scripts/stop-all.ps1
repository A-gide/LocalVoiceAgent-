# stop-all.ps1 - Strictly follows MASTER_PROMPT.md Section 29
# Stop only the processes this project started.
# NEVER taskkill /IM python.exe.
[CmdletBinding()]
param([string]$Root = "E:\AI\LocalVoiceAgent")

$data = Join-Path $Root "data"
$pidFile = Join-Path $data "pids.json"

function Say-PS($m, $l = "INFO") {
    Write-Host ("[{0}] {1}" -f $l, $m)
}

function Stop-SinglePid($procId, $label) {
    if (-not $procId) { return }
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $p) {
        Say-PS "$label : pid $procId already exited"
        return
    }
    
    # Terminate process tree
    $tree = @()
    $frontier = @($procId)
    while ($frontier.Count -gt 0) {
        $next = @()
        foreach ($id in $frontier) {
            $kids = Get-CimInstance Win32_Process -Filter "ParentProcessId=$id" -ErrorAction SilentlyContinue
            foreach ($k in $kids) {
                if ($k.Name -ne "conhost.exe") { $next += $k.ProcessId; $tree += $k.ProcessId }
            }
        }
        $frontier = $next
    }
    foreach ($id in ($tree | Sort-Object -Descending)) {
        try { Stop-Process -Id $id -Force -ErrorAction SilentlyContinue; Say-PS "$label : stopped child pid $id" } catch {}
    }
    try {
        Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
        Say-PS "$label : stopped pid $procId"
    } catch {
        Say-PS "$label : could not stop pid $procId - $_" "WARN"
    }
}

Say-PS "Stopping LocalVoiceAgent services..."

if (Test-Path $pidFile) {
    try {
        $pids = Get-Content $pidFile -Raw | ConvertFrom-Json
        if ($pids.open_llm_vtuber) { Stop-SinglePid $pids.open_llm_vtuber "Open-LLM-VTuber" }
        if ($pids.screenpipe) { Stop-SinglePid $pids.screenpipe "Screenpipe" }
        if ($pids.llama_server) { Stop-SinglePid $pids.llama_server "llama-server" }
        if ($pids.voice_server) { Stop-SinglePid $pids.voice_server "voice-server" }
    } catch {}
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

# Also check legacy pid files if present
foreach ($f in @("voice-server.pid", "screenpipe.pid", "llama-server.pid", "open-llm-vtuber.pid")) {
    $fp = Join-Path $data $f
    if (Test-Path $fp) {
        $id = Get-Content $fp -ErrorAction SilentlyContinue
        if ($id) { Stop-SinglePid $id $f }
        Remove-Item $fp -Force -ErrorAction SilentlyContinue
    }
}

# Stop LLM server if started by our scripts
$llmServe = Join-Path $Root "scripts\llm_serve.py"
if (Test-Path $llmServe) {
    & (Join-Path $Root "venv\Scripts\python.exe") $llmServe --stop
}

Say-PS "All LocalVoiceAgent background services stopped cleanly."
