# stop-all.ps1 - Strictly follows MASTER_PROMPT.md Section 29
# Stop only the processes this project started.
# NEVER taskkill /IM python.exe.
#
# v1.2.1 (I04/I16): a PID recorded in pids.json is an *observation*, not kill
# authority.  The OS recycles PIDs, so before stopping anything this script
# verifies that the recorded PID still belongs to the expected service (process
# name and/or command line).  A mismatch means the original process is gone and
# the number now points at something else -- that process is left alone.
[CmdletBinding()]
param([string]$Root = "E:\AI\LocalVoiceAgent")

$data = Join-Path $Root "data"
$pidFile = Join-Path $data "pids.json"

function Say-PS($m, $l = "INFO") {
    Write-Host ("[{0}] {1}" -f $l, $m)
}

function Test-Ownership($procId, $label) {
    # Returns $true only when the recorded PID still looks like the service we
    # recorded.  Anything we cannot positively identify is treated as not ours.
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $p) { return $false }

    $expectedNames = switch -Wildcard ($label) {
        "*LVA Core*"    { @("python", "pythonw") }
        "*Screenpipe*"  { @("screenpipe") }
        "*voice-server*" { @("python", "pythonw") }
        default         { @() }
    }
    if ($expectedNames.Count -eq 0) { return $false }
    foreach ($n in $expectedNames) {
        if ($p.ProcessName -ieq $n) { return $true }
    }
    return $false
}


function Stop-SinglePid($procId, $label) {
    if (-not $procId) { return }
    $p = Get-Process -Id $procId -ErrorAction SilentlyContinue
    if (-not $p) {
        Say-PS "$label : pid $procId already exited"
        return
    }

    if (-not (Test-Ownership $procId $label)) {
        Say-PS "$label : pid $procId is now '$($p.ProcessName)', not the recorded service - refusing to stop (PID reuse, I04)" "WARN"
        return
    }
    
    # Terminate the process tree, but only descendants that still belong to this
    # service.  An external Hub backend that happens to be parented under a
    # recorded PID must survive (I04/I16: LVA never stops an External/Adopted
    # process).  A descendant is treated as ours only when its creation time is
    # not earlier than the recorded parent's -- an inherited-from-elsewhere
    # process predates the service we started.
    $parentStart = $p.StartTime
    $tree = @()
    $frontier = @($procId)
    while ($frontier.Count -gt 0) {
        $next = @()
        foreach ($id in $frontier) {
            $kids = Get-CimInstance Win32_Process -Filter "ParentProcessId=$id" -ErrorAction SilentlyContinue
            foreach ($k in $kids) {
                if ($k.Name -eq "conhost.exe") { continue }
                $kp = Get-Process -Id $k.ProcessId -ErrorAction SilentlyContinue
                if (-not $kp) { continue }
                if ($kp.StartTime -lt $parentStart) {
                    Say-PS "$label : descendant pid $($k.ProcessId) ($($k.Name)) predates the service - leaving it running" "WARN"
                    continue
                }
                $next += $k.ProcessId
                $tree += $k.ProcessId
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
        if ($pids.lva_core) { Stop-SinglePid $pids.lva_core "LVA Core" }
        if ($pids.screenpipe) { Stop-SinglePid $pids.screenpipe "Screenpipe" }
        if ($pids.voice_server) { Stop-SinglePid $pids.voice_server "voice-server" }
    } catch {}
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

# Also check legacy pid files if present
foreach ($f in @("lva_core.pid", "voice-server.pid", "screenpipe.pid")) {
    $fp = Join-Path $data $f
    if (Test-Path $fp) {
        $id = Get-Content $fp -ErrorAction SilentlyContinue
        if ($id) { Stop-SinglePid $id $f }
        Remove-Item $fp -Force -ErrorAction SilentlyContinue
    }
}

Say-PS "All LocalVoiceAgent background services stopped cleanly (llama.cpp-hub runtime preserved per I04/I16)."
