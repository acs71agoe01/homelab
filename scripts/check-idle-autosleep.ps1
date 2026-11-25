# Scheduled every 5 minutes as SYSTEM. Suspends to S3 only when headless & idle.
$stateFile = "C:\ProgramData\OllamaAutoSleep\idle_count.txt"

if (Get-Process -Name explorer -ErrorAction SilentlyContinue) {
    Set-Content -Path $stateFile -Value "0"
    exit 0
}

$busy = $false
try {
    $ps = Invoke-RestMethod -Uri "http://127.0.0.1:11434/api/ps" -TimeoutSec 3
    if ($ps.models -and $ps.models.Count -gt 0) { $busy = $true }
} catch { $busy = $true }

if (Get-NetTCPConnection -LocalPort 11434 -State Established -ErrorAction SilentlyContinue) {
    $busy = $true
}

if ($busy) {
    Set-Content -Path $stateFile -Value "0"
    exit 0
}

$count = 0
if (Test-Path $stateFile) { [void][int]::TryParse((Get-Content $stateFile -Raw).Trim(), [ref]$count) }
$count++

if ($count -ge 2) {
    Set-Content -Path $stateFile -Value "0"
    Add-Type -MemberDefinition '[DllImport("powrprof.dll", SetLastError=true)] public static extern bool SetSuspendState(bool hibernate, bool forceCritical, bool disableWakeEvent);' -Name Power -Namespace Win32
    [Win32.Power]::SetSuspendState($false, $false, $false)
} else {
    Set-Content -Path $stateFile -Value "$count"
}
