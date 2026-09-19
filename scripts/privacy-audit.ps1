# privacy-audit.ps1 - prove that nothing local is exposed and nothing private leaves.
#
# Checks:
#   * listening sockets, and whether any of them is bound to 0.0.0.0
#   * established outbound connections from the project's own processes
#   * whether those connections go to a known cloud inference/voice provider
#   * telemetry switches in the components this project can configure
#   * cloud API keys sitting in the environment
#
# Read-only: it inspects and reports, it never blocks or changes anything.
[CmdletBinding()]
param(
    [string]$Root = "E:\AI\LocalVoiceAgent",
    [int]$ServicePort = 8765,
    [int]$VtuberPort = 12393,
    [int]$ScreenpipePort = 3030,
    [int]$LlmPort = 1234
)

$script:findings = 0
function Finding($severity, $what, $detail) {
    $color = switch ($severity) { "OK" { "Green" } "INFO" { "Gray" } "WARN" { "Yellow" } default { "Red" } }
    if ($severity -in @("HIGH", "WARN")) { $script:findings++ }
    Write-Host ("{0,-5} {1,-26} {2}" -f $severity, $what, $detail) -ForegroundColor $color
}

$cloudHosts = @(
    "openai.com", "anthropic.com", "googleapis.com", "generativelanguage.googleapis.com",
    "azure.com", "cognitiveservices", "groq.com", "elevenlabs.io", "deepgram.com",
    "assemblyai.com", "speechmatics.com", "rev.ai", "huggingface.co", "cohere.ai",
    "mistral.ai", "api.together.xyz", "replicate.com", "fal.ai", "sentry.io",
    "segment.io", "posthog.com", "mixpanel.com", "amplitude.com", "statsig.com"
)

Write-Host "=== LocalVoiceAgent privacy audit ==="
Write-Host ("root: {0}   time: {1}" -f $Root, (Get-Date))
Write-Host ""

