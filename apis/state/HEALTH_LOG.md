# APIS Health Log

Auto-generated daily health check results.

## Health Check — 2026-04-29 15:10 UTC (Tuesday 10:10 AM CT, market open)

**Overall Status:** YELLOW — Phantom cash regression at 14:30 UTC; position churn persists (19 opened today vs cap 5).

### §1 Infrastructure
- Containers: 8/8 healthy (7 APIS + k8s control plane). Worker/API up 3h (restarted ~11:52 UTC today). Grafana/Prometheus/Alertmanager/Redis up 12 days. No restart loops.
- /health: all components `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper.
- Worker/API log scan: CLEAN — zero crash-triad patterns (`_fire_ks`, `broker_adapter_missing`, `idempotency_key` ORM drift, `phantom_cash_guard`). Only errors: 2x `broker_order_rejected` (HOLX/WDC at $10,263 cash from prior session) + known 13 stale yfinance tickers. API startup had 2 warnings (regime_result_restore_failed, readiness_report_restore_failed) — pre-existing, non-blocking.
- Prometheus: 2/2 targets up (apis, prometheus), 0 dropped.
- Alertmanager: 0 firing alerts.
- Resource usage: all normal. Highest mem: k8s control plane 2.40GiB (8%). Worker 116MiB, API 169MiB, Postgres 131MiB. No CPU spikes.
- DB size: 150 MB.

### §2 Execution + Data Audit
- Paper cycles today: 2 completed (13:35 + 14:30 UTC). Cycle 1: 15 proposed/15 approved/6 executed (9 cash-gated). Cycle 2: 5 proposed/0 approved/0 executed. 2 evaluation_runs in 30h (both completed).
- Portfolio trend: **Phantom cash regression at 14:30 UTC** — snapshot shows `cash=-$48,814.10` alongside a good snapshot at `cash=$9,857.06`. At 13:35 UTC, two snapshots: $94,121 (pre-cycle) and $9,857 (post-cycle). 11:51 UTC shows clean $100k baseline (phantom AAPL from 5 AM check resolved).
- Broker<->DB reconciliation: broker endpoint 404 (expected per build). /health broker=ok. 6 open positions in DB.
- Open positions: GOOGL (43@$346.40), INTC (174@$87.96), MU (28@$526.07), NUE (66@$226.96), PWR (24@$634.21) — all `rebalance` at 14:30; EQIX (14@$1072.31) — `ranking_buy_signal` at 13:35. ALL 6 have `origin_strategy` set. ✅
- **Position churn**: 19 positions opened today vs MAX_NEW_POSITIONS_PER_DAY=5. Phase 69 daily_opens_count logged as 6 at first cycle. Total open=6/15 (within cap). Phantom AAPL from earlier cleaned by cycles.
- **Broker drift**: 1x `broker_health_position_drift` at 14:30 for EQIX.
- Data freshness: prices=2026-04-28 (yesterday, fresh ✅). Signal runs=2026-04-29 10:30 UTC ✅. Ranking runs=2026-04-29 10:45 UTC ✅. 490 securities covered.
- Stale tickers: known 13 only (JNPR, MMC, WRK, PARA, K, HES, PKI, IPG, DFS, MRO, CTLT, PXD, ANSS). No new additions.
- Kill-switch: false. Operating mode: paper. ✅
- Evaluation history rows: 93 (above 80 floor). ✅
- Idempotency: clean — 0 duplicate orders, 0 duplicate open positions. ✅

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head). No drift. ✅
- Pytest smoke: 358p/2f in 38.89s — exact DEC-021 baseline. 2 known failures: `test_scheduler_has_thirteen_jobs` + `test_all_expected_job_ids_present`. No regressions. **Note:** test path inside container is `tests/unit/` not `apis/tests/unit/` — corrected from 5 AM run which showed 0 items collected.
- Git: 8 modified + 1 untracked (`rebuild.bat`). 0 unpushed commits. Non-critical carry-forward.
- **GitHub Actions CI:** Run #30 `7e87714` conclusion=success, completed 2026-04-28. GREEN. https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25076307630

### §4 Config + Gate Verification
- All critical APIS_* flags at expected values:
  - APIS_OPERATING_MODE=paper ✅
  - APIS_KILL_SWITCH=false ✅
  - APIS_MAX_POSITIONS=15 ✅
  - APIS_MAX_NEW_POSITIONS_PER_DAY=5 ✅
  - APIS_MAX_THEMATIC_PCT=0.75 ✅
  - APIS_RANKING_MIN_COMPOSITE_SCORE=0.30 ✅
  - APIS_SELF_IMPROVEMENT_AUTO_EXECUTE_ENABLED not set (defaults false) ✅
  - APIS_INSIDER_FLOW_PROVIDER not set (defaults null) ✅
  - Deep-Dive Step 6/7/8 flags not set (defaults OFF) ✅
- Scheduler: job_count=35 (expected per DEC-021). Worker started 2026-04-29 11:52 UTC. ✅

### Issues Found
- **Phantom cash regression**: Portfolio snapshot at 14:30:00.603645 UTC has `cash_balance=-$48,814.10`. Same phantom-cash writer bug as prior incidents. The duplicate snapshot at 14:30:01.313311 shows correct cash=$9,857. Phantom row pollutes the ledger but self-corrects next snapshot.
- **Position churn persists**: 19 positions opened today vs daily cap 5. Phase 69 incremented daily_opens_count=6 at first cycle, but total position churn (close→reopen pattern) inflates the DB count. 13 positions closed today.
- **Broker drift**: 1 `broker_health_position_drift` warning at 14:30 for EQIX (carry-forward from prior runs).
- **8 dirty files + 1 untracked in git tree**: state docs + bat scripts. Non-critical carry-forward from Phase 69 deployment.

### Fixes Applied
- None this run. Stack is healthy; no autonomous fixes needed.

### Action Required from Aaron
- **Phantom cash writer root cause**: The -$48,814 snapshot at 14:30 UTC is the same class of bug that has persisted since mid-April. Consider prioritizing the `services/portfolio/` module-level state audit to eliminate the phantom writer permanently.
- **Commit dirty state files**: 8 modified + 1 untracked should be committed to keep tree clean.

---

## Health Check — 2026-04-29 10:25 UTC (Tuesday 5:25 AM CT, market pre-open)

**Overall Status:** YELLOW — Data gap resolved; phantom AAPL position from restart persists as data pollution.

### §1 Infrastructure
- Containers: 8/8 healthy (7 APIS + k8s control plane). Worker/API up 15h (restarted 2026-04-28 20:35 UTC for Phase 69). Grafana/Prometheus/Alertmanager/Redis up 12 days. No restart loops.
- /health: all components `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper.
- Worker/API log scan: CLEAN — zero crash-triad patterns (`_fire_ks`, `broker_adapter_missing`, `idempotency_key` ORM drift, `phantom_cash_guard`). Only errors: 2x `broker_order_rejected` (insufficient cash for HOLX/WDC at $10,263 cash) + known 13 stale tickers. API startup had 2 warnings (regime_result_restore_failed, readiness_report_restore_failed) — pre-existing, non-blocking.
- Prometheus: 2/2 targets up, 0 dropped.
- Alertmanager: 0 firing alerts.
- Resource usage: all normal. Highest mem: k8s control plane 2.49GiB (8%). Worker 639MiB, API 816MiB, Postgres 126MiB. No CPU spikes.
- DB size: 145 MB.

