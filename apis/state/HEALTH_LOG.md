# APIS Health Log

Auto-generated daily health check results.

---

## Health Check — 2026-04-17 10:11 UTC (Friday, pre-market 06:11 ET)

**Overall Status:** 🟡 → ✅ GREEN (after fix) — Discovered and fixed a critical DB schema mismatch blocking portfolio/state restore. Three pending Alembic migrations applied. API restarted. All /health components now `ok`.

### Container Status
All 7 APIS containers `Up 7 hours`:
- docker-api-1 — Up 7h (healthy) → restarted at 10:15 UTC as part of fix
- docker-worker-1 — Up 7h (healthy)
- docker-postgres-1 — Up 7h (healthy), port 5432
- docker-redis-1 — Up 7h (healthy), port 6379
- docker-prometheus-1 — Up 7h, port 9090
- docker-grafana-1 — Up 7h, port 3000
- docker-alertmanager-1 — Up 7h, port 9093
(Plus unrelated `apis-control-plane` kind node.)

### Initial API Health Endpoint (before fix)
`paper_cycle: no_data` — all other components `ok`. Root cause traced to startup restore failures.

### Root Cause: Missing DB Migrations
API startup at 2026-04-17T03:31 UTC logged three restore failures:
- `load_portfolio_snapshot_failed` — `column portfolio_snapshots.idempotency_key does not exist`
- `portfolio_state_restore_failed` — same missing column
- `closed_trades_restore_failed` — `column positions.origin_strategy does not exist`

Alembic `current` = `j0k1l2m3n4o5`; `heads` = `m3n4o5p6q7r8`. Three migrations pending:
1. `k1l2m3n4o5p6_add_idempotency_keys` — adds `idempotency_key` col + unique index on `portfolio_snapshots`, `position_history`, `evaluation_runs` (Deep-Dive Step 2 Rec 4).
2. `l2m3n4o5p6q7_add_position_origin_strategy` — adds `positions.origin_strategy` (Deep-Dive Step 5 Rec 7).
3. `m3n4o5p6q7r8_add_proposal_outcomes` — creates new `proposal_outcomes` table (Deep-Dive Step 6 Rec 10).

These migration files are dated 2026-04-16/17 and track the Deep-Dive Plan (memory: `project_deep_dive_review_2026-04-16.md`). Their ORM models landed but the migrations were never applied against the running DB — likely because Alembic is not wired into worker/api startup and no manual `alembic upgrade` was run.

### Fix Applied
1. `docker exec -w /app/apis docker-worker-1 alembic upgrade head` — all 3 migrations applied cleanly; new head = `m3n4o5p6q7r8`. All changes are additive (nullable column adds + new table) so no existing data was affected.
2. `docker restart docker-api-1` — triggered `_load_persisted_state` with the new schema.