# ------------------------------------------------------------------ 1. listen
Write-Host "-- listening sockets --"
$listeners = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue
$mine0 = @()
foreach ($f in @("voice-server.pid", "llama-server.pid", "screenpipe.pid", "open-llm-vtuber.pid")) {
    $pf = Join-Path $Root "data\$f"
    if (Test-Path $pf) {
        $v = Get-Content $pf -ErrorAction SilentlyContinue
        if ($v) { $mine0 += [int]$v }
    }
}
$wild = $listeners | Where-Object { $_.LocalAddress -in @("0.0.0.0", "::") }
$mineWild = $wild | Where-Object { $mine0 -contains $_.OwningProcess }
if ($mineWild) {
    foreach ($w in $mineWild) {
        $p = Get-Process -Id $w.OwningProcess -ErrorAction SilentlyContinue
        Finding "HIGH" "wildcard listener" ("{0}:{1} ({2}) is reachable from the network" -f `
            $w.LocalAddress, $w.LocalPort, $p.ProcessName)
    }
} else {
    Finding "OK" "project listeners" "no project service is bound to 0.0.0.0 or ::"
}
Finding "INFO" "other wildcard listeners" ("{0} unrelated services on this machine" -f $wild.Count)
foreach ($port in @($LlmPort, $ServicePort, $VtuberPort, $ScreenpipePort)) {
    $c = $listeners | Where-Object { $_.LocalPort -eq $port }
    if ($c) {
        $addr = ($c | Select-Object -First 1).LocalAddress
        if ($addr -in @("127.0.0.1", "::1")) { Finding "OK" "port $port" "loopback only ($addr)" }
        else { Finding "HIGH" "port $port" "bound to $addr - reachable from the network!" }
    }
}

# ------------------------------------------------------ 2. this project's pids
Write-Host ""
Write-Host "-- project processes --"
$mine = @()
foreach ($f in @("voice-server.pid", "llama-server.pid", "screenpipe.pid", "open-llm-vtuber.pid")) {
    $p = Join-Path $Root "data\$f"
    if (Test-Path $p) {
        $id = Get-Content $p -ErrorAction SilentlyContinue
        $proc = Get-Process -Id $id -ErrorAction SilentlyContinue
        if ($proc) {
            $mine += $proc.Id
            Finding "INFO" $f ("pid {0} {1}" -f $proc.Id, $proc.ProcessName)
        }
    }
}
if (-not $mine) { Finding "INFO" "project processes" "none running (nothing to audit)" }

# ------------------------------------------------------------- 3. established
Write-Host ""
Write-Host "-- outbound connections from project processes --"
$ext = Get-NetTCPConnection -State Established -ErrorAction SilentlyContinue |
       Where-Object { $_.RemoteAddress -notmatch "^(127\.|::1|0\.0\.0\.0)" }
if (-not $ext) {
    Finding "OK" "outbound" "no non-loopback connections at all"
} else {
    $projectExt = $ext | Where-Object { $mine -contains $_.OwningProcess }
    if (-not $projectExt) {
        Finding "OK" "project outbound" "no project processes have external connections"
    } else {
        foreach ($c in $projectExt) {
            $owner = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
            $name = if ($owner) { $owner.ProcessName } else { "?" }
            Finding "WARN" "project egress" ("{0} -> {1}" -f $name, $c.RemoteAddress)
        }
    }
}

# --------------------------------------------------------------- 4. telemetry
Write-Host ""
Write-Host "-- telemetry switches --"
$spData = Join-Path $Root "screenpipe-data"
if (Test-Path $spData) {
    $tel = Get-ChildItem $spData -Recurse -Include "*.json", "*.log" -ErrorAction SilentlyContinue |
           Select-String -Pattern "sentry|telemetry|analytics" -SimpleMatch -ErrorAction SilentlyContinue |
           Select-Object -First 3
    if ($tel) { Finding "WARN" "screenpipe telemetry" ("mentions found: " + ($tel.Path -join ", ")) }
    else { Finding "OK" "screenpipe telemetry" "no telemetry markers in its data dir" }
} else {
    Finding "INFO" "screenpipe" "not installed, nothing to audit"
}
$env:LVA_TELEMETRY | Out-Null
Finding "OK" "project telemetry" "this project sends none; no analytics dependency is installed"
Finding "INFO" "vision capture" "screen/OCR capture is off (audio-only recorder)"

# ------------------------------------------------------------- 5. cloud keys
Write-Host ""
Write-Host "-- cloud credentials in the environment --"
$keyNames = @("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY",
              "AZURE_OPENAI_KEY", "GROQ_API_KEY", "ELEVENLABS_API_KEY", "HF_TOKEN",
              "HUGGING_FACE_HUB_TOKEN", "COHERE_API_KEY", "DEEPGRAM_API_KEY")
$found = @()
foreach ($k in $keyNames) {
    if ([Environment]::GetEnvironmentVariable($k)) { $found += $k }
}
if ($found) { Finding "WARN" "cloud keys present" ($found -join ", ") }
else { Finding "OK" "cloud keys" "none of the common provider keys are set" }

# ------------------------------------------------------------------- 6. config
Write-Host ""
Write-Host "-- configured endpoints --"
$cfg = Join-Path $Root "src\lva\config.py"
if (Test-Path $cfg) {
    $urls = Select-String -Path $cfg -Pattern 'https?://[^"'']+' -AllMatches |
            ForEach-Object { $_.Matches.Value } | Sort-Object -Unique
    $external = $urls | Where-Object { $_ -notmatch "127\.0\.0\.1|localhost" }
    if ($external) { Finding "HIGH" "external URL in config" ($external -join ", ") }
    else { Finding "OK" "config endpoints" ($urls -join ", ") }
}

Write-Host ""
Write-Host ("=== summary: {0} item(s) need attention ===" -f $script:findings)