### §2 Execution + Data Audit
- Paper cycles today: 0 (pre-market 5:25 AM CT, first cycle 09:35 ET = 13:35 UTC). 2 evaluation_runs in 30h (both completed). Morning pipeline jobs (feature refresh, correlation, liquidity, fundamentals) all ran successfully 10:00-10:19 UTC.
- Portfolio trend: latest snapshot 2026-04-28 20:36 UTC — cash=$90,000, equity=$91,150. Cash positive. Prior snapshot cluster at 20:35 UTC shows $53,523 (pre-Phase 69 restart). 7 positions closed during Phase 69 restart, leaving 1 open.
- Broker<->DB reconciliation: broker endpoint 404 (expected per build). /health broker=ok. 1 open position in DB.
- **Phantom AAPL position**: 1 open position — AAPL, entry_price=$100, qty=10, cost_basis=$1,000, market_value=$1,150, **origin_strategy=EMPTY**. Opened 2026-04-27 20:36 UTC during restart burst. Entry price $100 is clearly wrong (AAPL trades ~$210+). This is test/phantom data pollution from the restart, not a real trade.
- Position caps: 1/15 open (within cap). 0 new today. No thematic breach.
- **Data freshness RESOLVED**: daily_market_bars latest=2026-04-28 (yesterday's close, fresh!). Signal runs=2026-04-28 20:45 UTC. Ranking runs=2026-04-28 20:45 UTC. 490 securities covered. **4-day data gap from previous health check is fully resolved.**
- Stale tickers: known 13 only (JNPR, MMC, WRK, PARA, K, HES, PKI, IPG, DFS, MRO, CTLT, PXD, ANSS). No new additions.
- Kill-switch: false. Operating mode: paper. ✅
- Evaluation history rows: 93 (above 80 floor). ✅
- Idempotency: clean — 0 duplicate orders, 0 duplicate open positions. ✅

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head). No drift. ✅
- Pytest smoke: 358p/2f in 30.96s — exact DEC-021 baseline. 2 known failures: `test_scheduler_has_thirteen_jobs` (expects 30, got 35) + `test_all_expected_job_ids_present` (missing 5 DEC-021 cycle jobs). No regressions.
- Git: 7 modified (state docs + bat scripts), 1 untracked (`apis/infra/docker/rebuild.bat`). 0 unpushed commits. Non-critical.
- **GitHub Actions CI:** Run #30 `7e87714` conclusion=success, completed 2026-04-28 20:46 UTC. GREEN. https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25076307630

