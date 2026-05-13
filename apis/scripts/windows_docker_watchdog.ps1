#Requires -Version 5.1
<#
.SYNOPSIS
    APIS Docker Watchdog — Phase 81-D (DEC-084) durable mitigation for the
    Docker Desktop Autostart Blocker incident pattern (recurring since
    2026-04-15, most recently 2026-05-12 → 2026-05-13).

.DESCRIPTION
    The Phase 71 in-container healthcheck cannot recover from scenarios
    where the Docker engine pipe is never exposed (Docker Desktop crashed
    or never auto-started after a Windows reboot). When that happens the
    container itself isn't running, so the in-container restart logic has
    nothing to recover from.

    This script runs OUTSIDE Docker as a Windows Scheduled Task. Every
    INTERVAL_SECONDS it checks:
      1. Is Docker Desktop's named pipe responsive?
         If not → start Docker Desktop (Start-Process).
      2. Are the 4 core APIS containers running and healthy?
         If not → cd into compose dir and run `docker compose up -d`.
      3. Has the worker:scheduler_heartbeat key updated within the last
         SCHEDULER_STALE_SECONDS?
         If not → `docker compose restart worker`.

    Every recovery action is logged to WATCHDOG_LOG. The script never
    raises — diagnostics fall through to the next tick.

.PARAMETER ComposeDir
    Path to the directory containing docker-compose.yml. Defaults to the
    APIS infra/docker directory.

.PARAMETER IntervalSeconds
    Sleep between watchdog iterations. Defaults to 120 (2 minutes).

.PARAMETER SchedulerStaleSeconds
    How long the scheduler_heartbeat can lag before we force a worker
    restart. Defaults to 900 (15 minutes — 3x the 5-min heartbeat).

.PARAMETER WatchdogLog
    Path to the rolling watchdog log. Defaults to
    C:\ProgramData\APIS\watchdog.log

