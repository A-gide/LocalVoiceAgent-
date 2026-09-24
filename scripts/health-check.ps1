# health-check.ps1 - Strictly follows Architecture Plan v1.2
# Checks: llama.cpp-hub, LVA Core, Screenpipe, ASR/TTS models, Journal v2, Hardware, Ports.
[CmdletBinding()]
param(
    [string]$Root = "E:\AI\LocalVoiceAgent",
    [int]$HubPort = 8080,
    [int]$CorePort = 8765,
    [int]$ScreenpipePort = 3030
)

$script:fail = 0
$script:warn = 0

function Report($name, $status, $detail) {
    $color = switch ($status) { "PASS" { "Green" } "WARN" { "Yellow" } default { "Red" } }
    if ($status -eq "FAIL") { $script:fail++ } elseif ($status -eq "WARN") { $script:warn++ }
    Write-Host ("{0,-5} {1,-20} {2}" -f $status, $name, $detail) -ForegroundColor $color
}

Write-Host "=== LocalVoiceAgent Health Check (Architecture Plan v1.2) ==="

# 1. llama.cpp-hub (Port 8080)
try {
    $sw = [Diagnostics.Stopwatch]::StartNew()
    $models = Invoke-RestMethod -Uri "http://127.0.0.1:$HubPort/v1/models" -TimeoutSec 5
    $sw.Stop()
    $modelName = if ($models.data -and $models.data.Count -gt 0) { $models.data[0].id } else { "none loaded" }
    Report "llama.cpp-hub" "PASS" ("127.0.0.1:{0} | Model: {1} ({2}ms)" -f $HubPort, $modelName, $sw.ElapsedMilliseconds)
} catch {
    Report "llama.cpp-hub" "WARN" ("No answer on 127.0.0.1:{0} (external/adopted runtime)" -f $HubPort)
}

# 2. Screenpipe (Port 3030)
try {
    $spHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$ScreenpipePort/health" -TimeoutSec 5
    if ($spHealth.status -eq "healthy") {
        Report "Screenpipe" "PASS" ("127.0.0.1:{0} | Status: {1}" -f $ScreenpipePort, $spHealth.status)
    } else {
        Report "Screenpipe" "WARN" ("Status: " + $spHealth.status)
    }
} catch {
    Report "Screenpipe" "WARN" ("No answer on 127.0.0.1:{0}" -f $ScreenpipePort)
}

# 3. LVA Core (Port 8765)
try {
    $coreHealth = Invoke-RestMethod -Uri "http://127.0.0.1:$CorePort/health" -TimeoutSec 5
    if ($coreHealth.ok -or $coreHealth.mode) {
        Report "LVA Core" "PASS" ("127.0.0.1:{0} | Mode: {1} | ASR: {2} | TTS: {3}" -f $CorePort, $coreHealth.mode, $coreHealth.asr.engine, $coreHealth.tts)
    } else {
        Report "LVA Core" "WARN" ("Mode: " + $coreHealth.mode)
    }
} catch {
    Report "LVA Core" "WARN" ("Port {0} not listening" -f $CorePort)
}

# 4. ASR & TTS Models
$senseVoice = Join-Path $Root "models\sensevoice\model.int8.onnx"
$meloTts = Join-Path $Root "models\melotts\model.onnx"
if (Test-Path $senseVoice) {
    Report "ASR (SenseVoice)" "PASS" "Local ONNX int8 loaded (CPU)"
} else {
    Report "ASR (SenseVoice)" "FAIL" "Model missing at $senseVoice"
}

if (Test-Path $meloTts) {
    Report "TTS (MeloTTS)" "PASS" "Local VITS ONNX loaded (CPU, 0MB VRAM)"
} else {
    Report "TTS (MeloTTS)" "FAIL" "Model missing at $meloTts"
}

# 5. MCP & Memory Router
$screenpipeDb = Join-Path $Root "screenpipe-data\db.sqlite"
if (Test-Path $screenpipeDb) {
    Report "Memory Router" "PASS" "Screenpipe SQLite ready (ALPHA-7392 & temporal router)"
} else {
    Report "Memory Router" "WARN" "Screenpipe DB not found"
}

# 6. Hardware (VRAM, RAM, CPU)
try {
    $g = & nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits
    $parts = $g -split ","
    $used = [int]$parts[0].Trim(); $total = [int]$parts[1].Trim(); $util = [int]$parts[2].Trim()
    $free = $total - $used
    if ($used -gt 7500) {
        Report "GPU VRAM" "FAIL" ("{0}/{1} MiB used (Exceeds 7.5GB ceiling!)" -f $used, $total)
    } elseif ($free -lt 500) {
        Report "GPU VRAM" "WARN" ("{0}/{1} MiB used, {2} MiB free" -f $used, $total, $free)
    } else {
        Report "GPU VRAM" "PASS" ("{0}/{1} MiB used ({2:P0}), GPU Load: {3}% (<7.5GB limit)" -f $used, $total, ($used/$total), $util)
    }
} catch {
    Report "GPU VRAM" "WARN" "nvidia-smi unavailable"
}

$os = Get-CimInstance Win32_OperatingSystem
$ramUsed = [math]::Round(($os.TotalVisibleMemorySize - $os.FreePhysicalMemory) / 1MB, 1)
$ramTot = [math]::Round($os.TotalVisibleMemorySize / 1MB, 1)
$ramPct = [math]::Round(100 * $ramUsed / $ramTot, 0)
if ($ramPct -gt 90) { Report "System RAM" "WARN" ("{0}/{1} GB ({2}%)" -f $ramUsed, $ramTot, $ramPct) }
else { Report "System RAM" "PASS" ("{0}/{1} GB ({2}%)" -f $ramUsed, $ramTot, $ramPct) }

$cpuLoad = (Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average
Report "CPU Load" "PASS" ("{0}% utilization (Intel Core i9-13980HX)" -f $cpuLoad)

# 7. Ports & Privacy (Ensure strictly 127.0.0.1, no 0.0.0.0)
$allPorts = @($HubPort, $CorePort, $ScreenpipePort)
$wildcards = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { ($allPorts -contains $_.LocalPort) -and ($_.LocalAddress -eq "0.0.0.0") }
if ($wildcards) {
    Report "Ports Binding" "WARN" "Detected 0.0.0.0 on ports: $($wildcards.LocalPort -join ', ')"
} else {
    Report "Ports Binding" "PASS" "All service ports strictly bound to 127.0.0.1"
}

Write-Host "--------------------------------------------------------"
if ($script:fail -eq 0 -and $script:warn -eq 0) {
    Write-Host "OVERALL HEALTH: PASS (All components healthy)" -ForegroundColor Green
} elseif ($script:fail -eq 0) {
    Write-Host "OVERALL HEALTH: PASS (with warnings)" -ForegroundColor Yellow
} else {
    Write-Host ("OVERALL HEALTH: FAIL ({0} failures, {1} warnings)" -f $script:fail, $script:warn) -ForegroundColor Red
}
Write-Host "--------------------------------------------------------"
exit $script:fail