### Post-Fix Verification
`GET /health` → all components `ok` (db, broker, scheduler, paper_cycle, broker_auth, kill_switch).
New startup log shows:
- `portfolio_snapshot_restored` equity=94,403.69, last_cycle_at=2026-04-16 19:30:04 UTC (yesterday's 15:30 ET close).
- `portfolio_state_restored_from_db` positions=5, cash=$44,326.61, equity=$94,403.69 (clean, positive cash — phantom-cash guard not triggered).
- `closed_trades_restored_from_db` count=99.
- `evaluation_history_restored_from_db` count=84.
- `paper_cycle_count_restored`=15.

### Worker — Yesterday's Paper Cycles (2026-04-16)
7 paper_trading_cycle_complete events (13:35–19:30 UTC = 09:35–15:30 ET). Executed counts: 10, 0, 10, 0, 10, 0, 10 — alternating pattern. Proposed=10, Approved=10 every cycle. Not an error per se (every other cycle the rebalancer nets no changes) but worth noting: this pattern looks similar to the pre-Phase-65 alternating churn. Phase 65 fix landed 2026-04-16 AM; first full-day data is today's trading. Watch today's 09:35+ cycles for the same pattern.

### Signal & Ranking Pipeline
Yesterday: signal_generation 10:30 UTC → 498 tickers, 2490 signals; ranking_generation 10:45 UTC → 15 ranked. Today both are scheduled for 10:30/10:45 UTC (06:30/06:45 ET) — next_run confirmed in job registry.

### Prometheus
`apis` scrape target health=up, lastScrape 10:16:01 UTC, lastError="". `prometheus` self-scrape also up. 0 dropped targets.

### Database
`pg_isready` → accepting connections. Latest snapshots (Paper):
- 2026-04-16 19:30:04 UTC — cash 44,326.61 / equity 94,403.69
- 2026-04-16 19:30:02 UTC — cash 1,587.43 / equity 99,950.09
- 2026-04-16 18:30:05 UTC — cash 65,409.33 / equity 94,229.05

### Known Issues & Data Quality
1. **13 stale delisted tickers (non-blocking):** unchanged from prior runs — WRK, K, CTLT, ANSS, MMC, HES, PARA, DFS, PXD, JNPR, IPG, MRO, PKI still yfinance-fail. Ingestion completes PARTIAL on the remaining 503 tickers.
2. **Pre-existing warnings (non-blocking, not introduced today):**
   - `regime_result_restore_failed: detection_basis_json` — JSON field naming mismatch in regime_result restore path.
   - `readiness_report_restore_failed: ReadinessGateRow.__init__() missing 1 required positional argument: 'description'` — ORM/builder mismatch in readiness gate restore. Live-Mode Readiness Report update runs on its own schedule and succeeds — this only affects the in-memory restore-on-startup cache.
   Both were present in the 2026-04-15 restart logs; leaving for operator review since they don't block paper trading.
3. **Alternating executed_count (10/0/10/0) on 2026-04-16:** watch today's cycles to confirm Phase 65 fix holds.

### Fixes Applied This Run
- **CRITICAL FIX:** Ran `alembic upgrade head` inside worker container (j0k1l2m3n4o5 → m3n4o5p6q7r8, 3 migrations). Restarted docker-api-1 to re-run `_load_persisted_state` with correct schema. Portfolio state, snapshot, and closed trades now restore cleanly.

### Action Items
- Watch today's 06:30 ET signal_generation and 09:35 ET first paper cycle (executed_count should be > 0 after Phase 61 price-injection fix — the Phase 60/61 validation now has a clean-state DB to validate against).
- Consider adding `alembic upgrade head` to api/worker container startup (entrypoint script) so future schema drift self-heals. Currently the DB can drift from code if an operator forgets the manual migration step.
- Investigate alternating 10/0 executed_count on 2026-04-16 after today's cycles run — could be benign (no-op rebalance every other cycle) or Phase 65 regression.
- Pre-existing `readiness_report_restore_failed` and `regime_result_restore_failed` warnings remain open for operator review.

---

## Health Check — 2026-04-16 10:15 UTC (Thursday, pre-market 06:15 ET)

**Overall Status:** ✅ GREEN — Stack stable after yesterday's Docker Desktop recovery. All containers healthy, all /health components ok, pre-market ingestion pipeline ran cleanly. One non-blocking data-quality issue flagged (13 delisted tickers in universe).

### Container Status
All 7 APIS containers `Up` (17–23 hours uptime, all reporting healthy where healthcheck is defined):
- docker-api-1 — Up 17h (healthy), port 8000
- docker-worker-1 — Up 17h (healthy)
- docker-postgres-1 — Up 23h (healthy), port 5432
- docker-redis-1 — Up 23h (healthy), port 6379
- docker-prometheus-1 — Up 23h, port 9090
- docker-grafana-1 — Up 23h, port 3000
- docker-alertmanager-1 — Up 23h, port 9093

### API Health Endpoint
`GET /health` → `status=ok, service=api, mode=paper`. All components `ok`: db, broker, scheduler, paper_cycle, broker_auth, kill_switch.

### Worker — Pre-Market Pipeline (today)
Ingestion pipeline ran cleanly this morning:
- 06:00 ET — Market Data Ingestion: 498 tickers, 121,239 bars, status=PARTIAL (13 delisted failures — see below)
- 06:05 ET — Alternative Data Ingestion: 498 records stored
- 06:10 ET — Intel Feed Ingestion: 5 policy signals + 8 news insights, status=ok
- 06:30 ET — Signal Generation (scheduled, not yet run at check time 06:15 ET)
- 09:35 ET — First paper trading cycle (scheduled)

No ERROR/CRITICAL lines other than expected yfinance delisting warnings. No `execution_rejected_zero_quantity`, no `portfolio_state_sync_failed`, no `persist_portfolio_snapshot_failed`.

### Worker — Yesterday's Paper Cycles (2026-04-15)
3 paper_trading_cycle_complete events observed (17:30, 18:30, 19:30 UTC = 13:30/14:30/15:30 ET), all with `proposed_count=0, approved_count=0, executed_count=0`. Root cause: worker scheduler initialized at 17:12 UTC (13:12 ET) after Docker Desktop recovery, past the 06:30 ET signal-generation window, so no fresh signals/rankings were available for those cycles. Not a regression; expected consequence of yesterday's late-day stack restart. Today's 06:30 ET signal generation is on the original schedule.

### Signal & Ranking Pipeline
Signal Generation registered with next_run 2026-04-16 06:30:00 EDT (i.e. ~15 min after this check). Signal Quality Update ran successfully yesterday 17:20 ET (skipped_no_trades — expected, no closed paper trades yet).

### Prometheus
`apis` scrape target health=up, scrapeUrl `http://api:8000/metrics`, lastScrape 2026-04-16T10:13:12Z, lastScrapeDuration=2.5ms, lastError="". `prometheus` self-scrape also up. 0 dropped targets.

### Database
`pg_isready` → accepting connections. `/health db=ok` confirms app-layer DB connectivity. (Detailed snapshot query skipped — Windows cmd quoting issues; app health endpoint is authoritative.)

### Known Issues & Data Quality
1. **13 stale tickers in universe (non-blocking):** `JNPR, MMC, WRK, PARA, K, HES, PKI, IPG, DFS, MRO, CTLT, PXD, ANSS` all fail yfinance lookups as "possibly delisted". These are legacy S&P 500 names that have been merged/renamed/removed (e.g. JNPR→HPE 2025 merger, PXD→XOM 2024). Ingestion completes with status=PARTIAL on the remaining 498 tickers; no pipeline failure. **Recommended follow-up (not applied this run):** prune these 13 symbols from the seed list in `apis/infra/db/seed_securities.py` or add a delisted flag. Left for operator review — not attempting autonomous fix because it touches the security master seed and the Phase A/A.2 Norgate point-in-time universe work may be the cleaner path.
2. **Yesterday's 3 paper cycles with 0 executions:** explained above — not a Phase 60 regression.

### Fixes Applied This Run
None — no issues meeting the autonomous-fix criteria were found.

### Action Items
- Watch today's 09:35 ET paper cycle for `executed_count > 0` once universe ticker stale-data isn't the gate.
- Operator: consider pruning 13 delisted tickers from seed or enabling `APIS_UNIVERSE_SOURCE=pointintime` now that Phase A.2 is landed.
- Docker Desktop autostart blocker remains open (tracked in memory `project_docker_desktop_autostart_blocker.md`) — recommend migrating off GUI-gated Docker Desktop.

---

## Health Check — 2026-04-15 11:19 UTC (third run, post-recovery)

**Overall Status:** ✅ GREEN — Docker Desktop blocker resolved. Stack is up and healthy. Pre-market (07:19 ET); first paper cycle scheduled for 09:35 ET.

### Container Status
All 7 APIS containers `Up` (just started ~11:17 UTC — operator signed in to Docker Desktop to clear the autostart blocker):
docker-api-1 (healthy), docker-worker-1 (health: starting), docker-postgres-1 (healthy), docker-redis-1 (healthy), docker-prometheus-1, docker-grafana-1, docker-alertmanager-1.

### API Health Endpoint
`GET /health` → status ok, mode paper. All components ok: db, broker, scheduler, paper_cycle, broker_auth, kill_switch.

### Worker
Scheduler started at 11:17:46 UTC; 35 jobs registered. Today's paper_trading_cycle schedule intact (09:35, 10:30, 11:30, 12:00, 13:30, 14:30, 15:30 ET). Daily eval/attribution/reports queued for 17:00–18:45 ET. No ERROR or CRITICAL lines in last 30 min. No execution_rejected_zero_quantity, no portfolio_state_sync_failed, no persist_portfolio_snapshot_failed.

### Prometheus
`apis` scrape target health=up, lastScrape 11:18:48 UTC, 0 errors.

### Database
`pg_isready` → accepting connections. (Detailed snapshot query skipped due to Windows cmd quoting — pg_isready + /health db=ok is sufficient.)

### Fixes Applied This Run
None needed — stack recovered after operator signed in to Docker Desktop (resolving the blocker flagged in the two previous health checks today).

### Action Items
- Watch 09:35 ET paper cycle to confirm Phase 61 price-injection fix validates as expected (see memory `project_phase61_price_injection.md`).
- Docker Desktop autostart blocker recommendation still open: move runtime off GUI-gated Docker Desktop so scheduled checks can self-heal.

---

## Health Check — 2026-04-15 ~14:00 UTC (second run)

**Overall Status:** 🔴 RED — Docker Desktop still not running; same blocker as this morning's check. Engine pipe `//./pipe/dockerDesktopLinuxEngine` unavailable. All 7 containers down. No downstream checks possible.

### What I Observed
- `docker ps -a` → `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`.
- `Get-Process *docker*` showed only `com.docker.backend` (x2) — no `Docker Desktop.exe` frontend.
- `com.docker.backend` was already running from this morning's earlier remediation attempts, but the frontend orchestrator (which launches dockerd) never came up.

### Remediation Attempted
1. `start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"` (cmd) — returned with no error, but frontend process never appeared after 90s wait.
2. `Start-Process -FilePath 'C:\Program Files\Docker\Docker\Docker Desktop.exe'` (powershell) — same outcome.
3. `mcp__computer-use__request_access` for Docker Desktop — timed out after 60s, confirming scheduled task has no interactive desktop session to drive GUI.

### Root Cause
Confirmed repeat of this morning's diagnosis: scheduled-task session cannot attach Docker Desktop frontend to an interactive desktop. Operator sign-in still required.

### Fixes Applied This Run
None — same interactive-desktop blocker.

### Action Items
- **URGENT (operator):** sign in and launch Docker Desktop manually. This is the third health check in a row gated on this. Once engine is up, restart stack with `cd /d "C:\Users\aaron\OneDrive\Desktop\AI Projects\Auto Trade Bot\apis\infra\docker" && docker compose --env-file "../../.env" up -d`.
- **Repeated recommendation:** move Docker runtime off Docker Desktop (GUI-gated) to a Windows service / WSL autostart / rootless Linux VM so daily checks can self-heal.
- Today is Wednesday 2026-04-15 (market day). Every hour the stack stays down loses another paper_trading_cycle run and blocks Phase 61 validation data collection.

---

## Health Check — 2026-04-15 ~09:30 UTC

**Overall Status:** 🔴 RED — Docker Desktop is NOT running on the host. Engine pipe `//./pipe/dockerDesktopLinuxEngine` unavailable. All 7 APIS containers are therefore down. Unable to complete any downstream checks (API health, worker logs, Prometheus, Postgres). Operator intervention required.

### What I Observed
- `docker ps -a` → `failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine; check if the path is correct and if the daemon is running`.
- Initial process scan showed NO `Docker Desktop.exe`, no `com.docker.backend` — Docker Desktop had not been launched since last reboot.
- WSL distro `docker-desktop` was in `Stopped` state.

### Remediation Attempted (all failed to bring the engine up)
1. `Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"` — spawned `com.docker.backend` processes (x2) and `vmmem`, but the frontend GUI (`Docker Desktop` window process) never appeared and the named pipe was never created. Waited ~2 minutes between attempts.
2. `cmd /c start "" "C:\Program Files\Docker\Docker\Docker Desktop.exe"` → `Access is denied.` (UAC / integrity-level mismatch when invoking from this session.)
3. Killed `com.docker.backend` and re-launched via `Start-Process` — same outcome (backend + vmmem up, no frontend, no engine pipe).
4. Manually started the WSL distro via `wsl -d docker-desktop -- echo ready` → distro moved to `Running`, but engine pipe still not exposed (dockerd inside the distro is not launched without the frontend orchestrator).
5. `DockerCli.exe -SwitchDaemon` and `DockerCli.exe -Start` — both exited 0 in <1s with no effect.

### Root Cause (likely)
This scheduled task runs in a session where the Docker Desktop GUI process cannot attach to an interactive desktop (no logged-in user session for the frontend, or the launch is being squashed by Windows session isolation / integrity-level rules). The backend services start but dockerd is only brought up by the frontend process during normal startup.

### Container Status
- docker-api-1 — ❌ engine down
- docker-worker-1 — ❌ engine down
- docker-postgres-1 — ❌ engine down
- docker-redis-1 — ❌ engine down
- docker-prometheus-1 — ❌ engine down
- docker-grafana-1 — ❌ engine down
- docker-alertmanager-1 — ❌ engine down

### API Health Endpoint
Not reachable (no api container).

### Worker Logs
Not reachable.

### Signal/Ranking Pipeline
Not reachable. Today is Wednesday 2026-04-15 (market day) — if containers remain down through 09:35 ET, today's paper trading cycles will be missed entirely.

### Prometheus & Monitoring
Not reachable (scrape target + Grafana are themselves containers).

### Database Health
Not reachable.

### Fixes Applied This Run
None — could not get past the engine-startup blocker without an interactive desktop session.

### Action Items
- **URGENT (operator):** log into the desktop and start Docker Desktop manually (click the Docker Desktop tray icon or launch the shortcut). Once the whale icon is steady, run `docker ps` to confirm engine is up; then `cd /d "C:\Users\aaron\OneDrive\Desktop\AI Projects\Auto Trade Bot\apis\infra\docker" && docker compose --env-file "../../.env" up -d` to restart the stack.
- **MEDIUM:** Investigate enabling Docker Desktop to start automatically with Windows sign-in (Docker Desktop → Settings → General → "Start Docker Desktop when you sign in"), or configure it to launch headlessly at boot so the daily health check is no longer gated on GUI availability.
- **MEDIUM:** After containers are back, spot-check that Phase 61/62/63/64 fixes remained in place (paper_cycle ok, latest_rankings non-empty after restart, paper broker prices injected, positions persisted). Yesterday's log already flagged the `phase60-rebalance-monitor` was the dispositive test and that cycle was due this week.
- **LOW:** The scheduled task's autonomous-fix authority cannot cover "Docker Desktop not running" without interactive desktop access; consider moving the Docker runtime to a service-based distribution (e.g., rootless Linux host in a VM or native Windows Service) so the daily check can self-heal.

---

## Health Check — 2026-04-14 10:11 UTC

**Overall Status:** ⚠️ YELLOW — All 7 containers green, all 6 health components OK, Prometheus targets up, Postgres healthy. BUT: latest portfolio snapshots (2026-04-13 14:00–19:30 UTC) show persistent `cash_balance = -$94,162.98` with `equity_value ≈ $95.9k` while the `positions` and `orders` tables are EMPTY. Today's 09:35 ET Phase 61 validation cycle has NOT yet run (current time ~06:11 ET).

### Container Status
| Container | Status |
|-----------|--------|
| docker-api-1 | ✅ Up 2d (healthy) |
| docker-worker-1 | ✅ Up 18h (healthy) — restarted at 13:39 UTC for Phase 61 fix |
| docker-postgres-1 | ✅ Up 4d (healthy) |
| docker-redis-1 | ✅ Up 4d (healthy) |
| docker-prometheus-1 | ✅ Up 2d |
| docker-grafana-1 | ✅ Up 4d |
| docker-alertmanager-1 | ✅ Up 4d |

### API Health Endpoint
HTTP 200, all 6 components green: db=ok, broker=ok, scheduler=ok, paper_cycle=ok, broker_auth=ok, kill_switch=ok.

### Worker Logs
Morning ingestion ran cleanly: Market Data (62 tickers / 15,500 bars), Alternative Data (62 records), Intel Feed (5 policy + 8 news). No ERROR/CRITICAL lines in last 2h. Signal generation / ranking jobs have not yet run for today (next stage of morning pipeline).

### Prometheus & Monitoring
`apis` job target `api:8000` health=up (last scrape 10:11:44 UTC, 1.8 ms). `prometheus` self-scrape up. No dropped targets.

### Database Health
`pg_isready` → accepting connections. ✅

### Critical Finding: Phantom Cash Debit / Phantom Equity in Snapshots
Latest snapshot (2026-04-13 19:30:02 UTC): `cash_balance = -$94,162.98`, `equity_value = $95,905.87` → implied position equity ≈ $190k on a $100k account.

However:
- `SELECT … FROM positions WHERE status='open'` → **0 rows**
- `SELECT … FROM orders` → **0 rows**
- All four post-fix `paper_trading_cycle_complete` events (17:30, 18:30, 19:30 UTC) report `proposed_count=0, approved_count=0, executed_count=0`. The pre-fix 13:35 UTC cycle had `proposed=10, approved=10, executed=0` (all 10 rejected with the Phase 61 "No price available" error).

So no orders/positions were created post-fix, yet `broker.get_account()` keeps reporting ~$190k of position exposure that gets persisted into every snapshot. The pattern repeats every cycle: snapshot at HH:30:00 shows a clean `cash=$100,000, equity=$100,000`, then the snapshot 2 seconds later (post-broker-sync) flips to `cash=-$94,162.98, equity≈$95.9k`.

**Hypothesis:** the `PaperBrokerAdapter` is rehydrating phantom positions from somewhere (possibly a persisted broker state file, or initial-condition fixture) on worker startup. The broker-state-sync code in `paper_trading.py` (Phase 60b) trusts `broker.get_account()` and writes the resulting cash/equity into `portfolio_snapshots`, but does not write phantom positions back to the `positions` table — explaining the divergence.

**Also notable:** `proposed_count=0` for every post-fix cycle. Either (a) `latest_rankings` is empty (Phase 62 restore not firing) and no candidates flow into the portfolio engine, or (b) all candidates are filtered. Today's signal/ranking jobs haven't run yet, so we'll get a clean signal at the 09:35 ET cycle.

### Phase 61 Validation Status
**Pending.** The 09:35 ET cycle that would validate the price-injection fix (set_price() before place_order()) is still 3+ hours away. The `phase60-rebalance-monitor` scheduled task is set to fire at 09:35 ET and will inspect that cycle in detail.

### Fixes Applied This Run
**None.** Did NOT make code changes because:
1. Phase 61 fix has not yet had a chance to run during market hours — premature to second-guess it.
2. The cash/equity divergence is non-destructive (no real orders, no real positions). It's a snapshot-accuracy bug, not a trading bug.
3. Root cause needs more investigation: where the phantom broker positions originate. A blind broker reset could mask the real bug.

### Action Items
- **HIGH:** `phase60-rebalance-monitor` at 09:35 ET (~13:35 UTC) — verify `executed_count > 0`, real positions appear in `positions` table, and clarify whether snapshot cash flips negative again.
- **HIGH:** If 09:35 cycle still has `proposed_count=0`, investigate the ranking restore (Phase 62) and rankings table contents for today.
- **MEDIUM:** Investigate origin of phantom broker state (grep `PaperBrokerAdapter`, look for state persistence / fixture seeding on startup). Once identified, flush stale state cleanly (do not delete real positions).

---

## Health Check — 2026-04-13 13:40 UTC

**Overall Status:** 🟡 YELLOW — Phase 61 bug found and fixed. Paper broker had no prices injected → `executed_count=0` on today's 09:35 ET cycle. Root-cause fix deployed; awaiting next cycle validation.

### Critical Finding: Phase 61 — Paper Broker Price Injection Bug

**Symptom:** `executed_count=0` despite `proposed_count=10`, `approved_count=10`.
All 10 actions rejected with: `"No price available for [ticker]. Call set_price() before placing orders in paper mode."`

**Root Cause:** `ExecutionEngineService` receives `request.current_price` (fetched via `_fetch_price()` in the paper trading job) but never calls `broker.set_price()` to inject it into the `PaperBrokerAdapter` before `place_order()`. The paper broker stores prices in an internal `_price_overrides` dict and requires explicit injection — unlike a live broker that fetches market prices.

**Fix Applied:** Added a `hasattr`-guarded `set_price()` call in `ExecutionEngineService.execute_action()` (file: `services/execution_engine/service.py`), just before the action-type dispatch. This is broker-agnostic — only fires for adapters that expose `set_price()` (i.e., paper).

**Validation:**
- 55/55 unit tests pass (test_execution_engine.py + test_paper_broker.py)
- Worker restarted at 13:39 UTC — picked up fix via volume mount
- Next live validation: 2026-04-14 09:35 ET morning cycle

### Other Health Checks

| Check | Status | Detail |
|-------|--------|--------|
| Health endpoint | ✅ OK | All 6 components green: db, broker, scheduler, paper_cycle, broker_auth, kill_switch |
| Portfolio equity | ✅ Positive | equity_value=$57,484.16, cash_balance=$52,934.16 |
| Prometheus scrape | ✅ UP | `apis` job target `api:8000` healthy, last scrape 13:35 UTC |
| paper_cycle field | ✅ OK | Restored from DB on startup (Phase 60b fix holding) |
| Learning acceleration | ✅ Reverted | 7 cycles/day, min_score=0.30, max_positions=3 |

### Note on Today's 09:35 Cycle
The cycle ran but produced zero fills due to the price injection bug. The pipeline otherwise worked correctly:
- 10 rebalance actions generated (AAPL, ABBV, AMD, AMZN, ANET, ARM, ASML, AVGO, BAC, BRK-B)
- All 10 passed risk validation with zero violations
- Portfolio engine produced 0 opens/closes (expected — no existing positions + no new rankings with score > 0.30)
- Equity captured at $100,000 (SOD)

---

## Health Check — 2026-04-12 10:11 UTC

**Overall Status:** ✅ GREEN — Saturday (non-trading day). All 7 containers up and healthy. API health fully green. Phase 60/60b fixes holding steady. System idle as expected for weekend.

### Container Status
| Container | Status | Notes |
|-----------|--------|-------|
| docker-api-1 | ✅ Up 19h (healthy) | Port 8000 |
| docker-worker-1 | ✅ Up 20h (healthy) | Idle (weekend) |
| docker-postgres-1 | ✅ Up 2d (healthy) | Port 5432, pg_isready OK |
| docker-redis-1 | ✅ Up 2d (healthy) | Port 6379 |
| docker-prometheus-1 | ✅ Up 20h | Port 9090 |
| docker-grafana-1 | ✅ Up 2d | Port 3000 |
| docker-alertmanager-1 | ✅ Up 2d | Port 9093 |

All 7 containers running. No restarts since Phase 60b deployment.

### API Health Endpoint
- HTTP 200 from `/health` — `status: ok`, `mode: paper`, `timestamp: 2026-04-12T10:10:47Z`
- Components: **db=ok, broker=ok, scheduler=ok, paper_cycle=ok, broker_auth=ok, kill_switch=ok**
- All 6 components green. `scheduler=ok` continues to hold (Phase 60b fix confirmed stable).

### Worker Logs
- No activity in last 2–4 hours (expected — Saturday)
- No ERROR or CRITICAL log lines
- Next scheduled job: Broker Token Refresh at 2026-04-13 05:30 ET
- First paper trading cycle: 2026-04-13 09:35 ET

### Signal & Ranking Pipeline
- ⏸️ No activity expected (Saturday). Next run: Monday 2026-04-13 06:00 ET

### Prometheus & Monitoring
- `apis` scrape target: **health=up**, last scrape 2026-04-12T10:10:34Z, duration 2.4ms ✅
- `prometheus` self-scrape: **health=up**, duration 2.8ms ✅
- No dropped targets. Scrape URL `api:8000` (Phase 60b DNS fix stable).

### Database Health
- Postgres: `pg_isready` → accepting connections ✅
- Latest snapshot (2026-04-11 14:39:24): cash_balance=$100,000, equity_value=$100,000 ✅
- Equity is positive ✅ (Phase 60b negative-cash fix holding)

### Known Issue Checks
- ✅ `scheduler=ok` — stable since Phase 60b fix
- ✅ Learning acceleration at baseline: `MIN_COMPOSITE_SCORE=0.30`, `MAX_NEW_POSITIONS_PER_DAY=3`, `MAX_POSITION_AGE_DAYS=20`
- ✅ `APIS_SELF_IMPROVEMENT_AUTO_EXECUTE_ENABLED` not in .env → defaults to False
- ⏳ Phase 60 execution gap fix — verification deferred to Monday 09:35 ET (`phase60-rebalance-monitor` task)

### Fixes Applied
- **None needed.** All systems green.

### Action Items for Monday 2026-04-13
- **HIGH:** `phase60-rebalance-monitor` fires at 09:35 ET — verify `executed_count > 0`, positive equity, `paper_cycle=ok`

---

## Health Check — 2026-04-13 10:11 UTC

**Overall Status:** ✅ GREEN — Monday (pre-market). All 7 containers up and healthy. API health fully green. Morning data pipeline completed successfully. Phase 60/60b fixes holding. First paper trading cycle at 09:35 ET will be the critical Phase 60 verification.

### Container Status
| Container | Status | Notes |
|-----------|--------|-------|
| docker-api-1 | ✅ Up 44h (healthy) | Port 8000 |
| docker-worker-1 | ✅ Up 44h (healthy) | Morning jobs running |
| docker-postgres-1 | ✅ Up 3d (healthy) | Port 5432, pg_isready OK |
| docker-redis-1 | ✅ Up 3d (healthy) | Port 6379 |
| docker-prometheus-1 | ✅ Up 44h | Port 9090 |
| docker-grafana-1 | ✅ Up 3d | Port 3000 |
| docker-alertmanager-1 | ✅ Up 3d | Port 9093 |

All 7 containers running. No restarts needed.

### API Health Endpoint
- HTTP 200 from `/health` — `status: ok`, `mode: paper`, `timestamp: 2026-04-13T10:11:20Z`
- Components: **db=ok, broker=ok, scheduler=ok, paper_cycle=ok, broker_auth=ok, kill_switch=ok**
- All 6 components green. `paper_cycle=ok` confirms Phase 60b timestamp persistence fix is working after restart.

### Worker Logs
- **05:30 ET:** Broker Token Refresh — skipped (no broker configured) ✅
- **06:00 ET:** Market Data Ingestion — 62 tickers, 15,500 bars persisted, status=SUCCESS ✅
- **06:05 ET:** Alternative Data Ingestion — 62 records ingested ✅
- **06:10 ET:** Intel Feed Ingestion — 5 macro policy signals, 8 news insights ✅
- No ERROR or CRITICAL log lines in last 2 hours
- No paper trading cycles yet (expected — first at 09:35 ET)

### Signal & Ranking Pipeline
- ⏳ Signal generation, feature enrichment, and ranking generation not yet run (scheduled ~06:30–06:52 ET). Data ingestion completed successfully, so inputs are ready.

### Prometheus & Monitoring
- `apis` scrape target: **health=up**, last scrape 2026-04-13T10:11:31Z, duration 2.2ms ✅
- `prometheus` self-scrape: **health=up**, duration 2.5ms ✅
- No dropped targets. Scrape URL `api:8000` (Phase 60b DNS fix stable).

### Database Health
- Postgres: `pg_isready` → accepting connections ✅
- Latest snapshot (2026-04-11 14:39:24): cash_balance=$100,000, equity_value=$100,000 ✅
- Equity positive ✅ (Phase 60b negative-cash fix holding)

### Known Issue Checks
- ✅ Learning acceleration at baseline: `MIN_COMPOSITE_SCORE=0.30`, `MAX_NEW_POSITIONS_PER_DAY=3`, `MAX_POSITION_AGE_DAYS=20`, 7 cycles/day
- ✅ `APIS_SELF_IMPROVEMENT_AUTO_EXECUTE_ENABLED` not in .env → defaults to False
- ✅ `APIS_OPERATING_MODE=paper`
- ⏳ Phase 60 execution gap — first live verification at 09:35 ET today

### Fixes Applied
- **None needed.** All systems green.

### Action Items
- **HIGH:** Monitor 09:35 ET paper trading cycle — verify `executed_count > 0`, positive equity, no `execution_rejected_zero_quantity` errors. This is the critical Phase 60 verification on the first trading day since the fix.

---

## Health Check — 2026-04-13 16:35 UTC (Follow-Up Investigation)

**Overall Status:** ⚠️ YELLOW → ✅ GREEN (after fix). Two issues found and one resolved.

### Issue 1: executed_count=0 at 09:35 ET
- The 09:35 ET cycle ran BEFORE the Phase 61 fix was deployed: `proposed_count=10, approved_count=10, executed_count=0`
- This is **expected** — Phase 61 (price injection fix) was deployed at 09:39 ET, 4 minutes after the cycle
- The 09:35 cycle ran with old code where `set_price()` was never called → all orders rejected by paper broker
- Phase 61 validation deferred to tomorrow's 09:35 ET cycle

### Issue 2: skipped_no_rankings on all subsequent cycles (10:30, 11:30, 12:00 ET)
- **Root cause:** Worker restart at 09:39 ET (Phase 61 deployment) cleared `app_state.latest_rankings` in memory
- Signal generation (06:30 ET) and ranking generation (06:45 ET) had already passed → scheduled for tomorrow
- Rankings existed in DB (190 rows from 10:45 UTC morning run) but worker never restored them
- The API container had this restoration logic, but the worker did not

### Fix Applied: Phase 62 — Worker Rankings Restoration
- Added `_restore_rankings_from_db()` to `apps/worker/main.py` mirroring the API's restoration logic
- Worker restarted at 16:34 UTC — confirmed: `latest_rankings_restored_from_db count=10`
- Remaining afternoon cycles (Early Afternoon 13:30, Afternoon 14:30, Pre-Close 15:30 ET) should now have rankings
- This also ensures the Phase 61 price injection fix will be testable at the next cycle

### Action Items
- **HIGH:** Monitor the 14:30 ET (18:30 UTC) paper trading cycle — verify `executed_count > 0` now that both Phase 61 (price injection) and Phase 62 (rankings restoration) are deployed
- **HIGH:** Verify Phase 61 price injection fix at tomorrow 09:35 ET with fresh pipeline run
- **MEDIUM:** Confirm signal generation at 06:30 ET and rankings at 06:45 ET
- **LOW:** Monitor `scheduler` health throughout first full trading day post-Phase 60b

---

## Health Check — 2026-04-12 01:50 UTC

**Overall Status:** ✅ GREEN — Saturday (non-trading day). All 7 containers up and healthy. API health fully green (all components "ok"). Phase 60/60b fixes deployed yesterday are holding. System idle as expected for weekend.

### Container Status
| Container | Status | Notes |
|-----------|--------|-------|
| docker-api-1 | ✅ Up 11h (healthy) | Port 8000 |
| docker-worker-1 | ✅ Up 11h (healthy) | Restarted after Phase 60b deploy |
| docker-postgres-1 | ✅ Up 2d (healthy) | Port 5432, pg_isready OK |
| docker-redis-1 | ✅ Up 2d (healthy) | Port 6379 |
| docker-prometheus-1 | ✅ Up 11h | Port 9090 |
| docker-grafana-1 | ✅ Up 2d | Port 3000 |
| docker-alertmanager-1 | ✅ Up 2d | Port 9093 |

All 7 containers running. API and worker restarted ~11h ago after Phase 60b deployment.

### API Health Endpoint
- HTTP 200 from `/health` — `status: ok`, `mode: paper`, `timestamp: 2026-04-12T01:50:30Z`
- Components: **db=ok, broker=ok, scheduler=ok, paper_cycle=ok, broker_auth=ok, kill_switch=ok**
- 🎉 **`scheduler=ok`** — previously recurring as "stale" on April 7 and 8. The Phase 60b fix to `_load_persisted_state()` (restoring `last_paper_cycle_at`) appears to have resolved this.

### Worker Logs
- No activity in last 2 hours (expected — Saturday overnight)
- Last activity: 2026-04-11 14:40 UTC — worker startup after Phase 60b restart
- 40 jobs registered successfully, all scheduled for next trading day (Monday 2026-04-13)
- Next scheduled job: Broker Token Refresh at 2026-04-13 05:30 ET
- First paper trading cycle: 2026-04-13 09:35 ET
- No ERROR or CRITICAL log lines

### Signal & Ranking Pipeline
- ⏸️ No activity expected (Saturday). Next run: Monday 2026-04-13 06:00 ET (market data ingestion)

### Prometheus & Monitoring
- `apis` scrape target: **health=up**, last scrape 2026-04-12T01:50:25Z, duration 3.2ms ✅
- `prometheus` self-scrape: **health=up** ✅
- Scrape URL correctly pointing to `api:8000` (Phase 60b DNS fix confirmed)
- No dropped targets

### Database Health
- Postgres: `pg_isready` → accepting connections ✅
- Portfolio snapshots: 332 total records
- Latest snapshot (2026-04-11 14:39:24): cash_balance=$100,000, equity_value=$100,000 ✅
- Open positions: 0 (expected — portfolio reset during Phase 60b fixes)
- Equity is positive ✅ (Phase 60b negative-cash fix holding)

### Known Issue Checks
- ✅ `scheduler=stale` **RESOLVED** — now showing "ok" after Phase 60b `_load_persisted_state()` fix
- ✅ Learning acceleration settings at baseline: `MIN_COMPOSITE_SCORE=0.30`, `MAX_NEW_POSITIONS_PER_DAY=3`, `MAX_POSITION_AGE_DAYS=20`
- ✅ `APIS_SELF_IMPROVEMENT_AUTO_EXECUTE_ENABLED` not in .env → defaults to False (correct)
- ⏳ Phase 60 execution gap fix — cannot verify until Monday 09:35 ET first paper trading cycle. `phase60-rebalance-monitor` task scheduled.

### Fixes Applied
- **None needed.** All systems green.

### Action Items for Monday 2026-04-13
- **HIGH:** `phase60-rebalance-monitor` fires at 09:35 ET — verify `executed_count > 0`, positive equity, Prometheus alert cleared, `paper_cycle=ok`
- **MEDIUM:** Confirm signal generation produces signals at 06:30 ET and rankings at 06:45 ET
- **LOW:** Continue monitoring `scheduler` health status — verify it remains "ok" across the full trading day

---

## Follow-Up Fixes — 2026-04-11 14:40 UTC

**Overall Status:** ✅ Three additional fixes deployed addressing secondary issues from the earlier investigation.

### Fix 1 — Negative cash_balance in portfolio_state (RESOLVED)
**Root cause:** `paper_trading.py` broker sync (lines 803-806) only updated *existing* positions in `portfolio_state.positions`. New positions opened by the execution engine were never added. After buying, `cash` was debited but `gross_exposure` stayed 0 → `equity = cash + 0 = negative`. This caused `apply_ranked_opportunities` to return 0 opens every other cycle.
**Fix:** Added an `else` branch to create new `PortfolioPosition` objects from broker positions not yet in `portfolio_state.positions`.

### Fix 2 — Prometheus scrape DNS (RESOLVED)
**Root cause:** `prometheus.yml` had `apis_api:8000` as the scrape target, but the docker-compose service is named `api`. Prometheus couldn't resolve the hostname → `APISScrapeDown` alert firing since Apr 9.
**Fix:** Changed target to `api:8000`. Updated matching comment in `apis_alerts.yaml`. Prometheus container restarted.

### Fix 3 — `last_paper_cycle_at` null after restart (RESOLVED)
**Root cause:** `_load_persisted_state()` in `main.py` restored many fields from DB on startup (kill switch, cycle count, rankings, portfolio state) but never restored `last_paper_cycle_at`. After every container restart, the health check showed `paper_cycle: "no_data"` until the first cycle completed.
**Fix:** Added restoration of `last_paper_cycle_at` from the latest portfolio snapshot timestamp during startup. Also ensured the restored timestamp is timezone-aware (DB stores naive UTC timestamps, health check uses aware datetimes).

### Test Results
- Paper cycle simulation: 43/43 pass
- Execution engine: 23/23 pass
- Risk engine: 55/55 pass
- Portfolio engine: 39/40 (1 pre-existing)
- Signal + ranking: 58/58 pass

### Health After Restart
```json
{"status":"degraded","components":{"db":"ok","broker":"ok","scheduler":"ok","paper_cycle":"ok","broker_auth":"ok","kill_switch":"active"}}
```
`paper_cycle` now shows `"ok"` (was `"no_data"`). `kill_switch: "active"` is from env var (expected in paper mode).

---

## Investigation & Fix — 2026-04-11 14:25 UTC

**Overall Status:** ✅ FIX DEPLOYED — Root cause of the proposal→execution gap identified and fixed. Containers restarted. Fix will be active for Monday's first trading cycle.

### Root Cause: `execution_rejected_zero_quantity`

The rebalancing service (`services/risk_engine/rebalancing.py`) was creating OPEN actions with `target_quantity` (shares) but leaving `target_notional` at its default of `Decimal("0")`. The execution engine (`services/execution_engine/service.py`) only used `target_notional / price` to compute order quantity — it never read `target_quantity`. Result: every rebalance-originated order computed `0 / price = 0` shares and was rejected.

**Evidence from worker logs (Apr 10):**
- Every cycle: `proposed_count=10, approved_count=10, executed_count=0`
- All 10 tickers pass risk checks (`risk_validate_action passed=true`)
- All 10 rejected with `execution_rejected_zero_quantity, target_notional=0`
- Pattern repeated across all 12 cycles on Apr 10

### Fixes Applied

**Fix 1 — `services/risk_engine/rebalancing.py` line 275:**
Added `target_notional=Decimal(str(round(target_usd, 2)))` to the OPEN action constructor. The `target_usd` value was already calculated from drift but never passed to the PortfolioAction.

**Fix 2 — `services/execution_engine/service.py` `_execute_open()`:**
Added fallback: if `target_notional` is 0 but `target_quantity` is set, use `target_quantity` directly instead of computing from notional/price. Logs the fallback as `execution_using_target_quantity_fallback`.

### Test Results
- Rebalancing tests: 61/67 pass (6 failures pre-existing: auth token, stale job count)
- Execution engine tests: 23/23 pass
- Paper cycle simulation: 43/43 pass

### Deployment
- Source is volume-mounted (`:ro`), no rebuild needed
- `docker restart docker-worker-1` and `docker restart docker-api-1` at 14:25 UTC
- API health: `status=ok`, all components ok, `mode=paper`, `scheduler=ok`

### Secondary Issue Identified (not yet fixed)
Portfolio snapshots in DB show alternating `cash_balance=-94162.98` and `cash_balance=100000.00`. The negative-cash snapshots occur at cycle start; the $100K snapshots after broker sync with a fresh PaperBrokerAdapter. This means `portfolio_state.equity` is negative when `apply_ranked_opportunities` runs, causing it to produce 0 opens (negative notionals fall below `_MIN_NOTIONAL=100`). The rebalancing fix bypasses this because rebalance actions are generated from drift targets, not portfolio sizing. However, this secondary bug should be investigated separately — the portfolio state is not correctly persisted across cycles.

### Action Required
- **MONITOR Monday 09:35 ET:** Watch the first cycle for `executed_count > 0`. The rebalance OPEN actions should now have valid `target_notional` values.
- **MEDIUM: Investigate negative cash_balance in portfolio_state.** The -94162.98 value appears at every cycle start. Trace where `portfolio_state.cash` is being set to a negative value between the broker sync (which resets to $100K) and the next cycle start.
- **Carryover: Fix Prometheus scrape target DNS.** `APISScrapeDown` alert still active.

---

## Health Check — 2026-04-11 10:10 UTC

**Overall Status:** ℹ️ WEEKEND — Saturday, no trading day. Infrastructure verification could not be performed this session (Docker CLI unavailable in sandbox, Chrome extension not connected, web_fetch blocked for localhost). No pipeline or cycle checks applicable.

### Docker Containers
| Container | Status | Notes |
|-----------|--------|-------|
| docker-api-1 | ❓ Unknown | Could not verify — no Docker CLI or HTTP access |
| docker-worker-1 | ❓ Unknown | Could not verify |
| docker-postgres-1 | ❓ Unknown | Could not verify |
| docker-redis-1 | ❓ Unknown | Could not verify |
| docker-prometheus-1 | ❓ Unknown | Could not verify |
| docker-grafana-1 | ❓ Unknown | Could not verify |
| docker-alertmanager-1 | ❓ Unknown | Could not verify |

Tools attempted: `mcp__workspace__bash` (docker not installed in sandbox), `mcp__workspace__web_fetch` (rejects localhost/127.0.0.1), Chrome extension (not connected — user not present for scheduled task). No Desktop Commander MCP available.

### API Health Endpoint
- Could not reach `localhost:8000/api/v1/health` — all access methods blocked this session.
- Last known state (2026-04-10 10:12 UTC): `status: ok`, `mode: paper`, all components ok.

### Worker Log Check
- **Classification: UNKNOWN** — no access to Docker logs or dashboard.
- Last known state (2026-04-10): INFERRED OK, scheduler YELLOW ("7 cycles recorded but no timestamp").

### Signal Pipeline
| Stage | Status | Details |
|-------|--------|---------|
| Securities table | ℹ️ N/A (weekend) | Last known: 62 rows (Apr 10) |
| Market data ingestion | ℹ️ N/A (weekend) | No ingestion expected |
| Signal generation | ℹ️ N/A (weekend) | No signals expected |
| Ranking generation | ℹ️ N/A (weekend) | No rankings expected |

### Paper Trading Cycles
| Expected by now | Executed | Skipped | Status |
|-----------------|----------|---------|--------|
| 0 | 0 | 0 | ℹ️ WEEKEND — no cycles scheduled |

### Kubernetes
- ❓ Could not verify — `kubectl` not available and Chrome not connected.
- Last known state (2026-04-10): API pod running, postgres/redis pods running, worker pod absent (correct).

### Issues Found (carryover from Apr 10)
- ⚠️ **Prometheus scrape DNS issue (ongoing since Apr 9).** `APISScrapeDown` alert firing — Prometheus config uses `apis_api` hostname which fails DNS. API is reachable on localhost:8000. Metrics collection broken.
- ⚠️ **Worker scheduler YELLOW (ongoing).** `last_cycle_at` not being persisted correctly despite cycles running.
- ⚠️ **CRITICAL (ongoing): Zero trades executed.** 7+ cumulative paper cycles, $100K equity unchanged, 0 positions. Proposal→execution gap unresolved since Apr 8. This is the #1 operational issue.
- ℹ️ **Learning Acceleration active** — 12 cycles/day, min composite score 0.15. Must revert before live trading per DEC-021.
- ℹ️ **Session tooling gap.** Scheduled health check cannot access any local services — Docker CLI, localhost HTTP, and Chrome are all unavailable. Consider ensuring Chrome is open or Desktop Commander MCP is configured for scheduled runs.

### Fixes Applied
- None. No access to services for diagnostics or restarts.

### Action Required
- **HIGH (ongoing): Fix proposal→execution gap.** Remains the top priority. No new data today (weekend) but investigation should happen in next interactive session.
- **HIGH (ongoing): Fix Prometheus scrape target DNS.** Update `prometheus.yml` hostname.
- **MEDIUM: Ensure health check tooling access.** This scheduled task had zero ability to inspect services. For future runs, ensure either Chrome extension is connected or Desktop Commander MCP is available.
- **MEDIUM (ongoing): Investigate `last_cycle_at` persistence.** Worker scheduler YELLOW.
- **LOW: Verify Kubernetes pods** — could not check; ensure K8s worker remains at 0 replicas.

---

## Health Check — 2026-04-10 10:12 UTC

**Overall Status:** ⚠️ DEGRADED — Friday trading day. API and all accessible services responding. Scheduler component reports YELLOW ("7 cycles recorded but no timestamp"). Prometheus scrape target alert active since yesterday (Docker DNS issue — API is actually up). No trades executed to date despite 7 cumulative paper cycles. Morning pipeline jobs pending (06:15–06:45 ET). Note: Desktop Commander MCP unavailable this session; health data gathered via HTTP endpoints (API health, dashboard, Prometheus, Alertmanager).

### Docker Containers
| Container | Status | Notes |
|-----------|--------|-------|
| docker-api-1 | ✅ Up (inferred) | localhost:8000 responding, /health ok |
| docker-worker-1 | ✅ Up (inferred) | Dashboard shows scheduler YELLOW, jobs registered |
| docker-postgres-1 | ✅ Up (inferred) | API component db=ok |
| docker-redis-1 | ✅ Up (inferred) | API component broker=ok |
| docker-prometheus-1 | ✅ Up | localhost:9090 responding |
| docker-grafana-1 | ✅ Up | localhost:3000 responding (login page) |
| docker-alertmanager-1 | ✅ Up | localhost:9093 responding |

All 7 containers inferred running (verified via HTTP endpoints; Docker CLI not available this session).

### API Health Endpoint
- HTTP 200 from `/health` — `status: ok`, `mode: paper`, `timestamp: 2026-04-10T10:12:27Z`
- Components: db=ok, broker=ok, **scheduler=ok**, paper_cycle=no_data, broker_auth=ok, kill_switch=ok
- `paper_cycle=no_data` is expected — check ran at 06:12 ET, before first cycle at 09:35 ET.
- `scheduler=ok` — healthy for the 2nd consecutive day after the Apr 7–8 stale period.

### Worker Log Check
- **Classification: INFERRED OK** — Could not pull `docker logs` directly (no Docker CLI access). Dashboard shows:
  - Infrastructure: 5 healthy, 1 warning (worker scheduler YELLOW — "7 cycles recorded but no timestamp")
  - Alternative Data: 62 records ingested (social_mention source)
  - Market Regime: BULL_TREND (100% confidence, detected 2026-04-09 21:28)
  - Correlation Risk: computed 2026-04-09 21:28, 62 tickers, 1891 pairs
  - Liquidity Filter: computed 2026-04-09 21:28, 62/62 liquid
  - Earnings Calendar: refreshed 2026-04-09 21:28, 0 at-risk tickers
- Pending today: Feature Refresh (06:15), Correlation/Liquidity/VaR/Regime/Stress (06:16–06:22), Signal Generation (06:30), Ranking Generation (06:45), 12 paper trading cycles starting 09:35 ET (updated schedule per Learning Acceleration DEC-021)

### Signal Pipeline
| Stage | Status | Details |
|-------|--------|---------|
| Securities table | ✅ 62 rows | Confirmed via dashboard (62 tickers in universe) |
| Market data ingestion | ⏳ Pending | Scheduled 06:00 ET — dashboard shows prior day's data present |
| Signal generation | ⏳ Pending | Scheduled 06:30 ET — not yet fired |
| Ranking generation | ✅ Rankings exist | Top 5: XOM (0.826), EQIX (0.824), INTC (0.824), COP (0.815), DELL (0.808) — from yesterday's run, still loaded in app state |

### Paper Trading Cycles
| Expected by now | Executed | Skipped | Status |
|-----------------|----------|---------|--------|
| 0 | 0 | 0 | ⏳ NO CYCLES YET — first at 09:35 ET |

Details: Check ran at ~06:12 ET, before first cycle. Dashboard shows 7 cumulative cycles completed (all previous days combined), 0 error cycles, **0 closed trades, 0 open positions, $100K equity unchanged**. The updated schedule (Learning Acceleration, Apr 9) now runs 12 cycles/day at ~30-min intervals. The ranking minimum composite score was lowered to 0.15 to allow more trade signals through. Despite these changes, **no trades have been executed to date** — the proposal→execution gap persists.

### Kubernetes
- ⚠️ Could not verify — `kubectl` not available in this session. Yesterday's check showed: API pod running, postgres/redis pods running, worker pod correctly absent.

### Prometheus & Alertmanager
- **Active Alert: `APISScrapeDown`** (critical, since 2026-04-09 21:31 UTC)
  - Prometheus cannot resolve Docker-internal hostname `apis_api:8000` — DNS lookup fails
  - API is actually running (verified via localhost:8000/health) — this is a Docker networking issue, not an outage
  - Prometheus self-scrape: healthy (up=1)
  - Alert is firing to `slack-critical` receiver

### Issues Found
- ⚠️ **Prometheus scrape DNS issue.** Active `APISScrapeDown` alert since yesterday 21:31 UTC. Prometheus config uses hostname `apis_api` which fails DNS resolution. API is accessible on localhost:8000. Metrics collection is broken — no API metrics being gathered.
- ⚠️ **Worker scheduler YELLOW.** Dashboard reports "7 cycles recorded but no timestamp" — `last_cycle_at` is not being persisted/read correctly. The scheduler itself is running.
- ⚠️ **CRITICAL (ongoing): Zero trades executed.** 7 cumulative paper cycles across multiple days, $100K equity unchanged, 0 open positions, 0 closed trades. The pipeline produces rankings (top scores ~0.82) and rebalancing shows 10 actionable drifts to OPEN, but no positions are being entered. The proposal→execution gap flagged since Apr 8 remains unresolved.
- ℹ️ **Readiness Report: FAIL** (5 pass, 2 warn, 1 fail) — `min_evaluation_history` at 0/5, expected while no trades are executing.
- ℹ️ **Learning Acceleration active** — 12 cycles/day, min composite score lowered to 0.15. Must be reverted before live trading per DEC-021.

### Fixes Applied
- None applied. No Docker CLI access this session for container restarts. No fixes were indicated — all containers are responding.

### Action Required
- **HIGH: Fix Prometheus scrape target DNS.** Update `prometheus.yml` to use `host.docker.internal:8000` or the correct Docker service hostname instead of `apis_api:8000`. This will resolve the `APISScrapeDown` alert and restore API metrics collection.
- **HIGH (ongoing): Investigate proposal→execution gap.** This is the #1 operational issue — rankings exist, rebalancing identifies 10 positions to OPEN, but zero trades are executed. Trace the path from ranking→paper_trading_cycle→order_submission. Check: is the broker adapter actually placing paper orders? Are pre-trade checks rejecting everything? Is there a config gate blocking execution?
- **MEDIUM: Investigate worker `last_cycle_at` persistence.** Dashboard shows YELLOW because cycle timestamp is null despite 7 cycles recorded. Check the field write path in the paper trading cycle job.
- **LOW: Verify Kubernetes pods** — could not check this session. Ensure K8s worker remains at 0 replicas.

---

## Health Check — 2026-04-09 10:12 UTC

**Overall Status:** ✅ HEALTHY — Thursday trading day. All 7 containers up and healthy. API reports `status: ok` with **`scheduler=ok`** (resolved after 2 consecutive days of `stale`). Morning pipeline executing on schedule. Signal/ranking gen pending (06:30–06:45 ET). Paper trading cycles start at 09:35 ET.

### Docker Containers
| Container | Status | Notes |
|-----------|--------|-------|
| docker-api-1 | ✅ Up 10h (healthy) | Port 8000 |
| docker-worker-1 | ✅ Up 10h (healthy) | 35 jobs registered |
| docker-postgres-1 | ✅ Up 6d (healthy) | Port 5432 |
| docker-redis-1 | ✅ Up 6d (healthy) | Port 6379 |
| docker-prometheus-1 | ✅ Up 6d | Port 9090 |
| docker-grafana-1 | ✅ Up 6d | Port 3000 |
| docker-alertmanager-1 | ✅ Up 6d | Port 9093 |

All 7 containers running. API and worker both restarted ~10h ago (00:13 UTC). No issues.

### API Health Endpoint
- HTTP 200 from `/health` — `status: ok`, `mode: paper`, `timestamp: 2026-04-09T10:11:35Z`
- Components: db=ok, broker=ok, **scheduler=ok**, paper_cycle=no_data, broker_auth=ok, kill_switch=ok
- **`scheduler=stale` RESOLVED.** After 2 consecutive days (Apr 7–8) reporting stale, the scheduler component is now healthy. The API+worker restart ~10h ago appears to have cleared the condition. Root cause still unknown — may recur; continue monitoring.
- `paper_cycle=no_data` is expected — check ran at 06:12 ET, before first cycle at 09:35 ET.

### Worker Log Check
- **Classification: OK** — APScheduler started at 00:13 UTC with 35 registered jobs, executing on schedule, no ERROR or exception lines
- Today's morning jobs already executed:
  - ✅ Broker Token Refresh (05:30 ET / 09:30 UTC) — skipped (no broker configured)
  - ✅ Market Data Ingestion (06:00 ET / 10:00 UTC) — **62 tickers, 15,500 bars persisted, SUCCESS**
  - ✅ Alternative Data Ingestion (06:05 ET / 10:05 UTC) — 62 records (social_mention adapter)
  - ✅ Intel Feed Ingestion (06:10 ET / 10:10 UTC) — 5 macro policy signals, 8 news insights
- Pending: Feature Refresh (06:15), Correlation/Liquidity/Fundamentals/VaR/Regime/Stress (06:16–06:22), Signal Generation (06:30), Ranking Generation (06:45), 7 paper trading cycles starting 09:35 ET
- ℹ️ yfinance TzCache warning present (cosmetic — `/root/.cache/py-yfinance` folder conflict, does not affect data ingestion)

### Signal Pipeline
| Stage | Status | Details |
|-------|--------|---------|
| Securities table | ✅ 62 rows | Matches universe config |
| Market data ingestion | ✅ SUCCESS | 62 tickers, 15,500 bars at 06:00 ET today |
| Signal generation | ⏳ Pending | Scheduled 06:30 ET — not yet fired. Previous days: 310 signals/day (Apr 6–8) |
| Ranking generation | ⏳ Pending | Scheduled 06:45 ET — not yet fired |

### Paper Trading Cycles
| Expected by now | Executed | Skipped | Status |
|-----------------|----------|---------|--------|
| 0 | 0 | 0 | ⏳ NO CYCLES YET — first at 09:35 ET |

Details: Check ran at ~06:12 ET, before first cycle. No cycle activity expected yet today.

### Kubernetes
- apis-api-54d7f467f4-f54hj: ✅ Running (1/1, 1 restart 6d14h ago, 9d age)
- postgres-0: ✅ Running (1/1, 2 restarts, 18d age)
- redis-79d54f5d6-nxkmh: ✅ Running (1/1, 2 restarts, 18d age)
- Worker pod: Not present (✅ correct — worker runs in Docker Compose only)

### Issues Found
- ℹ️ **`scheduler=stale` resolved but root cause unknown.** The API+worker restart cleared the condition. If it recurs tomorrow, the heartbeat write/read path investigation flagged on Apr 8 remains necessary.
- ℹ️ **Carryover: Proposal→execution gap.** Apr 8 report showed 20 proposals approved → 0 executed. Monitor today's cycles (starting 09:35 ET) to see if this pattern continues.
- ℹ️ **Carryover: Readiness Report FAIL** (5/8 pass, 2 warn, 1 fail) — expected while the proposal→execution gap persists.

### Fixes Applied
- None required. All systems healthy.

### Action Required
- **MEDIUM: Continue monitoring `scheduler` component** — if `stale` returns tomorrow, proceed with code-level investigation per Apr 8 action items (heartbeat write path in worker, read path in `apps/api/routes/health.py`).
- **MEDIUM: Monitor signal generation at 06:30 ET** — confirm `signal_generation_job_complete` with signals > 0.
- **MEDIUM: Monitor first paper trading cycle at 09:35 ET** — confirm it executes and produces trades (not just approved proposals with 0 executions).
- **MEDIUM (carryover): Investigate proposal→execution gap** — trace from approved proposals to executed trades. Check broker routing, pre-trade check gating, and config.

---

## Health Check — 2026-04-08 10:15 UTC

**Overall Status:** ⚠️ DEGRADED — Wednesday trading day. All 7 containers up. Morning ingestion pipeline executing on schedule. Signal/ranking gen pending (scheduled 06:30–06:45 ET). **`scheduler=stale` has recurred for the 2nd consecutive day** — per yesterday's action item, NOT auto-restarting this time and escalating to code-level investigation.

### Docker Containers
| Container | Status | Notes |
|-----------|--------|-------|
| docker-api-1 | ✅ Up 24h (healthy) | Port 8000 |
| docker-worker-1 | ✅ Up 4d (healthy) | Jobs executing on schedule |
| docker-postgres-1 | ✅ Up 5d (healthy) | Port 5432 |
| docker-redis-1 | ✅ Up 5d (healthy) | Port 6379 |
| docker-prometheus-1 | ✅ Up 5d | Port 9090 |
| docker-grafana-1 | ✅ Up 5d | Port 3000 |
| docker-alertmanager-1 | ✅ Up 5d | Port 9093 |

All 7 containers running. `docker-api-1` has 24h uptime — consistent with yesterday's remediation restart. No restarts this check.

### API Health Endpoint
- HTTP 200 from `/health` — `status: **degraded**`, `mode: paper`, `timestamp: 2026-04-08T10:11:15Z`
- Components: db=ok, broker=ok, **scheduler=stale**, broker_auth=ok, kill_switch=ok
- **Action taken: NONE.** Deliberately *not* restarting per yesterday's action item ("If this recurs daily, the heartbeat write path may be drifting and warrants a code-level investigation rather than a recurring restart.")
- This is now a **recurring** condition — second consecutive day. Treating the restart as a patch rather than a fix would mask the underlying heartbeat defect.

### Worker Log Check
- **Classification: OK** — APScheduler executing jobs on schedule, no ERROR or exception lines in tail 60
- Today's morning jobs already executed:
  - ✅ Broker Token Refresh (05:30 ET / 09:30 UTC) — skipped (no broker configured)
  - ✅ Market Data Ingestion (06:00 ET / 10:00 UTC) — **62 tickers, 15,500 bars persisted, SUCCESS**
  - ✅ Alternative Data Ingestion (06:05 ET / 10:05 UTC) — 62 records (social_mention)
  - ✅ Intel Feed Ingestion (06:10 ET / 10:10 UTC) — 5 macro policy signals, 8 news insights
- Pending: Signal Generation (06:30 ET), Ranking Generation (06:45 ET), 7 paper trading cycles starting 09:35 ET
- Yesterday's (Apr 7) evening pipeline ran cleanly: Daily Evaluation (grade D, 0 positions, 0.00% daily return), Attribution Analysis, Signal Quality (skipped — no trades), Daily Report (grade D, 1 proposal), Operator Summary, Self-Improvement (1 proposal), Auto-Execute (0 executed, 1 skipped), Fill Quality, Readiness Report (**FAIL: 5 pass / 2 warn / 1 fail**, target=human_approved).
- **Note:** The divergence between the API's `scheduler=stale` and the worker's actively-running APScheduler confirms this is an API-side heartbeat read issue — the scheduler itself is working fine.

### Signal Pipeline
| Stage | Status | Details |
|-------|--------|---------|
| Securities table | ✅ 62 rows | Matches universe config |
| Market data ingestion | ✅ SUCCESS | 62 tickers, 15,500 bars at 06:00 ET |
| Signal generation | ⏳ Pending | Scheduled 06:30 ET — not yet fired |
| Ranking generation | ⏳ Pending | Scheduled 06:45 ET — not yet fired |

### Paper Trading Cycles
| Expected by now | Executed | Skipped | Status |
|-----------------|----------|---------|--------|
| 0 | 0 | 0 | ⏳ NO CYCLES YET — first at 09:35 ET |

Details: Check ran at ~06:11–06:15 ET, before first cycle. `paper_trades` table does not exist (trades persist via `orders`/`positions`/`fills`). Yesterday produced 0 executed trades despite 20 approved proposals across 7 cycles — the proposal-to-execution gap from yesterday's report remains the open operational issue.

### Kubernetes
- apis-api-54d7f467f4-f54hj: ✅ Running (1/1, 1 restart 5d14h ago, 8d age)
- postgres-0: ✅ Running (1/1, 2 restarts, 17d age)
- redis-79d54f5d6-nxkmh: ✅ Running (1/1, 2 restarts, 17d age)
- Worker pod: Not present (✅ correct — worker runs in Docker Compose only)

### Issues Found
- ⚠️ **RECURRING (Day 2): API health `scheduler=stale`.** Yesterday's restart was a transient fix. Today the condition returned with only 24h uptime on docker-api-1. This is a code defect in the scheduler heartbeat write/read path, not a stuck container. Escalating from "fix" to "investigate".
- ℹ️ **Carryover: Proposal→execution gap.** Yesterday: 20 proposals approved → 0 executed across 7 cycles. Root cause likely in pre-trade check gating, broker routing, or config — unrelated to today's scheduler issue.
- ℹ️ **Carryover: Readiness Report FAIL** (5/8 pass, 2 warn, 1 fail) — expected while the proposal→execution gap persists.

### Fixes Applied
- **None.** Deliberately withheld auto-restart of docker-api-1 to preserve the failing state for diagnosis and to force a proper code-level fix.

### Action Required
- **HIGH (new): Investigate `scheduler=stale` root cause.** The scheduler is working (worker logs prove it) but the API's health endpoint reports it as stale on consecutive days. Check:
  1. Where does the API read the scheduler heartbeat from (Redis key? DB row? Prometheus metric?)
  2. Where does the worker write it? Is the write path firing on every job or only at startup?
  3. What is the staleness threshold? Is it set too aggressively?
  4. Relevant files likely under `apps/api/routes/health.py` and `apps/worker/` heartbeat logic.
- **HIGH: Monitor signal generation at 06:30 ET** — confirm `signal_generation_job_complete` with signals > 0
- **HIGH: Monitor ranking generation at 06:45 ET** — confirm rankings produced
- **HIGH: Monitor first paper trading cycle at 09:35 ET** — confirm it executes and produces trades (not just "skipped_no_rankings" or "approved_count > 0 / executed_count = 0")
- **MEDIUM (carryover): Investigate proposal→execution gap** — trace yesterday's path from `paper_trading_cycle_complete.approved_count=20` to `executed_count=0`. Is this a broker routing failure, a pre-trade check rejection, or a config gate?

---

## Health Check — 2026-04-07 10:17 UTC

**Overall Status:** ✅ HEALTHY — Tuesday trading day. All 7 containers up. Morning ingestion pipeline executing on schedule. Signal/ranking gen pending (scheduled 06:30–06:45 ET). API health restored after a precautionary restart cleared a transient `scheduler=stale` flag.

---