.PARAMETER OneShot
    Run a single check and exit (for Task Scheduler "On a schedule"
    triggers). Without this flag the script loops forever (for "At
    startup" triggers).

.EXAMPLE
    # Register with Task Scheduler to run at user logon AND every 5 minutes
    schtasks /Create /TN "APIS Docker Watchdog" `
        /TR "powershell -NoProfile -ExecutionPolicy Bypass -File C:\Projects\Auto Trade Bot\apis\scripts\windows_docker_watchdog.ps1 -OneShot" `
        /SC MINUTE /MO 5 /RL HIGHEST /F

.NOTES
    Phase 81-D / DEC-084 — 2026-05-13. See apis/state/DECISION_LOG.md.
#>
[CmdletBinding()]
param(
    [string]$ComposeDir = "C:\Projects\Auto Trade Bot\apis\infra\docker",
    [int]$IntervalSeconds = 120,
    [int]$SchedulerStaleSeconds = 900,
    [string]$WatchdogLog = "C:\ProgramData\APIS\watchdog.log",
    [string]$DockerDesktopPath = "C:\Program Files\Docker\Docker\Docker Desktop.exe",
    [switch]$OneShot
)

$ErrorActionPreference = "Continue"

# ── Logging helpers ──────────────────────────────────────────────────────────
function Initialize-WatchdogLog {
    $logDir = Split-Path -Path $WatchdogLog -Parent
    if (-not (Test-Path -Path $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
}

function Write-WatchdogEvent {
    param(
        [Parameter(Mandatory)] [string]$Level,
        [Parameter(Mandatory)] [string]$Event,
        [hashtable]$Fields = @{}
    )
    $entry = [ordered]@{
        ts    = (Get-Date).ToString("yyyy-MM-ddTHH:mm:ssK")
        level = $Level
        event = $Event
    }
    foreach ($k in $Fields.Keys) { $entry[$k] = $Fields[$k] }
    $line = ($entry | ConvertTo-Json -Compress)
    try {
        Add-Content -Path $WatchdogLog -Value $line -Encoding UTF8
    } catch {
        # Last-resort: write to stdout so Task Scheduler captures something.
        Write-Host $line
    }
}

# ── Docker engine + container probes ─────────────────────────────────────────
function Test-DockerEngine {
    # `docker version --format` is the cheapest probe of the engine pipe.
    try {
        $null = & docker version --format "{{.Server.Version}}" 2>$null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Start-DockerDesktop {
    if (-not (Test-Path -LiteralPath $DockerDesktopPath)) {
        Write-WatchdogEvent -Level "ERROR" -Event "docker_desktop_executable_missing" `
            -Fields @{ path = $DockerDesktopPath }
        return $false
    }
    Write-WatchdogEvent -Level "WARN" -Event "starting_docker_desktop"
    try {
        Start-Process -FilePath $DockerDesktopPath -WindowStyle Hidden
    } catch {
        Write-WatchdogEvent -Level "ERROR" -Event "docker_desktop_start_failed" `
            -Fields @{ error = $_.Exception.Message }
        return $false
    }
    # Wait up to 120s for the engine pipe to come up.
    $waited = 0
    while ($waited -lt 120) {
        Start-Sleep -Seconds 5
        $waited += 5
        if (Test-DockerEngine) {
            Write-WatchdogEvent -Level "INFO" -Event "docker_desktop_engine_ready" `
                -Fields @{ waited_seconds = $waited }
            return $true
        }
    }
    Write-WatchdogEvent -Level "ERROR" -Event "docker_desktop_engine_did_not_come_up" `
        -Fields @{ waited_seconds = $waited }
    return $false
}

function Get-RunningContainerNames {
    try {
        $out = & docker ps --format "{{.Names}}" 2>$null
        if ($LASTEXITCODE -ne 0) { return @() }
        return ($out | Where-Object { $_ -and $_.Trim() })
    } catch {
        return @()
    }
}

function Start-ApisStack {
    Write-WatchdogEvent -Level "WARN" -Event "starting_apis_stack" `
        -Fields @{ compose_dir = $ComposeDir }
    try {
        Push-Location -Path $ComposeDir
        & docker compose --env-file "..\..\.env" up -d 2>&1 | Out-Null
        $exit = $LASTEXITCODE
    } catch {
        Write-WatchdogEvent -Level "ERROR" -Event "compose_up_threw" `
            -Fields @{ error = $_.Exception.Message }
        return $false
    } finally {
        Pop-Location
    }
    if ($exit -ne 0) {
        Write-WatchdogEvent -Level "ERROR" -Event "compose_up_nonzero_exit" `
            -Fields @{ exit_code = $exit }
        return $false
    }
    Write-WatchdogEvent -Level "INFO" -Event "compose_up_complete"
    return $true
}

function Restart-WorkerContainer {
    Write-WatchdogEvent -Level "WARN" -Event "restarting_worker"
    try {
        Push-Location -Path $ComposeDir
        & docker compose restart worker 2>&1 | Out-Null
        $exit = $LASTEXITCODE
    } finally {
        Pop-Location
    }
    if ($exit -ne 0) {
        Write-WatchdogEvent -Level "ERROR" -Event "worker_restart_nonzero_exit" `
            -Fields @{ exit_code = $exit }
        return $false
    }
    Write-WatchdogEvent -Level "INFO" -Event "worker_restart_complete"
    return $true
}

function Get-SchedulerHeartbeatAge {
    # Returns age in seconds, or -1 if Redis is unreachable / key missing.
    $script = "import os,time,redis,sys;" `
        + "r=redis.Redis.from_url(os.environ.get('APIS_REDIS_URL','redis://localhost:6379/0'));" `
        + "v=r.get('worker:scheduler_heartbeat');" `
        + "sys.stdout.write(str(int(time.time()-float(v))) if v else '-1')"
    try {
        $out = & docker exec docker-worker-1 python -c $script 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $out) { return -1 }
        return [int]$out.Trim()
    } catch {
        return -1
    }
}

# ── Main loop ────────────────────────────────────────────────────────────────
function Invoke-WatchdogTick {
    Write-WatchdogEvent -Level "DEBUG" -Event "tick_start"

    # 1. Docker engine probe ─────────────────────────────────────────────────
    if (-not (Test-DockerEngine)) {
        Write-WatchdogEvent -Level "WARN" -Event "docker_engine_unreachable"
        $started = Start-DockerDesktop
        if (-not $started) {
            Write-WatchdogEvent -Level "ERROR" -Event "tick_aborted_engine_down"
            return
        }
    }

    # 2. Core container running check ────────────────────────────────────────
    $expected = @(
        "docker-postgres-1",
        "docker-redis-1",
        "docker-api-1",
        "docker-worker-1"
    )
    $running = Get-RunningContainerNames
    $missing = @($expected | Where-Object { $running -notcontains $_ })
    if ($missing.Count -gt 0) {
        Write-WatchdogEvent -Level "WARN" -Event "core_containers_missing" `
            -Fields @{ missing = ($missing -join ",") }
        $null = Start-ApisStack
        # Give the stack a moment to settle before the heartbeat check.
        Start-Sleep -Seconds 15
    }

    # 3. Scheduler heartbeat freshness ───────────────────────────────────────
    $hb = Get-SchedulerHeartbeatAge
    if ($hb -lt 0) {
        Write-WatchdogEvent -Level "WARN" -Event "scheduler_heartbeat_unreachable"
    } elseif ($hb -gt $SchedulerStaleSeconds) {
        Write-WatchdogEvent -Level "WARN" -Event "scheduler_heartbeat_stale" `
            -Fields @{ age_seconds = $hb; threshold_seconds = $SchedulerStaleSeconds }
        $null = Restart-WorkerContainer
    } else {
        Write-WatchdogEvent -Level "DEBUG" -Event "scheduler_heartbeat_fresh" `
            -Fields @{ age_seconds = $hb }
    }

    Write-WatchdogEvent -Level "DEBUG" -Event "tick_complete"
}

Initialize-WatchdogLog
Write-WatchdogEvent -Level "INFO" -Event "watchdog_starting" `
    -Fields @{
        compose_dir = $ComposeDir
        interval    = $IntervalSeconds
        one_shot    = [bool]$OneShot
    }

if ($OneShot) {
    Invoke-WatchdogTick
    Write-WatchdogEvent -Level "INFO" -Event "watchdog_one_shot_complete"
} else {
    while ($true) {
        try {
            Invoke-WatchdogTick
        } catch {
            Write-WatchdogEvent -Level "ERROR" -Event "tick_uncaught_exception" `
                -Fields @{ error = $_.Exception.Message }
        }
        Start-Sleep -Seconds $IntervalSeconds
    }
}