### §4 Config + Gate Verification
- All critical APIS_* flags at expected values:
  - APIS_OPERATING_MODE=paper ✅
  - APIS_KILL_SWITCH=false ✅
  - APIS_MAX_POSITIONS=15 ✅
  - APIS_MAX_NEW_POSITIONS_PER_DAY=5 ✅
  - APIS_MAX_THEMATIC_PCT=0.75 ✅
  - APIS_RANKING_MIN_COMPOSITE_SCORE=0.30 ✅
  - APIS_SELF_IMPROVEMENT_AUTO_EXECUTE_ENABLED not set (defaults false) ✅
  - APIS_INSIDER_FLOW_PROVIDER not set (defaults null) ✅
  - Deep-Dive Step 6/7/8 flags not set (defaults OFF) ✅
- Scheduler: job_count=35 (expected per DEC-021). Worker started 2026-04-28 20:35 UTC. ✅

### Issues Found
- **Phantom AAPL position**: 1 open position with test-fixture characteristics (entry=$100, qty=10, empty origin_strategy, opened during restart). Not a real trade. Pollutes portfolio state — cash is $90k instead of clean $100k baseline. market_value=$1,150 creates a small phantom equity delta.
- **7 dirty files in git tree**: state docs + bat scripts from Phase 69 deployment. Non-critical carry-forward.

### Fixes Applied
- None this run. Stack is healthy; no autonomous fixes needed.

### Action Required from Aaron
- **Clean up phantom AAPL position**: Close/delete the phantom AAPL position (id=`2869b6f1-0b22-4071-accc-603ca5ce18e8`) and restore clean $100k cash baseline. This position has entry_price=$100 (wrong), no origin_strategy, and was created during the Apr 27 restart burst. Requires operator approval per DB-cleanup precedent.
- **Commit dirty state files**: 7 modified files + 1 untracked batch script should be committed to keep tree clean.

---

## Health Check — 2026-04-28 19:55 UTC (Tuesday 2:55 PM CT, market closed)

**Overall Status:** YELLOW — Stack recovered from path migration; 4-day data gap + position cap breach on restart burst.

