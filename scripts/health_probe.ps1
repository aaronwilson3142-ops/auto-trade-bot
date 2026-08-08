# APIS lightweight health probe - installed 2026-08-08 (Cowork health-check session)
# Runs 3x/day via Windows Task Scheduler (05:05 / 10:05 / 14:05 CT). No AI involved.
# Appends one line to state\AUTO_PROBE_LOG.md, commits + pushes so the cloud
# watchdog trigger (apis-health-check-v3) can verify the machine is alive.
# Silence in git = machine off or probe broken -> watchdog push-notifies Aaron.

$ErrorActionPreference = 'Continue'
$repo = 'C:\Projects\Auto Trade Bot'
$log  = Join-Path $repo 'state\AUTO_PROBE_LOG.md'
$now  = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd HH:mm')
$issues = @()
$verdict = 'GREEN'

# 1. Expected APIS containers all running
$expected = @('docker-worker-1','docker-api-1','docker-postgres-1','docker-redis-1',
              'docker-grafana-1','docker-prometheus-1','docker-alertmanager-1')
$up = @(docker ps --format '{{.Names}}' 2>$null)
$missing = @($expected | Where-Object { $up -notcontains $_ })
if ($missing.Count -gt 0) { $verdict = 'RED'; $issues += ('containers_down:' + ($missing -join '+')) }

# 2. /health endpoint
$h = $null
try {
  $h = Invoke-RestMethod -Uri 'http://localhost:8000/health' -TimeoutSec 15
  if ($h.status -ne 'ok') {
    if ($verdict -ne 'RED') { $verdict = 'YELLOW' }
    $issues += ('health:' + $h.status)
  }
  if ($h.components.kill_switch -ne 'ok') { $verdict = 'RED'; $issues += 'kill_switch_engaged' }
} catch {
  $verdict = 'RED'; $issues += 'health_unreachable'
}

# 3. $1.00 phantom fills in last 7 days (Phase 87 regression check)
$fills = docker exec docker-postgres-1 psql -U apis -d apis -tAc "SELECT count(*) FROM fills WHERE fill_price=1.0 AND fill_timestamp > now() - interval '7 days'" 2>$null
if ($LASTEXITCODE -ne 0 -or $null -eq $fills -or $fills.Trim() -eq '') {
  if ($verdict -ne 'RED') { $verdict = 'YELLOW' }
  $issues += 'db_probe_failed'
} elseif ([int]$fills.Trim() -gt 0) {
  $verdict = 'RED'; $issues += ('dollar_fills_7d:' + $fills.Trim())
}

# 4. Paper-cycle snapshot recency (78h tolerates weekends + Monday pre-open)
$snapAge = docker exec docker-postgres-1 psql -U apis -d apis -tAc "SELECT round(extract(epoch FROM (now() - max(snapshot_timestamp)))/3600) FROM portfolio_snapshots WHERE mode='paper'" 2>$null
if ($snapAge -and $snapAge.Trim() -ne '') {
  if ([double]$snapAge.Trim() -gt 78) {
    if ($verdict -ne 'RED') { $verdict = 'YELLOW' }
    $issues += ('snapshot_stale_h:' + $snapAge.Trim())
  }
}

# 5. Append log line + commit + push (probe files only)
if ($issues.Count -gt 0) { $detail = ($issues -join ', ') }
else { $detail = 'all nominal (containers 7/7, health ok, 0 dollar-fills 7d, snapshots fresh)' }
$line = "- $now UTC | $verdict | $detail"
Add-Content -Path $log -Value $line -Encoding UTF8

Set-Location $repo
git add 'state/AUTO_PROBE_LOG.md' 'scripts/health_probe.ps1' 2>&1 | Out-Null
git commit -m "state: auto-probe $now UTC - $verdict" 2>&1 | Out-Null
git push origin main 2>&1 | Out-Null
exit 0