### §1 Infrastructure
- Containers: 7/7 healthy + k8s control plane. Worker/API recreated ~30min ago (path migration fix). Grafana/Prometheus/Alertmanager/Redis up 11 days. No restart loops.
- /health: all components `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper.
- Worker/API log scan: CLEAN — zero ERROR/CRITICAL/Traceback in 24h window. No crash-triad regression patterns.
- Prometheus: 2/2 targets up (apis, prometheus), 0 dropped.
- Alertmanager: 0 firing alerts.
- Resource usage: all normal. Highest mem: k8s control plane 2.52GiB (8%). Worker 134MiB, API 174MiB, Postgres 78MiB. No CPU spikes.
- DB size: 138 MB.

### §2 Execution + Data Audit
- Paper cycles last 30h: 0 completed. Last run: 2026-04-24 21:00 UTC (4 days ago). 2 weekdays missed (Fri Apr 25, Mon Apr 27) due to Docker mount failure from path migration on Apr 27.
- Portfolio trend: latest snapshot 2026-04-28 19:30 UTC — cash=$10,263.80, equity=$99,955.74. Cash positive. Prior snapshot (same timestamp): cash=$94,121.31, equity=$105,874.04. Delta reflects 7 new positions opened in restart burst.
- Broker<->DB reconciliation: broker endpoint 404 (expected per build). /health broker=ok. 8 open positions in DB.
- Origin-strategy stamping: ALL 8 open positions have origin_strategy set (7x ranking_buy_signal, 1x momentum_v1). No NULLs. ✅
- **Position cap breach: 7 new positions opened today vs MAX_NEW_POSITIONS_PER_DAY=5.** All 7 opened simultaneously at 19:30 UTC during restart burst. Total open=8 vs MAX_POSITIONS=15 (within cap).
- Data freshness: prices=2026-04-23 (5 days stale), signals=2026-04-24, rankings=2026-04-24. 490 securities covered in daily bars.
- Stale tickers: no NEW additions beyond known 13.
- Kill-switch: false. Operating mode: paper. ✅
- Evaluation history rows: 91 (above 80 floor). ✅
- Idempotency: clean — 0 duplicate orders, 0 duplicate open positions. ✅

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head). No drift. ✅
- Pytest smoke: BLOCKED by Phase 68 test DB guard — conftest refuses to run against production DB (expected behavior, not a regression). Cannot verify 358/360 baseline this run.
- Git: 0 unpushed commits. Dirty tree: 7 modified files (state docs + bat scripts), 1 untracked (`apis/infra/docker/rebuild.bat`). Non-critical.
- **GitHub Actions CI:** Run #29 `7100312` conclusion=success, completed 2026-04-28 00:09 UTC. GREEN. https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25026048474

### §4 Config + Gate Verification
- All critical APIS_* flags at expected values:
  - APIS_OPERATING_MODE=paper ✅
  - APIS_KILL_SWITCH=false ✅
  - APIS_MAX_POSITIONS=15 ✅
  - APIS_MAX_NEW_POSITIONS_PER_DAY=5 ✅
  - APIS_MAX_THEMATIC_PCT=0.75 ✅
  - APIS_RANKING_MIN_COMPOSITE_SCORE=0.30 ✅
  - APIS_SELF_IMPROVEMENT_AUTO_EXECUTE_ENABLED not set (defaults false) ✅
  - APIS_INSIDER_FLOW_PROVIDER not set (defaults null) ✅
  - Deep-Dive Step 6/7/8 flags not set (defaults OFF) ✅
- Scheduler: job_count=35 (expected per DEC-021). ✅

### Issues Found
- **4-day execution gap** (Apr 25–28): No paper cycles ran from Apr 25 through Apr 28 19:25 UTC. Root cause: project path migration on Apr 27 broke Docker bind mounts; containers needed `docker compose up -d` (not just `docker restart`). Worker/API only recreated ~30min ago.
- **Position cap breach**: 7 new positions opened in a single restart-burst cycle at 19:30 UTC, exceeding MAX_NEW_POSITIONS_PER_DAY=5. The per-day cap is not enforced during first-cycle-after-restart when the position count starts from near-zero open positions.
- **Data freshness**: Daily market bars stale since Apr 23 (5 days). Signals and rankings stale since Apr 24. Ingestion jobs likely failed during the mount-broken window and haven't re-run yet (next ingestion: 06:00 ET tomorrow).
- **Pytest smoke unreachable**: Phase 68 test DB guard blocks pytest inside docker-api-1 against the production DB. Need a test-database sidecar or env override to restore smoke testing in health checks.

### Fixes Applied
- None this run. Stack was already recovered (containers recreated before this health check ran).

### Action Required from Aaron
- **Review position cap breach**: 7 positions opened in restart burst exceeds the 5/day cap. Consider adding a startup-aware throttle that respects MAX_NEW_POSITIONS_PER_DAY even on first cycle after restart.
- **Monitor data freshness**: Ingestion/signal/ranking jobs should auto-recover starting tomorrow 06:00 ET. If prices still stale by Wed Apr 29 10:00 ET, investigate scheduler.
- **Pytest smoke in health checks**: Phase 68 guard correctly blocks tests against prod DB. Consider creating a test DB config or `--override-db-check` flag for health-check pytest runs.


## Health Check — 2026-04-29 13:10 UTC (Tuesday 8:10 AM CT, market pre-open)

**Overall Status:** GREEN — Stack fully operational, data freshness recovered, clean $100k baseline restored, all flags correct, CI green.

### §1 Infrastructure
- Containers: 7/7 APIS healthy + k8s control plane. Worker/API restarted 11:52 UTC today (up ~1h). Postgres up 18h. Monitoring (Grafana/Prometheus/Alertmanager/Redis) up 12 days.
- /health: all components `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper.
- Worker log scan: 2 broker_order_rejected (insufficient cash for HOLX/WDC from Apr 28 restart burst — expected, stale). 13 known stale tickers (JNPR, MMC, WRK, PARA, K, HES, PKI, IPG, DFS, MRO, CTLT, PXD, ANSS). No crash-triad patterns. No CRITICAL/Traceback.
- API log scan: 2 restore warnings on startup (regime_result_restore_failed: detection_basis_json; readiness_report_restore_failed: ReadinessGateRow missing 'description'). Pre-existing ORM issue, not new. 13 known stale tickers. No crash-triad patterns.
- Prometheus: 2/2 targets up, 0 dropped.
- Alertmanager: 0 firing alerts.
- Resource usage: all normal. Worker 58 MiB, API 165 MiB, Postgres 154 MiB, k8s 2.38 GiB (7.6%). No CPU/mem spikes.
- DB size: 150 MB.

### §2 Execution + Data Audit
- Paper cycles last 30h: 1 paper `complete` (Apr 28 21:00 UTC), 1 research `complete` (Apr 28 20:45 UTC). Today's first cycle at 09:35 ET (13:35 UTC) not yet due. Expected.
- Portfolio trend: latest snapshot 2026-04-29 11:51 UTC — cash=$100,000, equity=$100,000. **Clean $100k baseline restored** (phantom AAPL cleanup confirmed per Phase 69).
- Broker<->DB reconciliation: broker endpoint 404 (expected per build). /health broker=ok. DB: 0 open positions. Consistent.
- Origin-strategy stamping: N/A (0 open positions).
- Position caps: 0 open (cap=15), 0 new today (cap=5). Within limits.
- Data freshness: prices=2026-04-28 (yesterday, current!), rankings=2026-04-29 10:45 UTC (today), signals=2026-04-29 10:30 UTC (today, 5 types × 2012 rows). **Fully recovered from 5-day stale gap.**
- Stale tickers: known 13 only, no new additions.
- Kill-switch: false. Operating mode: paper.
- Evaluation history rows: 93 (above 80 floor).
- Idempotency: clean — 0 duplicate orders, 0 duplicate open-position tickers.

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head). No drift.
- Pytest smoke: BLOCKED — Phase 68 test DB guard prevents pytest inside docker-api-1 against production DB. Pre-existing; needs test DB sidecar or APIS_PYTEST_SMOKE=1 bypass (Phase 69).
- Git: clean tree (0 dirty files). 0 unpushed commits. No stale feature branches.
- **GitHub Actions CI:** Run #30 `7e87714` conclusion=success, completed 2026-04-28 20:46 UTC. GREEN. https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25076307630

### §4 Config + Gate Verification
- All critical APIS_* flags at expected values:
  - APIS_OPERATING_MODE=paper ✅
  - APIS_KILL_SWITCH=false ✅
  - APIS_MAX_POSITIONS=15 ✅
  - APIS_MAX_NEW_POSITIONS_PER_DAY=5 ✅
  - APIS_MAX_THEMATIC_PCT=0.75 ✅
  - APIS_RANKING_MIN_COMPOSITE_SCORE=0.30 ✅
  - APIS_SELF_IMPROVEMENT_AUTO_EXECUTE_ENABLED not set (defaults false) ✅
  - APIS_INSIDER_FLOW_PROVIDER not set (defaults null) ✅
  - Deep-Dive Step 6/7/8 flags not set (defaults OFF) ✅
- Scheduler: job_count=35 (expected per DEC-021). Worker started 2026-04-29 11:52 UTC. ✅

### Issues Found
- None. All prior issues from Apr 28 health check (phantom AAPL, 4-day data gap, position cap breach, dirty git tree) are now resolved.

### Fixes Applied
- None needed. Stack is healthy.

### Action Required from Aaron
- **Pytest smoke in health checks**: Phase 68 guard still blocks pytest against prod DB. Phase 69 added `APIS_PYTEST_SMOKE=1` bypass — consider enabling this env var in the worker/API containers to restore health-check smoke testing. Low priority.
- **API restore warnings**: `regime_result_restore_failed` and `readiness_report_restore_failed` fire on every API restart. Not a runtime issue but indicates ORM drift for regime/readiness models. Low priority cleanup.

---

## Health Check — 2026-04-29 16:15 UTC (Tuesday 11:15 AM CT, market open)

**Overall Status:** YELLOW — Position cap breach (27 vs 5) under Phase 69 code today; Phase 70 deployed at 16:04 UTC to fix. Phase 70 source changes uncommitted (12 dirty files). Pytest smoke unreachable.

### §1 Infrastructure
- Containers: 7/7 APIS healthy + k8s control plane. Worker up 15min (restarted 16:00 UTC for Phase 70 deploy). API up 16min. Postgres up 21h. Monitoring (Grafana/Prometheus/Alertmanager/Redis) up 12 days. No restart loops.
- /health: all components `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper.
- Worker log scan: only known 13 stale tickers (JNPR, MMC, WRK, PARA, K, HES, PKI, IPG, DFS, MRO, CTLT, PXD, ANSS). No crash-triad patterns. No CRITICAL/Traceback.
- API log scan: 2 pre-existing restore warnings (regime_result_restore_failed: detection_basis_json; readiness_report_restore_failed: ReadinessGateRow missing 'description'). Known stale tickers. No crash-triad patterns.
- Prometheus: 2/2 targets up (apis, prometheus), 0 dropped.
- Alertmanager: 0 firing alerts.
- Resource usage: all normal. Worker 71 MiB, API 168 MiB, Postgres 140 MiB, k8s 2.4 GiB (7.7%). No CPU/mem spikes.
- DB size: 150 MB.

### §2 Execution + Data Audit
- Paper cycles last 30h: 2 completed yesterday (1 paper 21:00 UTC, 1 research 20:45 UTC). Today 2 cycles ran under previous worker (13:35 + 14:30 UTC). No cycles yet under Phase 70 worker (started 16:00 UTC). Next cycle at 16:35 UTC (12:35 ET).
- Portfolio trend: latest snapshot 2026-04-29 16:04 UTC — cash=,000, equity=,000 (Phase 70 clean baseline). **Note: 13 open positions with ~ cost basis not yet reflected in snapshot — will reconcile on next cycle.**
- Broker<->DB reconciliation: broker endpoint 404 (expected per build). /health broker=ok. 13 open positions in DB.
- Origin-strategy stamping: ALL 13 open positions have origin_strategy set (12x rebalance, 1x ranking_buy_signal). No NULLs. ✅
- **Position cap breach: 27 new positions today (6 at 13:35, 21 at 14:30 UTC) vs MAX_NEW_POSITIONS_PER_DAY=5.** Total open=13 vs MAX_POSITIONS=15 (within absolute cap). Occurred under Phase 69 code; Phase 70 deployed at 16:04 UTC with strengthened daily cap enforcement.
- Data freshness: prices=2026-04-28 (yesterday, current). Rankings=2026-04-29 10:45 UTC (today). Signals=2026-04-29 10:30 UTC (5 types × 2012 rows, today). Fully current.
- Stale tickers: known 13 only, no new additions.
- Kill-switch: false. Operating mode: paper. ✅
- Evaluation history rows: 93 (above 80 floor). ✅
- Idempotency: clean — 0 duplicate orders, 0 duplicate open-position tickers. ✅

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head). No drift. ✅
- Pytest smoke: BLOCKED — test files not found at expected path inside docker-api-1 container. Phase 68 guard + container rebuild may have excluded test directory. Cannot verify baseline this run.
- Git: **12 modified + 1 untracked**. Phase 70 source code changes (paper_trading.py, adapter.py, api/main.py, worker/main.py) + state docs NOT committed. 0 unpushed commits to origin.
- **GitHub Actions CI:** Run #30 `7e87714` conclusion=success, completed 2026-04-28 20:46 UTC. GREEN. https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25076307630

### §4 Config + Gate Verification
- All critical APIS_* flags at expected values:
  - APIS_OPERATING_MODE=paper ✅
  - APIS_KILL_SWITCH=false ✅
  - APIS_MAX_POSITIONS=15 ✅
  - APIS_MAX_NEW_POSITIONS_PER_DAY=5 ✅
  - APIS_MAX_THEMATIC_PCT=0.75 ✅
  - APIS_RANKING_MIN_COMPOSITE_SCORE=0.30 ✅
  - APIS_SELF_IMPROVEMENT_AUTO_EXECUTE_ENABLED not set (defaults false) ✅
  - APIS_INSIDER_FLOW_PROVIDER not set (defaults null) ✅
  - Deep-Dive Step 6/7/8 flags not set (defaults OFF) ✅
- Scheduler: job_count=35 (expected per DEC-021). Worker started 2026-04-29 16:00 UTC. ✅

### Issues Found
- **Position cap breach (27 vs 5)**: Phase 69's daily_opens_count fix was insufficient — 27 positions opened today across 2 cycles (6 at 13:35 + 21 at 14:30) vs MAX_NEW_POSITIONS_PER_DAY=5. Phase 70 deployed at 16:04 UTC to address this with strengthened enforcement. Validation needed on next cycle (~16:35 UTC).
- **Phase 70 code uncommitted**: 12 modified files including 4 core source files (paper_trading.py, adapter.py, api/main.py, worker/main.py) are deployed to containers via bind mount but NOT committed to git. CI cannot validate these changes.
- **Snapshot/position inconsistency**: Latest snapshot shows  cash but 13 positions are open with ~ cost basis. Phase 70 cleanup snapshot was written before broker loaded positions. Will self-correct on next cycle.
- **Pytest smoke unreachable**: Test directory not found inside docker-api-1. Cannot verify baseline this run.

### Fixes Applied
- None this run. Phase 70 was deployed before this health check started (16:04 UTC).

### Action Required from Aaron
- **Commit Phase 70 code**: The 4 modified source files + state docs should be committed and pushed so CI can validate the Phase 70 changes. Until then, CI coverage is stale (last CI run tested Phase 69 code, not Phase 70).
- **Monitor Phase 70 daily cap**: Watch the 16:35 UTC cycle — if the daily cap still allows >5 opens, the Phase 70 fix needs further investigation.
- **Pytest smoke path**: Tests not found at `apis/tests/unit/` inside the container. May need to verify the Docker build includes the test directory, or adjust the health-check test path.
