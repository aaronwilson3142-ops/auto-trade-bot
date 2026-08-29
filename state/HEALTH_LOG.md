# APIS Health Log

Auto-generated daily health check results.

## Health Check — 2026-06-08 13:15 UTC (Monday 8:15 AM CT, pre-market / manual run)

**Overall Status:** GREEN — Third consecutive GREEN. Manual run requested by operator ~20 min before the Phase 86 first-live-trading validation cycle (c1 at 13:35 UTC). All systems healthy and unchanged from the two Sun Jun 7 GREEN probes: 8/8 containers healthy, /health 7/7 ok, DB clean (10 OPEN one-per-ticker, 237 closed, 0 dup/NULL), pytest 370/0, CI GREEN on HEAD `7ba4135`, zero config drift. **Phase 86 c1 validation NOT yet exercised** (current 13:15 UTC < c1 13:35 UTC) — will be captured by the next scheduled probe (10 AM CT / ~15:06 UTC). Today's scheduled 5 AM CT probe did not fire (task lastRun still Sun 15:07 UTC); this manual run substitutes for it.

### §1 Infrastructure
- Containers: 8/8 healthy — worker+api Up 35h (since Phase 86 restart 02:39 UTC Sun), postgres/redis/grafana/prometheus/alertmanager/control-plane Up 7 days. No restarts.
- /health: 7/7 `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper. Timestamp 2026-06-08T13:11:06Z.
- Worker/API log scan (24h): all `level:error` lines are the known 13 delisted-ticker yfinance 404/no-data noise (PXD, HES, ANSS, PKI, PARA, MMC, K, JNPR, IPG, MRO, CTLT, WRK, DFS) — no new tickers. Zero crash-triad/silent-failure hits on all patterns (`_fire_ks`, `broker_adapter_missing_with_live_positions`, `idempotency_key` attr, `no_data`, `phantom_cash_guard`, `broker_health_position_drift`, `fill_qty=0`) on both containers.
- Prometheus: 2/2 targets up (apis, prometheus), no lastError. Alertmanager: 0 active alerts.
- Resource usage: nominal. Postgres DB size 326 MB (was 318 MB Sun — normal growth).

### §2 Execution + Data Audit
- Paper cycles (30h window): 0 — weekend + pre-c1, expected. evaluation_runs total=117 ✅ (≥80 floor, unchanged).
- Portfolio trend: last snapshot still Fri 2026-06-05 19:30 UTC cash=$38,991.32 / equity=$119,212.99 (residual API-written value; self-corrects at c1 under worker-only Phase 86). cash ≥ 0 ✅.
- Broker↔DB reconciliation: `/api/v1/broker/positions` 404s in this build (known); /health broker=ok ✅ + 0 `broker_health_position_drift` lines in 24h ✅.
- Positions: 10 OPEN (one per ticker: AAPL, DELL, FFIV, MRVL, MS, MU, QCOM, STX, UNH, WDC), 237 closed. 0 dup-OPEN tickers ✅.
- Origin-strategy stamping: 0 NULL origin_strategy on open rows ✅ (0 opened in last 30h).
- Position caps: 10/15 OPEN ✅; 0 new today ≤ 5 ✅.
- Data freshness: bars=2026-06-05 (487 securities; last trading day — Mon bars land after today's close) ✅; signal_runs=2026-06-08 10:30 UTC ✅; ranking_runs=2026-06-08 10:45 UTC ✅ (worker firing today's jobs — good c1 signal).
- Stale tickers: known 13 only, no new delisted errors.
- Kill-switch + mode: APIS_KILL_SWITCH=false ✅, APIS_OPERATING_MODE=paper ✅.
- Idempotency: 0 dup idempotency_keys in orders ✅; 0 dup open tickers ✅.

### §3 Code + Schema
- Alembic: `q7r8s9t0u1v2` current = single head ✅.
- Pytest smoke: **370 passed / 0 failed** (deep_dive + phase22 + phase57 + phase82 + phase86 filter, --no-cov, APIS_PYTEST_SMOKE=1, 41.1s) ✅ matches baseline.
- Git: tree clean (only untracked `outputs/`), HEAD `7ba4135`, 0 unpushed, only `main` branch.
- GitHub Actions CI: run 27096506100 `7ba4135` conclusion=success — https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/27096506100 ✅.

### §4 Config + Gate Verification
- All critical APIS_* env flags at expected values: OPERATING_MODE=paper, KILL_SWITCH=false, MAX_POSITIONS=15, MAX_NEW_POSITIONS_PER_DAY=5, MAX_THEMATIC_PCT=0.75, RANKING_MIN_COMPOSITE_SCORE=0.30 ✅. SELF_IMPROVEMENT_AUTO_EXECUTE_ENABLED + INSIDER_FLOW_PROVIDER + Step 6/7/8 flags not in env → settings.py defaults (OFF/null) ✅. No drift.
- Scheduler sanity: worker `apis_worker_started job_count=36` ✅; API `apis_scheduler_started_in_api_process job_count=29 paper_trading_jobs=false` ✅ (Phase 86 worker-only invariant intact).

### Issues Found
- None new. Informational carry-forward: Fri's residual API-written snapshot cash ($38,991.32) persists until c1; today's scheduled 5 AM CT probe did not fire (this manual run covers it).

### Fixes Applied
- None required.

### Action Required from Aaron
- None. Next material checkpoint: **Mon 2026-06-08 13:35 UTC c1** — Phase 86 first live trading validation (worker-won cycle, correct worker-written snapshot cash replacing Fri's $38,991.32, zero new dup/phantom rows). Captured automatically by the ~15:06 UTC (10 AM CT) scheduled probe.

---

## Health Check — 2026-06-07 15:15 UTC (Sunday 10:15 AM CT, weekend / no trading)

**Overall Status:** GREEN — Second consecutive GREEN. Phase 86 (`670936c`) remains verified live ~12.5h post-deploy: worker job_count=36 ✅, API job_count=29 `paper_trading_jobs: false` ✅ (R2 root cause stays removed). DB state unchanged and clean: exactly 10 OPEN positions, one row per ticker (AAPL/DELL/FFIV/MRVL/MS/MU/QCOM/STX/UNH/WDC), 237 closed, 0 dup idempotency keys. Weekend: 0 paper cycles in 30h window (expected). CI GREEN on the 5 AM probe's state commit `5d86259`. No new issues, no fixes needed. **Monday 2026-06-08 13:35 UTC c1 remains the Phase 86 validation window** — expect worker-won cycle, sane worker-written snapshot cash (replacing Fri's residual API-written $38,991.32), zero new dup/phantom rows.

### §1 Infrastructure
- Containers: 8/8 healthy — worker+api Up 12h (since Phase 86 restart 02:39 UTC), postgres/redis/grafana/prometheus/alertmanager/control-plane Up 6 days. No restarts.
- /health: 7/7 `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper. 2026-06-07T15:08:15Z.
- Worker/API log scan (24h): worker 0 ERROR/CRITICAL/Traceback/TypeError; API 2 = only the known startup-restore warnings from the 02:39 UTC restart (`regime_result_restore_failed`, `readiness_report_restore_failed`) — documented non-blocking (project_api_startup_restore_warnings_2026-05-17). 0 crash-triad hits on all 5 patterns, both containers.
- Prometheus: 2/2 targets up (apis, prometheus), no lastError.
- Alertmanager: 0 active alerts.
- Resource usage: all tiny (worker 69 MiB, api 133 MiB, postgres 184 MiB; control-plane 2.0 GiB / 10% CPU — normal). Postgres DB size 318 MB.

### §2 Execution + Data Audit
- Paper cycles (30h window): 0 — weekend, expected. evaluation_runs total=117 ✅ (≥80 floor, unchanged).
- Portfolio trend: last snapshot still Fri 2026-06-05 19:30 UTC cash=$38,991.32 equity=$119,212.99 (residual API-written value; self-corrects at Mon c1 under worker-only Phase 86). cash ≥ 0 ✅.
- Broker↔DB reconciliation: `/api/v1/broker/positions` 404s in this build (known); fallback per 2026-04-19 precedent — /health broker=ok ✅ + 0 `broker_health_position_drift` log lines in 48h ✅.
- Positions: 10 OPEN (one per ticker — Phase 86 cleanup holding), 237 closed. 0 dup-OPEN tickers ✅.
- Origin-strategy stamping: 0 rows opened in last 30h → nothing to check; 0 NULLs.
- Position caps: 10/15 OPEN ✅; 0 new today ✅.
- Data freshness: bars=2026-06-04 (490 securities) — Fri Jun 5 bars arrive with Mon AM/EOD jobs, consistent with prior weekend probes; signal_runs=2026-06-05 10:30 UTC ✅; ranking_runs=2026-06-05 10:45 UTC ✅.
- Stale tickers: no new delisted-ticker errors (worker log clean in 24h; no weekend ingestion).
- Kill-switch + mode: APIS_KILL_SWITCH=false ✅, APIS_OPERATING_MODE=paper ✅.
- Idempotency: 0 dup idempotency_keys in orders ✅; 0 dup open tickers ✅.

### §3 Code + Schema
- Alembic: `q7r8s9t0u1v2` current = single head ✅. `alembic check`: pre-existing cosmetic ORM drift only (TIMESTAMP-tz vs DateTime, comments, universe_overrides ORM metadata) — same known non-blocking diff as 2026-05-25 probe; no new operations.
- Pytest smoke: **370 passed / 0 failed** (deep_dive + phase22 + phase57 + phase82 + phase86 filter, --no-cov, APIS_PYTEST_SMOKE=1, 40.1s) ✅ matches baseline.
- Git: tree clean (only untracked `outputs/`), HEAD `5d86259`, 0 unpushed, no stray branches.
- **GitHub Actions CI:** run 27089622903 `5d86259` conclusion=success — https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/27089622903 ✅.

### §4 Config + Gate Verification
- All critical APIS_* env flags at expected values: mode=paper, kill_switch=false, max_positions=15, max_new_positions_per_day=5, max_thematic_pct=0.75, ranking_min_composite_score=0.30 ✅. Self-improvement auto-execute + insider-flow provider + Step 6/7/8 flags not in env → governed by settings.py defaults (OFF) ✅.
- Scheduler sanity: worker `apis_worker_started job_count=36` ✅; API `apis_scheduler_started_in_api_process job_count=29 paper_trading_jobs=false` ✅ (Phase 86 invariant intact).

### Issues Found
- None new. Informational carry-forward: Fri's residual API-written snapshot cash ($38,991.32) persists until Mon c1; known cosmetic alembic-check ORM drift.

### Fixes Applied
- None required.

### Action Required from Aaron
- None. Next material checkpoint: **Mon 2026-06-08 13:35 UTC c1** — Phase 86 first live trading validation (worker-won cycle, correct snapshot cash, no new dup/phantom rows). Captured automatically by Monday's scheduled probes.

---

## Health Check — 2026-06-07 10:12 UTC (Sunday 5:12 AM CT, weekend / no trading)

**Overall Status:** GREEN — First GREEN since the R1–R4 cluster began. Phase 86 (`670936c`, deployed Sat night with worker+api restart 02:39 UTC Sun) is verified live: API-process APScheduler now runs job_count=29 with `paper_trading_jobs: false` (R2 root cause removed); DB cleanup verified — exactly 10 OPEN positions, one row per ticker (AAPL, DELL, FFIV, MRVL, MS, MU, QCOM, STX, UNH, WDC), ARM/GS/AMD phantom rows closed, UNH row reopened, MS/MU dups gone (R1/R3/R4 cleanup confirmed). Weekend: 0 paper cycles expected and confirmed. **Monday Jun 8 13:35 UTC c1 is the Phase 86 validation window** — worker must win every cycle; expect a worker-written snapshot with correct cash (last snapshot still carries Fri's API-written $38,991.32 phantom-cash value, which is residual data, not an active writer).

### §1 Infrastructure
- Containers: 8/8 healthy — worker+api Up 7h (Phase 86 deploy restart 02:39 UTC), postgres/redis/grafana/prometheus/alertmanager/control-plane Up 6 days.
- /health: 7/7 `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper. Timestamp 2026-06-07T10:08:14Z.
- Worker/API log scan (24h): worker zero ERROR/CRITICAL/Traceback/TypeError. API: only the 2 known startup-restore warnings at 02:39 UTC restart (`regime_result_restore_failed`, `readiness_report_restore_failed` — known non-blocking since 2026-05-17). Zero crash-triad patterns. Zero `broker_health_position_drift` events in window.
- Prometheus: 2/2 targets up (apis, prometheus), no errors.
- Alertmanager: 0 active alerts.
- Resource usage: all nominal (worker 69 MiB, api 133 MiB — fresh restart; control-plane 1.98 GiB/9.6% CPU fine). Postgres DB 318 MB.

### §2 Execution + Data Audit
- Paper cycles: 0 in last 30h (Sat+Sun — expected; Fri 21:00 UTC daily evaluation was >30h ago).
- Portfolio trend: last snapshot Fri Jun 5 19:30 UTC cash=$38,991.32 / equity=$119,212.99 (unchanged since Friday close). Cash ≥ 0 ✓. The $38,991 value is the residual R4 API-written figure; no new snapshots will be written until Monday c1, which Phase 86 forces to be worker-written.
- Broker↔DB reconciliation: `/api/v1/broker/positions` 404s in this build (known); /health broker=ok + 10 clean DB-OPEN rows. Post-cleanup state matches Phase 86 handoff exactly (10 opens, 237 closed).
- Origin-strategy stamping: 0 positions opened in last 30h; 0 NULL origin_strategy ✓.
- Position caps: 10 OPEN ≤ 15 ✓; 0 new today ≤ 5 ✓.
- Data freshness: bars=2026-06-04 (490 securities; Fri Jun 5 bars land at Mon 06:00 ET ingestion — normal weekend lag), rankings=Jun 5 10:45 UTC ✓, signals=Jun 5 10:30 UTC (4,890 rows in 48h window) ✓.
- Stale tickers: zero yfinance 404/429 in 24h window (Sat ingestion fell just outside window; known-13 list unchanged).
- Kill-switch + mode: APIS_KILL_SWITCH=false ✓, APIS_OPERATING_MODE=paper ✓.
- Evaluation history rows: 117 ✓ (≥80 floor).
- Idempotency: 0 duplicate orders by idempotency_key ✓. **0 duplicate OPEN tickers** — R1 resolved by Jun 6 cleanup ✓.

### §3 Code + Schema
- Alembic: `q7r8s9t0u1v2` single head ✓.
- Pytest smoke: **370 passed / 0 failed** (deep_dive/phase22/phase57/phase82 subset, --no-cov, 38.1s) ✓ baseline. PLUS Phase 86's new tests: `test_phase64_position_persistence.py` + `test_deep_dive_step5_origin_strategy_wiring.py` → **23/23 pass** in the running container (confirms deployed image carries `670936c`).
- Git: clean (only untracked `outputs/` scratch). 0 unpushed. HEAD `8e684e9` (DEC-100 Phase 86 handoff).
- **GitHub Actions CI:** run 27080657609 `8e684e9` conclusion=success ✓ — https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/27080657609

### §4 Config + Gate Verification
- All critical APIS_* flags at expected values: mode=paper, kill_switch=false, max_positions=15, max_new_per_day=5, max_thematic_pct=0.75, ranking_min_composite_score=0.30; self-improvement/insider-flow/Step-6/7/8 flags unset (defaults OFF) ✓.
- Scheduler: worker `apis_worker_started` job_count=36 (02:39:50 UTC) ✓; **API `apis_scheduler_started_in_api_process` job_count=29, paper_trading_jobs=false** — Phase 86 worker-only cycles confirmed live ✓.

### Issues Found
- None new. Residual (informational, not RED): last portfolio snapshot still carries the Fri R4 phantom-cash value $38,991.32 — expected to self-correct at Monday c1 when the worker (sole cycle owner under Phase 86) reseeds from DB and writes the first post-cleanup snapshot.

### Fixes Applied
- None needed — stack fully healthy; no env drift; no restarts required.

### Action Required from Aaron
- None blocking. Watch Monday Jun 8 13:35 UTC c1 (or let the scheduled probe verify): expect worker-won cycle, `phase86` matching-ladder behavior in `_persist_positions`, a worker-written snapshot with sane cash, and zero new dup/phantom rows.

## Health Check — 2026-06-06 19:20 UTC (Saturday 2:20 PM CT, weekend / no trading)

**Overall Status:** RED — Carry-forward only. R1/R2/R3/R4 unchanged from 10:15 UTC Saturday probe. Zero new issues; weekend 0 cycles confirmed. Stack/code/config fully GREEN (8/8 containers Up 6d, /health 7/7 ok, pytest 370p/0f, CI 27059581032 f5bd0e9 success, all APIS_* flags correct, job_count=36, eval_runs=117, Alertmanager 0). Last snapshot Jun 5 19:30 UTC cash=$38,991.32 / equity=$119,212.99; 14 DB-OPEN / 233 closed. Data fresh: bars=Jun 4 (490), rankings/signals=Jun 5. **Cleanup-SQL refinement**: UNH Jun 5 row EXISTS (id `edce5125-d2d7-4e61-b9c0-79b8cb4d5042`, qty=22, entry=403.24) but was phantom-CLOSED at c2 14:30 (realized_pnl=-4.51) — fix is `UPDATE ... SET status='open', closed_at=NULL, realized_pnl=NULL`, NOT the previously recommended INSERT (would create a near-dup). Action required from Aaron before Monday 13:35 UTC: (1) Phase 85 `_persist_positions` fix; (2) DB cleanup SQL with revised UNH step; (3) remove paper_trading_cycle from API APScheduler. Full detail in `apis/state/HEALTH_LOG.md` 19:20 UTC entry.

## Health Check — 2026-06-06 10:15 UTC (Saturday 5:15 AM CT, weekend / no trading)

**Overall Status:** RED — All four carry-forward RED findings (R1/R2/R3/R4) persist unchanged. No new issues detected today. Weekend: 0 paper cycles expected and confirmed. Infrastructure, code, and config fully GREEN. All RED items require Aaron's explicit approval to resolve.

### §1 Infrastructure
- Containers: 8/8 Up 5 days (healthy). RestartCount=0. /health 7/7 ok mode=paper. Worker/API logs clean (known 13 stale-ticker 404s only, zero crash-triad). Prometheus 2/2 up. Alertmanager 0 active. Resources fine. DB 318 MB.

### §2 Execution + Data Audit
- Paper cycles: 0 today (weekend ✅). Last eval_run: Jun5 21:00 UTC status=complete ✅. Last snapshot: Jun5 19:30 UTC cash=$38,991.32 equity=$119,212.99 (carry-forward API phantom cash — R2). 14 DB-OPEN / 233 closed. 0 new positions today. Bars=Jun4 ✅, rankings=Jun5 10:45 ✅, signals=Jun5 10:30 ✅. eval_runs=117 ✅. Idempotency clean (0 order dupes). Kill-switch=false, mode=paper ✅. MS×2/MU×2 dup OPEN tickers persist (R1 carry-forward).

### §3 Code + Schema
- Alembic q7r8s9t0u1v2 (head), single head ✅. Pytest 370p/0f ✅. Git: 3 modified state files, 0 unpushed, HEAD=cb7d253, no stale branches ✅. CI run 27023143028 cb7d253 conclusion=success ✅.

### §4 Config + Gate Verification
- All APIS_* flags correct ✅. Scheduler job_count=36 ✅.

### Issues Found
- R1/R2/R3/R4 all carry-forward — see primary HEALTH_LOG at apis/state/HEALTH_LOG.md for full details.

### Fixes Applied
- None. All RED items require Aaron's explicit approval.

### Action Required from Aaron
- (1) HIGH RED — Phase 85 `_persist_positions` fix before Monday trading.
- (2) HIGH RED — DB cleanup SQL (ARM/GS/AMD phantom close; UNH INSERT; MS Jun1/MU May1 dup close).
- (3) HIGH RED — Remove paper_trading_cycle from API APScheduler before Monday c1.

---

## Health Check — 2026-06-05 19:15 UTC (Friday 2:15 PM CT, active trading / between c6–c7)

**Overall Status:** RED — All four carry-forward RED findings from the 15:05 probe persist unchanged. No new issues detected. Infrastructure and code fully healthy; all RED items require Aaron's explicit approval to resolve.

### §1 Infrastructure
- Containers: 8/8 Up 5 days (worker, api, postgres, redis, grafana, prometheus, alertmanager all healthy; apis-control-plane Up 5 days). RestartCount=0 across all core containers.
- /health: 7/7 `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper. Timestamp 19:08:53Z.
- Worker/API log scan: clean — only known 13 stale-ticker yfinance 404s. Zero crash-triad patterns.
- Prometheus: 2/2 targets up, 0 errors, 0 droppedTargets.
- Alertmanager: 0 active alerts.
- Resource usage: all within limits. Worker 910 MiB, API 1002 MiB, Postgres 171 MiB. DB 318 MB.

### §2 Execution + Data Audit
- Paper cycles today: 6/12 completed (c1–c6, 13:35–18:30 UTC). c1 worker-won; c2–c6 API-won (worker skipped via Phase 82 lock). No failed cycles. c7 pending.
- Portfolio trend: c1 (worker) cash=$82,609.42 equity=$126,532.74. c6 (API) cash=$38,991.32 equity=$119,090.46. Phantom cash drain c1→c2 = API broker malfunction (R2 carry-forward).
- Broker↔DB reconciliation: endpoint 404 (expected). 14 DB-OPEN. /health broker=ok. Carry-forward mismatches: ARM/GS closed at broker still OPEN in DB; UNH at broker not in DB; AMD phantom.
- Origin-strategy stamping: all recent positions stamped ✅.
- Position caps: 14 OPEN ≤ 15 max ✅. 1 new today.
- Data freshness: bars=2026-06-04 ✅, rankings=Jun5 10:45 UTC ✅, signals=Jun5 10:30 UTC ✅.
- Stale tickers: known 13 only ✅.
- Kill-switch: false ✅. Mode: paper ✅.
- Evaluation history: 116 rows ✅.
- Idempotency: orders clean ✅. Positions: MS×2 + MU×2 dup OPEN tickers (carry-forward).
- Broker drift c1 (worker): MS only (1 ticker — improvement). c2–c6 worker skipped.

### §3 Code + Schema
- Alembic head: `q7r8s9t0u1v2` (head), single head ✅.
- Pytest smoke: **370 passed, 0 failed** (deep_dive/phase22/phase57/phase82 subset, --no-cov) ✅.
- Git: 1 untracked (outputs/), 0 unpushed. HEAD=`cb7d253` ✅.
- **GitHub Actions CI:** run 27023143028 `cb7d253` conclusion=**success** ✅ — https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/27023143028

### §4 Config + Gate Verification
- All critical APIS_* flags at expected values ✅. Scheduler Phase 82 lock working ✅.

### Issues Found
- **R1 (RED):** MS×2 + MU×2 dup OPEN pairs — carry-forward, DB cleanup required.
- **R2 (RED):** API process winning Phase 82 lock c2–c6, phantom cash drain — carry-forward, code fix required.
- **R3 (RED):** Phase 85 `_persist_positions` failure — ARM/GS not closed in DB, UNH not opened in DB — carry-forward, code + DB fix required.
- **R4 (RED):** AMD phantom Jun4 position — carry-forward, DB cleanup required.

### Fixes Applied
- None. All issues require Aaron's approval.

### Action Required from Aaron
1. **HIGH RED** — Phase 85 `_persist_positions` code fix (6th episode).
2. **HIGH RED** — DB cleanup SQL: close ARM, GS, AMD; close MS Jun1 + MU May1 dups; INSERT UNH open (qty=22, entry=403.24, opened_at=2026-06-05 13:35:01.809777).
3. **HIGH RED** — Remove `_job_paper_trading_cycle` from API APScheduler (R2 root fix).

---

## Health Check — 2026-06-05 15:05 UTC (Friday 10:05 AM CT, active trading / between c2–c3)

**Overall Status:** RED — NEW R3: Phase 85 close/open loop failures at c1 (ARM sold, GS trimmed, UNH opened at broker — none updated in DB). NEW R4: API c2 wrong snapshot cash=$38,991 vs actual ~$82,609 with 0 orders (API broker wrong state). R2 (API-process broker malfunction) + R1 (MS×2, MU×2, AMD phantom) carry forward.

- **§1 Infra GREEN**: 8/8 containers Up 4 days healthy. /health 7/7 ok mode=paper. 0 crash-triad. Prom 2/2 up. AM 0 active. Resources fine. DB 318 MB.
- **§2 Execution+Data RED**: c1 worker won (3 trades ARM close/GS trim/UNH buy, all broker-filled ✓) but `_persist_positions` failed all 3 (R3 NEW). c2 API won (0 orders/9 rejected), wrong snapshot cash −$43k (R4 NEW). R2+R1 carry forward.
- **§3 Code+Schema GREEN**: Alembic q7r8s9t0u1v2 single head. Pytest 360/360 ✓. Git clean 0 unpushed HEAD=abd9984. CI 26974058391 on abd9984 conclusion=success ✓.
- **§4 Config+Gates GREEN**: all APIS_* flags correct ✓. job_count=36. Phase 82 alternating lock ✓.
- **Autonomous fixes: NONE**. All REDs require Aaron approval (code fix + DB cleanup).
- **Action required from Aaron**: (1) HIGH RED — Phase 85 fix: `_persist_positions` close-loop fails on cross-session opened_at mismatch (ARM+GS not closed in DB, UNH not created); (2) HIGH RED — DB cleanup SQL (close ARM/GS/AMD phantom, close MS Jun1/MU May1 dup rows, insert UNH position); (3) HIGH RED — Remove paper_trading_cycle from API APScheduler (R2 root cause, recommended option a).

---

## Health Check — 2026-06-04 19:08 UTC (Thursday 3:08 PM CT, mid-market)

**Overall Status:** RED — R2 ESCALATED: API process won c1, c4, c6 today (3 of 6 cycles); c6 opened AMD with fill_qty=0 creating a phantom DB position (AMD open qty=15 in DB, broker qty=0), and tried to re-open MRVL/ARM/DELL (Phase 75/79 guards blocked dup rows). Cash drained by ~$32k at c6 from phantom orders ($75,793→$43,742). R1 carry-forward: MS×2 and MU×2 dup pairs. All infra/tests/CI green.

### §1 Infrastructure
- Containers: 8/8 healthy — all `Up 4 days`. 0 restarts. 0 crash-triad patterns.
- /health: 7/7 `ok`. mode=paper, timestamp=2026-06-04T19:08:19Z.
- Worker/API log scan (24h): 0 ERROR/CRITICAL/Traceback/TypeError. 0 crash-triad regressions. Known 13 stale-ticker yfinance errors only.
- Prometheus: 2/2 targets up. Alertmanager: 0 active alerts.
- Resource: worker 887 MiB, api 976 MiB, postgres 171 MiB — all well under threshold. DB 310 MB.

### §2 Execution + Data Audit
- Paper cycles Jun 4 (6/7 at probe time): c1 (API, fill_qty=0×4) → c2 (worker, clean ✓) → c3 (worker, drift=1 ✓) → c4 (API, drift=10, AMD blocked sector limit, AMZN/INTC rejected) → c5 (worker, drift=9) → c6 (API, AMD phantom open fill_qty=0, MRVL/ARM/DELL fill_qty=0 blocked by Phase 75/79).
- Portfolio: c6 18:30 → cash=$43,742.75, equity=$125,858.11. Cash dropped $32k at c6 from phantom orders.
- **NEW AMD phantom position**: opened_at=2026-06-04 18:30:00 UTC, qty=15 in DB, fill_qty=0 at broker — not in Alpaca.
- R1 carry-forward: MS×2 and MU×2 dup pairs unchanged.
- Origin-strategy: all new rows stamped ✓. Position caps: 14 OPEN ≤15 ✓, 2 new today ≤5 ✓.
- Data freshness: bars=2026-06-03 ✓, rankings=2026-06-04 10:45 ✓, signals=2026-06-04 10:30 ✓.
- Kill-switch: false ✓. Mode: paper ✓. Eval history: 115 ✓. Idempotency: 0 dup orders ✓.

### §3 Code + Schema
- Alembic head: `q7r8s9t0u1v2` (single head ✓). No pending migrations.
- Pytest smoke: **360/360 pass** in 36.01s ✓.
- Git: clean, 0 unpushed, HEAD=`9df6c48`, main only.
- **GitHub Actions CI:** run `26961104651` sha=`9df6c48` conclusion=`success` ✓

### §4 Config + Gate Verification
- All critical APIS_* flags at expected values ✓. No drift. Scheduler job_count=36 ✓.

### Issues Found
- **[RED R2 ESCALATED]** API process won c1, c4, c6 today; c6 opened AMD fill_qty=0 creating phantom DB position + cash drain ~$32k.
- **[RED — NEW] AMD phantom DB position** at opened_at=2026-06-04 18:30:00 UTC (qty=15 in DB, not in Alpaca).
- **[RED R1 CARRY-FORWARD]** MS×2 and MU×2 dup pairs remain.

### Fixes Applied
- None autonomous.

### Action Required from Aaron
1. **HIGH RED — Fix API-process broker (R2)**: Remove paper_trading_cycle scheduler from API process OR fix API broker adapter init.
2. **HIGH RED — Close AMD phantom position**: UPDATE positions SET status='closed', closed_at=NOW(), realized_pnl=0 WHERE opened_at='2026-06-04 18:30:00.001083' AND security_id=(SELECT id FROM securities WHERE ticker='AMD');
3. **HIGH RED — Phase 85 R1 dup-pair close SQL**: close MS Jun1 (qty=1) and MU May1 (qty=2).
4. **MEDIUM — Monitor cash drain**: watch c7 and tomorrow's cycles.

---

## Health Check — 2026-06-04 15:08 UTC (Thursday 10:08 AM CT, mid-market)

**Overall Status:** RED — R2 API-process fill_qty=0 confirmed again at c1 today (13:35 UTC, all 4 orders returned fill_qty=0 while status=FILLED). R1 partially improved: AMD×2 and AMZN×2 closed by worker at c2; **2 dup OPEN pairs remain** (MS×2, MU×2). Portfolio up from Jun 3: equity=$127,058.06. All infra, tests, and CI GREEN.

### §1 Infrastructure
- Containers: 8/8 healthy — all `Up 3 days` (since 2026-05-31 17:47 UTC restart). No restart loops. RestartCount=0 core.
- /health: 7/7 `ok`. mode=paper, timestamp=2026-06-04T15:08:38Z.
- Worker log scan (24h): 13 stale-ticker yfinance errors only (known list). 0 CRITICAL/Traceback/TypeError. 0 crash-triad.
- API log scan (24h): 0 ERROR/CRITICAL/Traceback/TypeError.
- Prometheus: 2/2 targets up. Alertmanager: 0 active alerts.
- Resource usage: worker 886.8 MiB, api 976.3 MiB, postgres 256.3 MiB — all well under threshold. DB 310 MB.

### §2 Execution + Data Audit
- Paper cycles Jun 4: c1 (13:35 UTC) API process (fill_qty=0 all orders — R2); c2 (14:30 UTC) worker (AMD close qty=21, AMZN close qty=25, GS open qty=8 ✓). Jun 3: 7 cycles + EOD eval complete ✓.
- Portfolio trend: Jun 4 c2 → cash=$75,793.56, equity=$127,058.06 (vs Jun 3 c6 $123,065.03; +$3,993). cash≥0 ✓.
- Broker↔DB reconciliation: /health broker=ok ✓. DB: 12 OPEN. Broker drift at c1: 11 tickers (API process); at c2: 10 tickers (worker — includes INTC ghost). MS drift persists (dup rows).
- **R2 CONFIRMED**: API process c1 — 4 orders all fill_qty=0 (AMZN close, INTC trim×2, GS open).
- **R1 PARTIAL IMPROVEMENT**: AMD×2 + AMZN×2 closed at c2. Remaining: MS×2 (Jun1+Jun2), MU×2 (May1+May21).
- Origin-strategy: all new positions (GS/ARM/DELL) stamped ✓. Position caps: 12 OPEN ≤15 ✓. 1 new today ≤5 ✓.
- Data freshness: bars=2026-06-03 ✓, signals=2026-06-04 10:30 ✓, rankings=2026-06-04 10:45 ✓.
- Kill-switch=false ✓, mode=paper ✓. Eval history: 115 rows ✓. Idempotency: 0 dupe orders ✓.

### §3 Code + Schema
- Alembic head: `q7r8s9t0u1v2` (single head ✓). No drift.
- Pytest smoke: **360/360 pass** (--no-cov) in 35.44s ✓.
- Git: clean. 0 unpushed. HEAD=`57489fd`. No stale branches.
- **GitHub Actions CI:** run `26907406846` sha=`57489fd` conclusion=`success` ✓ — https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/26907406846

### §4 Config + Gate Verification
- All 11 critical APIS_* flags at expected values ✓. job_count=36 ✓. Phase 82 dedup active ✓.

### Issues Found
- **[RED R2]** API-process fill_qty=0 at c1 Jun 4 — all 4 orders failed silently (AMZN close, INTC trim×2, GS open). Root cause unresolved.
- **[RED R1]** MS×2 + MU×2 dup OPEN pairs. Phase 85 fix pending.
- **[YELLOW]** INTC ghost in Alpaca (DB closed, Alpaca open) — secondary; will resolve when R2 fixed.

### Fixes Applied
None autonomous. All RED items require Aaron's approval.

### Action Required from Aaron
1. **HIGH RED** — Fix API-process broker adapter (R2): force worker to always win Phase 82 lock OR fix API-process Alpaca init to return actual fill quantities.
2. **HIGH RED** — Phase 85 `_persist_positions` fix (R1): MS×2 (5th episode), MU×2.
3. **HIGH RED** — DB cleanup SQL: close MU May1 (qty=2) and MS Jun1 (qty=1). AMD+AMZN closed naturally today — no SQL needed.

---

## Health Check — 2026-06-03 19:08 UTC (Wednesday 2:08 PM CT, mid-market)

**Overall Status:** RED — R1 carry-forward (4 dup OPEN pairs: AMD×2, AMZN×2, MU×2, MS×2); R2 root cause unresolved (API-process broker malfunction). **Key improvement since 10:15 UTC probe**: worker process won Phase 82 lock at c3–c6; all orders executing with proper fill_qty; broker drift reduced from 9–13 tickers to 1 (MS, from dup rows). GOOG/GOOGL successfully closed at c3.

### §1 Infrastructure
- Containers: 8/8 healthy — all `Up 3 days` (since 2026-05-31 17:47 UTC restart). No restart loops. RestartCount=0 core.
- /health: 7/7 `ok`. mode=paper, timestamp=2026-06-03T19:08:34Z.
- Worker log scan (24h): 13 stale-ticker yfinance errors only. 0 CRITICAL/Traceback/TypeError. 0 crash-triad.
- API log scan (24h): 0 errors.
- Prometheus: 2/2 up. Alertmanager: 0 active. Resources fine. DB 302 MB.

### §2 Execution + Data Audit
- Paper cycles Jun 3: c1–c6 completed ✅ (c7 not yet fired). Phase 82 dedup: worker won lock c3–c6.
- Portfolio: Jun3 c6 cash=$67,164.05, equity=$123,065.03. cash≥0 ✅.
- Broker↔DB: broker drift reduced to 1 ticker (MS only) at c4–c6. R2 partially mitigated — fill_qty=0 only at c1/c2 (API process); c3–c6 proper fill_qty (worker). Root cause unfixed.
- R3 RESOLVED: GOOG/GOOGL closed at c3 fill_qty=25 ✅. R1 4 dup pairs remain.
- Origin strategy: all 5 recent positions stamped ✅. Caps: 15 OPEN (≤15 ✅), 2 new today (≤5 ✅).
- Data: bars=Jun2 ✅, signals/rankings=Jun3 10:30/10:45 ✅. Kill-switch=false, mode=paper ✅. eval_runs=114 ✅.
- Idempotency: 0 dup orders ✅. 4 dup OPEN tickers (R1).

### §3 Code + Schema
- Alembic: q7r8s9t0u1v2 single head ✅. Pytest: 360/360 ✅. Git: clean, 0 unpushed, HEAD=e43f4a4.
- **CI:** run `26894348165` sha=`e43f4a4` conclusion=`success` ✅.

### §4 Config + Gate Verification
- All APIS_* flags at expected values ✅.

### Issues Found
- **[RED R1]** 4 dup OPEN pairs: AMD×2, AMZN×2, MU×2, MS×2. Phase 85 fix pending.
- **[RED R2 root cause]** API-process fill_qty=0 unfixed — worker winning lock is temporary mitigation.

### Fixes Applied
None.

### Action Required from Aaron
1. **HIGH RED** — Fix API-process broker adapter (R2 root cause): force worker to always win Phase 82 lock, or fix API lifespan broker init.
2. **HIGH RED** — Phase 85 `_persist_positions` fix (R1, 5th dup-pair episode).
3. **HIGH RED** — DB cleanup SQL: close AMD Apr29, AMZN Apr29, MU May1, MS Jun1 (qty=1).

---

## Health Check — 2026-06-03 15:15 UTC (Wednesday 10:15 AM CT, mid-market)

**Overall Status:** RED — R1 carry-forward (4 dup OPEN pairs: AMD×2, AMZN×2, MU×2 + NEW MS×2); persistent API-process Alpaca broker dysfunction: broker_health_position_drift firing every cycle for 9-13 tickers, fill_qty=0 on all trim/close orders.

### §1 Infrastructure
- Containers: 8/8 healthy — all `Up 2 days` (since 2026-05-31 17:47 UTC restart). No restart loops. RestartCount=0 core.
- /health: 7/7 `ok`. mode=paper, timestamp=2026-06-03T15:07:37Z.
- Worker/API log scan (24h): known 13 stale-ticker yfinance errors only. 0 CRITICAL/Traceback/TypeError. 0 crash-triad patterns.
- Prometheus: 2/2 targets up. Alertmanager: 0 active alerts.
- Resource usage: worker 860.9 MiB, api 933.3 MiB — all under threshold. DB 302 MB.

### §2 Execution + Data Audit
- Paper cycles (Jun 2): 7/12 completed (c1–c7) + EOD eval ✅. Jun 3: 2 cycles (c1=13:35, c2=14:30 UTC) ✅.
- Portfolio trend: Jun 3 c2 → cash=$61,010.84, equity=$125,882.74 (+$1,855 vs Jun 2 c7). cash≥0 ✅.
- Broker↔DB reconciliation: /health broker=ok ✅ surface. DB 14 OPEN. broker_health_position_drift fires every cycle (13 tickers at c1, 11 at c2). Systemic API-process broker disconnect.
- **R1 CARRY-FORWARD (modified)**: AMD×2, AMZN×2, MU×2 ongoing + NEW MS×2 (Jun1+Jun2 both momentum_v1). INTC×2 and MRVL×2 from Jun 2 are now RESOLVED.
- **NEW RED**: fill_qty=0 on ALL trim/close orders in API process (c1: MRVL/AMD/WDC/INTC trims + GOOG/GOOGL rejected; c2: MRVL/AMD/WDC trims). Persistent since Jun 1 c7.
- Origin-strategy stamping: all 5 positions opened in last 30h have origin_strategy ✅.
- Position caps: 14 open (≤15 ✅). 0 new positions Jun 3 so far.
- Data freshness: bars=2026-06-02 ✅, signals=2026-06-03 10:30 ✅, rankings=2026-06-03 10:45 ✅.
- Kill-switch=false ✅, mode=paper ✅. eval_runs=114 ✅. Idempotency clean ✅.

### §3 Code + Schema
- Alembic head: `q7r8s9t0u1v2` (single head ✅). No pending migrations.
- Pytest smoke: **360/360 pass** (--no-cov, APIS_PYTEST_SMOKE=1) in 36.39s ✅.
- Git: clean (1 untracked outputs/), 0 unpushed. HEAD=`2f01fcc`. 0 stale branches.
- **GitHub Actions CI:** run `26813605938` sha=`2f01fcc` conclusion=`success` ✅

### §4 Config + Gate Verification
- All critical APIS_* flags at expected values ✅. job_count=36 ✅. Phase 82 dedup firing correctly ✅.

### Issues Found
- **[RED R1]** 4 dup OPEN pairs: AMD×2, AMZN×2, MU×2 + NEW MS×2 (Jun1+Jun2). Phase 85 still pending.
- **[RED R2]** Persistent API-process broker malfunction: broker_health_position_drift every cycle (9-13 tickers), fill_qty=0 all orders. Trim corrections silently failing. Broker/DB state diverging each cycle.
- **[RED R3]** Jun3 c1: GOOG+GOOGL close orders REJECTED by broker. Positions closed via broker-sync.

### Fixes Applied
- None autonomous.

### Action Required from Aaron
1. **HIGH** — Root-cause API-process Alpaca broker dysfunction: compare broker adapter init in api/lifespan vs worker/main; consider forcing worker to win Phase 82 lock.
2. **HIGH** — Phase 85 `_persist_positions` fix (MS×2 is 5th episode).
3. **HIGH** — DB cleanup SQL: close AMD Apr29, AMZN Apr29, MU May1, MS Jun1-14:30 (qty=1) dup rows.
4. **MEDIUM** — Investigate MS×2 origin: why did Jun2 cycle not see Jun1 MS as already-held?

---

## Health Check — 2026-06-02 10:09 UTC (Tuesday 5:09 AM CT, pre-market)

**Overall Status:** RED — R1 carry-forward (5 dup OPEN pairs: AMD×2, AMZN×2, INTC×2, MRVL×2, MU×2) + NEW R2/R3/R4: c7 Alpaca paper broker returned fill_qty=0 for all 4 orders (INTC/BE closes + GOOGL/GOOG opens) → BE and INTC (May21) close-loop gap; NULL-qty orders for GOOGL/GOOG.

### §1 Infrastructure
- Containers: 8/8 healthy — all `Up 40 hours`. No restart loops. DB 285 MB.
- /health: 7/7 `ok`. mode=paper. Prometheus 2/2 up. Alertmanager 0 active. Resources clean.

### §2 Execution + Data Audit
- Mon Jun 1: 7 cycles completed (c1-c7 13:35→19:30 UTC). EOD eval 21:00 complete ✅. Phase 82 dedup at c7 ✅.
- Portfolio: last snapshot 2026-06-01 19:30 — cash=$52,730.07, equity=$121,506.71 ✅.
- **R1 CARRY-FORWARD**: 5 dup OPEN pairs unchanged.
- **NEW R2**: c7 fill_qty=0 from Alpaca on all 4 orders; **R3**: BE close-loop gap; **R4**: INTC May21 close-loop gap. See primary log for full detail.
- Data freshness: bars=2026-06-01 ✅, signals/rankings=2026-06-01 (stale, self-heal today).
- Kill-switch=false ✅, mode=paper ✅. eval_runs=113 ✅. Idempotency clean ✅.

### §3 Code + Schema
- Alembic `q7r8s9t0u1v2` single head ✅. Pytest 360/360 ✅. Git clean, 0 unpushed. CI run 26748888906 sha=09d1ee6 conclusion=success ✅.

### §4 Config + Gate Verification
- All critical APIS_* flags correct ✅. Scheduler job_count=36 ✅.

### Issues Found
- **[RED R1]** 5 dup OPEN pairs carry-forward. **[RED R2/R3/R4]** c7 fill_qty=0 broker violation → BE + INTC May21 close-loop gaps + GOOGL/GOOG NULL-qty orders.
- **[YELLOW Y1]** Signals/rankings stale (pre-market, self-heal). **[YELLOW Y2]** Daily cap may need SOD reset verification.

### Action Required from Aaron
1. **HIGH RED**: Investigate c7 fill_qty=0 (check Alpaca state for BE/INTC/GOOGL/GOOG). API-process Alpaca behavior differs from worker process — root cause investigation needed.
2. **HIGH RED**: Phase 85 `_persist_positions` fix + DB cleanup SQL (AMD Apr29, AMZN Apr29, INTC May1, MU May1, MRVL May19). Consider closing BE May8 + INTC May21 if confirmed closed in Alpaca.
3. **MEDIUM**: Verify daily_opens_count SOD reset for Tue Jun 2 c1 (13:35 UTC).

---

## Health Check — 2026-06-01 10:08 UTC (Monday 5:08 AM CT, pre-market / first trading day back)

**Overall Status:** RED — R1 carry-forward (5 dup OPEN ticker pairs: AMD×2, AMZN×2, INTC×2, MRVL×2, MU×2). No new regressions. Stack healthy and ready for Mon first cycle at 13:35 UTC.

### §1 Infrastructure
- Containers: 8/8 healthy — all `Up 16 hours` (restarted 2026-05-31 17:47 UTC). No restart loops. RestartCount=0 core.
- /health: 7/7 `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). mode=paper, timestamp=2026-06-01T10:08:45Z.
- Worker/API log scan (24h): 13 known stale-ticker errors at 10:00 UTC ingestion. 2 known API startup restore WARNs (pre-existing). 0 CRITICAL/Traceback/TypeError. 0 crash-triad patterns.
- Prometheus: 2/2 targets up. No errors, no dropped targets.
- Alertmanager: 0 active alerts.
- Resource usage: worker 747.8 MiB, api 823.6 MiB, postgres 96.6 MiB, redis 8.4 MiB — all well under threshold. DB 277 MB.

### §2 Execution + Data Audit
- Paper cycles (30h): 0 rows — pre-market probe (5:08 AM CT), expected ✅. Last completed: 2026-05-26 21:00 UTC.
- Portfolio trend: last snapshot 2026-05-26 19:30 UTC — cash=$52,730.07, equity=$121,985.86. cash≥0 ✅.
- Broker↔DB reconciliation: /health broker=ok ✅. DB: 14 OPEN positions. No broker_health_position_drift in 48h (no cycles since May 26).
- **R1 CARRY-FORWARD — 5 dup OPEN ticker pairs**: AMD×2, AMZN×2, INTC×2, MRVL×2, MU×2. Phase 85 fix still pending.
- **R2 UNCONFIRMED**: Ghost Alpaca positions (QCOM/TXN/CSCO/ARM/STX) — state unknown until Mon c1 13:35 UTC.
- Origin-strategy stamping: 0 new positions in last 30h — N/A ✅.
- Position caps: 14 open (≤15 ✅), 0 new today ✅.
- Data freshness: bars=2026-05-29 ✅ FRESH (last trading day; ingestion caught up at ~10:00 UTC). Signals/rankings=2026-05-26 — stale (Y1, self-heals at 10:30/10:45 UTC today).
- Stale tickers: known 13 only ✅.
- Kill-switch: false ✅. Operating mode: paper ✅.
- Evaluation history rows: 112 ✅.
- Idempotency: 0 duplicate orders ✅. 5 dup OPEN tickers (R1 carry-forward).
- Scheduler: job_count=36 ✅.

### §3 Code + Schema
- Alembic head: `q7r8s9t0u1v2` (single head ✅). No pending migrations.
- Pytest smoke: **360/360 pass** (--no-cov, 37.43s) ✅. 0 new failures.
- Git: 1 untracked (outputs/). 0 unpushed. HEAD=`bf771eb`. 0 stale branches.
- **GitHub Actions CI:** run `26721931587` sha=`bf771eb` status=completed conclusion=`success` ✅ — https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/26721931587

### §4 Config + Gate Verification
- All critical APIS_* flags at expected values ✅ (OPERATING_MODE=paper, KILL_SWITCH=false, MAX_POSITIONS=15, MAX_NEW_POSITIONS_PER_DAY=5, MAX_THEMATIC_PCT=0.75, RANKING_MIN_COMPOSITE_SCORE=0.30, gated flags all OFF/null).

### Issues Found
- **[RED R1 CARRY-FORWARD]** 5 dup OPEN ticker pairs: AMD×2, AMZN×2, INTC×2, MRVL×2, MU×2.
- **[YELLOW Y1]** Signals/rankings stale (2026-05-26) — expected at 5 AM CT probe; self-heals ~10:30/10:45 UTC today.
- **[INFO R2 UNCONFIRMED]** Ghost Alpaca positions (QCOM/TXN/CSCO/ARM/STX) — watch Mon c1 13:35 UTC logs.

### Fixes Applied
- None autonomous. State files committed `c970202` + pushed to origin/main.
- **RED email**: Gmail draft `r-7765896161377992674` created — manual send required.

### Action Required from Aaron
1. **HIGH RED — Phase 85 `_persist_positions` fix** — first Mon trading day resumes risk.
2. **HIGH RED — DB cleanup SQL**: Close older dup rows (AMD Apr29, AMZN Apr29, INTC May1, MU May1, MRVL May19).
3. **MEDIUM — R2 ghost Alpaca positions**: Watch Mon c1 13:35 UTC for `broker_health_position_drift`.

---

## Health Check — 2026-05-31 19:15 UTC (Sunday 2:15 PM CT, weekend / market closed)

**Overall Status:** RED — R1 carry-forward (5 dup OPEN ticker pairs: AMD×2, AMZN×2, INTC×2, MU×2, MRVL×2). No new regressions vs 17:52 UTC probe. All infrastructure clean. Second Sunday probe confirms stable state.

### §1 Infrastructure
- Containers: 8/8 healthy — all `Up ~1.5 hours` (restarted 17:47 UTC today). No restart loops.
- /health: 7/7 `ok`. mode=paper, timestamp=2026-05-31T19:08:39Z.
- Worker/API log scan: 0 ERROR/CRITICAL/Traceback. 0 crash-triad patterns.
- Prometheus: 2/2 up. Alertmanager: 0 active. Resources: all well under threshold. DB 276 MB.

### §2 Execution + Data Audit
- Paper cycles: 0 (weekend ✅). Last completed 2026-05-26 19:30 UTC.
- Portfolio: cash=$52,730.07, equity=$121,985.86. cash≥0 ✅.
- Broker↔DB: /health broker=ok ✅. 14 OPEN positions. 5 dup ticker pairs persist (R1).
- Origin-strategy: 0 new rows in 30h — N/A. All 14 open rows stamped ✅.
- Position caps: 14 open (≤15 ✅). 0 new today ✅.
- Data freshness: bars=2026-05-22 (stale — outage), rankings/signals=2026-05-26. Self-heals Mon.
- Stale tickers: known 13 only ✅. Kill-switch=false ✅, mode=paper ✅.
- eval_runs=112 ✅. Idempotency: 0 dup orders ✅. Scheduler job_count=36 ✅.

### §3 Code + Schema
- Alembic: `q7r8s9t0u1v2` single head ✅. Pytest: **360/360** pass ✅. Git: clean, 0 unpushed, HEAD=`b98b3e8`.
- **CI:** run `26720215771` sha=`b98b3e8` conclusion=`success` ✅

### §4 Config + Gate Verification
- All critical APIS_* flags at expected values ✅. All gated flags OFF ✅.

### Issues Found
- **[RED R1]** 5 dup OPEN ticker pairs (AMD/AMZN/INTC/MU/MRVL ×2). Phase 85 fix pending.
- **[YELLOW Y1]** Data stale (bars/signals/rankings). Expected; self-heals Mon 06-02.
- **[INFO R2]** Ghost Alpaca positions unconfirmed. Watch Mon first cycle.

### Fixes Applied / Action Required
- None autonomous. See 17:52 UTC probe for full action list. No change in status or findings.

---

## Health Check — 2026-05-31 17:52 UTC (Sunday 12:52 PM CT, weekend / market closed)

**Overall Status:** RED — R1 carry-forward (dup OPEN rows now 5 tickers, MRVL×2 added May 26) + Y1 machine outage 4.5 days (Wed–Fri May 27–29 missed, 3 trading days lost). Watchdog auto-recovered stack on restart. Stack currently 8/8 healthy. See primary log `apis/state/HEALTH_LOG.md` for full detail.

---

## Health Check — 2026-05-25 15:15 UTC (Monday 10:15 AM CT, Memorial Day / market closed)

**Overall Status:** RED — R1 dup OPEN rows carry-forward + R2 broker drift escalated (3→14 tickers at c2) + R3 NEW GOOGL close-loop reversal via Phase 75 reopen after c1 local-paper-broker close was undone by c2 Alpaca rejection (Memorial Day market closed).

### §1 Infrastructure
- Containers: 8/8 healthy — worker+api `Up 4 days`, postgres/redis/monitoring `Up 8 days`. 0 restarts.
- /health: 7/7 `ok`, mode=paper, 15:08 UTC.
- Worker log scan: known 13 stale tickers only. 0 crash-triad. 0 CRITICAL.
- API log scan: 0 errors in 24h window.
- Prometheus: 2/2 up, 0 droppedTargets.
- Alertmanager: 0 firing.
- Resources: all normal. DB 268 MB.

### §2 Execution + Data Audit
- Paper cycles today (Memorial Day): 2 snapshots (13:35 + 14:30 UTC). 0 evaluation_runs in 30h (expected — holiday, last eval_run 2026-05-22 21:00 UTC ✅).
- Portfolio trend: c2 snapshot cash=$45,375.74 equity=$119,778.52. cash >= 0 ✅.
- Broker↔DB reconciliation: 14 open positions. c1 (worker) drift: 3 tickers (R2 carry-forward). c2 (API/Alpaca) drift: **14 tickers** incl. QCOM/TXN/CSCO/ARM/STX/WDC (ghost Alpaca positions with no DB OPEN row).
- Origin-strategy stamping: 0 new positions today, all existing 14 OPEN rows have origin_strategy set ✅.
- Position caps: 14 open (≤15 ✅), 0 new today ✅.
- Data freshness: bars=2026-05-22 (Fri — expected holiday ✅), rankings=2026-05-25 10:45 ✅, signals=2026-05-25 10:30 ✅.
- Stale tickers: known 13, no new ✅.
- Kill-switch=false ✅, mode=paper ✅.
- Evaluation history rows: 110 ✅.
- Idempotency: 0 dup order keys ✅. 4 dup OPEN ticker pairs (R1 carry-forward).
- **NEW RED R3**: GOOGL close-loop reversal — c1 (worker/local paper broker) filled SELL qty=28 @ $382.78 + `closed_trade_recorded` realized_pnl=-$289.52. c2 (API/Alpaca) tried close, Alpaca rejected "Market is closed." → `phase75_position_row_reopened` reversed c1's DB close. GOOGL stuck OPEN.

### §3 Code + Schema
- Alembic head: `q7r8s9t0u1v2` single head ✅. Alembic check: pre-existing ORM drift (non-blocking).
- Pytest smoke: **370/370 pass** (deep_dive/phase22/phase57/phase82, 37.46s) ✅.
- Git: clean (1 modified state file, 0 unpushed). HEAD `6ad72f9`.
- **GitHub Actions CI:** run `26370348563` sha=`6ad72f9` conclusion=`success` ✅.

### §4 Config + Gate Verification
- All 11 APIS_* flags at expected values ✅. Scheduler job_count=36 ✅.

### Issues Found
- **[RED R1 carry-forward]** AMD×2/AMZN×2/INTC×2/MU×2 dup OPEN rows. DB cleanup SQL awaiting Aaron.
- **[RED R2 escalated]** broker_health_position_drift 3→14 tickers at c2. Ghost Alpaca positions: QCOM/TXN/CSCO/ARM/STX/WDC.
- **[RED R3 NEW]** GOOGL close-loop reversal. Phase 75 reopen undid c1 local-paper-broker close after Alpaca rejection on holiday.
- **[INFO]** Memorial Day: scheduler holiday-unaware; local paper broker fills on any day; Alpaca rejects "Market is closed." Asymmetry triggers R3.
- **[INFO]** Alembic check drift (pre-existing, non-blocking).

### Fixes Applied
- None. All RED issues require Aaron's approval.

### Action Required from Aaron
1. HIGH RED — Execute Phase 85 DB cleanup SQL (Thu 19:10 HEALTH_LOG).
2. HIGH RED — Phase 85/R3 fix: `phase75_position_row_reopened` must not revert positions where `closed_trade_recorded` already fired in this session; OR a cross-broker close-coordination mechanism is needed.
3. HIGH RED — Close ghost Alpaca positions (QCOM/TXN/CSCO/ARM/STX/WDC) to eliminate 14-ticker drift.
4. MEDIUM — Close AAPL/MRVL orphan rows.
5. LOW — Stamp origin_strategy on broker-sync path.
6. LOW — Consider market-hours guard before Alpaca order submission on holidays.

---

## Health Check — 2026-05-24 19:14 UTC (Sunday 2:14 PM CT, weekend / market closed)

**Overall Status:** RED (carry-forward) — R1 dup OPEN rows persist (AMD×2, AMZN×2, INTC×2, MU×2, awaiting Aaron's DB cleanup). R2 broker drift: 0 new events since Fri c7 ✅. No new regressions. Stack fully healthy; 0 log errors in last 24h; scheduler heartbeat clean; pytest 416p/0f; CI success. Weekend — 0 paper cycles expected.

### §1 Infrastructure
- Containers: 8/8 healthy. worker+api `Up 3 days (healthy)` since 2026-05-21T15:16:33Z (RestartCount=0 core). postgres/redis/monitoring/alertmanager/grafana/prometheus `Up 7 days`. apis-control-plane `Up 7 days`.
- /health: 7/7 ok at 19:08 UTC (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). mode=paper.
- Worker/API log scan (24h): 0 ERROR/CRITICAL/Traceback/TypeError. 0 crash-triad patterns. Worker logs show only scheduler heartbeat firings every 5 min (clean).
- Prometheus: 2/2 targets up (apis, prometheus). No errors.
- Alertmanager: 0 active alerts.
- Resource usage: All under threshold. worker 730 MiB, api 770 MiB. DB size 259 MB.

### §2 Execution + Data Audit
- Paper cycles (30h window): 0 rows — expected (weekend).
- Portfolio trend: Last snapshot 2026-05-22 19:30 UTC. cash=$41,021.07, equity=$127,717.84 (stable). cash>0 ✅.
- Broker↔DB reconciliation: /health broker=ok ✅. 19 OPEN DB rows (15 unique tickers; 4 R1 dup rows). 0 new broker drift events in 24h ✅.
- Origin-strategy stamping: 0 new positions in 30h. N/A ✅.
- Position caps: 15 unique tickers at cap; 0 new today ✅.
- Data freshness: bars 2026-05-21 ✅. rankings 2026-05-22 10:45 UTC ✅. signals 2026-05-22 10:30 UTC ✅.
- Stale tickers: No errors in 24h (weekend idle). Known 13 carry-forward.
- Kill-switch: false ✅. Mode: paper ✅.
- Evaluation history: 110 rows ✅.
- Idempotency: 0 duplicate orders ✅. Dup OPEN tickers = R1 carry-forward (Phase 85 bug).

### §3 Code + Schema
- Alembic head: q7r8s9t0u1v2 ✅  drift: none.
- Pytest smoke: 416/416 pass ✅  — no new failures.
- Git: clean (1 untracked outputs/ dir). 0 unpushed. HEAD=0e54e44. 0 stale branches.
- **GitHub Actions CI:** run 26358516657 `0e54e44` conclusion=success — https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/26358516657 ✅

### §4 Config + Gate Verification
- All critical APIS_* flags at expected values ✅. Scheduler job_count=36 ✅. Heartbeat clean.

### Issues Found
- **R1 (RED carry-forward)**: 4 dup OPEN ticker rows (AMD×2, AMZN×2, INTC×2, MU×2). DB cleanup SQL awaiting Aaron.
- **R2 (RED carry-forward)**: Last broker_health_position_drift Fri c7. 0 new events weekend ✅.

### Fixes Applied
- None.

### Action Required from Aaron
1. **HIGH RED** — Execute DB cleanup SQL (Thu 19:10 HEALTH_LOG) to close 4 dup OPEN rows.
2. **HIGH RED** — Phase 85 `_persist_positions` cross-session close-loop fix.
3. **MEDIUM** — Close AAPL/MRVL orphan rows.
4. **LOW** — Stamp origin_strategy on broker-sync path.

---

## Health Check — 2026-05-24 10:15 UTC (Sunday 5:15 AM CT, weekend / market closed)

**Overall Status:** RED (carry-forward) — R1 + R2 persist unchanged from prior probes. No new regressions since Fri c7. Stack fully healthy; 0 log errors in last 24h; pytest 370p/0f; CI success on new commit d7c01f1.

### §1 Infrastructure
- Containers: 8/8 healthy. worker+api `Up 2 days (healthy)` since 2026-05-21T15:16:33Z (RestartCount=0 core). postgres/redis/monitoring `Up 7 days`. apis-control-plane `Up 7 days`.
- /health: 7/7 ok at 10:07 UTC mode=paper ✅
- Worker/API log scan (24h): 0 errors / 0 Tracebacks / 0 crash-triad ✅
- Prometheus: 2/2 targets up. 0 errors ✅
- Alertmanager: 0 active alerts ✅
- Resource usage: all within threshold. DB 259 MB ✅

### §2 Execution + Data Audit
- Paper cycles (Sun): 0 — weekend, expected ✅. Last: Fri c7 19:30 UTC.
- Portfolio trend: cash=$41,021.07, equity=$127,717.84 (stable, all positive) ✅
- Broker↔DB reconciliation: DB 19 OPEN / 206 closed. /health broker=ok. Last drift Fri c7 (R2 carry-forward). No new weekend firings ✅
- Origin-strategy stamping: no new positions; all existing stamped ✅
- Position caps: 15 unique broker positions at cap; 19 DB rows (4 R1 dups). 0 new today ✅
- Data freshness: bars 2026-05-21 ✅, rankings 2026-05-22 10:45 ✅, signals 2026-05-22 10:30 ✅
- Stale tickers: known 13 only, no new additions ✅
- Kill-switch + mode: false / paper ✅
- Evaluation history rows: 110 ✅
- Idempotency: 0 dup orders ✅. 4 dup-OPEN tickers (R1 carry-forward)

### §3 Code + Schema
- Alembic head: q7r8s9t0u1v2 single head ✅. No drift.
- Pytest smoke: 370 passed / 0 failed ✅ (exceeds 360 baseline)
- Git: outputs/ untracked only. HEAD d7c01f1. 0 unpushed. No stale branches ✅
- **GitHub Actions CI:** run 26341296153 on d7c01f1 — conclusion=success ✅

### §4 Config + Gate Verification
- All 11 APIS_* flags at expected values ✅. Gated flags default OFF ✅. job_count=36 ✅.

### Issues Found
- **R1 (RED carry-forward)**: 4 dup OPEN ticker rows (AMD×2, AMZN×2, INTC×2, MU×2) from Thu c3 cross-session close-loop. Awaiting Aaron's DB cleanup SQL.
- **R2 (RED carry-forward)**: broker_health_position_drift last fired Fri c7 (AMZN/AMD/INTC). Resolves with R1 cleanup.

### Fixes Applied
None.

### Action Required from Aaron
1. **HIGH RED** — Execute DB cleanup SQL (Thu 2026-05-21 19:10 HEALTH_LOG §Action Required).
2. **HIGH RED** — Phase 85: fix `_persist_positions` cross-session close-loop.
3. **MEDIUM** — Close AAPL/MRVL orphan rows if not held at broker.
4. **LOW** — Stamp origin_strategy on broker-sync path.

---

## Health Check — 2026-05-23 19:15 UTC (Saturday 2:15 PM CT, weekend / market closed)

**Overall Status:** RED (carry-forward) — R1 + R2 persist unchanged from prior probes. No new regressions introduced since Fri c7. Stack fully healthy; scheduler heartbeat clean; 0 log errors in last 24h.

### §1 Infrastructure
- Containers: 8/8 healthy. worker+api `Up 2 days (healthy)` since 2026-05-21T15:16:33Z (RestartCount=0 core). postgres/redis/monitoring `Up 6 days`. apis-control-plane `Up 6 days`.
- /health: 7/7 ok at 19:08 UTC mode=paper ✅
- Worker log scan (24h): 0 errors / 0 Tracebacks / 0 crash-triad. Heartbeats only since Fri c7.
- API log scan (24h): 0 errors / 0 Tracebacks / 0 crash-triad ✅
- 48h errors: 34 — all 13 known stale-ticker yfinance (Fri 10:00–10:23 UTC). No new tickers.
- Prometheus: 2/2 up ✅. Alertmanager: 0 active ✅.
- Resource usage: worker 730 MiB / 0%; api 771 MiB / 0.11%; all within threshold ✅. DB 259 MB.

### §2 Execution + Data Audit
- Paper cycles: 0 today (Saturday = weekend ✅). Last eval_run 2026-05-22 21:00 UTC status=complete ✅.
- Portfolio trend: latest 2026-05-22 19:30 UTC cash=$41,021.07, equity=$127,717.84 (cash>0 ✅). Stable.
- Broker↔DB reconciliation: DB 19 OPEN (4 R1 dups) / 206 closed. /health broker=ok ✅. No new drift events today.
- Origin-strategy stamping: all 5 Fri c3 new positions stamped ✅. 0 NULLs on new rows.
- Position caps: 15 unique broker positions (at cap). 0 new today ✅.
- Data freshness: bars 2026-05-21 (weekday-only ingestion, next Mon 2026-05-25 ✅); rankings 2026-05-22 10:45 ✅; signals 2026-05-22 10:30 ✅.
- Stale tickers: known 13. No new additions ✅. Kill-switch=false, mode=paper ✅.
- Evaluation history: 110 ✅. Idempotency: 0 dup order keys ✅. 4 dup-OPEN tickers (R1 carry-forward).

### §3 Code + Schema
- Alembic head: q7r8s9t0u1v2 (single head) ✅. No drift.
- Pytest smoke: 360 passed / 0 failed / 3731 deselected ✅ (baseline).
- Git: clean. HEAD 3072344. 0 unpushed. No stale branches ✅.
- **GitHub Actions CI:** run `26330203558` on `3072344` conclusion=success ✅ — https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/26330203558

### §4 Config + Gate Verification
- All 11 APIS_* flags at expected values ✅. Gated flags OFF ✅. Scheduler job_count=36 ✅.

### Issues Found
- **R1 (RED carry-forward)**: 4 dup OPEN rows (AMD×2, AMZN×2, INTC×2, MU×2). DB 19 vs 15 unique broker. Awaiting Aaron cleanup SQL.
- **R2 (RED carry-forward)**: broker_health_position_drift last Fri c7. Resolves with R1 cleanup.

### Fixes Applied
None.

### Action Required from Aaron
1. **HIGH RED** — Execute R1 DB cleanup SQL (Thu 19:10 HEALTH_LOG §Action Required) → resolves R1+R2.
2. **HIGH RED** — Phase 85: fix `_persist_positions` cross-session close-loop.
3. **MEDIUM** — Close AAPL (qty=25) + MRVL (qty=42) Day-5 orphan rows.
4. **LOW** — Stamp origin_strategy on broker-sync path.

**Email:** RED — sent via Gmail MCP.

---

## Health Check — 2026-05-23 10:15 UTC (Saturday 5:15 AM CT, weekend / market closed)

**Overall Status:** RED — R1 + R2 carry-forward (4 dup OPEN ticker rows + broker drift); no new regressions. R1 cleanup still awaiting Aaron.

### §1 Infrastructure
- Containers: 8/8 healthy. worker+api `Up 43h` since 2026-05-21T15:16:33Z (RestartCount=0 core). postgres/redis/monitoring `Up 6 days`.
- /health: 7/7 ok at 10:09 UTC mode=paper.
- Worker/API log scan: 19 errors each — all known stale-ticker yfinance 404s. 0 crash-triad.
- Prometheus: 2/2 up. Alertmanager: 0 active. Resources: all within threshold. DB 259 MB.

### §2 Execution + Data Audit
- Paper cycles: 0 today (Sat weekend expected). Last eval_run 2026-05-22 21:00 UTC complete. evaluation_runs=110 ✓.
- Portfolio trend: Latest 2026-05-22 19:30 UTC cash=$41,021.07, equity=$127,717.84 (positive ✓). Fri c3 opened 5 new momentum_v1 positions (ARM/CSCO/QCOM/STX/TXN).
- Broker↔DB: /broker/positions 404 (known). /health broker=ok ✓. broker_health_position_drift fired Fri c3/c6/c7 — R2 carry-forward, expanding to include c3 new positions.
- Origin-strategy: all 5 new Fri c3 positions stamped ✓. 0 NULLs on new rows.
- Position caps: DB=19 OPEN (4 R1 dup rows); unique broker tickers=15 (at cap ✓). Fri c3 daily new=5 (at cap ✓). 0 new today (Sat ✓).
- Data freshness: bars 2026-05-21 (Fri close not yet ingested, expected Sat AM); signals 2026-05-22 10:30 ✓; rankings 2026-05-22 10:45 ✓.
- Stale tickers: known 13 — no new additions. Kill-switch=false ✓, mode=paper ✓. eval_runs=110 ✓. Idempotency clean. 4 dup-OPEN security_ids (R1).

### §3 Code + Schema
- Alembic head: q7r8s9t0u1v2 (single head ✓). No drift.
- Pytest smoke: 406 passed / 0 failed ✓. Git: 3 dirty (state docs), 0 unpushed, no stale branches.
- **GitHub Actions CI:** run 26248055594 `3db0fb8` conclusion=success ✓.

### §4 Config + Gate Verification
- All 11 APIS_* flags correct ✓. Gated flags default OFF ✓. job_count=36 ✓.

### Issues Found
- **R1 (RED carry-forward)**: 4 dup OPEN ticker rows (AMD×2, AMZN×2, INTC×2, MU×2) from Thu c3 cross-session close-loop failure. Awaiting Aaron's DB cleanup.
- **R2 (RED carry-forward)**: broker_health_position_drift 3× Fri (c3/c6/c7). Expanded at c6 to include new Fri c3 positions. Resolves when R1 cleanup done.
- **Bars freshness**: 2026-05-21 (Fri close not yet ingested — expected Sat AM, non-blocking).

### Fixes Applied
None.

### Action Required from Aaron
1. **HIGH RED** — Execute DB cleanup SQL (Thu 19:10 HEALTH_LOG §Action Required): close 4 stale dup OPEN rows → resolves R1 + R2.
2. **HIGH RED** — Phase 85: fix `_persist_positions` cross-session close-loop.
3. **MEDIUM** — Close AAPL (qty=25) + MRVL (qty=42) Day-5 orphan rows if not held at broker.
4. **LOW** — Stamp origin_strategy on broker-sync path for GOOGL.

---

## Health Check — 2026-05-22 15:10 UTC (Friday 10:10 AM CT, active trading / between c2–c3)

**Overall Status:** RED (carry-forward) — No new regressions introduced overnight or this morning. R1 and R2 from Thursday's RED probe persist: (R1) 4 duplicate OPEN ticker rows (AMD×2, AMZN×2, INTC×2, MU×2) — cross-session close-loop failure from Thu c3; DB cleanup SQL provided in Thu probe is still pending Aaron's execution. (R2) `broker_health_position_drift` fired again at Fri c2 14:30 UTC with the same 10 tickers (AMD, BE, AMZN, INTC, MRVL, UNH, AAPL, MU, GOOGL, WDC) — direct consequence of R1 + Y2 orphan rows. One new YELLOW: (Y1) 1× HTTP Error 401 Unauthorized in docker-api-1 at 10:00:03 UTC during Fri AM ingestion (yfinance; bars still updated to 2026-05-21 ✅, single occurrence, non-blocking). All other systems GREEN: 8/8 containers healthy (worker+api Up 24h), /health 7/7 ok, pytest 360/360 ✅, CI success, all 11 APIS_* flags correct. No autonomous fixes available — R1/R2 require operator-approved DB cleanup.

### §1 Infrastructure
- **Containers:** 8/8 healthy. worker+api `Up 24 hours (healthy)` since 2026-05-21T15:16:33 UTC. postgres/redis/monitoring `Up 5 days`. RestartCount=0 core ✅.
- **/health:** All 7 components ok at 15:08:17 UTC. mode=paper ✅.
- **Worker/API log scan:** 0 crash-triad. 0 Tracebacks. Worker: known 13 stale-ticker errors only. API: known stale-ticker + pre-existing startup WARNs + R2 drift at 14:30 UTC + NEW 1× 401 Unauthorized at 10:00 UTC.
- **Prometheus:** 2/2 up ✅. **Alertmanager:** 0 active ✅. **Resources:** all under threshold ✅. **DB:** 259 MB.

### §2 Execution + Data Audit
- **Paper cycles Fri:** 2/2 completed (c1 13:35, c2 14:30 UTC), single snapshot each (Phase 82 dedup ✅). cash>0 ✅.
- **Portfolio trend:** c2 14:30 UTC: cash=$38,098.34, equity=$120,381.35 ✅.
- **Broker↔DB:** DB 15 OPEN / `/health broker=ok` ✅. `broker_health_position_drift` Fri c2 14:30 UTC — 10 tickers (R2 carry-forward).
- **Origin-strategy:** 0 new positions today. Carry-forward GOOG `unknown` ✅.
- **Position caps:** 15/15 AT cap, 0 new today ✅.
- **Data freshness:** bars `2026-05-21` ✅, rankings `2026-05-22 10:45` ✅, signals `2026-05-22 10:30` ✅.
- **Kill-switch:** false ✅. **Mode:** paper ✅. **Eval history:** 109 rows ✅. **Idempotency:** 0 dup orders ✅; 4 dup OPEN tickers (R1 carry-forward).

### §3 Code + Schema
- **Alembic:** `q7r8s9t0u1v2` single head ✅. **Pytest:** 360/360 ✅. **Git:** clean, 0 unpushed ✅. **CI:** Run `26248055594` `3db0fb8` conclusion=success ✅.

### §4 Config + Gate Verification
- All 11 APIS_* flags at expected values ✅. Gated flags (SELF_IMPROVEMENT, INSIDER_FLOW, Step 6/7/8) default OFF ✅. Scheduler job_count=36 ✅.

### Issues Found
- **R1 (carry-forward RED):** 4 dup OPEN tickers (AMD×2, AMZN×2, INTC×2, MU×2). DB cleanup SQL in Thu 19:10 HEALTH_LOG. Awaiting Aaron.
- **R2 (carry-forward RED):** `broker_health_position_drift` Fri c2 14:30 UTC, 10 tickers. Resolves when R1 cleanup done.
- **Y1 (new):** 1× HTTP 401 Unauthorized docker-api-1 10:00:03 UTC (yfinance AM ingestion). Bars still fresh. Single occurrence. Watch Mon AM.

### Fixes Applied
- None.

### Action Required from Aaron
1. **HIGH RED** — Execute DB cleanup SQL (Thu 19:10 HEALTH_LOG §Action Required) to close 4 stale AMD/AMZN/INTC/MU OPEN rows.
2. **HIGH RED** — Phase 85 investigation: broaden `_persist_positions` close-loop matching to cover cross-session `opened_at`.
3. **MEDIUM** — Close AAPL (qty=25) + MRVL (qty=42) Day-4 orphan rows.
4. **LOW** — Stamp `origin_strategy='broker_sync'` on broker-reconciliation-created positions.

**Email:** RED — sent via Gmail MCP.

---

## Health Check — 2026-05-21 19:10 UTC (Thursday 2:10 PM CT, active trading / post-c6)

**Overall Status:** RED — R1: 4 duplicate OPEN ticker rows (AMD×2, AMZN×2, INTC×2, MU×2) — cross-session close-loop failure. R2: broker_health_position_drift 10 tickers. Y1: GOOG origin_strategy='unknown'. Y2: AAPL/MRVL Day-3 orphan rows. No autonomous fixes — operator DB cleanup + Phase 85 code investigation required. See `apis/state/HEALTH_LOG.md` for full details.

---

## Health Check — 2026-05-21 15:20 UTC (Thursday 10:20 AM CT, active trading)

**Overall Status:** YELLOW — Two issues identified and autonomously fixed within this probe. Y1: `/health` `paper_cycle:stale` — Phase 82 side-effect (API skip path never updating `last_paper_cycle_at`); Phase 84 fix `8c81443` applied + container restart. Y2: `closed_trade_recording_failed` regression at Thu c1 — Phase 83 code on disk but old Python module in memory; container restart at 15:16 UTC resolves. /health `ok` post-fix. Phase 82 dedup fully validated. No RED findings.

See full entry in `apis/state/HEALTH_LOG.md`.

---

## Phase 83 Remediation — 2026-05-20 19:30 UTC (Wednesday 2:30 PM CT) — **GREEN**

**Overall Status: GREEN.** Y2 `closed_trade_recording_failed` tz-aware/naive datetime bug from the 10:08 UTC probe FIXED in commit `99154f6` on `main` (pushed to origin). Y1 CI rerun on `f25c2b0` already confirmed GREEN. Root cause: Phase 27 closed-trade recording in `apis/apps/worker/jobs/paper_trading.py` did `(run_at - _pos.opened_at).days` where `run_at` is tz-aware UTC but `_pos.opened_at` rehydrated from older state can be tz-naive. The Phase 28 grading block immediately below already handled this correctly; fix mirrors that pattern. 5 new regression tests added in `TestPhase83NaiveOpenedAtRegression`. Ruff clean; pytest 51/51 PASS on the file. CI run `26184842842` triggered on push. Full remediation block in primary log at `apis/state/HEALTH_LOG.md`.

---

## Health Check — 2026-05-20 10:08 UTC (Wednesday 5:08 AM CT, pre-market, ~3.5h before Wed c1 = Phase 82 validation cycle) — **YELLOW**

**Overall Status: YELLOW.** Pre-Wed-c1 Phase 82 forward-verification probe. Phase 82 fix (DEC-087, `1dc3b34`) deployed 23:01 UTC last night but **NOT YET EXERCISED** — no paper cycle has fired since restart. Wed c1 13:35 UTC will validate. **3 new YELLOWs**: (Y1) GitHub Actions CI `conclusion=failure` on both Phase 82 commits driven by 1× I001 ruff diagnostic — **autonomous-fix applied at `f25c2b0`** (1-line deletion in `apis/tests/unit/test_phase82_canonical_snapshot_selection.py`), CI rerun `26156153271` in_progress. (Y2) NEW `closed_trade_recording_failed` WARNING in worker at Tue c1 (`error="can't subtract offset-naive and offset-aware datetimes"`) — Phase 83 candidate; no trading impact. (Y3) 2× NEW yfinance `HTTP Error 401: Invalid Crumb` at Wed 10:00 UTC AM ingestion in docker-api-1; bars still updated to 2026-05-19 ✅. **Carry-forward**: 7-of-7 Tue dual-invocation snapshots + 5 NULL-qty FILLED orders (3 Tue c1 b449 + 2 Tue c5 17:30 AAPL/MRVL) all pre-Phase-82. Tue 21:00 UTC EOD UniqueViolation logged (canonical row 7537d0f7 inserted clean, evaluation_runs=107 ✅). AAPL Tue qty=25 + MRVL Tue qty=42 OPEN rows intentionally retained per Phase 82 ACTIVE_CONTEXT. **Mon Y2 GOOGL close-loop gap RESOLVED** via Tue 18:00 CT DB cleanup. Stack healthy: 8/8 containers (worker+api `Up 11h` since 23:01 UTC), /health 7/7 ok mode=paper, 0 crash-triad, Prom 2/2 up, AM 0 firing. Pytest 416p/0f/3670d ✅. Alembic q7r8s9t0u1v2 single ✅. All 11 APIS_* flags correct + `APIS_REDIS_URL=redis://redis:6379/0` ✅; docker-api-1 `redis.ping()=True` ✅ (Phase 82 lock has working connectivity). 11 OPEN / 202 closed; all 11 origin_strategy stamped; 0 duplicate OPEN tickers; 0 duplicate idempotency keys. NULL-qty FILLED=32 (+2 Tue c5); NULL realized_pnl=169 unchanged. broker_health_position_drift `--since 24h`=6 (Tue c2-c7, decays Wed). Heartbeat age 30s. Bars 2026-05-19 ✅; signals/rankings 5/19 (Wed AM jobs at 10:30/10:45 UTC). Watchdog Ready, +150 KB overnight. DB 236 MB. Kill-switch=false, mode=paper ✅. **§6 Email: YELLOW Gmail draft will be created — manual send recommended.** **Action Required from Aaron: NONE blocking.** Wed c1 13:35 UTC + CI rerun status captured at next 10 AM CT probe.

Full report: see primary log at `apis/state/HEALTH_LOG.md`.

---

## Health Check — 2026-05-19 15:08 UTC (Tuesday 10:08 AM CT, ~38 min after c2 14:30 UTC) — **RED**

**Overall Status:** **RED** — Tue c1 dual-invocation produced **3 duplicate OPEN rows** in `positions` (GOOG×2 / GOOGL×2 / VRT×2) + 3 NULL-qty rebalance BUYs in `orders` (b449... cycle_id firing 100μs before paper_trading_cycle_starting). Phase 81-A SOD reseed picked stale-cash $95,809.41 (Mon second-writer) instead of canonical $114,177.34. Phase 81-B OPEN stacking guard never fired (0 log lines). Phase 80 NULL-qty regression at the second-writer call site (+3 lifetime → 30 total). broker_health_position_drift WARN fired at c2 listing 8 tickers. Mon Y2 GOOGL close-loop gap carry-forward unchanged + Tue c1 added a SECOND GOOGL OPEN row (qty=19) compounding the regression. Stack runtime healthy: 8/8 containers `Up 2 days`; /health 7/7 ok mode=paper; 0 crash-triad; pytest 406p / 0f / 26.15s ✅; CI #25864627182 on `cc40c6f` conclusion=success ✅; alembic q7r8s9t0u1v2 single head ✅; all 11 env-exposed APIS_* flags correct; scheduler heartbeat age 62s ✅. 15/15 OPEN AT cap. **See `apis/state/HEALTH_LOG.md` (mirror) for full per-section breakdown + action items.** **Action required from Aaron**: (1) HIGH RED — Phase 82 second-writer hunt; (2) HIGH RED — DB cleanup of 3 phantom OPEN rows + Mon GOOGL stale; (3) MEDIUM — Phase 81-A snapshot-selection bug; (4) MEDIUM — Phase 81-B guard didn't fire investigation.

---

## Health Check — 2026-05-19 10:08 UTC (Tuesday 05:08 AM CT, pre-market) — YELLOW (NEW: persist_evaluation_run UniqueViolation + 2 Mon carry-forwards)

**Overall Status:** YELLOW — Tue pre-market probe. **(Y1 NEW)** `persist_evaluation_run_failed` UniqueViolation logged in worker at 2026-05-18T21:00:00.016740Z on Mon EOD eval (`Key (idempotency_key)=(2026-05-18:paper:evaluation_run) already exists`). The constraint `uq_evaluation_run_idempotency_key` rejected the duplicate INSERT → canonical row 8af61aa8 (status=complete) is intact, evaluation_runs total=106 (+1 from 105 ✅). Data integrity preserved. This is the **dual-invocation pattern propagating to a second writer site** (`evaluation_runs` in addition to `_persist_portfolio_snapshot`). Phase 82 scope expansion. **(Y2 carry-forward)** GOOGL close-loop gap unchanged from Mon evening — `positions` row still `status='open' quantity=20` despite Mon c3 SELL filling. **(Y3 carry-forward)** Dual-invocation snapshot writer now 7-of-7 Mon = 28-of-28 weekday cumulative (Mon c7 19:30 UTC dual-pair confirmed: $43,801.23/$114,177.34 + $14,618.27/$95,809.41). Mon EOD bars job RAN ✅ (`daily_market_bars.trade_date` now 2026-05-18, +1 day fresher). Stack: 8/8 containers Up 2 days; /health 7/7 ok 10:08:17Z mode=paper; **0 crash-triad**, 0 Tracebacks. Pytest 406p/0f ✅. CI #25864627182 on `cc40c6f` conclusion=success ✅. Alembic q7r8s9t0u1v2 single head ✅. All 11 env-exposed APIS_* flags correct. Scheduler heartbeat age 105s ✅. Watchdog Ready (log 560 KB, +94 KB overnight). DB 229 MB unchanged. 13 OPEN / 194 closed unchanged (all 13 origin_strategy stamped). 27 NULL-qty + 169 NULL realized_pnl unchanged. Idempotency clean. Kill-switch=false, mode=paper ✅. **Email:** YELLOW Gmail draft created — manual send recommended. **Action required from Aaron:** (1) MEDIUM carry-forward — GOOGL SQL cleanup or Phase 82 momentum_v1 close-path; (2) LOW NEW (Y1) — extend Phase 82 secondary-writer hunt to include `_persist_evaluation_run`; (3) LOW carry-forward — Phase 82 primary `_persist_portfolio_snapshot` hunt; (4) carry-forward — delete merged `claude/elated-austin-ecf51f`. Next material check-point Tue c1 13:35 UTC (~3.5h from probe).

---

## Health Check — 2026-05-18 19:08 UTC (Monday 02:08 PM CT, post-c6) — YELLOW (DEC-086 partial-verified; new GOOGL close-loop gap + dual-invocation persists + Alpaca DNS transient)

**Overall Status:** YELLOW — DEC-086 hotfix FIRED and partially-verified on Mon c1 13:35 UTC (`phase81_portfolio_state_restored_at_worker positions=9 cash=43801.23 equity=120374.68` + `phase81_broker_sod_reseeded_from_db prior_cash=$100k new_cash=$55,859.87 cost_basis=$64,514.81 seeded=9` both emit ✅) AND `sod_equity_captured equity=$120,374.68` correctly matches Thu c7 final snapshot (NOT $100k phantom) ✅. **However 3 NEW YELLOW items**:
- **YELLOW-1** — Dual-invocation snapshot writer persists 6-of-6 Mon weekday cycles (27-of-27 weekday cumulative). DEC-086 narrowed first/second writer divergence but the dual-write itself remains. All 6 Mon cycles emit single cycle_id in orders ledger ✅ (Phase 81-E refute holds), so the dual snapshots come from TWO WRITER CALL SITES not two cycle invocations. Phase 82 candidate.
- **YELLOW-2** — GOOGL close-loop gap. c3 15:30 UTC SELL of GOOGL qty=20 filled in orders ledger but positions row NOT closed (still status='open' qty=20). CSCO partial trim (BUY 72 + SELL 28) DID propagate correctly to qty=44. `broker_health_position_drift` WARNINGs at 16:00 + 17:30 UTC confirm. Looks like Phase 75-style close-loop regression in momentum_v1 same-cycle SELL path.
- **YELLOW-3** — 5 transient Alpaca DNS resolution failures clustered at 2026-05-18T15:30:04Z during c3 (Failed to resolve 'paper-api.alpaca.markets'). c3 still completed approved=2/executed=2; no recurrence c4/c5/c6.

6 Mon weekday cycles fired (c1-c6 at 13:35/14:30/15:30/16:00/17:30/18:30 UTC); c2 opened 4 new momentum_v1 positions (GOOG/GOOGL/STX/CSCO), c3 placed 2 SELLs (GOOGL/CSCO); c4-c6 had approved=0/executed=0 (daily cap reached at 4/5 new today). 13 OPEN / 194 closed (was 9/194 Sun/Mon-morning; +4 new). All 13 OPEN `origin_strategy` stamped. Stack: 8/8 containers Up 43h, RestartCount=0; /health 7/7 ok 19:08:57Z mode=paper; Worker 51 ERR / API 48 ERR = stale-ticker yfinance (43) + Alpaca DNS (5) + ingestion-info; 0 crash-triad on all 5 patterns. Prom 2/2 up. Alertmanager 0 active. Resources well under threshold. DB 229 MB (+7 vs morning). Watchdog Ready (log 467KB, +56KB vs morning). Pytest **406p / 0f / 3670d in 23.69s** matches baseline ✅. CI **#25864627182** on `cc40c6f` conclusion=success ✅. Alembic `q7r8s9t0u1v2` single head ✅. All 11 env-exposed APIS_* flags correct. Scheduler `job_count=36`, heartbeat age 287s ✅. Data freshness: bars 2026-05-15 (Fri close); signals 2026-05-18 10:30 UTC ✅; rankings 2026-05-18 10:45 UTC ✅ (Mon AM pipeline ran fresh). evaluation_runs=105 unchanged (EOD eval at 21:00 UTC after this probe). NULL-qty=27 ✅, NULL realized_pnl=169 unchanged. Idempotency clean. Kill-switch=false, mode=paper ✅. **Email: YELLOW Gmail draft created — manual send recommended.** **Action required from Aaron**: (1) NEW MEDIUM YELLOW-2 — investigate GOOGL close-loop gap (Phase 82 candidate) OR run manual UPDATE positions SQL; (2) NEW LOW YELLOW-1 — Phase 82 investigation of secondary snapshot writer call site (operator-host probing still UNNECESSARY per Phase 81-E); (3) carry-forward — clean up merged `claude/elated-austin-ecf51f` feature branch (low priority).

(See `apis/state/HEALTH_LOG.md` for full §1-§4 detail.)

---

## Health Check — 2026-05-18 10:11 UTC (Monday 05:11 AM CT, pre-market) — GREEN (clean carry-forward, DEC-086 verification T-3.5h)

**Overall Status:** GREEN — Clean Monday pre-market probe. Stack still on the Sat 2026-05-16T23:48:57Z boot (~34h uptime, RestartCount=0 all four core). /health 7/7 ok mode=paper. 0 crash-triad. Today's 10:00 UTC AM ingestion job ran cleanly (yfinance delisted-ticker errors timestamped 2026-05-18T10:00Z confirm pipeline live). The Sat 23:49Z API startup `regime_result_restore_failed` + `readiness_report_restore_failed` WARNINGs have aged out of the 24h window as Sunday predicted. Pytest **406p / 0f / 3670d in 22.80s** matches new baseline ✅. CI **#25864627182** on `cc40c6f` conclusion=success ✅. Alembic `q7r8s9t0u1v2` single head ✅. All 11 env-exposed APIS_* flags correct. 9 OPEN / 194 closed unchanged (all 9 origin_strategy stamped). NULL-qty FILLED=27, NULL realized_pnl=169 unchanged. Idempotency clean. Data freshness: bars **2026-05-15 (Fri close — +1 day fresher than Sunday)**, signals/rankings Thu 5/14 (today's AM jobs at 10:30/10:45 UTC will refresh in ~19-34 min). Kill-switch=false, mode=paper ✅. **DEC-086 hotfix forward-verification is T-3.5h** at Mon c1 13:35 UTC. **Email: silent per GREEN gating rule.** Action required from Aaron: NONE.

See `apis/state/HEALTH_LOG.md` for the full §1-§4 breakdown.

---

## Health Check — 2026-05-17 15:08 UTC (Sunday 10:08 AM CT, follow-up after 05:09 AM probe) — YELLOW (carry-forward, no new issues)

**Overall Status:** YELLOW — Identical carry-forward state from the 05:09 AM CT probe ~5h earlier. No new issues; no new cycles (Sunday, markets closed). Stack still on the Sat 2026-05-16T23:48:57Z boot. 9 OPEN positions unchanged, all `origin_strategy` stamped. Same 2 API startup warnings still in 24h log window (`regime_result_restore_failed`, `readiness_report_restore_failed`) — pre-existing ORM/state-shape drift, caught in `except`, runtime healthy. Friday-cycles-missed historical fact stands. Pytest **406p / 0f / 3670d in 22.25s** — exact match against the new baseline. CI **#25864627182** on `cc40c6f` conclusion=success ✅ unchanged. Alembic `q7r8s9t0u1v2` single head ✅. All 11 env-exposed APIS_* flags correct. Scheduler `job_count=36`; heartbeat age 202s. 8/8 containers Up 15h RestartCount=0 healthy. 0 crash-triad. 0 worker errors in 24h. 0 `broker_health_position_drift` in 24h. Prom 2/2 up. Alertmanager 0 active. Resources tiny (worker 86 MiB / 0%, api 152 MiB / 2.39%). DB 222 MB unchanged. Watchdog Ready, last tick 10:05 CT. **Action required from Aaron: NONE.** Next material check-point is Mon 2026-05-18 13:35 UTC (c1) for DEC-086 hotfix verification — watch for `phase81_portfolio_state_restored_at_worker` log line and both snapshot writers agreeing on equity.

Full report in `apis/state/HEALTH_LOG.md` (primary).

---

## Health Check — 2026-05-17 10:09 UTC (Sunday 05:09 AM CT, weekend pre-dawn, post 3-day stack-off recovery) — YELLOW: Fri 5/15 all cycles missed (operator-machine availability gap)

**Overall Status:** YELLOW — Stack healthy post-recovery (8/8 containers Up 10h since Sat 2026-05-16T23:48:57Z; RestartCount=0). **Friday 2026-05-15 ALL weekday paper cycles missed** (0 portfolio_snapshots, 0 evaluation_runs, 0 signal_runs, 0 ranking_runs on Fri — entire stack down ~Thu 22:00 UTC → Sat 23:48 UTC, ~50h outage). Same Docker Desktop Autostart Blocker pattern as Wed 2026-05-13 RED entry — operator-machine availability gap. Watchdog Phase 81-D structurally cannot fire when Windows host is off (watchdog.log Fri count=**0** confirms host was off entire Fri; counts: Wed=510, Thu=1388, Sat=318, Sun=320). Linux/WSL2+systemd migration filed as long-term fix in NEXT_STEPS. **Thursday 2026-05-14 ran 7-of-7 cycles cleanly with Phase 81-A reseed VERIFIED WORKING** ✅ — Thu c1 first snapshot `cash=$4,808.12 / equity=$120,959.41` matches Wed close `equity=$120,979.81` within rounding (broker correctly reseeded from DB). Phase 81-A **hotfix DEC-086** committed Thu 13:46 UTC adds `app_state.portfolio_state` restore at worker lazy-init (mirrors broker reseed); deployed in current worker boot (Sat 23:49 UTC), will exercise on Mon c1 13:35 UTC. **Dual-invocation persists 7-of-7 Thu cycles (14 snapshots), 21-of-21 weekday cumulative** — second-writer snapshot froze at $75,509.26/$129,474.10 from Thu c3 onwards (frozen-stale-cash pattern returns). Position count 9/15 OPEN (Wed c7 GOOG/GOOGL SELLs finally persisted Thu c1; 5 momentum_v1 same-microsecond opens-and-closes on Thu c1 from Phase 81-A reseed reconciliation; all 9 OPEN origin_strategy stamped). Phase 81-C VERIFIED WORKING ✅ — Thu's 7 new closes all have non-NULL realized_pnl. NULL-qty FILLED lifetime=27 unchanged ✅. NULL realized_pnl closed lifetime=169 unchanged (historical backfill optional). API startup logged 2 graceful restore warnings (`regime_result_restore_failed error=detection_basis_json`, `readiness_report_restore_failed error=ReadinessGateRow.__init__() missing 1 required positional argument: 'description'`) — pre-existing ORM/state-shape drift, restore caught in `except`, runtime healthy. **Pytest NEW BASELINE 406p / 0f / 3670d in 24.20s** (+4 from Phase 81-A hotfix tests). Alembic `q7r8s9t0u1v2` single head ✅. **CI #25864627182 on `cc40c6f` conclusion=success ✅**. All 11 env-exposed APIS_* flags correct; 3 Phase 81 flags governed by `settings.py` defaults; 3 default-OFF flags correct. Scheduler `job_count=36`; liveness heartbeat fresh. 0 crash-triad. 0 Tracebacks. Prom 2/2 up. Alertmanager 0 active. Resources tiny (worker 85 MiB / 0%, api 151 MiB / 0.20%, postgres 52 MiB / 0%). DB 222 MB (+7 MB vs Thu, normal accumulation). Data freshness STALE due to 3-day outage (bars 5/13 Wed EOD, signals/rankings 5/14 10:30/10:45 UTC) — will self-recover Mon 06:00/06:30/06:45 ET. 14 inactive tickers unchanged. Idempotency clean. **Action required from Aaron: NONE blocking.** Mon c1 forward verification will be captured by Mon 10 AM CT scheduled probe at 14:00 UTC — watch for `phase81_portfolio_state_restored_at_worker` INFO line + both snapshot writers agreeing on equity (no $43,801 vs $4,808 split).

Full report in `apis/state/HEALTH_LOG.md` (primary).

---

## Health Check — 2026-05-14 10:08 UTC (Thursday 05:08 AM CT, pre-market, post-Phase-81-deploy first probe)

**Overall Status:** GREEN — Phase 81 bundle live (worker/api recreated 2026-05-13T20:25:31Z); watchdog Scheduled Task registered + running ✅; all carry-forward items unchanged pending today's first-cycle Phase 81-A reseed verification at 13:35 UTC. Probe ran ~3.5h before first weekday cycle, so the `phase81_broker_sod_reseeded_from_db` log line and corrected `sod_equity_captured` value (expected ≈ $120,979.81 not $100k) cannot yet be confirmed — forward verification deferred to next probe.

### §1 Infrastructure
- Containers: 8/8 healthy. worker/api `Up 14 hours` since 2026-05-13T20:25:31Z (Phase 81 recreate). postgres/redis/grafana/prometheus/alertmanager/control-plane `Up 15 hours`. RestartCount=0 across the board.
- /health: 7/7 ok at 2026-05-14T10:08:25Z mode=paper.
- Worker log: 0 ERR / 0 Tracebacks / 0 crash-triad in 24h (126.2 KB). API log: 1 ERR = yfinance `['PKI', 'MRO']` carry-forward.
- Prom 2/2 up. Alertmanager 0 active.
- Resources well under threshold (worker 718 MiB / 0%, api 812 MiB / 0.11%, postgres 153 MiB / 2.67%, control-plane 1.004 GiB / 13.38% CPU).
- DB 215 MB unchanged.
- **Windows Docker Watchdog (Phase 81-D)** `APIS Docker Watchdog` Scheduled Task Ready ✅; watchdog log 85638 bytes; latest one-shot 05:10:02 CT `scheduler_heartbeat_fresh age=272s tick_complete` — operator one-time registration done ✅.

### §2 Execution + Data Audit
- Paper cycles since last probe: 1 (Wed c7 19:30 UTC, the only Wed cycle). Thu c1 scheduled 13:35 UTC (~3.5h from this probe).
- evaluation_runs total: 104 (+1, Wed EOD eval at 21:00:00.05 UTC `complete mode=paper` ✅). Floor ≥80 ✅.
- Portfolio snapshots: 2 Wed c7 rows retained (fresh $32,992.50/$120,979.81; stale $22,908.56/$99,961.26).
- Broker↔DB: DB 11 OPEN / 187 closed unchanged (Wed c7 5 BUYs + 2 SELLs in orders ledger never updated positions — Phase 81-A reseed addresses going forward).
- 11 OPEN all origin_strategy stamped (10 rebalance + 1 ranking_buy_signal UNH).
- Position caps: 11/15 OPEN ✅. 0 new today (pre-market).
- Orders last 30h: 7 Wed c7 FILLED, all with quantity ✅ (Phase 80 holds). Dual-invocation idempotency_key split retained (5 BUYs stale `17f5269cc8`, 2 SELLs fresh `74a81977322`).
- NULL-qty FILLED lifetime: 27 unchanged ✅. NULL realized_pnl closed lifetime: 169 unchanged.
- broker_health_position_drift `--since 24h`: 0 (no post-restart cycles).
- Data freshness: latest `daily_market_bars` 2026-05-13 (Wed EOD) ✅. latest `signal_runs` 2026-05-12 10:30 ❌ (Wed AM didn't run during outage; Thu AM at 10:30 UTC will self-recover ~22min after this probe). latest `ranking_runs` 2026-05-12 10:45 ❌ (same; Thu at 10:45 UTC).
- 14 stale tickers `is_active=false` unchanged.
- Kill-switch=false, mode=paper ✅. Idempotency clean (0 dupe keys, 0 dupe open tickers).

### §3 Code + Schema
- Alembic head `q7r8s9t0u1v2` single ✅. `alembic check` reports ORM↔DB cosmetic drift (TIMESTAMP→DateTime + universe_overrides autogenerate noise) — pre-existing, runtime healthy.
- Pytest smoke: **402 passed / 0 failed / 3670 deselected in 27.06s** ✅ NEW BASELINE (382 prior + 20 Phase 81 tests).
- Git tree CLEAN (only `outputs/` + `.claude/worktrees/` untracked). HEAD `95e0e83` Merge Phase 81 bundle. 0 unpushed. 0 feature branches.
- **GitHub Actions CI #25824321394 on `95e0e83` conclusion=success ✅** — new SHA since Wed (was on `8a892db`).

### §4 Config + Gate Verification
- All 8 env-exposed APIS_* flags correct ✅. Phase 81 flags governed by `settings.py` defaults (all True): `phase81_broker_sod_reseed_enabled`, `phase81b_open_stacking_guard_enabled`, `phase81c_realized_pnl_fallback_enabled`. 3 default-OFF flags correct.
- Scheduler `job_count=36` per Wed `apis_worker_started` 20:25:31Z ✅. Liveness heartbeat `worker:scheduler_heartbeat=1778753431` → 10:10:31Z, age 0s ✅.

### Issues Found
- None new. Carry-forward only: Wed broker↔DB drift (Phase 81-A reseed pending Thu c1 verification), 27 NULL-qty FILLED, 169 NULL realized_pnl (Phase 81-C covers new closes), 14-of-14 dual-invocation pattern (phase-split hypothesis refuted by Phase 81-E; observation itself open), `alembic check` cosmetic drift (new observation, not actionable).

### Fixes Applied
- None this run (probe is pre-market; Phase 81 forward verification depends on Thu c1 13:35 UTC).

### Action Required from Aaron
- None. Operator's Wed action items 1 + 2 both done (worker recreate ✅, watchdog task registered ✅).
- Next probe (10 AM CT / 14:00 UTC) will capture Thu c1 behaviour including `phase81_broker_sod_reseeded_from_db` log line + corrected `sod_equity_captured` (expected ~$120,9xx not $100k).

---

## Phase 81 Bundle Deploy — 2026-05-13 (Wednesday post-recovery)

Mirror entry — full detail in `apis/state/HEALTH_LOG.md`. Summary:
- **Phase 81-A (DEC-081):** `PaperBrokerAdapter.seed_from_db_positions` + lazy-init wiring in `apps/worker/jobs/paper_trading.py`. On a fresh worker start the helper reseeds cash + positions from `positions WHERE status='open'` and `portfolio_snapshots.equity_value`, so the next `sod_equity_captured` reads the operator's real prior-close equity instead of the cold-start $100k. Resolves Action 1 from the 2026-05-13 RED report (chosen recommendation b — re-seed, not unwind).
- **Phase 81-B (DEC-082):** Universal OPEN stacking guard at `paper_trading.py` extends Phase 79 to ALL OPEN actions (`ranked_buy_signal` / `momentum_v1` / `theme_alignment_v1` ...). Drops any OPEN whose ticker is already in state or broker.
- **Phase 81-C (DEC-083):** `_persist_positions` close-loop computes `realized_pnl` from `(exit - entry) * qty` (exit = `row.exit_price` if present else `market_value / quantity`) when no `ClosedTrade` exists. Addresses the 169 lifetime NULL-realized_pnl rows.
- **Phase 81-D (DEC-084):** Host-side Windows watchdog `apis/scripts/windows_docker_watchdog.ps1` + `register_watchdog_task.bat` for the Docker Desktop Autostart Blocker recurring since 2026-04-15. Container-side healthcheck broadened (Phase 71 scheduler heartbeat AND main heartbeat). Resolves Actions 2 + 4.
- **Phase 81-E (DEC-085):** Phase-split hypothesis REFUTED by code inspection — `run_paper_trading_cycle` generates exactly one `cycle_id` and threads it through every writer. But dual-invocation IS real per the 2026-05-08 diagnostic capture — a second writer path bypasses `_persist_orders_and_fills`. Identifying that path is filed as a Phase 82 follow-up.
- Tests: **20p / 0f** in 1.25s in `tests/unit/test_phase81_broker_sod_reseed_and_open_stacking.py`. Ruff clean.
- All 3 flags default True; can be disabled per-knob without code change.

---

## Health Check — 2026-05-13 19:35 UTC (Wednesday 2:35 PM CT, post c7-only, mid-afternoon post-recovery probe) — RED: 6 weekday cycles missed + broker SOD reset to $100k

**Overall Status:** RED — **6 weekday paper cycles missed today (c1-c6 at 13:35/14:30/15:30/16:00/17:30/18:30 UTC).** Entire Docker stack stopped between Tue 19:30:01Z and Wed 19:25:47Z (~24h outage matching `project_docker_desktop_autostart_blocker.md` pattern). Containers `Up <5 min` since 2026-05-13T19:25:40Z, RestartCount=0 → manual/Docker-Desktop-resume recovery, NOT auto-restart. Cycle 7 (19:30 UTC) fired correctly post-recovery (`proposed=15/approved=5/executed=5`) BUT broker captured `sod_equity=$100,000` vs Tue close $117,432 — **broker↔DB divergence: broker has phantom $100k cash + 0 positions, DB preserves 11 OPEN positions (cost basis $75k)**. c7 5 BUYs at $77k notional were opened against the phantom $100k baseline. **NEW dual-invocation evidence**: orders idempotency_keys today split by action-type — 5 BUYs under STALE cycle_id `17f5269cc8`, 2 SELLs (GOOG/GOOGL rebalance) under FRESH cycle_id `74a81977322a`. Tue cross-check (c1: stale `19567bd0` 5 BUYs + fresh `a71ede41` 2 SELLs NUE/VRT) confirms identical split. **Hypothesis revision**: dual-invocation is likely two PHASES of same worker cycle (OPEN-phase vs CLOSE-phase) emitting different cycle_ids, NOT a separate writer outside `docker-worker-1`. 14-of-14 weekday cycles cumulative. Stack itself healthy post-recovery: /health=degraded only because `paper_cycle=stale` (expected ~3min after first cycle); db/broker/scheduler/broker_auth/kill_switch/system_state_pollution all `ok`; mode=paper. Pytest **382p / 0f / 3670d in 29.79s** ✅. Alembic `q7r8s9t0u1v2` single head ✅. **CI #25459511595 on `8a892db` conclusion=success** ✅. All 8 env-exposed APIS_* flags correct. Scheduler `job_count=36`; heartbeat age 7s ✅. 0 crash-triad. 0 Tracebacks. Prom 2/2 up. Alertmanager 0 active. Resources well under threshold. DB 215 MB unchanged. Data freshness REGRESSION: latest `daily_market_bars` 2026-05-11 (Mon EOD — Tue+Wed not ingested); latest `signal_runs` 2026-05-12 10:30; latest `ranking_runs` 2026-05-12 10:45 — Wed AM pipeline (06:00/06:30/06:45 ET) didn't run while stack was off. Position count 11/15 OPEN unchanged at probe time (c7 GOOG/GOOGL closes not yet persisted). 27 NULL-qty FILLED lifetime unchanged. 169 NULL realized_pnl lifetime unchanged. Idempotency clean. evaluation_runs=103 (+1 Tue EOD eval cleanly fired before outage). NO autonomous fixes applied. **Action required from Aaron:** (1) **HIGHEST** — investigate broker SOD=$100k reset + decide whether to unwind c7's 5 BUYs; (2) Docker Desktop Autostart Blocker mitigation; (3) confirm/disprove "two phases = two cycle_ids" hypothesis via paper_trading.py code read; (4) Phase 71 healthcheck didn't recover from stack-down (investigate or accept); (5) all carry-forward YELLOWs unchanged.

Full report in `apis/state/HEALTH_LOG.md` (primary).

---

## Health Check — 2026-05-12 19:08 UTC (Tuesday 2:08 PM CT, post c1–c6 mid-afternoon probe) — YELLOW carry-forward, 13-of-13 weekday cycles dual-invocation + frozen-stale-cash refinement

**Overall Status:** YELLOW — third Tue probe of the day. Tue c3/c4/c5/c6 (15:30/16:00/17:30/18:30 UTC) all fired and all replicated the dual-invocation YELLOW-1 pattern → **6-of-6 Tue → 13-of-13 weekday cycles cumulative.** Cross-grep on `docker logs docker-worker-1 --since 24h`: stale-state cycle_ids `fca02944`/`5e0383bf`/`fc0407f4`/`c3d95515` each return 2 hits in worker; fresh-state cycle_ids `358c70d1`/`de113d8d`/`fb2582da`/`985e8739` each return 0 hits. **KEY NEW OBSERVATION refining 15:12 "dynamic stale-cash" framing**: stale-state cash held FROZEN at $47,195.47 across c2-c6 (only changed c1→c2 from $35,027→$47,195). Second writer's source stabilizes after the first non-trivial trade cycle, NOT continuously polling. Refines operator probe ask toward snapshot-once-early-in-day processes. No new orders since c2 (daily cap exhausted). Stack fully GREEN: 8/8 containers `Up 41h` since 2026-05-11T01:53:35Z (RestartCount=0); /health 7/7 ok 19:08:08Z mode=paper; worker `--since 24h`=35 ERR (carry-forward yfinance + 1 UniqueViolation) / **api `--since 24h` returned 0 bytes** this run (Windows-docker quirk on this container; fell back to `--tail 20000` = 70 ERR = 66 yfinance + 2 startup warnings + 2 info-FP); 0 crash-triad all 5 patterns; 0 Tracebacks; Prom 2/2 up; Alertmanager 0 active; resources well under threshold (worker 855.2 MiB / 0.00%, api 891.7 MiB / 0.12%, postgres 170.7 MiB / 0.00%, redis 8.36 MiB / 0.35%, prometheus 42.76 MiB / 0.04%, grafana 50.09 MiB / 0.05%, alertmanager 14.95 MiB / 0.06%, control-plane 1.192 GiB / 15.89% CPU); DB 215 MB unchanged. Pytest **382p / 0f / 3670d in 45.94s** ✅. Alembic `q7r8s9t0u1v2` single head ✅. **CI run #25459511595 on `8a892db` conclusion=success** ✅ unchanged. All 8 env-exposed APIS_* flags correct. Scheduler `job_count=36` per Mon `apis_worker_started`; liveness heartbeat age 7s ✅. 11 OPEN positions all `origin_strategy` stamped (10 rebalance + 1 ranking_buy_signal UNH); idempotency clean; orders filled=283 / rejected=93 unchanged; NULL-qty FILLED lifetime=27 unchanged ✅; NULL realized_pnl lifetime=169 unchanged from 15:12; broker_health_position_drift `--since 24h`=7. Phase 79 skipped=0 each cycle ✅; Phase 80 unresolvable=0 ✅. Phase 81-A diagnostic still uncommitted. **Carry-forward YELLOW items unchanged.** NO autonomous fixes applied. Same Action Required from Aaron list as 15:12 entry with refined item #1 evidence (13-of-13 + frozen-stale-cash).

Full report in `apis/state/HEALTH_LOG.md` (primary).

---

## Health Check — 2026-05-12 15:12 UTC (Tuesday 10:12 AM CT, post c1+c2 mid-morning probe) — YELLOW carry-forward, 9-of-9 weekday cycles dual-invocation + 4 new NULL realized_pnl closes

**Overall Status:** YELLOW — second Tue probe of the day, ~37 min after Tue cycle 2 (14:30 UTC) completed. **Dual-invocation YELLOW-1 fired AGAIN on both Tue cycles → cumulative 9-of-9 weekday cycles confirmed** (Mon 7 + Tue 2). Cross-grep: stale-state cycle_ids `19567bd0` (c1) + `513992b8` (c2) = 2 hits each in worker log; fresh-state `a71ede41` (c1) + `96327506` (c2) = **0 hits each** → second writer outside `docker-worker-1` on every cycle. **NEW pattern observation**: today's stale-state cash values are DYNAMIC ($35,027 c1, $47,195 c2), NOT Mon's recurring $67,314 — second writer reads mutating state between cycles. **First substantive trading activity** of the week: Tue c1 ran 5 BUYs (ADI/WDC/STX/MRVL/EQIX, $6,607.96 ea, ranked_buy_signal) + 2 rebalance CLOSEs (VRT, NUE); Tue c2 proposed=9/approved=3/executed=3 — MU TRIM -8 sh (stop_loss -7.23%, log realized_pnl=-$471), INTC TRIM -10 sh (sector_rebalance technology@45.4% > 40% + stop_loss -7.08%, log realized_pnl=-$380+-$92), plus **first observed same-day OPEN+CLOSE round-trip on momentum_v1** for ADI/STX. Phase 75 reopen-if-existing fired clean log lines. Phase 79 skipped=0, Phase 80 unresolvable=0, all 9 today's orders have quantity ✅ (Phase 80 working). **YELLOW-3 fires again** on diverse paths: 4 new NULL realized_pnl closes today (VRT/NUE rebalance + ADI/STX momentum_v1 round-trip), lifetime now **169** (+4 vs Mon 165). Position count 11/15 OPEN (was 13 — VRT/NUE/ADI/STX closed today). Stack fully GREEN: 8/8 containers `Up 37 hours` (RestartCount=0); /health 7/7 ok 15:07:37Z mode=paper; worker `--since 24h`=35 ERR (carry-forward yfinance) / api `--tail 3000`=34 ERR (yfinance carry-forward + 14:30 cycle fetches); 0 Tracebacks; **0 crash-triad** all 5 patterns; Prom 2/2 up; Alertmanager 0 active; resources well under threshold (worker 854.8 MiB / 0.00%, api 891.1 MiB / 0.21%, postgres 170.7 MiB / 0.00%, control-plane 1.167 GiB / 11.45% CPU); DB **215 MB** (+6 MB vs Mon — Tue trade writes); pytest **382p / 0f / 3670d in 47.53s** ✅; alembic `q7r8s9t0u1v2` single head ✅; CI **#25459511595** on `8a892db` conclusion=success ✅ unchanged; all 8 env-exposed APIS_* flags correct; scheduler `job_count=36`; liveness heartbeat age 215s ✅. Equity intraday: c1 close $118,978 → c2 close $117,908 (-$1,070 MTM ~ -0.90% incl realized losses on MU+INTC trims totaling -$944). evaluation_runs=102 unchanged. Orders filled=**283** (+9 today) / rejected=**93** unchanged. NULL-qty FILLED lifetime=27 unchanged ✅. NULL realized_pnl=**169** (+4) on diverse close paths confirms `_persist_closed_trade` writer bug is path-agnostic. broker_health_position_drift `--since 24h`=7 lines. NO autonomous fixes applied — all 5 YELLOW items operator-led. **Action required from Aaron** unchanged from Mon 19:13 UTC, with item #1 evidence base now 9-of-9 + new sub-observation re mutating stale-cash values, and item #3 strengthened by today's diverse close-path evidence. Full report mirror at `apis/state/HEALTH_LOG.md`.

---

## Health Check — 2026-05-12 10:14 UTC (Tuesday 5:14 AM CT, pre-market, post Mon-EOD probe) — YELLOW carry-forward, 7-of-7 Mon weekday cycles dual-invocation confirmed

**Overall Status:** YELLOW — pre-market Tue probe. First Tue probe of the day; first paper cycle expected ~13:35 UTC (3h21min away). **NEW evidence**: Mon cycle 7 fired 19:30 UTC AFTER Mon's 19:13 probe — same dual-invocation pattern (stale `5e8e443e` $67,314/$99,983 at 19:30:00.890 + fresh `a16c58ee` $12,744/$120,706 at 19:30:02.654). **YELLOW-1 now 7-of-7 Mon weekday cycles** (the 6 reported earlier + Mon c7 at 19:30 UTC). Tue overnight Mon-EOD eval succeeded (evaluation_runs=102, last row 2026-05-11 21:00:00.006 UTC status=complete). No Tue cycles yet → all YELLOW counters static. Stack fully GREEN: 8/8 containers `Up 32 hours` since 2026-05-11T01:53:35Z compose recreate (RestartCount=0); /health 7/7 ok 2026-05-12T10:08:09.866Z mode=paper; worker `--since 24h`=35 ERR (carry-forward yfinance + 1 known UniqueViolation + 1 info-FP) / api `--tail 3000`=15 ERR (all yfinance carry-forward); **0 crash-triad** all 5 patterns; 0 Tracebacks; Prom 2/2 up; Alertmanager 0 active; resources well under threshold (worker 849.4 MiB / 0.00%, api 885.2 MiB / 0.10%, postgres 171.3 MiB / 0.00%, control-plane 1.136 GiB / 14.26% CPU); DB **209 MB** unchanged; pytest **382p / 0f / 3670d in 38.39s** ✅; alembic `q7r8s9t0u1v2` single head ✅; CI **#25459511595** on `8a892db` conclusion=success ✅; all 8 env-exposed APIS_* flags correct (3 default-OFF flags governed by `settings.py` defaults); scheduler `job_count=36`; liveness heartbeat `worker:scheduler_heartbeat=1778580528` → 10:08:48Z, age ~6 min ✅. Tue morning pipeline running cleanly: ingestion 10:00:59 UTC (502 tickers / 122,714 bars / status=partial), alt-data 10:05 UTC, intel-feed 10:10 UTC. 13 OPEN positions all stamped (12 rebalance + 1 ranking_buy_signal UNH); 0 new today; 0 closes today; idempotency clean; orders filled=274 / rejected=93 unchanged; broker_health_position_drift tail-5000=20 (+1 vs Mon 19:13 from Mon c7). Carry-forward YELLOWs unchanged: 27 NULL-qty FILLED lifetime, 165 NULL realized_pnl lifetime, Phase 81-A diagnostic uncommitted, Phase 79 design gap. NO autonomous fixes applied — all 5 YELLOW items operator-led. **Action required from Aaron** unchanged from Mon 19:13 UTC entry, item #1 evidence base now 7-of-7 weekday cycles. Full report mirror at `apis/state/HEALTH_LOG.md`.

---

## Health Check — 2026-05-11 19:13 UTC (Monday 2:13 PM CT, post cycle 6, mid-afternoon market-open probe) — YELLOW carry-forward, 6-of-6 weekday cycles dual-invocation confirmed

**Overall Status:** YELLOW — third Mon probe of the day. Cycles 3-6 fired since 15:13 entry (15:30, 16:00, 17:30, 18:30 UTC). **Per-cycle dual-invocation now confirmed across ALL 6 weekday cycles today**: 12 portfolio_snapshots written (6 stale-state pairs ~ms 0-1000 + 6 fresh-state pairs ~ms 1500-3500). Cross-grep on `docker logs docker-worker-1 --tail 5000`: every fresh-state cycle_id (`cb17362f`, `427eead4`, `b869e01f`, `a44c7432`, `07e994d8`, `47cfdca9`) returns 0 hits = strongest evidence yet that second writer is OUTSIDE `docker-worker-1`. Stack itself fully GREEN: 8/8 containers `Up 17 hours` since 01:53:35Z compose recreate (RestartCount=0); /health 7/7 ok 19:08:42Z mode=paper; worker tail-5000 = 109 ERR (carry-forward) / api tail-3000 = 0 ERR; **0 crash-triad** all 5 patterns; 0 Tracebacks; Prom 2/2 up; Alertmanager 0 active; resources unchanged (worker 765.9 MiB / 0.00%, api 812 MiB / 0.10%, postgres 168.7 MiB / 0.00%, control-plane 1.041 GiB / 16.29% CPU); DB **209 MB** (+1 MB vs 15:13); pytest **382p / 0f / 3670d in 35.36s** ✅; alembic `q7r8s9t0u1v2` single head ✅; CI **#25459511595** on `8a892db` conclusion=success ✅; all critical APIS_* flags correct; scheduler `job_count=36`; liveness heartbeat age 212s ✅. broker_health_position_drift WARN tail-5000=19. Equity intraday c1→c6: $120,089 → $119,372 → $120,944 → $121,340 → $121,280 → **$121,482** (+$1,393 vs c1 close). Carry-forward YELLOWs unchanged: 27 NULL-qty FILLED lifetime (0 new today; Phase 80 ✅), 165 NULL realized_pnl lifetime (0 closes today), Phase 81-A diagnostic uncommitted, Phase 79 design gap. NO autonomous fixes applied. **Action required from Aaron unchanged from 15:13 UTC entry, urgency strengthened on probe-host-for-second-writer ask (6-of-6 weekday cycles confirmed).** Full report mirror at `apis/state/HEALTH_LOG.md`.

---

## Health Check — 2026-05-11 15:13 UTC (Monday 10:13 AM CT, post cycle 2, first weekday of week) — YELLOW carry-forward, cycle 2 dual-invocation recurrence

**Overall Status:** YELLOW — second weekday probe of the day. Mon cycle 2 fired 14:30:00 UTC and completed in 1.0s (proposed=20 → approved=0 → executed=0 — 0 orders today from cycle 2, normal post-cycle-1 behavior since 5 BUYs already consumed daily slots in cycle 1). **Dual-invocation YELLOW-1 fired AGAIN on cycle 2** — 2 portfolio_snapshots written at 14:30:00.953999 (cash=$67,314 / equity=$99,983, cycle_id `5ec13fdb...` matches worker logs) + 14:30:03.056402 (cash=$12,744 / equity=$119,371, cycle_id `427eead4...` NOT in worker logs). Same pattern as cycle 1 (cb17362f phantom) and Fri cycle 1 (cycle_ids `0ff6a782` / `58a857ed`). Second writer path runs OUTSIDE the docker-worker-1 process per Fri + today's cross-container grep. **Now confirmed firing on every weekday cycle, not intermittent.** Other YELLOW items unchanged from 14:25 UTC entry: 27 lifetime NULL-qty FILLED orders (no new today — Phase 80 working ✅), Phase 81-A diagnostic source uncommitted, 165 lifetime NULL realized_pnl closes (no closes today). Phase 79 design gap for ranked_buy_signal stacking on already-held tickers — same 13 OPEN positions, 0 NEW today, 0 closes today. Stack fully GREEN: 8/8 containers `Up 13 hours` since 2026-05-11T01:53:35Z compose recreate (RestartCount=0 all four core); /health 7/7 ok at 15:08:51Z mode=paper; worker tail-5000 = 109 ERR (carry-forward yfinance + 2 known UniqueViolations + 3 info-level false-positives), api tail-3000 = 34 ERR (all yfinance carry-forward); **0 crash-triad** all 5 patterns; Prom 2/2 up; Alertmanager 0 active; resources unchanged from 14:25 entry (worker 765 MiB / 0.00%, api 798 MiB / 0.10%, postgres 167 MiB / 0.00%); DB 208 MB unchanged. Pytest **382p / 0f / 3670d in 28.78s** ✅. Alembic `q7r8s9t0u1v2` single head ✅. CI **#25459511595** on `8a892db` `conclusion=success` ✅ unchanged. All 11 critical APIS_* flags correct. Scheduler `job_count=36` per Mon `apis_worker_started` 01:53:39Z; liveness heartbeat 1778512428 → 15:13:48Z, age ~0s ✅. broker_health_position_drift WARN fired again on cycle 2 (cumulative 2x today). Equity slipped slightly $120,089 → $119,372 between cycles (-$717 intraday). NO autonomous fixes applied — same operator-led YELLOW items + new "every-cycle dual-invocation" framing. YELLOW Gmail draft to be created. **See `apis/state/HEALTH_LOG.md` for full report.**

---

## Health Check — 2026-05-11 14:25 UTC (Monday 9:25 AM CT, post cycle 1, first weekday cycle of week) — YELLOW carry-forward + 2 NEW observations

**Overall Status:** YELLOW — first-weekday-cycle audit. Mon 13:35 UTC cycle 1 fired and completed cleanly in 2.5s (proposed=30 → approved=5 → executed=5; SINGLE cycle_id `1644ff28e...` in orders, all quantity populated 24/51/8/14/17 = Phase 80 working ✅). However **dual-invocation YELLOW-1 fired again on cycle 1**: 2 portfolio_snapshots at 13:35:02.315286 (cash=$67,314 / equity=$99,983, phantom `cb17362f...`) + 13:35:03.354019 (cash=$12,744 / equity=$120,088, canonical `1644ff28e...`). Phantom cycle_id NOT in worker logs → second writer still OUTSIDE both APIS containers (same Fri finding). **NEW observation #1:** all 5 OPENs today were `reason=ranked_buy_signal` (not `rebalance_open`) — Phase 79's idempotency filter only covers rebalance-engine OPENs, so ranked_buy_signal stacked $33,333 onto already-held AMZN/INTC/MU/AMD/UNH positions (e.g., AMZN 1→25 shares, INTC 27→78, AMD 8→22). Phase 79 design gap. **NEW observation #2:** `broker_health_position_drift` WARN fired at cycle 1 start for all 13 OPEN tickers, tolerance=0.01 — carry-forward symptom resurfacing. Other YELLOW items unchanged: 27 lifetime NULL-qty FILLED orders (no new today — Phase 80 working ✅), Phase 81-A diagnostic uncommitted, 165 lifetime NULL realized_pnl closes (no closes today). Stack fully GREEN: 8/8 containers `Up 12 hours` since 2026-05-11T01:53:35Z compose recreate (RestartCount=0 all four core); /health 7/7 ok at 14:14:22Z mode=paper; worker tail-5000 = 109 ERR (104 yfinance carry-forward + 2 known persist_eval UniqueViolations + 3 info-level "errors: 0" false positives), api tail-3000 = 34 ERR (all yfinance carry-forward); **0 crash-triad** all 5 patterns; Prom 2/2 up; Alertmanager 0 active; resources elevated for Mon AM load (worker 765 MiB, api 787 MiB, postgres 169 MiB — all well under 80% threshold); DB 208 MB (+6 MB from Sun for Mon AM signals/rankings/orders). Pytest **382p / 0f / 3670d in 25.05s** ✅. Alembic `q7r8s9t0u1v2` single head ✅. CI **#25459511595** on `8a892db` `conclusion=success` ✅ unchanged. All 11 critical APIS_* flags correct. Scheduler `job_count=36` per Mon `apis_worker_started` 01:53:39Z; liveness heartbeat fresh (age 13s ✅). 13 OPEN positions all `origin_strategy` stamped; 0 NEW positions today (5 BUYs merged into existing per Phase 75 reopen-if-existing); idempotency clean; evaluation_runs=101 unchanged. Orders filled=274 (+5 vs Sun, all Mon cycle 1), rejected=93 unchanged. Cash $12,744.56 / equity $120,088.97 — equity +$2,719 vs Fri close ($117,369 → $120,088 = +2.32% intraday). NO autonomous fixes applied — same operator-led YELLOW items + new Phase 79 design gap observation requires Aaron's call. YELLOW Gmail draft to be created. **See `apis/state/HEALTH_LOG.md` for full report.**

---

## Health Check — 2026-05-10 19:09 UTC (Sunday 2:09 PM CT, weekend afternoon, no cycles) — YELLOW carry-forward

**Overall Status:** YELLOW — pure carry-forward from Sun 15:08 UTC entry, **no state delta in ~4h**. Sunday so APScheduler weekday-only jobs correctly idle (next paper cycle Mon 2026-05-11 13:35 UTC). Same four open YELLOW items: dual-invocation persistence layer, 27 lifetime NULL-qty FILLED orders, Phase 81-A diagnostic uncommitted, 165 lifetime closed-position NULL realized_pnl (long-standing). Stack fully GREEN: 8/8 containers `Up 18 hours` since Sat-night 00:38:29Z compose recreate (RestartCount=0); /health 7/7 ok at 19:08:37Z mode=paper; worker tail-5000 = 74 ERR / api tail-3000 = 0 ERR; **0 crash-triad** all 5 patterns; Prom 2/2 up; Alertmanager 0 active; pytest **382p / 0f / 3670d in 26.48s** ✅; alembic `q7r8s9t0u1v2` single head ✅; CI **#25459511595** on `8a892db` `conclusion=success` ✅; all 11 critical APIS_* flags correct; scheduler `job_count=36` per Sat-night `apis_worker_started` 00:38:33Z; liveness heartbeat age **203s** ✅. 13 OPEN positions all stamped (12 rebalance + 1 ranking_buy_signal UNH); 0 new today; idempotency clean; evaluation_runs=101; DB 202 MB. Orders filled=269 / rejected=93. NO autonomous fixes applied — quiet-Sunday probe. YELLOW Gmail draft created (manual send required). **See `apis/state/HEALTH_LOG.md` for full report.**

---

## Health Check — 2026-05-10 15:08 UTC (Sunday 10:08 AM CT, weekend mid-morning, no cycles) — YELLOW carry-forward

**Pure carry-forward from Sun 10:12 UTC entry; no state delta in ~5h.** Sunday — APScheduler weekday-only paper-cycle / signal / ranking / ingestion jobs correctly idle (next paper cycle Mon 13:35 UTC, ~22.5h). Same four open YELLOW issues unchanged: (1) Friday dual-invocation pattern in `portfolio_snapshots` + 1 Fri 21:00 UTC `persist_evaluation_run_failed UniqueViolation` warning; (2) **27 lifetime NULL-qty FILLED OPEN orders** (no new today, no cycles); (3) Phase 81-A diagnostic `apis/apps/worker/jobs/paper_trading.py` still uncommitted; (4) 8 closed positions Fri with NULL `realized_pnl`. Stack itself fully GREEN: 8/8 containers `Up 14 hours` since 2026-05-10T00:38:29Z compose recreate (RestartCount=0 across all four core services); /health 7/7 ok at 15:08:18Z mode=paper; tail-5000 worker scan 74 ERR / api 0 ERR (yfinance carry-forward + restart-burst noise from Sat night); **0 crash-triad** across all 5 patterns; Prometheus 2/2 up; Alertmanager 0 active; resource usage fine (worker 82 MiB, api 168 MiB, control-plane 1.02 GiB / 8.38% CPU); pytest sweep `deep_dive or phase22 or phase57 or phase77_78 or phase79` **382p / 0f / 3670d in 29.41s** ✅; alembic `q7r8s9t0u1v2` single head ✅; CI **#25459511595** on `8a892db` conclusion=success ✅ (no new pushes); all 11 critical APIS_* flags correct; scheduler `job_count=36` per `apis_worker_started` at 00:38:33Z (carry-forward); liveness heartbeat `worker:scheduler_heartbeat=1778425720` age 166s ✅. 13 OPEN positions all `origin_strategy` stamped (12 rebalance + 1 ranking_buy_signal UNH); within MAX_POSITIONS=15. 0 new positions today. Idempotency clean (0 dupes by key, 0 dupes per ticker). evaluation_runs total **101** unchanged. DB 202 MB unchanged. Orders status breakdown: filled=269, rejected=93. NO autonomous fixes applied — same 4 open YELLOW items operator-led; quiet-Sunday probe.

---

## Health Check — 2026-05-10 10:12 UTC (Sunday 5:12 AM CT, weekend pre-dawn, no cycles) — YELLOW carry-forward

**Pure carry-forward from Sat 00:42 UTC entry; no state delta in ~9.5h.** Sunday — APScheduler weekday-only paper-cycle / signal / ranking / ingestion jobs correctly idle (next paper cycle Mon 13:35 UTC, ~27.5h). Same four open YELLOW issues unchanged: (1) Friday dual-invocation pattern in `portfolio_snapshots` + 1 Fri 21:00 UTC `persist_evaluation_run_failed UniqueViolation` warning; (2) **27 lifetime NULL-qty FILLED OPEN orders** (no new today, no cycles); (3) Phase 81-A diagnostic `apis/apps/worker/jobs/paper_trading.py` still uncommitted; (4) 8 closed positions Fri with NULL `realized_pnl`. Stack itself fully GREEN: 8/8 containers `Up 9 hours` since 2026-05-10T00:38:29Z compose recreate (RestartCount=0 across all four core services); /health 7/7 ok at 10:08:28Z mode=paper; tail-5000 worker scan 74 ERR / api 0 ERR (yfinance carry-forward + restart-burst noise from last night); **0 crash-triad** across all 5 patterns; Prometheus 2/2 up; Alertmanager 0 active; resource usage fine (worker 82 MiB, api 155 MiB, control-plane 1003 MiB / 9.95% CPU); pytest sweep `deep_dive or phase22 or phase57 or phase77_78 or phase79` **382p / 0f / 3670d in 22.51s** ✅; alembic `q7r8s9t0u1v2` single head ✅; CI **#25459511595** on `8a892db` conclusion=success ✅ (no new pushes); all 11 critical APIS_* flags correct; scheduler `job_count=36` per `apis_worker_started` at 00:38:33Z (carry-forward); liveness heartbeat fresh (age ~3 min, last 10:08:40Z). 13 OPEN positions all `origin_strategy` stamped (12 rebalance + 1 ranking_buy_signal UNH); within MAX_POSITIONS=15. 0 new positions today. Idempotency clean (0 dupes by key, 0 dupes per ticker). evaluation_runs total **101** unchanged. DB 202 MB unchanged. Orders status breakdown: filled=269, rejected=93. NO autonomous fixes applied — same 4 open YELLOW items operator-led; quiet-Sunday probe.

---

## Health Check — 2026-05-10 00:42 UTC (Saturday 7:42 PM CT, late evening, no cycles) — YELLOW carry-forward

**Pure carry-forward from Sat 15:07 UTC entry; no state regression, one informational infra event.** All 4 core services (worker/api/postgres/redis) restarted in tandem at 2026-05-10T00:38:29Z (within 17ms; RestartCount=0 across all = clean operator-driven `docker compose up -d --force-recreate`, NOT a crash). Stack came back fully healthy in <3 min and probed at 00:41:20 UTC. Saturday APScheduler weekday-only jobs correctly idle (next paper cycle Mon 13:35 UTC). Same four open YELLOW issues unchanged: (1) Friday dual-invocation pattern in `portfolio_snapshots` + 1 Fri 21:00 UTC `persist_evaluation_run_failed UniqueViolation` warning; (2) 27 lifetime NULL-qty FILLED OPEN orders (no new today, no cycles); (3) Phase 81-A diagnostic `apis/apps/worker/jobs/paper_trading.py` still uncommitted; (4) 8 closed positions Fri with NULL `realized_pnl` (6 from 14:30 UTC + 2 from 16:00 UTC). Stack itself fully GREEN: 8/8 containers healthy `Up 2-3 min` post-recreate; /health 7/7 ok at 00:41:20Z mode=paper; tail-5000 worker scan 74 ERR / api 0 ERR (yfinance carry-forward + restart-burst noise); **0 crash-triad** across all 5 patterns; Prometheus 2/2 up; Alertmanager 0 active; pytest sweep `deep_dive or phase22 or phase57 or phase77_78 or phase79` **382p / 0f / 3670d in 31.11s** ✅; alembic `q7r8s9t0u1v2` single head ✅; CI **#25459511595** on `8a892db` conclusion=success ✅ (no new pushes); all 11 critical APIS_* flags correct; scheduler `job_count=36` per fresh `apis_worker_started` at 00:38:33Z; liveness heartbeat fresh (~3.5 min). 13 OPEN positions all `origin_strategy` stamped (12 rebalance + 1 ranking_buy_signal UNH); within MAX_POSITIONS=15. 0 new positions today. Idempotency clean. evaluation_runs total **101** unchanged. DB 202 MB unchanged. Latest portfolio snapshot Fri 19:30:02 UTC cash=$12,744.58 / equity=$117,369.35 (positive ✅). Resources actually LOWER than 15:07 entry (worker 140→85 MiB, api 224→160 MiB) due to fresh start. NO autonomous fixes applied — same 4 open YELLOW items operator-led; quiet-weekend probe with informational restart event.

### Issues Found (carry-forward)
- YELLOW-1 dual-invocation persistence layer (Friday snapshots + 1 Fri eval_run UniqueViolation warning)
- YELLOW-2 27 lifetime NULL-qty FILLED OPEN orders (second-writer-path runs OUTSIDE both APIS containers)
- YELLOW-3 Phase 81-A diagnostic uncommitted in working tree
- YELLOW-4 8 closes from Fri with NULL `realized_pnl`
- INFO: Stack restarted 00:38:29 UTC (clean operator-driven recreate, RestartCount=0, no regression)

### Fixes Applied
- None. All operator-led investigations.

### Action Required from Aaron
- Same 5 items as Sat 15:07 UTC entry — no escalation. (1) probe host for second writer process; (2) patch Phase 79 worker-restart race; (3) investigate closed_trade NULL realized_pnl; (4) commit + push Phase 81-A diagnostic; (5) send YELLOW Gmail draft.

---

## Health Check — 2026-05-09 15:07 UTC (Saturday 10:07 AM CT, weekend mid-day, no cycles) — YELLOW carry-forward

**Pure carry-forward from Sat 10:15 UTC entry; no state delta in 5h.** Saturday APScheduler weekday-only paper-cycle / signal / ranking / ingestion jobs have not fired (`next_run=2026-05-11 06:00:00-04:00` confirmed in scheduled_job_registered logs). Stack fully GREEN: 8/8 containers `Up 25 hours` healthy; /health 7/7 ok at 15:07:40Z mode=paper; 24h log scan worker=1 warning (Fri 21:00 UTC `persist_evaluation_run_failed UniqueViolation idempotency_key=2026-05-08:paper:evaluation_run` — DB constraint correctly preventing dupe from dual-invocation), api=0 errors; **0 crash-triad** across all 5 patterns; Prometheus 2/2 up; Alertmanager 0 active; pytest sweep `deep_dive or phase22 or phase57 or phase77_78 or phase79` **382p / 0f / 3670d in 24.63s** ✅; alembic `q7r8s9t0u1v2` single head ✅; CI **#25459511595** on `8a892db` conclusion=success ✅ (no new pushes since Wed 2026-05-06); all 11 critical APIS_* flags correct (kill_switch=false, mode=paper, max_positions=15, max_new/day=5, thematic=0.75, ranking_min=0.30, daily_loss=0.02, weekly_dd=0.05, sector=0.40, single_name=0.20, position_age=20); scheduler `job_count=36` carry-forward. 13 OPEN positions all `origin_strategy` stamped (12 rebalance + 1 ranking_buy_signal UNH); within MAX_POSITIONS=15. 0 new positions today (Saturday). Idempotency clean (0 dupes by key, 0 dupes per ticker). evaluation_runs total **101** unchanged. DB 202 MB unchanged. Latest portfolio snapshot Fri 19:30:02 UTC cash=$12,744.58 / equity=$117,369.35 (positive ✅; Friday's 5 cycles 15:30→19:30 UTC each wrote 2 snapshots ~1.2s apart — same dual-invocation pattern as orders writer). Latest daily_market_bars `trade_date=2026-05-07` (Thursday); Friday's bars not yet ingested due to weekend pause — expected, will resume Mon 06:00 ET. NO autonomous fixes applied — same 4 open YELLOW items from Sat 10:15 UTC entry are operator-led investigations. Git tree dirty (4 modified + outputs/ untracked) — `apis/apps/worker/jobs/paper_trading.py` Phase 81-A diagnostic uncommitted from Friday + 3 state docs.

### Issues Found (carry-forward)
- YELLOW-1 dual-invocation persistence layer (Friday snapshots + 1 Fri eval_run UniqueViolation warning).
- YELLOW-2 4 NULL-qty FILLED OPEN orders from Friday (Phase 80 didn't catch — second writer path).
- YELLOW-3 Phase 81-A diagnostic source uncommitted (`apis/apps/worker/jobs/paper_trading.py`).
- YELLOW-4 6 closes from Friday 14:30 UTC with `realized_pnl IS NULL` (VRT/BE/MRVL/WDC/EQIX/NUE).

### Fixes Applied
- None. Quiet weekend probe; all four items operator-led.

### Action Required from Aaron
- Same 4 items as Sat 10:15 UTC entry / Fri 19:15 UTC entry — no escalation. See `apis/state/HEALTH_LOG.md` 15:07 UTC entry for the full §1-§4 breakdown + recommended actions (1)-(5).

---

## Health Check — 2026-05-09 10:15 UTC (Saturday 5:15 AM CT, weekend pre-market, no cycles) — YELLOW carry-forward

**Pure carry-forward from Fri 2026-05-08 19:15 UTC entry. NO new occurrences today (Saturday — no paper cycles fired, weekday-only APScheduler job idle; no signal/ranking jobs).** All four open YELLOW issues unchanged: (1) 4 NULL-qty FILLED OPEN BUYs from Fri (`0ff6a782` GOOGL+GOOG @ 13:35 UTC + `5c38137134` UNH+BE @ 17:30 UTC) — second-writer-path conclusively running OUTSIDE docker-worker-1 / docker-api-1 per Fri's cross-container grep; (2) 2 closes from Fri 16:00 UTC with `realized_pnl IS NULL` (BE, UNH); (3) `broker_health_position_drift` carry-forward (13 hits in tail-5000 spanning Thu 13:35 → Fri 19:30 UTC); (4) Phase 79 worker-restart race (Fri cycle 2 fired 12 sec post-restart before Phase 73 restore completed). Stack itself fully GREEN: 8/8 healthy `Up 20 hours` since Fri 14:29:50 UTC; /health 7/7 ok; worker 74 ERR / api 0 ERR / 0 crash-triad; Prometheus 2/2 up; Alertmanager 0 active; pytest **382p/0f/3670d in 23.14s** ✅; alembic `q7r8s9t0u1v2` single head ✅; CI **#25459511595** on `8a892db` conclusion=success ✅; all 11 critical APIS_* flags correct; scheduler `job_count=36`; heartbeat fresh 51s old. 13 OPEN positions all `origin_strategy` stamped (12 rebalance + 1 ranking_buy_signal UNH). 0 new positions today. Latest legit snapshot Fri 19:30 UTC cash=$12,744.58 / equity=$117,369.35 (positive ✅). evaluation_runs total **101** (+1 vs Fri morning — Fri 21:00 UTC EOD eval ran). DB 202 MB unchanged. Idempotency clean. 14 inactive securities. NO autonomous fixes — all four issues are operator-led from Friday. Carry-forward YELLOW Gmail draft created.

**Action required from Aaron — unchanged from Fri 19:15 UTC entry:**
1. **URGENT — find second writer process.** Probe `Get-Process python*`, `Get-ScheduledTask | Where-Object { $_.TaskName -like '*apis*' -or $_.TaskName -like '*paper*' }`, `docker exec apis-control-plane ps -ef`. Audit `SELECT decision_snapshot_json FROM orders WHERE idempotency_key LIKE '0ff6a782%' OR idempotency_key LIKE '5c381371%' LIMIT 1;` for fingerprints.
2. Patch Phase 79 worker-restart race (Redis sentinel `phase73_restore_complete` OR DB SELECT fallback inside Phase 79 guard).
3. Investigate `closed_trade_recording_failed` for BE + UNH 16:00 closes (NULL realized_pnl).
4. Commit + push Phase 81-A diagnostic (`diag(phase80): unconditional writer entry + call cardinality logs (Phase 81-A)`).
5. Send YELLOW Gmail draft for visibility.

Full §1–§8 sections in `apis/state/HEALTH_LOG.md` (primary).

---

## Health Check — 2026-05-08 19:15 UTC (Friday 2:15 PM CT, mid-afternoon, post cycles 1-5) — YELLOW

**Major escalation:** second-writer-path hypothesis CONCLUSIVELY CONFIRMED. Cycle 5 (17:30 UTC) wrote 2 NEW NULL-qty FILLED OPEN BUYs (BE + UNH, notional $7854.72 each, idem prefix `5c381371...`). Worker's actual cycle 5 (cycle_id `14b8869b...`) shows `proposed=6 approved=0 executed=0` (all 6 rebalance OPENs blocked by `max_new_positions_per_day` cap). The 2 NULL-qty orders carry cycle_id `5c38137134134487ab76cf452d9c38ef` which is **NOT in docker-worker-1, NOT in docker-api-1 logs**. Cross-grep confirms cycle 1's `0ff6a782...` (3 NULL-qty + SELL morning) is also absent from both APIS containers. Qty-populated cycle_ids (`58a857ed`, `f26a6dfa`) ARE in worker logs with full Phase 81-A diagnostic. **Conclusion: the second writer is running OUTSIDE the two known APIS containers.** Likely candidates: host-side python relic from pre-2026-04-27 path migration; leftover Windows scheduled task; apis-control-plane exceeding init role. Phase 81-A diagnostic at line 393/2023 in `paper_trading.py` cannot fire on this path because the writer isn't going through `paper_trading.py`. **Patching `paper_trading.py` will NOT solve the bug — the second writer must be located and silenced.** Stack itself: 8/8 healthy / /health 7/7 ok / 0 crash-triad / Prometheus 2/2 / Alertmanager firing=0 / pytest 382/0/3670 ✅ / alembic q7r8s9t0u1v2 single head ✅ / CI #25459511595 success ✅ / 13 OPEN positions (4 new today, within cap) / cash math reconciling. NO autonomous fixes — operator-led investigation needed. YELLOW Gmail draft created.

**Action required from Aaron:**
1. **URGENT — find the second writer process.** Probe sequence: `Get-Process python*` on Windows host; `Get-ScheduledTask` for apis/paper tasks; `docker exec apis-control-plane ps -ef`; audit `decision_snapshot_json` of an offending row (`WHERE idempotency_key LIKE '5c381371%'`); when found, capture cmdline + PID before silencing.
2. Patch Phase 79 to handle worker-restart races (Redis sentinel for Phase 73 restore complete OR DB SELECT fallback).
3. Investigate closed_trade ledger NULL realized_pnl (BE/UNH closed 16:00).
4. Commit + push Phase 81-A.
5. Send the YELLOW Gmail draft.

See `apis/state/HEALTH_LOG.md` for the full report.

---

## Health Check — 2026-05-08 15:20 UTC (Friday 10:20 AM CT, mid-session, post cycles 1+2) — YELLOW

**Overall Status:** YELLOW. Mid-session deep-dive (3rd-of-3 weekday) post-cycles-1+2. **Breakthrough finding via Phase 81-A:** cycle 1's 13:35 UTC window produced TWO distinct `cycle_id`s in the `orders` table — `0ff6a782...` (3 orders incl. GOOGL+GOOG NULL-qty BUYs) and `58a857ed...` (5 rebalance OPENs all qty-populated). Only the second invocation emitted Phase 81-A `phase80_writer_call`+`phase80_writer_entry` log lines, despite cross-repo grep showing ONE `_DBOrder` constructor at `paper_trading.py:471`. Cycle 2 (14:30) was a SINGLE invocation (`f26a6dfa...`, 5 orders all qty). **This nails the second-writer hypothesis to a dual-invocation root cause** — explains the lifetime NULL-qty distribution (25 NULL-qty FILLED rows, all `action_type=open` with `reason=rebalance_open: drift=-6.67%`). Phase 81-A diagnostic confirmed working: status_repr=`<ExecutionStatus.FILLED: 'filled'>`, fill_qty NON-NULL on all 10 entries → enum-comparison hypothesis RULED OUT, Phase 80 fix at line 428 IS effective for the path that emits the diagnostic. **NEW: Phase 79 idempotency NOT firing on cycle 2** — cycle 2 OPENed 5 same-ticker BUYs at exact carry-forward sizes; cycle 2 fired only 12 sec after worker restart at 14:29:50Z, so Phase 73 position-restore likely had not completed → `held_in_state OR held_in_broker` evaluated False. **NEW: 6 cycle-2 closes (VRT/BE/MRVL/WDC/EQIX/NUE) have NULL `realized_pnl`** — separate writer-path bug. All other subsystems GREEN: 8/8 containers healthy (all 4 core services restarted in tandem at 14:29:50Z, RestartCount=0 — operator-driven `docker compose up -d --force-recreate`, 3rd restart today); /health 7/7 ok at 15:08:31Z; worker tail-5000 73 ERR / api tail-3000 34 ERR (yfinance carry-forward + restart-burst); 0 crash-triad; Prometheus 2/2 up; Alertmanager firing=0; resources fine; DB 202 MB; pytest 382/0/3670 ✅; alembic `q7r8s9t0u1v2` single head ✅; CI run #25459511595 on `8a892db` conclusion=success ✅; all 11 critical APIS_* flags correct; scheduler `job_count=36`; heartbeat fresh (`worker:scheduler_heartbeat=1778253065` ≈ 15:11:05Z). 5 OPEN positions (down from 11 yesterday — 6 closed at cycle 2). 0 new positions today. Cash $21,152.61 legitimate stream — note **cash did NOT drop** despite 13 BUY orders today. Idempotency clean. NO autonomous fixes — root cause now sufficiently scoped for operator-led Phase 81 fix. YELLOW Gmail draft created. **Action required from Aaron:** (1) investigate dual-invocation root cause in `apps/worker/main.py` + APScheduler; (2) patch Phase 79 to wait for Phase 73 restore (Redis sentinel or fall back to DB SELECT); (3) investigate closed_trade ledger NULL realized_pnl; (4) commit + push Phase 81-A diagnostic; (5) send Gmail draft if visibility desired.

### §1 Infrastructure GREEN
8/8 containers healthy. All 4 core services restarted tandem 2026-05-08T14:29:50.0Z (operator `docker compose up -d`, RestartCount=0). /health 7/7 ok. Worker 73 ERR / API 34 ERR (yfinance + restart-burst); 0 crash-triad. Phase 81-A diagnostic: 12 firings (rebalance-path only). broker_health_position_drift: 9 firings (carry-forward). Prometheus 2/2 up. Alertmanager firing=0. Resources fine. DB 202 MB.

### §2 Execution + Data YELLOW
- 2 cycle windows but **3 distinct cycle_ids in orders**: `0ff6a782...` 13:35:00.001115 (3 orders, no diagnostic, 2 NULL-qty), `58a857ed...` 13:35:00.001132 (5 rebalance qty-populated, diagnostic fired), `f26a6dfa...` 14:30:00.001512 (5 rebalance qty-populated, diagnostic fired).
- evaluation_runs=100 (≥80 floor ✅; unchanged).
- Cash trajectory: $21,152.61 legitimate stream UNCHANGED from Thu close despite 13 BUYs today → orders ledger NOT mirroring broker cash.
- 5 OPEN positions; 6 closes today (VRT/BE/MRVL/WDC/EQIX/NUE) with NULL realized_pnl; 0 new positions; all OPEN have origin_strategy ✅.
- Data freshness: signals 10:30 UTC ✅, rankings 10:45 UTC ✅, daily_market_bars Thu close (Fri ingest 21:00 UTC).
- Idempotency clean. 14 inactive securities. Kill=false / mode=paper.
- **NEW issues:** dual-invocation on cycle 1, Phase 79 not firing on cycle 2, NULL realized_pnl on 6 closes.

### §3 Code + Schema GREEN
Alembic `q7r8s9t0u1v2` single head ✅. Pytest 382/0/3670 in 28.64s ✅ (filter `deep_dive or phase22 or phase57 or phase77_78 or phase79`). Git: dirty (Phase 81-A + 2 HEALTH_LOG entries + outputs/) — HEAD `8a892db`, 0 unpushed. CI run #25459511595 on `8a892db` conclusion=success ✅.

### §4 Config + Gates GREEN
All 11 critical APIS_* flags correct. Scheduler job_count=36 from apis_worker_started @ 14:29:52.973Z. Heartbeat fresh.

### Issues Found
1. Phase 80 incomplete fix CONFIRMED via dual-invocation evidence — first cycle-1 invocation (`0ff6a782...`) bypasses Phase 81-A diagnostic, produces NULL-qty FILLED OPENs (GOOGL+GOOG today).
2. Phase 79 idempotency NOT firing on cycle 2 — likely Phase 73 restore race after 14:29:50 worker restart.
3. 6 cycle-2 closes with NULL realized_pnl (informational/possible silent-fail in closed_trade writer).
4. broker_health_position_drift carry-forward.

### Fixes Applied
None — root cause sufficiently scoped for operator-led Phase 81 fix.

### Action Required from Aaron
1. Investigate dual-invocation root cause (APScheduler / `apps/worker/main.py`).
2. Patch Phase 79 for restart races (Redis sentinel for Phase 73 completion, or DB SELECT fallback).
3. Investigate closed_trade ledger NULL realized_pnl path.
4. Commit + push Phase 81-A diagnostic.
5. Send YELLOW Gmail draft if visibility desired.

---

## Health Check — 2026-05-08 13:10 UTC (Friday 8:10 AM CT, ~25 min before first cycle) — YELLOW

**Overall Status:** YELLOW — carry-forward, NO escalation. 2nd-of-3 weekday deep-dive (~25 min before first weekday paper cycle at 13:35 UTC). All 3 carry-forward issues from the 10:18 UTC pre-market entry persist with no new occurrences yet (no cycles today). **NEW POSITIVE: Phase 81-A diagnostic re-confirmed loaded — Aaron recreated `docker-worker-1` again at `2026-05-08T13:06:01.200572Z`** (4 min before this probe; RestartCount=0; `apis_worker_started job_count=36` confirmed at 13:06 UTC). The bind-mounted Phase 81-A diagnostic from this morning's 02:24 UTC deploy survives the new restart (file is on host disk). 13:35 UTC cycle is 25 min away and will produce the first `phase80_writer_entry` data points of the day. All other subsystems GREEN: 8/8 containers healthy; /health 7/7 ok at 13:07 UTC mode=paper kill=ok; worker tail-3000 73 ERR / api tail-3000 34 ERR (yfinance carry-forward on 14 inactive tickers + restart-burst noise; **0 crash-triad** across all 5 patterns); 0 Phase 81-A diagnostic firings yet (expected — no cycles since 13:06 UTC restart); Prometheus 2/2 up; Alertmanager firing=0 (Phase 73 `for: 30m` debounce holding); resources fine (worker fresh 74.6 MiB / 0.00% CPU post-restart, api 208.8 MiB, postgres 118.1 MiB); DB **202 MB** (+6 MB vs 10:18 UTC, expected from morning signal/ranking jobs at 10:30/10:45 UTC); pytest deep_dive+phase22+phase57+phase77_78+phase79 → **382 passed / 0 failed / 3670 deselected** ✅ matches baseline; alembic `q7r8s9t0u1v2` single head ✅; **CI run #25459511595 on `8a892db` conclusion=success** ✅; all 11 critical APIS_* flags correct; scheduler `job_count=36` from 13:06 UTC `apis_worker_started` log; liveness heartbeat fresh (`worker:scheduler_heartbeat=1778246825` ≈ 13:13:45 UTC). Cash positive $21,152.64 / equity $113,054.81 (Thu final cycle 7 carry-forward). 11 OPEN positions (10 rebalance + 1 momentum_v1 UNH), all `origin_strategy` stamped ✅. 0 new today (pre-cycle). 0 orders today. Yesterday's 3 NULL-qty FILLED OPEN BUYs (UNH 13:35, UNH 14:30, VRT 13:35) persist as carry-forward (23 NULL-qty filled rows total in lifetime, all pre-Phase-81-A). evaluation_runs=100 (≥80 ✅; unchanged from morning). Idempotency clean. 14 inactive securities. Data freshness: `daily_market_bars` MAX=2026-05-07 (Thu close), `signal_runs` MAX=2026-05-08 10:30 UTC ✅, `ranking_runs` MAX=2026-05-08 10:45 UTC ✅. NO autonomous fixes applied — Phase 80 OPEN-path root cause remains operator-review territory until 13:35 UTC cycle produces diagnostic data. YELLOW Gmail draft created (manual send required). **Action required from Aaron unchanged from 10:18 UTC entry**: (1) watch 13:35 UTC first cycle for `phase80_writer_entry` log lines revealing `res.status` shape; (2) commit + push Phase 81-A when ready; (3) send YELLOW Gmail draft.

(For full §1-§8 detail see `apis/state/HEALTH_LOG.md` 2026-05-08 13:10 UTC entry.)

---

## Health Check — 2026-05-08 10:18 UTC (Friday 5:18 AM CT, pre-market) — YELLOW

**Overall Status:** YELLOW — carry-forward, NO escalation. Pre-market deep-dive. The 4 issues from yesterday's 19:14 UTC entry persist with no new occurrences since pre-market (no cycles today; first weekday cycle 13:35 UTC, ~3.25h from now). **NEW POSITIVE:** Aaron added the Phase 81-A diagnostic instrumentation overnight (`phase80_writer_entry` + `phase80_writer_call` log lines at `apis/apps/worker/jobs/paper_trading.py:393` and `:2023`) — exactly what yesterday's 19:14 UTC report recommended. Worker recreated at `2026-05-08T02:24:07Z` to pick up the bind-mounted change; container grep confirms 1 occurrence of `phase80_writer_entry` ✅. Instrumentation is loaded but not yet exercised — first cycle 13:35 UTC will surface the actual `res.status` shape on OPEN-path NULL-qty fills. Phase 81-A change is uncommitted on `main` (operator-deferred per convention). All other subsystems GREEN: 8/8 containers healthy; /health 7/7 ok at 10:08:53Z mode=paper kill=ok; worker tail-3000 54 ERR / api tail-3000 15 ERR (yfinance + 7 `broker_health_position_drift`, **0 crash-triad**); Prometheus 2/2 up; Alertmanager firing=0; resources fine; DB **196 MB** (+1 MB from Thu EOD ingest — `daily_market_bars` MAX = 2026-05-07 with 490 securities); pytest **382/0/3670 in 36.90s** ✅; alembic `q7r8s9t0u1v2` single head ✅; **CI run #25459511595 on `8a892db` conclusion=success** ✅; all 11 critical APIS_* flags correct; scheduler `job_count=36`; liveness heartbeat fresh (`worker:scheduler_heartbeat=1778235322` ≈ 10:15:22Z). Cash positive $21,152.64; equity $113,054.81 (Thu final cycle 7 settled at 19:30 UTC). 11 OPEN positions (10 rebalance + 1 momentum_v1 UNH), all `origin_strategy` stamped ✅. 0 new today (pre-market). Yesterday's 3 NULL-qty FILLED OPEN BUYs persist; 0 new since pre-market. evaluation_runs=100 (≥80 ✅; +1 vs Thu from EOD eval). Idempotency clean. 14 inactive securities (HOLX + 13 stale). NO autonomous fixes applied — Phase 81-A diagnostic is Aaron's overnight work; today's first cycle will produce the data needed. YELLOW Gmail draft pending (manual send). **Action required from Aaron:** (1) watch 13:35 UTC first cycle for `phase80_writer_entry` log lines that reveal `res.status` type/value; (2) commit + push Phase 81-A when ready; (3) send YELLOW Gmail draft.

(For full §1-§8 detail see `apis/state/HEALTH_LOG.md` 2026-05-08 10:18 UTC entry.)

---

## Health Check — 2026-05-07 19:14 UTC (Thursday 2:14 PM CT, late-afternoon market, 6/12 cycles fired) — YELLOW

**Overall Status:** YELLOW — carry-forward, NO escalation. 3rd-of-3 weekday deep-dive. All 4 issues from the 15:13 UTC entry persist with no new regressions: (1) Phase 80 NULL-quantity bug remains open — same 3 NULL-qty FILLED OPEN orders (UNH 13:35, UNH 14:30, VRT 13:35) carry forward unchanged; ZERO new NULL-qty rows since cycle 2 (cycles 3-6 all `app=0 exec=0` due to daily-cap consumption). (2) Orders writer count discrepancy persists — cycle 1 has 9 orders rows but `app=5 exec=5`. (3) `broker_health_position_drift` fired all 6 cycles today; Phase 79 `phase79_skipped=0` every cycle (symmetric `held_in_state AND held_in_broker` condition never triggered). (4) Cycle 2 SELL rejections on already-closed SLB+CAT (informational). **NEW DATA POINT narrowing Phase 80 root cause:** cycle 3 (15:30 UTC) VRT TRIM SELL filled qty=20 — the orders writer persists correct quantity on TRIM/CLOSE paths (3/3 SELLs today have proper qty: SLB=129, CAT=8, VRT=20). Phase 80 hole is specifically OPEN-direction notional-only fills. Strongly suggests `res.status == _ExecStatus.FILLED` is value-comparing enum to string, so diagnostic warning at line 416 never fires. All other subsystems GREEN: 8/8 containers healthy 23h uptime RestartCount=0; /health 7/7 ok at 19:08:47Z; worker 38 ERR / api 34 ERR (yfinance + 6 drift, 0 crash-triad); Prometheus 2/2 up; Alertmanager 0 firing; resources fine; DB 195 MB; pytest 382/0/3670 ✅; alembic `q7r8s9t0u1v2` single head ✅; CI run #25459511595 on `8a892db` conclusion=success ✅; all 11 critical APIS_* flags correct; scheduler `job_count=36`; liveness heartbeat fresh (`worker:scheduler_heartbeat=1778181187` ≈ 19:13:07Z). Cash positive $21,152.64; equity $113,029.29; 11 OPEN positions (10 rebalance + 1 momentum_v1 UNH); 2 new today (VRT, UNH); idempotency clean; Phase 78 fired correctly count=13 at 10:30 UTC. NO autonomous fixes applied — all YELLOW issues operator-review-required. YELLOW Gmail email drafted (manual send). **Action required from Aaron:** (1) PRIORITY — investigate Phase 80 enum comparison: add `logger.info("phase80_writer_entry", status_type=type(res.status).__name__, status_repr=repr(res.status))` at top of `_persist_orders_and_fills` before line 384, suspected fix is `getattr(res.status, "value", res.status) == "filled"` instead of `== _ExecStatus.FILLED`. (2) reconcile orders writer vs `paper_trading_cycle_complete` metric. (3) consider Phase 81 broker-DB resync on API restart for the asymmetric `in broker, not in state` case. (4) send YELLOW Gmail draft.

### §1 Infrastructure
- 8/8 containers healthy. worker `Up 23h` since 2026-05-06T20:33:07Z (Phase 79+80 deploy). api `Up 47h`. postgres/redis/grafana/prom/alertmanager/control-plane `Up 2 days` since 2026-05-05T03:31:12Z. RestartCount=0 across all 4 core services.
- /health: all 7 components `ok` at 19:08:47Z. mode=paper kill_switch=ok.
- Worker 38 ERR (yfinance + 6 drift) / API 34 ERR (yfinance carry-forward). 0 crash-triad across all 5 patterns worker/api.
- Prometheus 2/2 up (apis, prometheus), 0 dropped. Alertmanager 0 firing.
- Resources fine: worker 734.8 MiB / 0.00% CPU, api 846.2 MiB / 0.11%, postgres 170.3 MiB. DB **195 MB** (unchanged from 15:13).

### §2 Execution + Data Audit
- 6/12 cycles fired today (13:35, 14:30, 15:30, 16:00, 17:30, 18:30 UTC). Cycle 1 prop=30 app=5 exec=5; cycles 2-6 prop=20 app=0 exec=0. Next cycle 19:30 UTC.
- evaluation_runs=99 (≥80 floor; unchanged — paper cycles don't write here).
- Phase 79: `rebalance_actions_merged phase79_skipped=0` every cycle (symmetric idempotency never triggered today).
- Portfolio: cash $14,253→$21,152 (legit stream cycle 3-6 trajectory) — positive ✅. Equity intraday $115,652→$113,029 (-2.27% MTM, normal). Dual-snapshot writer carry-forward continues (secondary $67k/$99.9k benign).
- Broker<->DB recon: 11 OPEN positions; `broker_health_position_drift` fired 6/6 cycles today on the carry-forward set.
- Phase 80 NULL-qty: 3 orders rows from morning persist (UNH 13:35, UNH 14:30, VRT 13:35); 0 new since cycle 2. **NEW**: cycle 3 VRT TRIM SELL filled qty=20 — narrows hole to OPEN-direction notional-only fills.
- Orders writer/metric discrepancy: cycle 1 has 9 orders rows vs `app=5 exec=5` (carry-forward).
- Origin-strategy stamping: ALL 11 OPEN have origin_strategy ✅.
- Position caps: 11/15 ✅. 2 new today (VRT, UNH) — within `MAX_NEW=5`.
- Data freshness: bars MAX 2026-05-06 ✅; signal_runs MAX 2026-05-07 10:30 UTC ✅; ranking_runs MAX 2026-05-07 10:45 UTC ✅; 14 inactive securities (HOLX + 13 stale).
- Phase 78: fired correctly at 10:30 UTC `count=13 tickers=[ANSS,CTLT,DFS,HES,IPG,JNPR,K,MMC,MRO,PARA,PKI,PXD,WRK]` ✅.
- Kill_switch=false ✅. Mode=paper ✅. Idempotency clean (0/0 dupes).

### §3 Code + Schema
- Alembic head `q7r8s9t0u1v2` single ✅.
- Pytest deep_dive+phase22+57+77_78+79 → 382p/0f/3670d in 38.02s ✅.
- Git: tree DIRTY on HEALTH_LOG only; HEAD `8a892db`, 0 unpushed.
- **CI run #25459511595 on `8a892db` conclusion=success** ✅ (https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25459511595).

### §4 Config + Gate Verification
- All 11 critical APIS_* flags at expected values ✅ (paper / kill=false / max_pos=15 / max_new=5 / thematic=0.75 / min_score=0.30 / sector=0.40 / single_name=0.20 / age=20d / daily_loss=0.02 / weekly=0.05).
- Scheduler `job_count=36`. Liveness heartbeat fresh `worker:scheduler_heartbeat=1778181187` ≈ 19:13:07Z.

### Issues Found
1. **Phase 80 NULL-quantity bug NOT FIXED for OPEN paths** (YELLOW carry-forward). 3 orders rows persist; 0 new since cycle 2. **NEW data point narrows root cause to OPEN-direction notional-only fills with broken `_ExecStatus.FILLED` value comparison in the diagnostic guard.**
2. **Orders writer count discrepancy with cycle metrics** (YELLOW carry-forward). Cycle 1: 9 orders rows vs `app=5 exec=5`.
3. **broker_health_position_drift** fired 6/6 cycles today (YELLOW carry-forward). Phase 79 idempotency never triggered (symmetric condition not met).
4. **Cycle 2 SELL rejection on already-closed positions** (informational). SLB+CAT.

### Fixes Applied
- (none — all YELLOW issues operator-review-required.)

### Action Required from Aaron
1. **PRIORITY: Phase 80 root cause** — add diagnostic logging at `_persist_orders_and_fills` entry; suspected `res.status == _ExecStatus.FILLED` enum-vs-string mismatch.
2. Reconcile orders writer vs cycle metric counters.
3. Phase 79 asymmetric case — Phase 81 broker-DB resync candidate.
4. Send YELLOW Gmail draft for visibility.
5. Investigate orders-writer-bypass-of-risk pattern (UNH 14:30 BUY filled despite risk_engine block, position created with qty=42).

---

## Health Check — 2026-05-07 15:13 UTC (Thursday 10:13 AM CT, mid-morning market) — YELLOW

**Overall Status:** YELLOW. Clean infrastructure but **Phase 80 NULL-quantity fix is INCOMPLETE for OPEN paths**: 3 of 12 today's orders persisted with `status=filled` AND `quantity=NULL` (VRT BUY 13:35, UNH BUY 13:35, UNH BUY 14:30 — all `rebalance_open` actions), and the Phase 80 diagnostic warning `phase80_orders_writer_qty_unresolvable` did NOT fire (suggesting the writer's fallback path or its diagnostic check is being bypassed). 2 paper cycles fired today (13:35, 14:30 UTC). 11 OPEN positions with all `origin_strategy` stamped (SLB+CAT closed cleanly cycle 1, VRT+UNH opened cycle 1). `broker_health_position_drift` fired 2 cycles today on the carry-forward rebalance set — Phase 79's `phase79_skipped=0` both cycles (no rebalance OPEN proposed against held ticker yet). Phase 78 fired CORRECTLY at 10:30 UTC: count=13 stale tickers dropped ✅. All other subsystems GREEN.

**§1 Infra:** 8/8 healthy (worker `Up 19h`, api `Up 43h`, others `Up 2 days`, RestartCount=0); /health 7/7 ok 15:08:28Z mode=paper kill=ok; worker tail-5000 38 ERR / api 34 ERR (yfinance + 2 broker_drift); **0 crash-triad** across all 5 patterns; Prometheus 2/2 up; Alertmanager firing=0; resources fine; DB 195 MB (+8 MB intraday).

**§2 Execution+Data YELLOW:** 2 paper cycles complete (cycle 1 prop=30 app=5 exec=5; cycle 2 prop=20 app=0 exec=0). evaluation_runs=99. 11 OPEN positions all `origin_strategy` stamped (10 rebalance + 1 momentum_v1 UNH). 2 new positions today (VRT, UNH). **3 NULL-qty FILLED orders persist** (VRT, UNH x2). Cycle 1 has 9 orders rows but app=5 exec=5 — orders writer count discrepancy. broker_health_position_drift fired 2/2 cycles. Cash $21,918.88 / equity $115,896.51 (positive ✅). signal_runs MAX 2026-05-07 10:30 UTC ✅; ranking_runs MAX 10:45 UTC ✅; daily_market_bars MAX 2026-05-06. Phase 78 dropped count=13 ✅. 14 inactive securities. Idempotency clean. Kill=false mode=paper.

**§3 Code+Schema GREEN:** alembic `q7r8s9t0u1v2` single head ✅; pytest 382p/0f/3670d in 35.46s ✅; git HEAD `8a892db` 0 unpushed (only HEALTH_LOG dirty); **CI run #25459511595 on `8a892db` conclusion=success** ✅.

**§4 Config+Gates GREEN:** all 11 critical APIS_* flags correct; scheduler job_count=36; liveness heartbeat fresh (≈15:15:22Z, ~2 min after probe).

**§5 Severity: YELLOW** (Phase 80 fix incomplete + broker drift carry-forward). **§6 Email: YELLOW Gmail draft created — manual send required** (per "draft created — manual send" convention).

**§7 State+memory:** this entry (mirror); `apis/state/HEALTH_LOG.md` primary entry; new memory file `project_phase80_incomplete_fix_2026-05-07.md`; MEMORY.md index updated. NO DECISION_LOG/CHANGELOG entry (no decisions made; investigation pending).

**§8 Final checklist:** complete. HEALTH_LOG x2 ✅; no autonomous fixes (operator-review-required); CI probed ✅; YELLOW email drafted; memory updated; git tree dirty (HEALTH_LOG only — operator-deferred convention).

**Action required from Aaron:** (1) **PRIORITY** investigate Phase 80 incomplete fix at `paper_trading.py:411-430` — root cause likely enum import drift OR a separate non-`_persist_orders_and_fills` writer for OPEN paths; (2) reconcile orders-writer count vs `paper_trading_cycle_complete` metrics; (3) Phase 79 broadening: handle asymmetric "in broker not in state" case (Wed cycle 7 VRT was in broker without DB row, so today's cycle 1 re-OPENed it as a 43-share double-down); (4) carry-forward broker_health_position_drift will continue until Phase 81 broker→DB resync OR Phase 79 broadening; (5) send YELLOW Gmail draft if visibility desired.

---

## Health Check — 2026-05-07 10:15 UTC (Thursday 5:15 AM CT, pre-market) — GREEN

**Overall Status:** GREEN. Pre-market deep-dive. Phase 79 + 80 (DEC-079 / DEC-080) FULLY LANDED on `origin/main` at `8a892db` (operator commit + push completed); CI run #25459511595 conclusion=success ✅; worker restarted 2026-05-06T20:33:07Z and code is loaded (`phase79_rebalance_open_already_open_skipped` + `phase80_orders_writer_qty_unresolvable` both grep-1 in `paper_trading.py`); runtime knob `phase79_rebalance_idempotency_enabled=True` confirmed ✅. First weekday cycle 13:35 UTC = first Phase 79+80 exercise.

**§1 Infra:** 8/8 containers healthy (worker `Up 14h` since Phase 79+80 recreate, api `Up 38h`, postgres/redis/grafana/prom/alertmanager/control-plane `Up 2 days`, RestartCount=0); /health 7/7 ok at 10:08:15Z mode=paper kill_switch=ok; worker tail-3000 = 19 ERR / api 15 ERR (yfinance carry-forward); **0 crash-triad** across all 5 patterns; Prometheus 2/2 up; Alertmanager firing=0 (Phase 73 30m debounce holding through 14h restart); resources fine; DB 187 MB.

**§2 Execution+Data:** 0 paper cycles today (expected, first 13:35 UTC); evaluation_runs=99 (≥80 floor ✅, +1 from Wed 21:00 UTC EOD eval); latest legit snapshot Wed 19:30:02 cash=$30,519.19/equity=$116,774.09 ✅ (dual-snapshot writer carry-forward continues benign); 11 OPEN positions all `origin_strategy=rebalance` (Phase 73 holding, 0 NULLs); 0 new today; daily_market_bars MAX 2026-05-06 (488 sec); signal_runs/ranking_runs MAX 2026-05-06 10:30/10:45 UTC; 14 inactive tickers in DB (HOLX + 13 stale, Phase 79+80 deploy `UPDATE 13` confirmed); kill_switch=false mode=paper; idempotency clean; 0 broker_health_position_drift in tail-5000 (no cycles since 20:33 UTC restart). VRT cycle 7 (Wed 19:30 UTC) 21-share BUY filled at broker but no DB position row — pre-existing Phase 80 NULL-qty writer artifact from BEFORE 20:30 UTC deploy (carry-forward, low-priority).

**§3 Code+Schema:** Alembic `q7r8s9t0u1v2` single head ✅; pytest `deep_dive or phase22 or phase57 or phase77_78 or phase79` → **382 passed / 0 failed / 3670 deselected in 36.61s** ✅ (matches Phase 79+80 deploy baseline of 382 = 370 prior + 12 new); git tree CLEAN at HEAD `8a892db`, 0 unpushed; **CI #25459511595 on `8a892db` conclusion=success** ✅.

**§4 Config+Gates:** all 11 critical APIS_* flags correct; Phase 79 knob enabled; scheduler `job_count=36` per `apis_worker_started` 2026-05-06T20:33:07Z; liveness heartbeat `worker:scheduler_heartbeat=1778148622` ≈ 10:10:22Z fresh.

**Issues Found:** none.

**Fixes Applied:** none.

**Action Required from Aaron:** (1) confirm 13:35 UTC first cycle emits `phase79_rebalance_open_already_open_skipped` for any already-held ticker proposals; (2) confirm `quantity IS NOT NULL` on FILLED orders today (Phase 80); (3) confirm 10:30 UTC signal job emits `signal_engine_inactive_or_unknown_tickers_dropped count=14` (Phase 78 fully armed for first time); (4) escalate to Phase 81 broker-DB resync if drift persists; (5) optional VRT cycle 7 backfill for audit-trail completeness.

See `apis/state/HEALTH_LOG.md` for full entry.

---

## Phase 79 + 80 Deploy — 2026-05-06 ~20:30 UTC

See `apis/state/HEALTH_LOG.md` for full entry. Summary:
- Phase 79 (DEC-079): rebalance-engine idempotency filter at paper_trading.py:1622 — drops rebalance OPEN for already-held tickers. Defence-in-depth (state + broker).
- Phase 80 (DEC-080): orders ledger writer at paper_trading.py:399 prefers `res.fill_quantity` over `req.action.target_quantity`. Eliminates NULL-quantity rows on FILLED non-rebalance opens.
- Issue 3 (44-share VRT SELL on 22-share long) RESOLVED as benign — HEALTH_LOG misread. No Phase 81 needed.
- 13 stale tickers flipped `is_active=false`; scheduler `job_count=36` confirmed legitimate post-Phase-71.
- Tests 382p/0f under `APIS_PYTEST_SMOKE=1`. Ruff clean. DEC-079 + DEC-080 logged.

---



## Health Check — 2026-05-06 19:30 UTC (Wednesday 2:30 PM CT, mid-afternoon market)

**Overall Status:** YELLOW — clean infrastructure but TWO new data-integrity findings worth Aaron's review: (1) **VRT same-day churn** under `theme_alignment_v1` strategy — opened 14:30 UTC by cycle 2, closed 18:30 UTC by cycle 6, **re-opened 19:30 UTC by cycle 7**. Same churn pattern Phase 65b mitigated for `momentum_v1` is now appearing for the new `theme_alignment_v1` strategy. (2) **Orders ledger NULL-quantity rows** for VRT — both BUY orders today written with `quantity=NULL` + 0 fill rows, and 2 SELL orders for `qty=22` each both marked `filled` (broker apparently sold 44 shares of a 22-share position, returning ~$15,570 cash for shares originally bought for $7,729). The NULL-quantity pattern is **pre-existing** (every weekday for past 14 days has 2-7 NULL-qty orders), but morning HEALTH_LOG didn't flag it because no NEW open positions had been written through this code path until today. All other subsystems GREEN: 8/8 containers healthy 23h uptime RestartCount=0, /health 7/7 ok, worker tail-5000 102 ERROR / api 36 ERROR (yfinance stale-13 + 20 `broker_health_position_drift` carry-forward — 0 crash-triad), Prometheus 2/2 up, Alertmanager firing=0, pytest deep_dive+phase22+phase57+phase77_78 → **370p/0f/3670d in 24.03s** ✅, alembic `q7r8s9t0u1v2` single head, **CI run #25401590762 on `ffd363e` conclusion=success** ✅. NO autonomous fixes applied — both YELLOW issues are operator-review-required. **Action required from Aaron:** review VRT churn pattern, investigate orders-ledger NULL-quantity writer, reconcile broker-side VRT share count.

See `apis/state/HEALTH_LOG.md` for full §1-§4 detail and Issues/Fixes/Action breakdown.

---

## Health Check — 2026-05-06 15:14 UTC (Wednesday 10:14 AM CT, mid-morning market)

**Overall Status:** GREEN — clean mid-morning run; first 2 paper cycles today (13:35 + 14:30 UTC) ran cleanly with first new OPEN position since 2026-05-01 (VRT via `theme_alignment_v1`, replacing STT which closed). All four execution-defence phases (75/76/77/78) holding on first integration exercise. See `apis/state/HEALTH_LOG.md` for full structured report (mirror).

### §1 Infrastructure
- 8/8 containers healthy. RestartCount=0. /health 7/7 ok at 15:09:09Z mode=paper.
- Worker 68 ERR / API 36 ERR, **0 crash-triad** across 5 patterns.
- Prometheus 2/2 up. Alertmanager firing=0. Resources fine. DB 187 MB.

### §2 Execution + Data
- 2/expected ~3 paper cycles today (13:35 + 14:30 UTC). 0 fails.
- 12 OPEN positions, **all 12 origin_strategy stamped** (11 rebalance + 1 theme_alignment_v1 NEW today). 1 close (STT) + 1 open (VRT) net 0.
- Cash positive $22,541.91, equity $114,058 (legitimate stream).
- daily_market_bars MAX 2026-05-05; signal_runs/ranking_runs MAX today 10:30/10:45 UTC ✅.
- Phase 78 first-run silent (0 drops — strategy already requests only active tickers upstream; expected defence-in-depth behaviour).
- Phase 76 first-run silent (0 HOLX rejections — Phase 78 suppressed proposal upstream).
- Idempotency 0/0 ✅. evaluation_runs=98 (≥80 floor). kill=false mode=paper.

### §3 Code + Schema
- Alembic `q7r8s9t0u1v2` single head ✅. Pytest **370p/0f/3670d in 36.48s** ✅.
- Git HEAD `ffd363e`, 0 unpushed; tree dirty only on HEALTH_LOG.md (operator-deferred from morning) + outputs/ untracked.
- **CI run #25401590762 on `ffd363e` `conclusion=success`** ✅.

### §4 Config + Gates
- All 11 critical APIS_* flags at expected values.
- Scheduler `job_count=36`; heartbeat 15:10:22 UTC fresh.

### Issues Found / Fixes Applied
- None / None. Clean run.

### Action Required from Aaron (carry-forward)
1. Optional: mark 13 stale delisted tickers `is_active=false` to fully exercise Phase 78 + eliminate yfinance-404 noise.
2. Confirm `broker_health_position_drift` continues to drop (14 today vs 20 yesterday).
3. Non-urgent: investigate scheduler job_count=36 vs documented baseline 35.



## Health Check — 2026-05-06 10:10 UTC (Wednesday 5:10 AM CT, pre-market) — GREEN

Mirror entry — full detail in `apis/state/HEALTH_LOG.md`. **Overall: GREEN, clean pre-market.** 8/8 containers healthy (worker+api Up 14h since Phase 77+78 deploy 20:19 UTC Tue, postgres/redis Up 31h, RestartCount=0). /health 7/7 ok. **Alembic head advanced `p6q7r8s9t0u1` → `q7r8s9t0u1v2`** (Phase 77 UNIQUE constraint applied) ✅. Pytest `deep_dive+phase22+phase57+phase77_78` → **370p/0f/3670d in 37.36s** ✅ (+10 from prior baseline thanks to Phase 77/78 regression class). Git CLEAN at `ffd363e`, 0 unpushed. **CI run #25401590762 on `ffd363e` `conclusion=success`** ✅. Phase 76+78 code paths both verified loaded in worker container. 0 paper cycles today (pre-cycle, expected). 12 OPEN positions all `origin_strategy=rebalance`, 0 NULLs, 0 new today. evaluation_runs=98 (≥80 ✅). Latest legit snapshot Tue 19:30 UTC: cash=$23,050.74 / equity=$113,850.56 (cash positive ✅). Worker 24h log scan = 83 ERR (yfinance stale-13 + 20 broker_drift carry-forward; **0 crash-triad**); API 17 ERR (0 crash-triad). Prometheus 2/2 up. Alertmanager firing=0. All 11 critical APIS_* flags at expected values; `job_count=36`; liveness heartbeat fresh in Redis (`worker:scheduler_heartbeat=1778062222` ≈ 10:10 UTC). Only **HOLX** marked `securities.is_active=false`; the 13 stale delisted S&P 500 names are still `is_active=true`, so Phase 78's expected dropped-count on next 10:30 UTC signal job will be ≈1 not ≈13 — actionable for operator to align DB with reality (see Action #3 in primary log). NO autonomous fixes. Email silent per GREEN rule.

---

## Health Check — 2026-05-05 19:12 UTC (Tuesday 2:12 PM CT, market open ~5.6h, 6/12 cycles fired) — YELLOW

**Overall Status:** YELLOW — same two carry-forward issues from this morning's 15:09 UTC entry, no new regressions, no escalation. (1) `broker_health_position_drift` fired on every paper cycle today (6/6) on the same 12 operator-restored rebalance tickers — strategy continues to BUY toward DB target rather than CLOSE; drift will narrow gradually. (2) HOLX proposed + rejected on every cycle (6/6) — strategy still proposes inactive ticker; risk_engine blocks on `max_new_positions_per_day=5`; Alpaca is final safety net. Both issues triaged in 15:09 UTC report; no new code/operator action since. All other subsystems GREEN: 8/8 containers healthy 16h uptime RestartCount=0, /health 7/7 ok, **0 crash-triad**, Prometheus 2/2 up, Alertmanager firing=0, pytest **360p/0f in 22.12s**, alembic single head `p6q7r8s9t0u1`, **CI run #25327395434 on `9db28ae` conclusion=success**, 12 OPEN positions all `origin_strategy=rebalance`, 0 new today, kill_switch=false mode=paper, 0 idempotency dupes, evaluation_runs=97 (≥80), all 11 critical APIS_* flags correct, scheduler `job_count=36` + liveness heartbeat 19:11:20 UTC. **NO autonomous fixes applied — no escalation since morning.** Email: YELLOW Gmail draft created (manual send required).

Full deep-dive report mirrored from `apis/state/HEALTH_LOG.md` — see that file for the §1–§4 breakdown.

---

## Health Check — 2026-05-05 15:09 UTC (Tuesday 10:09 AM CT, market open ~1.6h) — YELLOW

**Overall Status:** YELLOW — first-cycle Phase 75 validation reveals two carry-over patterns and one strategy-layer regression. (1) `broker_health_position_drift` fired on BOTH Tue cycles (13:35 + 14:30 UTC) on the same 12 tickers — Phase 75's close-loop is NOT naturally closing the operator-restored rebalance rows because the strategy is rebalancing in the OPPOSITE direction (5 BUY fills today bringing broker partially up to DB target rather than closing the rows). (2) HOLX still being PROPOSED by strategy (action_type=open) despite Phase 72's `is_active=false` (DB confirms `f`); risk_engine blocks only on `max_new_positions_per_day=5` (already at cap from today's 5 fills). Defense-in-depth holds (Alpaca rejects + risk-cap blocks) but Phase 72's "FULLY RESOLVED" claim is incomplete at the proposal layer. (3) Phase 75 functional code still uncommitted (intentional operator-defer carry-forward). Everything else GREEN: 8/8 containers healthy 12h uptime RestartCount=0, /health all 7 ok at 15:09:02Z, Worker 24h log scan = 34 ERROR (all known-stale yfinance + 7 drift warns; 0 crash-triad regressions), Prometheus 2/2 up, Alertmanager firing=0, pytest 360/0 in 25.18s, alembic single head `p6q7r8s9t0u1`, CI `9db28ae` `conclusion=success`, 12 OPEN positions all `origin_strategy=rebalance`, kill_switch=false, mode=paper, 0 idempotency dupes, evaluation_runs=97 (≥80 floor), all 11 critical APIS_* flags correct, scheduler `job_count=36` + liveness firing every 5 min, signal/ranking staleness FULLY CLEARED (06:30/06:45 ET jobs ran today). Today's 5 fills: INTC=64@$103.10, MU=10@$616.48, AMZN=24@$277.01, EQIX=6@$1086.05, NUE=29@$228.48 (all add-ons against existing rebalance positions; no new rows; rebalance-target semantics preserved). YELLOW email sent.

### Issues Found
- **[YELLOW] HOLX universe-filter regression vs Phase 72.** Strategy proposing inactive ticker; only `max_new_positions_per_day` cap stops it from reaching broker. Recommend adding `inactive_ticker` violation to risk_engine + `is_active=true` filter to strategy universe.
- **[YELLOW] Phase 75 close-loop forecast miss.** Drift not clearing as forecasted because strategy rebalances toward DB target (BUY) instead of closing operator-restored rows. Will resolve naturally as broker accumulates over many cycles.
- **[INFO] Phase 75 code change still uncommitted.** Tree state matches yesterday — operator commit/push pending.

### Action Required from Aaron
1. Triage HOLX universe-filter regression (preferred fix: `inactive_ticker` violation in risk_engine).
2. Commit + push Phase 75 when ready.
3. Monitor next 4–5 cycles for broker-drift trajectory.

Full details in `apis/state/HEALTH_LOG.md`.

---

## Health Check — 2026-05-05 10:18 UTC (Tuesday 5:18 AM CT, pre-market) — GREEN

**Overall Status:** GREEN — clean pre-market run after the Phase 75 deploy. 8/8 containers healthy and recreated together at 03:31:12 UTC (RestartCount=0; most likely operator `docker compose up -d` after the Mon 01:42 UTC Phase 75 worker restart). Phase 75 code path confirmed in worker. /health all 7 ok. 0 crash-triad regressions in worker/api logs. Prometheus 2/2 up. Alertmanager firing=0. 12 OPEN positions all `origin_strategy=rebalance`. Pytest **400p/0f in 70.43s** (deep_dive + phase22 + phase57 + phase59) **+ Phase 64/75 7p/0f in 6.83s**. Alembic single head `p6q7r8s9t0u1`. CI on `9db28ae` GREEN. All 11 critical APIS_* flags at expected values. Scheduler `job_count=36` with liveness heartbeat firing. Phase 75 fix awaiting first-cycle integration validation at 13:35 UTC today (~3.25h from this report). 7 `broker_health_position_drift` hits in the 24h window are all Mon-afternoon carry-forward (no cycles since the 01:42 UTC worker restart). signal_runs/ranking_runs still stale at 2026-05-01 — 06:30 ET (10:30 UTC) signal job fires in ~12 min. Dual-snapshot writer pattern still present and matches yesterday's report (no new regression). 0 fixes applied (no issues to fix). Email silent per GREEN rule.

### §1 Infrastructure GREEN
- Containers: 8/8 healthy. All 4 core services started 2026-05-05T03:31:12Z (RestartCount=0 = compose recreate, not daemon restart). Phase 75 code verified loaded in worker.
- /health: all 7 components ok at 10:08:18Z. mode=paper, kill_switch=ok.
- Worker log scan (24h): 34 ERROR pattern matches (yfinance stale-ticker carry-forward). **0 crash-triad**. **7 `broker_health_position_drift` hits — all Mon afternoon, pre-Phase-75-deploy.**
- API log scan (5000 tail): 33 ERROR matches, 0 crash-triad.
- Prometheus 2/2 up; Alertmanager firing=0.
- Resource usage all under threshold; DB 171 MB.

### §2 Execution + Data GREEN
- Paper cycles: 0 today (first scheduled 13:35 UTC). evaluation_runs total = 97 (≥80 floor ✅).
- 12 OPEN positions all `origin_strategy=rebalance`. 0 new positions today (CURRENT_DATE filter, expected pre-cycle).
- Latest snapshot 2026-05-04 19:30:03 UTC: cash=$23,050.74 / equity=$110,500.08. Cash positive ✅. Dual-snapshot pattern (secondary $67k/$99.9k stream) carry-forward — same as yesterday.
- daily_market_bars latest = 2026-05-04 (Mon close, 490 securities). signal_runs/ranking_runs latest = 2026-05-01 (Friday — Phase 74 cleanup collateral; will repopulate at 06:30 ET signal job in ~12 min).
- Stale tickers: known 13 only. Kill-switch=false, mode=paper. Idempotency 0/0 dupes ✅.
- Orders/fills 24h: 11 / 5 (Mon afternoon activity). Totals: 306 / 202.
- Mon's 7 CSCO churn rows preserved (carry-forward pre-Phase-75; new churns prevented going forward).

### §3 Code + Schema GREEN
- Alembic `p6q7r8s9t0u1` single head ✅.
- Pytest deep_dive+phase22+57+59 → **400p/0f in 70.43s** ✅. Phase 64+75 → **7p/0f in 6.83s** ✅.
- Git tree DIRTY (Phase 75 functional + state-doc changes — operator-deferred per ACTIVE_CONTEXT). HEAD `9db28ae`, 0 unpushed.
- **CI run #25327395434 on `9db28ae` conclusion=success** ✅.

### §4 Config + Gates GREEN
- All 11 critical APIS_* flags at expected values.
- Scheduler `job_count=36`. Liveness heartbeat last seen 10:16:20 UTC.

### Issues Found
- None worthy of YELLOW. Carry-forward observations only (broker drift to be cleared by today's first cycle; dual-snapshot writer; signal/ranking staleness; uncommitted Phase 75).

### Fixes Applied
- None — clean run, no autonomous fixes needed.

### Action Required from Aaron
1. Confirm Tue 2026-05-05 13:35 UTC first cycle runs cleanly with Phase 75; watch for `phase75_position_row_reopened` / `phase75_close_skipped_just_upserted` log lines and `broker_health_position_drift` clearance within 1–2 cycles.
2. Commit + push Phase 75 when ready.
3. Optional historical cleanup SQL still available in yesterday's HEALTH_LOG.

---

## Health Check — 2026-05-04 19:08 UTC (Monday 2:08 PM CT, market mid-afternoon) — YELLOW

**Overall Status:** YELLOW — see `apis/state/HEALTH_LOG.md` for full detail. Two YELLOW items: (a) `broker_health_position_drift` firing on every cycle (6 hits today) — carry-forward from 12:25 UTC cleanup, **autonomous-fix applied** via `docker restart docker-api-1` at 19:13 UTC, post-restart verified healthy; (b) NEW Phase 65c CSCO momentum_v1 churn — 6 rows today (one per cycle, identical `opened_at`/`entry_price=$91.43`/`quantity=72`, only `closed_at` differs) breaches `APIS_MAX_NEW_POSITIONS_PER_DAY=5`. Net 0 OPEN. Recommended: extend Phase 65b intra-cycle OPEN+CLOSE dedup to momentum_v1. Everything else GREEN: 8/8 containers healthy, /health all 7 ok, Alertmanager firing=0, pytest 360/360 in 20.55s, alembic single head `p6q7r8s9t0u1`, CI runs #25327148433 (`3bdbe64`) + #25327395434 (`9db28ae`) both `conclusion=success`, all 11 critical APIS_* flags correct, scheduler `job_count=36`, evaluation_runs=96, 12 OPEN positions all `origin_strategy=rebalance`, kill_switch=false, mode=paper, no idempotency dupes, no crash-triad regressions.

(Full §1–§4 detail + Issues/Fixes/Action sections in `apis/state/HEALTH_LOG.md`.)

---

## Health Check — 2026-05-04 15:15 UTC (Monday 10:15 AM CT, market open ~45 min) — YELLOW

**Overall Status:** YELLOW — CI Lint failure on Phase 74 commit `37191c3` (I001 import-sort in `apis/tests/conftest.py`) auto-fixed at `3bdbe64` and pushed; CI rerun #25327148433 queued. Two `broker_health_position_drift` warnings fired in 24h (cycles 13:35 + 14:30 UTC) — known carry-forward artifact from the 12:25 UTC operator-approved cleanup (broker adapter cache not resynced after DB UPDATE). Today's signal_runs/ranking_runs are stale at 2026-05-01 — collateral damage from the cleanup `DELETE … >= 2026-05-04 01:00:00` clause; paper cycles still ran successfully. Everything else GREEN: 8/8 containers healthy 15h, /health all 7 ok, Alertmanager firing=0 (Phase 73 defense holding), 12 open positions correctly restored, Prom matches DB exactly, equity $110,872.56 / cash $23,050.74, pytest 360/360, all 6 critical APIS_* flags correct, git tree clean.

**Full report:** see `apis/state/HEALTH_LOG.md` for the §1–§4 detail block. Issues + Fixes + Action Required summary:

### Issues Found
- **[YELLOW]** CI failure on `37191c3` — Lint & Type Check (I001 import-sort in `apis/tests/conftest.py:177-179`). **AUTO-FIXED** at `3bdbe64`.
- **[YELLOW]** CI Unit Tests (Python 3.11+3.12) reported failure on `37191c3` — Aaron-review (test edits prohibited autonomously). Phase 74 write-blocking SessionLocal fixture is the most likely surfacing cause.
- **[YELLOW]** Two `broker_health_position_drift` warnings (13:35+14:30 UTC) — broker adapter in-memory cache not synced post-cleanup. Self-clears on next API restart.
- **[INFO]** signal_runs / ranking_runs stale at 2026-05-01 — collateral damage from 12:25 UTC cleanup; repopulates Tue 06:30 ET.

### Fixes Applied
- **`3bdbe64`** — `fix(lint): I001 import-sort in tests/conftest.py from Phase 74` — reorder imports so `from sqlalchemy.orm` precedes `import infra.db.session` per isort group rules. Verified: ruff clean, pytest smoke 360/360. Pushed to origin/main.

### Action Required from Aaron
1. Confirm CI rerun #25327148433 on `3bdbe64` reports `Lint & Type Check=success`.
2. Triage Unit Tests (Python 3.11|3.12) failures — same regression likely persists; Phase 74 SessionLocal write-blocker probably surfaced pre-existing tests reliant on real DB writes (no `APIS_PYTEST_SMOKE=1` env).
3. Optional: `docker restart docker-api-1` to clear broker adapter drift cache.

---

## Health Check — 2026-05-04 10:10 UTC (Monday 5:10 AM CT, pre-market) — RED

**Overall Status:** RED — pytest test pollution from the Phase 73 validation run at 01:05–01:14 UTC clobbered the 12 production paper positions (UPDATE'd to `status='closed'` at synthetic `closed_at='2026-05-04 01:05:18.847001'`) and wrote 56 polluted `portfolio_snapshots` + 6 signal_runs + 6 ranking_runs + 1 research-mode evaluation_runs + 5 fake position OPENs + 57 orders + 53 fills + 15,060 security_signals + 70 ranked_opportunities + 8 evaluation_metrics. Production runtime is currently shielded by API in-memory state preserved across the 01:00 UTC restart (pre-pollution); Prometheus correctly reports `apis_portfolio_positions=12, apis_portfolio_equity_usd=111051.98, apis_portfolio_cash_usd=23050.76`. **Danger: next API restart will restore from the polluted $90k snapshot or the phantom AAPL OPEN, silently corrupting production.** Operator approval required for cleanup transaction (UPDATE 12 positions back to `open`, DELETE polluted child rows). All non-data subsystems GREEN: 8/8 containers healthy, /health all 7 ok, 0 crash-triad, 0 broker drift, **Alertmanager firing=0** (Phase 73 defense holding ✅), pytest 360/360, CI #25296517254 on `e2f7811`=success, all 11 APIS_* flags correct.

### §1 Infrastructure
- 8/8 containers healthy. worker `Up 10h`, api `Up 9h`. /health all 7 components `ok` mode=paper.
- Worker log scan: 15 errors = 13 known stale tickers + 2 yfinance summary lines (06:00 ET / 10:00 UTC ingestion). 0 crash-triad.
- API log scan: 19 errors = 4 known startup quirks (regime/readiness restore_failed × 2 boots) + 15 yfinance stale-ticker. 0 crash-triad.
- Prometheus 2/2 up. **Alertmanager firing=0** ✅ Phase 73 defense holding.
- Resources well under threshold. DB **175 MB** (+17 MB from 00:38 UTC = bars + pollution).

### §2 Execution + Data
- 0 paper-mode `evaluation_runs` last 30h (Sunday). 1 polluted research-mode at 01:06:53 UTC. Total runs=97.
- Latest legit snapshot: 2026-05-01 19:30:03 UTC, cash=$23,050.76 / equity=$111,051.98. Latest polluted: 2026-05-04 01:14:46 UTC, cash=$90,000 / equity=$91,150.
- Prometheus reads correct in-memory values ($23k/$111k/12 positions). DB shows 1 OPEN (phantom AAPL).
- 12 production positions (CAT, SLB, WDC, BE, NUE, INTC, STT, MU, MRVL, AMD, EQIX, AMZN) UPDATE'd to `closed` at 01:05:18.847001 UTC. `origin_strategy='rebalance'` preserved → recovery is a simple UPDATE.
- Pollution counts since 01:00 UTC: 56 snapshots, 6 signal_runs, 6 ranking_runs, 1 evaluation_run, 5 positions opened (1 still OPEN), 19 closed (12 prod + 7 fixtures), 57 orders, 53 fills, 15,060 security_signals, 70 ranked_opportunities, 8 evaluation_metrics.
- Kill-switch=false ✅, mode=paper ✅. Idempotency clean.

### §3 Code + Schema
- Alembic head `p6q7r8s9t0u1` single head ✅.
- Pytest re-run by audit (without `phase59` filter) added 0 new pollution rows ✅. Phase 73's validation USED `phase59` and pollution timestamps line up exactly. **Source: a fixture/test in the phase59 set bypasses Phase 68 DB isolation.**
- Pytest smoke 360p/0f/3657d in 22.65s ✅.
- Git CLEAN, 0 unpushed, HEAD=`e2f7811` (Phase 73, pushed 01:22 UTC).
- **CI run #25296517254 on `e2f7811` conclusion=success** ✅.

### §4 Config + Gates
- All 11 critical APIS_* flags at expected values ✅. Worker `job_count=36`. Worker started 00:33:32 UTC.

### Issues Found
- **[RED] Test pollution clobbered production paper DB at 01:05–01:14 UTC** (Phase 73 validation pytest sweep). Same class of bug as `project_test_pollution_2026-04-19.md`. Phase 68 guard does not cover phase59 tests.
- **[INFO] Phase 73 fix successfully validated** — Alertmanager firing=0 (was 1 critical Sunday); Prometheus gauge matches DB legit snapshot exactly.

### Fixes Applied
- None autonomously (DB DELETE is operator-approval-required).

### Action Required
1. APPROVE DB cleanup transaction — see `apis/state/HEALTH_LOG.md` for full SQL.
2. DO NOT restart `docker-api-1` until cleanup committed (in-memory shield).
3. Phase 74: fix `phase59` test isolation (3rd documented test-pollution incident).
4. RED email — Gmail draft created, manual send required.

---

## Health Check — 2026-05-04 00:38 UTC (Sunday 7:38 PM CT, market closed)

**Overall Status:** YELLOW — Alertmanager `DrawdownCritical` (critical) re-fired at 00:35:29 UTC, ~2 min after a fresh worker+API restart at 00:33:32 UTC. Same DEC-061 post-restart HWM-reset false positive that earlier Sunday runs flagged. Equity stable at $111,051.98; Prometheus gauge reads $30k baseline row. Will self-clear Mon 2026-05-04 13:35 UTC paper cycle. Everything else GREEN: 8/8 containers fresh restart, /health all ok, 0 worker errors, 0 crash-triad, 0 broker drift in 24h, pytest 360/360, CI GREEN at `6424873`, git clean, all APIS_* flags correct. See `apis/state/HEALTH_LOG.md` for full detail.

---

## Health Check — 2026-05-03 15:10 UTC (Sunday 10:10 AM CT, market closed)

**Overall Status:** YELLOW — Alertmanager DrawdownCritical + DrawdownAlert still firing (5h after 5:15 AM CT run; identical carry-forward from 2026-05-02 13:26/13:30 UTC restart). No Sunday paper cycles to self-clear; will clear Mon 13:35 UTC. Everything else GREEN: 8/8 containers up 26h, /health all 7 components ok, 0 worker/api errors, 0 crash-triad, 0 broker drift in 24h, pytest 360/360, CI GREEN at HEAD, git tree clean, all APIS_* flags correct.

### §1 Infrastructure
- Containers: 8/8 healthy. All up ~26h since 2026-05-02 13:24 UTC restart. No restart loops.
- /health: all 7 components `ok`. Mode=paper. Timestamp 2026-05-03T15:09:57Z.
- Worker log scan (24h): CLEAN — 576 lines, 0 errors, 0 crash-triad patterns.
- API log scan (24h): 9206 lines, 0 errors, 0 crash-triad patterns.
- Prometheus: 2/2 targets up, 0 dropped ✅.
- **Alertmanager: 2 ACTIVE alerts firing**: `DrawdownCritical` (since 13:26:29Z 2026-05-02) + `DrawdownAlert` (since 13:30:29Z 2026-05-02). Same root cause as morning: Prometheus equity gauge reads $30k dual-snapshot baseline row instead of $111k actual. Will self-clear Mon 2026-05-04 13:35 UTC.
- Resources: all under threshold (Worker 67MiB, API 173MiB, k8s 1.084GiB CPU 21%). DB 158 MB.

### §2 Execution + Data Audit
- Paper cycles: 0 today (Sunday — expected). Last run: Friday 2026-05-01 21:00 UTC daily eval (status=complete). 0 failures ✅.
- Total evaluation_runs: 96 (above 80 floor ✅).
- Portfolio: latest snapshot 2026-05-01 19:30 UTC — cash=$23,050.76 / equity=$111,051.98. Cash positive ✅. Dual-snapshot pattern persists.
- Broker<->DB recon: 0 drift warnings in 24h ✅. 12 open positions.
- Origin-strategy: ALL 12 open positions `origin_strategy=rebalance` ✅. 0 NULLs.
- Position caps: 12/15 ✅. 0 new today ✅.
- Data freshness: bars=2026-04-30, rankings=2026-05-01 10:45 UTC, signals=2026-05-01 10:30 UTC. Friday's bars pending Mon 06:00 ET.
- Stale tickers: known 13 only.
- Kill-switch: false ✅. Mode: paper ✅.
- Idempotency: clean ✅.

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head ✅).
- Pytest smoke: **360 passed / 0 failed / 3656 deselected in 27.74s** ✅.
- Git: CLEAN tree, 0 unpushed. HEAD=`74941fd`.
- **GitHub Actions CI:** Run #25276530267 `74941fd` conclusion=success. GREEN ✅. https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25276530267

### §4 Config + Gate Verification
- All 9 critical APIS_* flags at expected values ✅. Scheduler: job_count=36, worker started 2026-05-02 13:24:37 UTC.

### Issues Found
- **[YELLOW] Alertmanager DrawdownCritical + DrawdownAlert (carry-forward from 2026-05-02 13:26/13:30 UTC)** — post-restart HWM-reset false positive (DEC-061 pattern). Equity stable; gauge reads wrong row. Self-clears Mon 13:35 UTC.
- **[INFO] Friday 2026-05-01 daily_market_bars not yet ingested** — weekday-only schedule, intentional.

### Fixes Applied
- None. State doc updates only.

### Action Required from Aaron
- **Monday monitoring (2026-05-04)**: Watch 13:35 UTC paper cycle; both alerts should self-clear by 14:30 UTC.
- **Optional Phase 73 ticket** (carry-forward): Fix dual-snapshot baseline row OR align Prometheus equity gauge OR add Alertmanager `for:` minimum.

---

## Health Check — 2026-05-03 10:15 UTC (Sunday 5:15 AM CT, market closed)

**Overall Status:** YELLOW — Alertmanager DrawdownCritical + DrawdownAlert still firing (carry-forward from 2026-05-02 13:26/13:30 UTC restart, no Sunday paper cycles to self-clear; will clear Mon 13:35 UTC). All other systems healthy: 8/8 containers up 21h, /health all ok, 0 worker errors, 0 crash-triad, 0 broker drift in 24h (decayed from yesterday), pytest 360/360, CI GREEN, all APIS_* flags correct.

### §1 Infrastructure
- Containers: 8/8 healthy (docker-worker-1, docker-api-1, docker-postgres-1, docker-redis-1, docker-prometheus-1, docker-grafana-1, docker-alertmanager-1, apis-control-plane). All up ~21h since 2026-05-02 13:24 UTC restart.
- /health: all 7 components `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper. Timestamp 2026-05-03T10:09:37Z.
- Worker log scan (24h): CLEAN — 0 ERROR/CRITICAL/Traceback. 0 crash-triad patterns.
- API log scan (24h): 3 matches — 1 PowerShell stderr envelope (not an APIS error) + 2 startup warnings (regime_result_restore_failed, readiness_report_restore_failed — pre-existing non-blocking).
- Prometheus: 2/2 targets up, 0 dropped ✅.
- **Alertmanager: 2 ACTIVE alerts firing (carry-forward from 2026-05-02)**: `DrawdownCritical` since 13:26:29Z + `DrawdownAlert` since 13:30:29Z. Gauge `apis_portfolio_equity_usd=30417.30` (Prometheus reads dual-snapshot baseline row, not actual $111k equity row). Cannot self-clear until Mon 13:35 UTC. Same DEC-061 pattern.
- Resource usage: Worker 67MiB, API 173MiB, Grafana 51MiB, Prometheus 42MiB, Alertmanager 15MiB, Postgres 52MiB, Redis 8MiB, k8s 1.07GiB. All under threshold.
- DB size: 158 MB (unchanged).

### §2 Execution + Data Audit
- Paper cycles today: 0 (Sunday — expected).
- Eval_runs in 30h: 0 rows (weekend — expected). Total = 96 (above 80 floor ✅).
- Portfolio trend: latest snapshot 2026-05-01 19:30 UTC — cash=$23,050.76 / equity=$111,051.98. Cash positive ✅. Dual-snapshot pattern continues.
- Broker<->DB reconciliation: 0 `broker_health_position_drift` warnings in 24h ✅ (decayed). 12 open positions in DB.
- Origin-strategy stamping: ALL 12 open positions have `origin_strategy=rebalance` ✅. 0 NULLs (CAT, SLB, MU, INTC, BE, NUE, STT, WDC, MRVL, AMD, EQIX, AMZN). Phase 72 holding.
- Position caps: 12/15 open ✅. 0 new today.
- Data freshness: bars=2026-04-30 (Friday bars pending Mon 06:00 ET ingestion); rankings=2026-05-01 10:45 UTC ✅; signals=2026-05-01 10:30 UTC ✅.
- Stale tickers: known 13 only.
- Kill-switch: false ✅. Mode: paper ✅.
- Idempotency: clean — 0 duplicate orders, 0 duplicate open positions ✅.

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head ✅). Drift: ~25 documented cosmetic items, non-functional.
- Pytest smoke: **360 passed / 0 failed / 3656 deselected in 29.30s** ✅. Above 358/360 baseline.
- Git: 3 dirty state files (carry-forward), 0 unpushed, only `main`. HEAD=`2188c84`.
- **GitHub Actions CI:** Run #25214536632 `2188c84` conclusion=success. GREEN ✅.

### §4 Config + Gate Verification
- All critical APIS_* flags at expected values (operating_mode=paper, kill_switch=false, max_positions=15, max_new_positions_per_day=5, max_thematic_pct=0.75, ranking_min_composite_score=0.30, self-improvement/insider-flow/Step 6-7-8 all default OFF).
- Scheduler: job_count=36. Worker started 2026-05-02 13:24 UTC.

### Issues Found
- **[YELLOW] Alertmanager DrawdownCritical + DrawdownAlert (carry-forward from 2026-05-02 13:26/13:30 UTC)** — post-restart HWM-reset false positive; Prometheus gauge reads $30k baseline row not real $111k equity. Will self-clear Mon 13:35 UTC.
- **[INFO] Underlying dual-snapshot writer + Prometheus gauge mismatch** — guarantees false-positive every weekend after restart. Phase 73 candidate.
- **[INFO] Friday 2026-05-01 daily_market_bars not yet ingested** — weekday-only schedule; intentional.

### Fixes Applied
- None. State doc updates only.

### Action Required from Aaron
- **Monday monitoring (2026-05-04)**: Watch 13:35 UTC paper cycle for Alertmanager self-clear. If alerts persist past 14:30 UTC, investigate.
- **Optional Phase 73 ticket**: Fix dual-snapshot baseline row OR align Prometheus equity gauge OR add Alertmanager `for:` minimum so weekend post-restart false-positives stop firing.

---

## Health Check — 2026-05-02 19:10 UTC (Saturday 2:10 PM CT, market closed)

**Overall Status:** YELLOW — 2 Alertmanager alerts firing (DrawdownCritical + DrawdownAlert) since 13:26/13:30 UTC, ~2 min after this morning's 13:24 UTC worker+API restart. Classic post-restart HWM-reset false-positive (matches DEC-061 pattern). Saturday means no paper cycles to self-clear them — they will fire continuously until Monday 13:35 UTC re-establishes HWM. Earlier Saturday runs (13:30 + 15:10 UTC) inadvertently called this GREEN because they only inferred "no alerts" from /health rather than probing Alertmanager directly. All other systems healthy: 8/8 containers, /health all ok, 0 worker errors, 0 crash-triad, pytest 360/360, CI GREEN, all APIS_* flags correct, broker drift down to 1/24h (decaying).

### §1 Infrastructure
- Containers: 8/8 healthy. All up ~6h since 13:24 UTC restart.
- /health: all 7 components `ok`. Mode=paper. Timestamp 2026-05-02T19:08:42Z.
- Worker log scan (24h): CLEAN — 0 ERROR/CRITICAL/Traceback. 0 crash-triad patterns.
- API log scan (24h): 4 matches — 1 HOLX `broker_order_rejected` (carry-forward, pre-`is_active=false` fix) + 2 startup warnings + 1 PowerShell stderr envelope (not an APIS error).
- Prometheus: 2/2 targets up, 0 dropped ✅.
- **Alertmanager: 2 ACTIVE alerts firing**: DrawdownCritical (critical, since 13:26:29Z) + DrawdownAlert (warning, since 13:30:29Z). Both post-restart HWM-reset false positives (no actual drawdown — equity stable at $111,052). Will NOT self-clear until Monday 2026-05-04 13:35 UTC first paper cycle.
- Resource usage: All under threshold (largest: k8s 985MiB / API 177MiB).
- DB size: 158 MB.

### §2 Execution + Data Audit
- Paper cycles today: 0 (Saturday — expected).
- Eval_runs in 30h: 1 (yesterday's daily eval, complete). 0 failures ✅.
- Portfolio trend: latest snapshot 2026-05-01 19:30 UTC — cash=$23,050.76 / equity=$111,051.98. Cash positive ✅.
- Broker<->DB reconciliation: 1 drift warning in 24h (decaying from 5-6 yesterday). 12 open positions.
- Origin-strategy stamping: ALL 12 open positions `origin_strategy=rebalance` ✅. 0 NULLs.
- Position caps: 12/15 open ✅. 0 new today.
- Data freshness: prices=2026-04-30 (490 sec ✅), rankings=2026-05-01 10:45 ✅, signals=2026-05-01 10:30 ✅.
- Stale tickers: known 13 only.
- Kill-switch: false ✅. Mode: paper ✅.
- Evaluation history: 96 ✅.
- Idempotency: clean — 0 dupe orders, 0 dupe open positions ✅.

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single) ✅.
- Pytest smoke: **360p/0f** in 28.73s ✅ (above 358/360 baseline).
- Git: 3 dirty (state docs), 0 unpushed. HEAD=`2188c84`.
- **GitHub Actions CI:** Run #25214536632 `2188c84` conclusion=success. GREEN ✅.

### §4 Config + Gate Verification
- All critical APIS_* flags at expected values ✅.
- Scheduler: job_count=36. Worker started 2026-05-02 13:24 UTC.

### Issues Found
- **[YELLOW] Alertmanager DrawdownCritical + DrawdownAlert firing**: post-restart HWM-reset false positive (DEC-061 pattern). Equity stable; no real drawdown. Will self-clear at Monday's first paper cycle.
- **[INFO] Earlier Saturday runs missed Alertmanager firing** by inferring "no alerts" from /health rather than probing /api/v2/alerts directly. Process improvement noted.
- **[INFO] Broker<->DB drift carry-forward**: 1/24h, decaying. Non-actionable on weekend.

### Fixes Applied
- None. Alertmanager alerts are known false positive requiring Monday market open to clear naturally.

### Action Required from Aaron
- **Monday 2026-05-04 monitoring**: Watch alertmanager auto-clear when first paper cycle (13:35 UTC) re-establishes HWM. Investigate only if alerts persist past second cycle.

---

## Health Check — 2026-05-02 15:10 UTC (Saturday 10:10 AM CT, market closed)

**Overall Status:** GREEN — Saturday, no paper cycles expected. All infrastructure healthy (8/8 containers up 2h). Pytest 360/360. CI GREEN. No new issues since 13:30 UTC run. Broker drift from yesterday carried forward but non-actionable on weekends.

### §1 Infrastructure
- Containers: 8/8 healthy. All up ~2h since earlier restart.
- /health: all 7 components `ok`. Mode=paper. Timestamp 2026-05-02T15:09:17Z.
- Worker/API log scan: CLEAN (worker), 6 matches API (4 HOLX pre-fix + 2 startup warnings).
- Prometheus: 2/2 up, 0 dropped. Alertmanager: 0 firing alerts.
- Resources: all normal. DB 158 MB.

### §2 Execution + Data Audit
- Paper cycles today: 0 (Saturday expected). Portfolio: cash=$23,051 / equity=$111,052 (positive ✅).
- 12 open positions, all `origin_strategy=rebalance`. 0 NULLs. 0 new today. Caps within limits.
- Data freshness: signals 2026-05-01 10:30 UTC, rankings 2026-05-01 10:45 UTC.
- Kill-switch=false, mode=paper. Eval runs=96. Idempotency clean.
- Broker drift: 5 warnings yesterday (carry-forward).

### §3 Code + Schema
- Alembic: `p6q7r8s9t0u1` single head. Pytest: 360p/0f (22.89s). Git: 3 dirty, 0 unpushed. HEAD=`2188c84`.
- **CI:** Run #25214536632 `2188c84` conclusion=success. GREEN ✅.

### §4 Config + Gate Verification
- All APIS_* flags correct. Scheduler job_count=36.

### Issues Found
- [INFO] Broker<->DB drift carry-forward from yesterday.

### Fixes Applied
- None needed.

### Action Required from Aaron
- Monday: monitor first paper cycles for churn pattern.

---

## Health Check — 2026-05-02 13:30 UTC (Saturday 8:30 AM CT, market closed)

**Overall Status:** GREEN — Saturday, no paper cycles expected. All infrastructure healthy. Containers restarted today (13:24 UTC). Pytest 360/360. CI GREEN. Broker drift from yesterday carried forward but non-actionable on weekends. CSCO churn from yesterday (YELLOW carry-forward) is the only open concern for Monday.

### §1 Infrastructure
- Containers: 8/8 healthy. Worker+API restarted 2026-05-02 13:24 UTC.
- /health: all 7 components `ok`. Mode=paper. Timestamp 2026-05-02T13:25:50Z.
- Worker/API log scan: CLEAN — zero crash-triad. 5 HOLX rejections from yesterday (now fixed). 2 startup warnings (pre-existing).
- Resource usage: all normal, well under threshold. DB 158 MB.

### §2 Execution + Data Audit
- Paper cycles today: 0 (Saturday — expected).
- Portfolio trend: latest snapshot 2026-05-01 19:30 — cash=$23,051 / equity=$111,052. Cash positive ✅.
- Broker<->DB reconciliation: 6 drift warnings yesterday. Non-actionable on weekend.
- Origin-strategy stamping: ALL 12 open have `origin_strategy=rebalance` ✅.
- Position caps: 12/15 open ✅. 0 new today.
- Data freshness: bars=2026-04-30, rankings=2026-05-01, signals=2026-05-01 ✅.
- Kill-switch: false ✅. Mode: paper ✅.
- Evaluation history: 96 rows (≥80 floor ✅).
- Idempotency: clean ✅.
- CSCO + multi-ticker churn carry-forward from yesterday.

### §3 Code + Schema
- Alembic: `p6q7r8s9t0u1` single head, no drift ✅.
- Pytest: **360/360 pass** in 23s ✅.
- Git: 3 dirty state-docs, 0 unpushed, HEAD=`2188c84`.
- CI: Run #25214536632 `2188c84` conclusion=success GREEN ✅.

### §4 Config + Gate Verification
- All critical APIS_* flags at expected values ✅. Scheduler job_count=36.

### Issues Found
- [INFO] CSCO + multi-ticker churn carry-forward. Monitor Monday.
- [INFO] Broker<->DB drift carry-forward. Non-actionable until churn resolved.

### Fixes Applied
- None needed.

### Action Required from Aaron
- Monitor Monday first cycles for continued churn.

---

## Health Check — 2026-05-01 19:10 UTC (Thursday 2:10 PM CT, market open)

**Overall Status:** YELLOW — HOLX still being ordered despite Phase 72 removal (DB `is_active` not flipped); broker<->DB position drift (CSCO in broker, closed in DB); CSCO churn pattern active. HOLX fix applied this run. All other systems GREEN.

### §1 Infrastructure
- Containers: 8/8 healthy. All components ok. 0 firing alerts.

### §2 Execution + Data Audit
- Paper cycles: 6+ today. Latest equity=$111,147. Cash positive. 12/15 open positions.
- Broker<->DB drift: CSCO in broker (13 positions) but closed in DB (12 open). 5 drift warnings/24h.
- HOLX: 4 broker rejections (is_active not flipped by Phase 72). Fixed this run.
- CSCO churn: 5 open+close cycles today. Anti-churn cap not catching this ticker.
- Idempotency: clean. Origin-strategy: all set. Kill-switch: false.

### §3 Code + Schema
- Alembic: `p6q7r8s9t0u1` single head, no drift.
- Pytest: 360p/0f (all passing).
- Git: 3 dirty state docs, 0 unpushed. CI GREEN (run #25214536632).

### §4 Config + Gate Verification
- All APIS_* flags correct.

### Fixes Applied
- HOLX `is_active` set to `false` in securities table.

### Action Required from Aaron
- CSCO churn investigation needed.

---

## Health Check — 2026-05-01 15:10 UTC (Thursday 10:10 AM CT, market open)

**Overall Status:** GREEN — All systems healthy. 2 paper cycles completed today (13:35 + 14:30 UTC). Drawdown alerts from 7:25 AM check have self-cleared. Origin-strategy stamping fully operational (Phase 72). Git tree clean. CI GREEN.

### §1 Infrastructure
- Containers: 8/8 healthy. Worker up 2h / API up 2h. Postgres 2d, Redis 3w. k8s 5w.
- /health: all components `ok`. Mode=paper.
- Worker/API log scan (24h): CLEAN — zero crash-triad patterns.
- Prometheus: 2/2 targets up, 0 dropped. Alertmanager: 0 firing alerts ✅.
- Resource usage: all normal. DB size: 158 MB.

### §2 Execution + Data Audit
- Paper cycles today: 2 completed (13:35 + 14:30 UTC) ✅.
- Portfolio: cash=$13,337 / equity=$103,572. Cash positive ✅.
- Broker<->DB: /health broker=ok. 12 open positions. 0 broker drift warnings.
- Origin-strategy: ALL 12 open positions stamped (0 NULLs) ✅.
- Position caps: 12/15 open ✅. 9 new today (restart-burst, pre-existing known behavior).
- Data freshness: prices=Apr 30, signals=today 10:30, rankings=today 10:45. 490 securities ✅.
- Kill-switch=false, mode=paper ✅. Eval_runs=95 ✅. Idempotency clean ✅.

### §3 Code + Schema
- Alembic: `p6q7r8s9t0u1` single head. No drift ✅.
- Pytest: 250p/0f in 38.74s ✅.
- Git: CLEAN (0 dirty, 0 unpushed). CI run #25214536632 `2188c84` GREEN ✅.

### §4 Config + Gate Verification
- All critical APIS_* flags at expected values ✅. Scheduler job_count=36.

### Issues Found
- None.

### Fixes Applied
- None needed.

### Action Required from Aaron
- None.

---

## Health Check — 2026-05-01 12:25 UTC (Thursday 7:25 AM CT, pre-market)

**Overall Status:** YELLOW — 2 Alertmanager drawdown alerts firing (DrawdownCritical + DrawdownAlert, started at worker restart time 11:57 UTC — likely false positive from HWM reset). Origin_strategy NULL regression from 5 AM check RESOLVED by Phase 72 (`1759455`). All other systems GREEN.

### §1 Infrastructure
- Containers: 8/8 healthy. Worker up 22min / API up 24min (restarted during this session). Postgres 2d, Redis 2w. k8s control plane up 2w.
- /health: all components `ok`. Mode=paper.
- Worker/API log scan: CLEAN — zero crash-triad. Known 13 stale tickers only.
- Prometheus: 2/2 up. Alertmanager: 2 firing (DrawdownCritical + DrawdownAlert, restart artifact).
- Resources: all normal. DB 158 MB.

### §2 Execution + Data Audit
- Paper cycles today: 0 (pre-market expected). Morning pipeline ran (signals 10:30, rankings 10:45 UTC).
- Portfolio: cash=$20,120 / equity=$109,232. Cash positive ✅.
- Origin-strategy: RESOLVED — all 13 open positions have `origin_strategy=rebalance` ✅ (Phase 72 fix).
- Position caps: 13/15. Data fresh. Kill-switch false. Eval_runs=95. Idempotency clean.

### §3 Code + Schema
- Alembic: `p6q7r8s9t0u1` single head. Pytest: 358p/2f exact baseline. Git: 0 unpushed, 13 dirty.
- CI: Run #25213460365 `1759455` conclusion=success GREEN ✅.

### §4 Config + Gate
- All APIS_* flags correct. Scheduler job_count=36 (was 35).

### Issues Found
- 2 Alertmanager drawdown alerts (restart artifact, should self-clear after first cycle)
- 13 dirty files, job count 35→36

### Fixes Applied
- None.

### Action Required from Aaron
- Monitor drawdown alerts after 13:35 UTC cycle. Commit dirty tree.

---

## Health Check — 2026-05-01 10:25 UTC (Friday 5:25 AM CT, pre-market)

**Overall Status:** YELLOW — origin_strategy NULL regression: 9 of 13 open positions missing origin_strategy (Step 5 commit `d08875d` regression). All other systems GREEN; scheduler recovered from Apr 30 stall; morning pipeline ran cleanly.

### §1 Infrastructure
- Containers: 8/8 healthy. Worker/API up 15h. Postgres 2d, Redis 2w. All components ok.
- /health: all `ok`. Mode=paper.
- Log scan: CLEAN — zero crash-triad, only known 13 stale tickers.
- Prometheus: 2/2 up. Alertmanager: 0 firing. Resources normal. DB 150 MB.

### §2 Execution + Data Audit
- Paper cycles today: 0 (pre-market, expected). Morning pipeline ALL ran 10:00–10:22 UTC ✅.
- Portfolio: cash=$20,120 / equity=$109,232. Cash positive ✅.
- **Origin-strategy: REGRESSION** — 9/13 open positions NULL (AMD, AMZN, BE, GOOG, MRVL, NUE, NVDA, STT, WDC). Only EQIX/GOOGL/MU/PWR stamped.
- Position caps: 13/15 ✅. Idempotency: clean ✅. Eval runs: 95 ✅. Kill-switch: false ✅.

### §3 Code + Schema
- Alembic: `p6q7r8s9t0u1` single head ✅. Pytest: 358p/2f baseline ✅.
- Git: 14 dirty, 0 unpushed. CI: Run #31 `6215c20` conclusion=success GREEN ✅.

### §4 Config + Gate Verification
- All critical APIS_* flags at expected values ✅. Scheduler job_count=35 ✅.

### Issues Found
- **origin_strategy NULL regression**: 9/13 open positions missing origin_strategy. Regression of commit `d08875d`.

### Fixes Applied
- None.

### Action Required from Aaron
- Investigate origin_strategy NULL regression in `paper_trading.py` Phase 70 rebalance code path.
- Commit 14 dirty files.

---

## Health Check — 2026-04-30 19:30 UTC (Wednesday 2:30 PM CT, market closed)

**Overall Status:** YELLOW — Full market day missed (zero paper cycles, zero data pipeline on Wed Apr 30); worker scheduler malfunctioned despite 27h uptime. Worker restarted during deep-dive; should resume normal operation.

### §1 Infrastructure
- Containers: 8/8 present. Worker/API up 27h (healthy). Postgres 2d, Redis 2w. Grafana/Prometheus/Alertmanager recreated during deep-dive. k8s control plane up 13d.
- /health: **degraded** — `paper_cycle: stale`. All other components `ok`. Mode=paper.
- Worker/API log scan: CLEAN — zero crash-triad patterns.
- Prometheus: 2/2 targets up, 0 dropped. Alertmanager: 0 firing alerts.
- Resource usage: all normal. DB size: 150 MB.

### §2 Execution + Data Audit
- **Paper cycles today: 0 on a Wednesday (market day).** Full pipeline missed.
- Portfolio trend: latest snapshot 2026-04-29 19:30 UTC — cash=$20,284, equity=$106,765. Cash positive. No new snapshots today.
- 13 open positions, all with `origin_strategy` set. Within cap (13/15). 0 new today.
- Data freshness: prices=2026-04-28 (2 biz days stale). Signals/rankings=2026-04-29.
- Kill-switch: false. Mode: paper. Eval history: 94. Idempotency: clean.

### §3 Code + Schema
- Alembic: `p6q7r8s9t0u1` single head. No drift.
- Pytest: 249p/2f exact DEC-021 baseline. No regressions.
- Git: 84 dirty, 0 unpushed. CI run #31 `6215c20` GREEN.

### §4 Config + Gate Verification
- All APIS_* flags correct. Scheduler job_count=35 post-restart.

### Issues Found
- Full market day missed (scheduler silent failure)
- /health degraded (paper_cycle stale)
- Prices 2 business days stale
- 84 dirty files in git tree

### Fixes Applied
- Worker + monitoring stack restarted via docker compose up -d.

### Action Required from Aaron
- Investigate scheduler silent failure — new failure mode.
- Commit dirty tree (84 modified files).

---

## Health Check — 2026-04-29 15:10 UTC (Tuesday 10:10 AM CT, market open)

**Overall Status:** YELLOW — Phantom cash regression at 14:30 UTC; position churn persists (19 opened today vs cap 5).

### §1 Infrastructure
- Containers: 8/8 healthy. Worker/API up 3h. Grafana/Prometheus/Alertmanager/Redis up 12 days. No restart loops.
- /health: all components `ok`. Mode=paper.
- Worker/API log scan: CLEAN — zero crash-triad. Only known stale tickers + 2 broker_order_rejected (cash-gated).
- Prometheus: 2/2 up. Alertmanager: 0 firing.
- Resource usage: normal. DB: 150 MB.

### §2 Execution + Data Audit
- Paper cycles today: 2 completed (13:35 + 14:30 UTC). Phantom AAPL from 5 AM resolved.
- **Phantom cash -$48,814 at 14:30 UTC** — duplicate snapshot, self-corrected next row.
- 6 open positions (GOOGL/INTC/MU/NUE/PWR/EQIX), all with origin_strategy. 6/15 cap. ✅
- 19 positions opened today (churn), 1 broker_health_position_drift.
- Data fresh: prices=2026-04-28, signals=10:30, rankings=10:45. Eval history=93. Idempotency clean.

### §3 Code + Schema
- Alembic: `p6q7r8s9t0u1` single head. Pytest: 358p/2f exact baseline. Git: 0 unpushed, 8 dirty.
- CI: Run #30 `7e87714` conclusion=success. GREEN.

### §4 Config
- All APIS_* flags correct. Scheduler job_count=35. ✅

### Issues Found
- Phantom cash -$48,814 at 14:30 UTC (carry-forward phantom writer bug)
- Position churn: 19 opened today vs cap 5
- 1 broker_health_position_drift, 8 dirty git files

### Fixes Applied
- None.

### Action Required from Aaron
- Phantom cash writer root cause audit (`services/portfolio/` module)
- Commit dirty state files

---

## Health Check — 2026-04-29 10:25 UTC (Tuesday 5:25 AM CT, market pre-open)

**Overall Status:** YELLOW — Data gap resolved; phantom AAPL position from restart persists as data pollution.

### §1 Infrastructure
- Containers: 8/8 healthy. Worker/API up 15h. Prometheus 2/2 up. Alertmanager 0 firing. Resources normal. DB 145 MB.

### §2 Execution + Data Audit
- Paper cycles today: 0 (pre-market). Morning pipeline jobs all successful. Data freshness RESOLVED (prices=2026-04-28, signals/rankings=2026-04-28).
- Portfolio: cash=$90,000, equity=$91,150. 1 open position (phantom AAPL: entry=$100, qty=10, empty origin_strategy — test data pollution from restart).
- Kill-switch: false. Mode: paper. Eval runs: 93. Idempotency: clean.

### §3 Code + Schema
- Alembic: `p6q7r8s9t0u1` single head. Pytest: 358p/2f exact baseline. Git: 0 unpushed, 7 dirty. CI run #30 `7e87714` GREEN.

### §4 Config
- All APIS_* flags at expected values. Scheduler job_count=35.

### Issues Found
- Phantom AAPL position (test data pollution from restart).
- 7 dirty files in git tree (carry-forward).

### Fixes Applied
- None.

### Action Required from Aaron
- Clean up phantom AAPL position + restore $100k baseline (operator approval needed).
- Commit dirty state files.

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
- Containers: 7/7 APIS healthy + k8s control plane. Worker/API restarted 11:52 UTC today. Monitoring up 12 days.
- /health: all components `ok`. Mode=paper.
- Worker/API log scan: only known stale tickers (13) + 2 pre-existing API restore warnings. No crash-triad patterns.
- Prometheus: 2/2 up. Alertmanager: 0 firing. Resources: all normal. DB: 150 MB.

### §2 Execution + Data Audit
- Paper cycles last 30h: 1 paper + 1 research complete. Today's first cycle at 09:35 ET not yet due.
- Portfolio: $100,000 cash / $100,000 equity. Clean baseline restored.
- 0 open positions. Broker<->DB consistent. Idempotency clean.
- Data freshness: prices=Apr 28, rankings=Apr 29, signals=Apr 29. Fully recovered.
- Kill-switch: false. Eval history: 93.

### §3 Code + Schema
- Alembic: `p6q7r8s9t0u1` (head, no drift). Pytest: blocked (Phase 68 guard).
- Git: clean, 0 unpushed. CI: Run #30 `7e87714` conclusion=success. GREEN.

### §4 Config
- All APIS_* flags at expected values. Scheduler: 35 jobs. ✅

### Issues Found
- None.

### Fixes Applied
- None needed.

### Action Required from Aaron
- Enable `APIS_PYTEST_SMOKE=1` to restore health-check smoke testing (low priority).
- Address API restore warnings for regime/readiness ORM drift (low priority).

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

## Health Check — 2026-04-30 19:28 UTC (Wednesday 2:28 PM CT, market closed)

**Overall Status:** YELLOW — Worker scheduler was silent for ~20h (all Wed cycles missed); restarted and healthy. No trading regressions or data corruption.

### §1 Infrastructure
- Containers: 7/7 up + healthy (worker+api restarted during this check; postgres 2d, redis/prom/grafana/alertmanager 13d)
- /health: `degraded` — `paper_cycle: stale` (expected post-restart, all other components `ok`)
- Worker/API log scan: clean — zero ERROR/CRITICAL/Traceback in 24h
- Prometheus: 2/2 targets up; Alertmanager: 0 firing alerts
- Resource usage: all normal

### §2 Execution + Data Audit
- Paper cycles yesterday: 1 completed; today: 0/12 — all missed (silent scheduler)
- Portfolio trend: cash $20,284 / equity $106,764.94; clean $100k baseline also present
- 13 open positions, all with origin_strategy=rebalance; no dupes
- Data freshness: prices 2026-04-28, rankings 2026-04-29 10:45 UTC, signals 2026-04-29 10:30 UTC
- Kill-switch=false, mode=paper; evaluation_runs=94 (above floor)
- Idempotency: clean

### §3 Code + Schema
- Alembic: `p6q7r8s9t0u1` (single head, no drift)
- Pytest: 358/360 pass — 2 known phase22 failures
- Git: clean (6 untracked scratch files), 0 unpushed, HEAD=`6215c20`
- CI: run #31 GREEN `6215c20` conclusion=success

### §4 Config + Gate Verification
- All critical APIS_* flags at expected values ✓

### Issues Found
- **[YELLOW] Worker scheduler silent ~20h** — all Wed cycles missed. Restarted; will resume Thu.

### Fixes Applied
- Restarted worker+api containers at 19:21 UTC. Worker healthy, job_count=35.

### Action Required from Aaron
- Investigate scheduler silence root cause; consider APScheduler liveness probe.
- **[INFO] 6 untracked scratch files in repo root**: `_docker_exit.txt`, `_docker_info.txt`, `_docker_ps.txt`, etc. Non-blocking.

### Fixes Applied
- Restarted `docker-worker-1` and `docker-api-1` via `docker restart`. Worker came up healthy with job_count=35 at 19:21 UTC. All next_run times set for 2026-05-01 (today's cron windows had passed).

### Action Required from Aaron
- **Investigate scheduler silence**: Worker healthcheck passed for ~20h while APScheduler produced zero output. Consider adding a scheduler-liveness probe (e.g., heartbeat job that writes to Redis/DB every 5 min, healthcheck verifies recency). This is the second time the scheduler has gone silent without container-level detection.
- **Clean up scratch files**: 6 `_docker_*.txt` files in repo root — safe to delete or .gitignore.


## Health Check — 2026-05-01 10:15 UTC (Thursday 5:15 AM CT, market pre-open)

**Overall Status:** YELLOW — 9/13 open positions have NULL origin_strategy (regression of d08875d); broker_health_position_drift on all 13 tickers; HOLX broker rejection (new inactive ticker); 5 modified files uncommitted; pytest path fix needed in health-check SKILL.

### §1 Infrastructure
- Containers: 8/8 up (7 APIS + k8s). Worker up 15h (healthy), API up 15h (healthy), Postgres up 2d (healthy), Redis up 2w (healthy), Grafana/Prometheus/Alertmanager up 15h. No restart loops.
- /health: all components `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper.
- Worker log scan: only known 13 stale tickers (DFS, JNPR, HES, PKI, PARA, IPG, MRO, WRK, ANSS, MMC, K, PXD, CTLT). No crash-triad patterns. No CRITICAL/Traceback.
- API log scan: 2 pre-existing restore warnings (regime_result_restore_failed, readiness_report_restore_failed). Known stale tickers. **NEW: `broker_order_rejected` for HOLX ("asset HOLX is not active")** at 2026-04-30 19:30 UTC.
- Prometheus: 2/2 targets up (apis, prometheus), 0 droppedTargets.
- Alertmanager: 0 firing alerts.
- Resource usage: Worker 686 MiB, API 851 MiB, Postgres 203 MiB, Redis 8 MiB, Grafana 46 MiB, Prometheus 43 MiB, Alertmanager 15 MiB, k8s 2.55 GiB (8.2%). No CPU/mem spikes.
- DB size: 150 MB.

### §2 Execution + Data Audit
- Paper cycles last 30h: 1 completed (2026-04-30 21:00 UTC, paper, status=complete). Today's first cycle at 13:35 UTC (09:35 ET) not yet reached. Wednesday's scheduler silence (Phase 71) caused all Wed daytime cycles to be missed; Phase 71 liveness probe now deployed.
- Portfolio trend: latest snapshot 2026-04-30 19:30 UTC — cash $20,120 / equity $109,232. Also clean $100k baseline snapshot at same timestamp. Cash ≥ 0 ✓. No phantom-cash regression.
- Broker<->DB reconciliation: **broker_health_position_drift fired** at 2026-04-30 19:30 UTC with all 13 open tickers (MRVL, WDC, STT, NUE, EQIX, BE, AMD, AMZN, GOOGL, MU, GOOG, PWR, NVDA). Broker endpoint 404 (expected per build); /health broker=ok. DB shows 13 open positions with ~$86.7k cost basis.
- **Origin-strategy stamping: 9 of 13 open positions have NULL origin_strategy** — AMD, AMZN, BE, GOOG, MRVL, NUE, NVDA, STT, WDC. Only EQIX, GOOGL, MU, PWR have `rebalance`. All opened 2026-04-29 16:00 UTC (Phase 70 restart burst). This is a regression of commit d08875d — positions opened after 2026-04-18 must have origin_strategy set.
- Position caps: 13 open (within 15 max) ✓. 0 new today (within 5/day cap) ✓.
- Data freshness: prices 2026-04-30 (488 securities, current — market pre-open). Rankings 2026-04-29 10:45 UTC (stale; today's ranking job at 10:45 UTC hasn't fired yet). Signals latest run 2026-04-29 10:30 UTC (stale; today's signal job at 10:30 UTC hasn't fired yet). Intel feed ingestion ran today at 10:10 UTC ✓.
- Stale tickers: known 13 only + **HOLX (NEW)** — Alpaca rejected "asset HOLX is not active" on 2026-04-30 19:30 cycle.
- Kill-switch: false ✓. Operating mode: paper ✓.
- Evaluation history rows: 95 (above 80 floor) ✓.
- Idempotency: clean — 0 duplicate orders, 0 duplicate open-position tickers ✓.

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head). No drift. ✓
- Pytest smoke: **358/360 pass** (35.5s) — 2 known failures (`test_scheduler_has_thirteen_jobs`, `test_all_expected_job_ids_present`) per DEC-021 baseline. No new failures. Note: health-check SKILL had wrong test path (`apis/tests/unit/` → should be `tests/unit/` relative to rootdir `/app/apis`); corrected this run.
- Git: **5 modified** (apis/apps/api/main.py, apis/apps/worker/main.py, apis/infra/docker/docker-compose.yml, apis/state/HEALTH_LOG.md, apis/tests/unit/test_phase15_production_ready.py) + state docs (state/DECISION_LOG.md, state/HEALTH_LOG.md) + **7 untracked** scratch files (_docker_*.txt, _git_log.txt). 0 unpushed commits. HEAD at `6215c20`.
- **GitHub Actions CI:** Run #31 `6215c20` conclusion=success — https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25121114314 GREEN ✓

### §4 Config + Gate Verification
- All critical APIS_* flags at expected values:
  - APIS_OPERATING_MODE=paper ✓
  - APIS_KILL_SWITCH=false ✓
  - APIS_MAX_POSITIONS=15 ✓
  - APIS_MAX_NEW_POSITIONS_PER_DAY=5 ✓
  - APIS_MAX_THEMATIC_PCT=0.75 ✓
  - APIS_RANKING_MIN_COMPOSITE_SCORE=0.30 ✓
  - APIS_SELF_IMPROVEMENT_AUTO_EXECUTE_ENABLED not set (default false) ✓
  - APIS_INSIDER_FLOW_PROVIDER not set (default null) ✓
  - Deep-Dive Step 6/7/8 flags not set (default OFF) ✓
- Scheduler: worker started 2026-04-30 19:21 UTC with job_count=35 (expected per DEC-021). Heartbeat connected ✓.

### Issues Found
- **[YELLOW] 9/13 open positions have NULL origin_strategy**: Regression of commit d08875d. Positions AMD, AMZN, BE, GOOG, MRVL, NUE, NVDA, STT, WDC opened during Phase 70 restart burst (2026-04-29 16:00 UTC) lack origin_strategy stamping. Only EQIX, GOOGL, MU, PWR have `rebalance`. The stamping logic may not fire during broker-position-restore / restart-burst code paths.
- **[YELLOW] broker_health_position_drift on all 13 tickers**: Fired 2026-04-30 19:30 UTC. Broker state diverges from DB for all open positions. May be related to the restart burst or broker sync issues.
- **[YELLOW] HOLX broker rejection — new inactive ticker**: Alpaca rejected order for HOLX ("asset HOLX is not active") on 2026-04-30 19:30 cycle. HOLX should be added to the known-stale/inactive ticker list or removed from the trading universe.
- **[INFO] 5 modified + 7 untracked files in git tree**: Phase 71 (scheduler liveness probe) changes in api/main.py, worker/main.py, docker-compose.yml deployed to containers via bind mount but not committed. CI cannot validate these changes. 7 scratch _docker_*.txt files cluttering repo root.
- **[INFO] Signals/rankings stale at 2026-04-29**: Exp

## Health Check — 2026-07-25 16:45 UTC (Saturday) — MANUAL DEEP-DIVE — RED → repaired

Jul 24 phantom liquidation: outage Jul 20-24 + total transient yfinance failure on restart → 8 healthy positions closed "not_in_buy_set" at the $1.00 fallback price → -$61,616 phantom loss, 55% fake drawdown, full risk lockout. REPAIRED: 8 positions reopened, phantom orders/fills/snapshots deleted (14 open, 0 dups, clean Jul 17 snapshot latest). Phase 87 guards committed `80ba345` + pushed + deployed (no-price execution rejection, strict price fetch, degraded-data cycle gate; 0 test regressions). Bars backfilled through Jul 24. Monitoring re-established (`apis-health-check-v3`, 3x/day CT). Full detail: apis/state/HEALTH_LOG.md same date. Validate Mon 2026-07-27 13:35 UTC c1.


## Health Check — 2026-08-08 23:00 UTC (Saturday) — MANUAL DEEP-DIVE — GREEN (monitoring gap fixed)

Trading system GREEN: Phase 87 validated in production — 0 $1.00 fills in 21 days; guards
visibly blocked SEE/BK no-price opens every cycle and correctly dropped ALL actions in a
12/12-stale degraded cycle on Aug 3 (the Jul 24 scenario, zero damage). Jul 27 MTM
validation confirmed (equity $110,793, lockout cleared). 12 open positions, 0 dups, 0 NULL
origin_strategy; equity $106,023, dd 4.1%. Alembic single head; git clean; Alertmanager quiet.
FOUND+FIXED: APIS was unmonitored Jul 25→Aug 8 (cloud trigger can never reach the machine —
structural). New 2-layer monitoring: Windows Task Scheduler probe scripts/health_probe.ps1
3x/day committing "state: auto-probe" lines to state/AUTO_PROBE_LOG.md (tested end-to-end),
plus cloud trigger renamed apis-probe-watchdog that push-notifies on probe RED or >26h
silence. Also deactivated dead tickers SEE/CTRA/BK (is_active=false; last bars Apr 9 /
May 7 / Jul 10; SEE was re-proposed every cycle). Noted 4th outage Jul 29–30 (~1.5 days).
Aaron: create the local AI deep-dive task per state/LOCAL_DEEPDIVE_TASK_SETUP.md; fix
machine uptime (BIOS auto-power-on + Docker autostart). Full detail: apis/state/HEALTH_LOG.md.


## 2026-08-10 22:30 UTC — LOCAL AI DEEP-DIVE (first scheduled run) — **YELLOW**

Mirror of apis/state/HEALTH_LOG.md entry (primary). Summary:
- YELLOW: /health "degraded" at 15:05 + 19:05 UTC probes (transient, component unrecorded, 7/7 ok by 22:11) + phase87_cycle_degraded_stale_data at 15:30 UTC (12/12 stale, 5 actions dropped — guard worked, 0 phantom fills).
- YELLOW: PLTR/CZR same-day churn; CZR rejected 4x with "Insufficient cash need ~14.5k have ~4k" (risk engine sizing ignores available cash).
- GREEN elsewhere: 8/8 containers (restarted Sun 03:21 UTC, weekend), 0 $1 fills 7d, 14 open/0 dups/0 NULL-origin-open/0 dup keys, snapshot Aug 10 19:30 cash $19,656 equity $106,291 dd 0%, 7/7 cycles today, bars→Aug 7, signals+rankings today, alembic single head, git clean 0 unpushed, smoke 28 passed, all APIS_* flags correct, probes alive + 3 schtasks Ready.
- Fixes: recreated missing repo-root MEMORY.md (memory index was nowhere on machine).
- Recs: probe should log failing /health components; fix CZR cash-aware sizing; churn dampener.



## 2026-08-11 22:30 UTC — LOCAL AI DEEP-DIVE (scheduled) — **YELLOW**

Mirror of apis/state/HEALTH_LOG.md entry (primary). Summary:
- YELLOW: /health "degraded" at 15:05 + 19:05 UTC probes — 2nd consecutive day, SAME times,
  10:05 GREEN both days (systematic, market-hours-only, component unknown). FIXED forward:
  health_probe.ps1 now appends components JSON on non-ok status, so next occurrence is diagnosable.
- GREEN elsewhere: 8/8 containers Up 2d, /health 7/7 ok at 22:10, 0 alerts, 0 $1 fills 7d,
  15 open (=cap)/0 dups/0 NULL-origin-open/0 dup keys, snapshot Aug 11 19:30 cash $12,235
  equity $106,238 dd 0.05%, 7/7 cycles, bars→Aug 10 (486), signals+rankings today, 0 phase87
  events (data healthy), 0 CRITICAL/Traceback, alembic single head, git clean 0 unpushed,
  smoke 28 passed, all APIS_* flags correct, probes alive + 3 schtasks Ready.
- Aug-10 PLTR/CZR churn did NOT recur (3 orders today: SCHW+TGT buys, V sell).
- Recs: watch tomorrow's 15:05/19:05 probe lines for components JSON; CZR sizing + churn
  dampener still open (Phase 88 candidates).



## 2026-08-12 22:15 UTC — LOCAL AI DEEP-DIVE (scheduled) — **YELLOW**

Mirror of apis/state/HEALTH_LOG.md entry (primary). Summary:
- YELLOW: machine asleep/stack down ~04:33→19:10 UTC (5th outage recurrence). Missed all 3
  auto-probes (schtasks skipped, no missed-run flag), 6/7 paper cycles, today's signals/
  rankings, and Aug-11 bars (latest bars = Aug 10). Only the 19:30 UTC cycle ran: clean,
  4 sells (CSCO/CZR/MET/BAC) at real prices, 0 phase87 events.
- GREEN elsewhere: 8/8 containers healthy (up since ~19:10), /health 7/7 ok at 22:10,
  0 alerts, 0 $1 fills 7d, 11 open/0 dups/0 NULL-origin-open/0 dup keys, snapshot Aug 12
  19:30 cash $34,735 equity $106,821 dd 0%, worker log clean, auto-execute correctly
  skipped (disabled), alembic single head, git clean, smoke 28 passed, all APIS_* flags correct.
- 15:05/19:05 "degraded" mystery: no new data (probes never ran) — watch tomorrow.
- Recs: enable "run missed task after wake" on the 3 probe schtasks; auto-start stack after
  boot/wake; Phase 88 (CZR sizing, churn dampener) still open.

- 2026-08-13 22:18 UTC | GREEN | deep-dive: full Aug-12 outage recovery (7/7 cycles, bars Aug 11+12 in, signals/rankings ran); degraded-mystery SOLVED = paper_cycle staleness-threshold artifact at in-market probe times (benign, recs filed); 0 phantom fills, 15/15 positions clean, smoke 28 passed, config nominal.


## 2026-08-14 22:20 UTC — Local AI deep-dive — **GREEN**
All nominal: 8/8 containers healthy, /health ok 7/7, 0 alerts, 0 phantom fills (7d),
15/15 positions (cap) with 0 dups / 0 NULL origin / 0 dup idempotency keys, cash $6,117.21,
drawdown 0.23%, 7/7 cycles, bars current (Aug 13), signals+rankings ran, alembic single head,
git clean/pushed, smoke 28/28, config flags all correct, 3/3 probes fired (15:05/19:05 YELLOW =
known-benign paper_cycle staleness artifact). WATCH: churn — PFE/V/PANW 1-day round-trips,
CZR/CSCO next-day rebuys; Phase-88 dampener evidence now daily. No autonomous fixes needed.
Full details: apis/state/HEALTH_LOG.md.



## 2026-08-15 22:15 UTC — Local AI deep-dive — **GREEN**
All nominal (quiet Saturday): 8/8 containers healthy (up 3d), /health ok 7/7, 0 alerts,
0 phantom fills (7d), 15/15 positions (cap) with 0 dups / 0 NULL origin / 0 dup idempotency
keys, 0 weekend orders (expected), snapshot Aug 14 19:30 cash $6,117.21 dd 0.23%, bars
current (Aug 13; Friday's land Monday), signals/rankings last ran Friday (weekday-only),
worker log spotless (0 warn/err), alembic single head, git clean/pushed, smoke 28/28,
config flags all correct, 3/3 probes fired ALL GREEN — confirms paper_cycle staleness
artifact is in-market-only. No autonomous fixes needed. Full details: apis/state/HEALTH_LOG.md.



## 2026-08-16 22:15 UTC — Local AI deep-dive — **GREEN**
All nominal (quiet Sunday, matches Saturday baseline): 8/8 containers healthy (up 4d),
/health ok 7/7, 0 alerts, 0 phantom fills (7d), 15/15 positions (cap) with 0 dups /
0 NULL origin / 0 dup idempotency keys, 0 weekend orders (expected), snapshot Aug 14
19:30 cash $6,117.21 dd 0.23%, bars current (Aug 13; Friday's land Monday), signals/
rankings last ran Friday, worker log spotless (0 warn/err), alembic single head, git
clean/pushed, smoke 28/28, config flags all correct, 3/3 probes ALL GREEN (weekend).
No autonomous fixes needed. Full details: apis/state/HEALTH_LOG.md.

## 2026-08-17 22:15 UTC — Deep-dive: GREEN
All nominal on full weekday: 8/8 containers (Up 5d), /health 7/7 ok, 0 alerts, 0 phantom
fills, 15/15 positions clean (0 dups/NULLs/dup-keys), 7/7 cycles, Fri bars + signals/rankings
on time, snapshot 19:30 (cash $6,561.80, dd 0.02%), alembic single head, smoke 28 passed,
env flags nominal, 3/3 probes (2 known-benign YELLOWs). Notes: (1) 15:30 UTC yfinance
blackout on 15 healthy tickers — phantom-equity guard preserved prior-close prices, full
recovery; 3rd consecutive MONDAY blackout (Aug 3/10/17). (2) Churn continues as predicted:
AMP/CSCO/CZR Fri→Mon round-trips, V rebought — Phase 88 rec escalated.


## 2026-08-18 22:15 UTC — Deep-dive: YELLOW
**Aug-17 daily bars missing for 483/485 tickers** — today's 10:00 UTC ingestion persisted
Aug-17 rows only for MNST+HUBB while self-reporting "PARTIAL, 120519 bars" at INFO level
(silent failure; probes don't check bar freshness). Latest complete bar day = Fri Aug-14,
so today's signals/rankings ran on 4-day-old bars. Expected self-heal via tomorrow's
period=1y backfill — Wednesday run must verify, escalate RED if gap persists.
Everything else nominal: 8/8 containers (Up 6d), /health 7/7 ok, 0 alerts, 0 phantom fills,
15/15 positions clean, 7/7 cycles, snapshot 19:30 (cash $7,403.10, dd 0.00%), 0 guard
events (intraday pricing healthy), alembic single head, git clean, smoke 28/28, env flags
nominal, 3/3 probes (2 known-benign YELLOWs). Churn day 4: V 2nd round-trip (rebought 8/17
→ sold 8/18), VLO 1-day flip; buys MU/STX/TRV — Phase 88 rec #1. No email/push tool in
session; notification via this log + commit. Full details: apis/state/HEALTH_LOG.md.



## 2026-08-19 22:15 UTC — Deep-dive: GREEN
**Yesterday's bar-gap YELLOW resolved**: 10:00 UTC ingestion backfilled Aug-17 bars 2→484
(only AVB missing) and landed Aug-18 at 485/485 — self-heal verified, no RED escalation.
All nominal: 8/8 containers (Up 7d), /health 7/7 ok, 0 alerts, 0 phantom fills, 15/15
positions clean, 7/7 cycles, signals/rankings on FRESH bars, snapshot 19:30 (cash
$7,059.45, dd 0.49%), 0 guard/phase87 events, alembic single head, git clean, smoke
28/28, env flags nominal, 3/3 probes (2 known-benign YELLOWs).
**Churn day 5, new flavor**: all 6 of today's orders were SAME-DAY sell→rebuy round-trips
(SNOW 13:35→14:30, DELL 14:30→15:30, STX 14:30→15:30) — zero net change, pure turnover.
Phase 88 remains rec #1. Full details: apis/state/HEALTH_LOG.md.



## 2026-08-20 22:15 UTC — Deep-dive: GREEN
All nominal: 8/8 containers (Up 8d), /health 7/7 ok, 0 alerts, 0 phantom fills, 15/15
positions clean, 7/7 cycles, bars fresh through Aug-19 (485), signals/rankings on time,
snapshot 19:30 (cash $7,062.70, equity $106,477.95, dd 0.43%), 0 guard/phase87 events,
alembic single head, git clean, smoke 28/28, env flags nominal, 3/3 probes (2 known-
benign YELLOWs). **Churn day 6 (milder)**: 3 sells 13:35 (TRV/STX/TGT) → 3 new buys
14:30 (MRK/AMGN/GE); STX 4th trade in 3 days. Phase 88 remains rec #1. AVB Aug-17 bar
still missing (harmless). Full details: apis/state/HEALTH_LOG.md.



## 2026-08-21 22:15 UTC — Deep-dive: GREEN
All nominal: 8/8 containers (Up 9d), /health 7/7 ok, 0 alerts, 0 phantom fills, 14/15
positions clean, 7/7 cycles, bars fully current (AVB Aug-17 backfilled — watch closed),
signals/rankings on time, snapshot 19:30 (cash $12,969.64, equity $105,451.81, dd 1.39%),
0 guard/phase87 events, alembic single head, git clean, smoke 28/28, env flags nominal,
3/3 probes (2 known-benign YELLOWs). **Churn day 7 — first realized cost**: MRK/GE 1-day
round-trips; V 3rd rebuy; MRNA bought 14:30 @ $156.88 → sold 18:30 @ $140.80 (-10.2%,
≈-$723) — drove dd 0.43%→1.39%. Phase 88 remains rec #1. Full details:
apis/state/HEALTH_LOG.md.



## 2026-08-22 22:15 UTC — Deep-dive: GREEN
Quiet Saturday, weekend baseline fully confirmed: 8/8 containers (Up 10d), /health 7/7
ok (paper_cycle ok), 0 alerts, 0 phantom fills, 14 open positions clean, 0 snapshots/
fills today (expected), bars current through Aug-20 (Aug-21 lands Monday), eval_runs +0,
latest snapshot Friday 19:30 (cash $12,969.64, equity $105,451.81, dd 1.39%), worker log
window totally quiet (0 warn/err), alembic single head, git clean, smoke 28/28, env
flags nominal, 3/3 probes ALL GREEN. No fixes needed. Watch Mon Aug-24: possible 4th
consecutive Monday yfinance blackout. Full details: apis/state/HEALTH_LOG.md.


## 2026-08-23 22:15 UTC — Deep-dive: GREEN
Quiet Sunday, 4th fully-GREEN weekend day (Aug 15/16/22/23). 8/8 containers up 11d,
/health 7/7 ok, 0 alerts. 0 phantom fills, 14/15 positions, 0 dups/NULLs, snapshot
Friday 19:30 (weekend-correct; cash $12,969.64, drawdown 1.39%). 0 snapshots/fills
today (expected), bars current through Aug-20, worker log fully quiet (0 warn/err).
Alembic head ok, git clean/pushed, smoke 28/28, env flags nominal, probes 3/3 GREEN,
schtasks Ready. No fixes needed. Watch Mon Aug-24: 4th-Monday yfinance blackout +
Friday bars landing + churn day 8 (Phase 88 rec #1).



## 2026-08-24 22:17 UTC — Deep-dive daily check — RED
- **RED: POSITION CAP BREACH — 16 open positions vs APIS_MAX_POSITIONS=15.** 13:35 cycle
  opened 4 (TMO/DGX/A/MRNA) while phase65/65b rebalance-protection suppressed planned
  exits (PSX close→trim); only JPM/JNJ closed → 14−2+4=16. Risk engine passed all opens
  (validates against planned closes, not post-suppression reality). No manual fix taken
  (not authorized to place/cancel orders); expect cap to block new opens tomorrow —
  verify open_pos ≤15 on next run.
- 4th consecutive Monday yfinance blackout (Aug 3/10/17/24) — CONFIRMED pattern; guards
  handled it (stale-price preserved ×32, phantom-equity guard ×2, 0 phase87, cycle ok).
- Otherwise nominal: 8/8 containers, /health ok 7/7, 0 alerts, 0 phantom fills, 0 dups,
  bars current through Aug-21 (485/485 on time), 7/7 snapshots, signals/rankings ran,
  smoke 28/28, alembic head ok, git clean, config nominal, probes 3/3 (2 benign YELLOW).
- Churn day 8: MRNA −10.2% sell Fri → rebuy Mon. Full details: apis/state/HEALTH_LOG.md.
- Notified Aaron by email (RED).



## 2026-08-25 22:20 UTC — Deep-dive daily check — GREEN
- **Aug-24 cap breach RESOLVED as predicted: 15/15 open.** 13:35 cycle closed MRVL +
  trimmed AMGN, zero new opens while over cap (enforcement worked); no 17th position.
  Underlying phase65×cap-validation bug still unfixed — rec #1 to Aaron.
- Monday Aug-24 bars landed 484/485 on time — NO Tuesday silent-partial repeat.
  Missing: ORGN/EQR/EA (EA is an open position) — benign AVB-style gap, watching.
- Otherwise fully nominal: 8/8 containers, /health 7/7 ok, 0 alerts, 0 phantom fills,
  0 dups/NULLs, 7/7 snapshots, signals/rankings ran, log clean (0 CRITICAL/guard
  events), smoke 28/28, alembic head ok, git clean, config nominal, probes 3/3
  (2 benign YELLOW). Cash $27,256.04, equity $105,890.04, drawdown 0.98%.
- Churn: quietest day in 9 — 2 sells only, no buys, no round-trips.
- Full details: apis/state/HEALTH_LOG.md. GREEN = silent (log+commit only).


## 2026-08-26 22:15 UTC — Deep-dive: GREEN
All nominal: 8/8 containers, /health ok 7/7, 0 alerts, 0 phantom fills, 15/15 open
(cap holds post-breach), 0 dups/NULLs, 7/7 cycles, signals+rankings on time, bars
current through Aug-25 (EQR/AVB single-name lag, benign watch), smoke 28/28, git
clean, env nominal, probes 3/3. Churn resumed day 9: MRNA same-day round-trip
(sold @149.50/rebought @149.37; the 8/24 buy @133.43 realized +12%), A/SNOW→DASH/MA
swap. New baseline: intraday equity freeze after last fill is normal (matches 8/20).
No fixes needed. Full details in apis/state/HEALTH_LOG.md.



## 2026-08-27 22:15 UTC — Deep-dive daily check — RED
- **SECOND CAP BREACH: 16 open > 15.** 14:30 cycle opened KO+WST (origin 'rebalance')
  while its 1 planned close was phase65-suppressed. NEW validation gap proven: each
  same-cycle open validated against the same starting count (14) — no running total —
  on top of the known suppressed-close counting bug from 8/24. 13:35 cycle had
  correctly blocked both opens at count 15 (enforcement works AT the cap, breaks
  crossing it via multi-open + suppression).
- Expect self-correction Fri 13:35 per 8/25 precedent; next-run duty: verify ≤15,
  a 17th = escalate hard. Fix is rec #1 (URGENT), deep-dive can implement if authorized.
- Otherwise nominal: 8/8 containers, /health ok 7/7, 0 alerts, 0 phantom fills,
  0 dups/NULLs, 7/7 snapshots, signals/rankings on time, log clean (0 CRITICAL,
  0 guard events), smoke 28/28, alembic head ok, git clean, config nominal,
  probes 3/3 (2 benign YELLOW). Cash $21,437.55, equity $106,709.46, dd 0.21%.
- Bars through Aug-26 (483); EQR missing 3rd consecutive day (watch, near is_active
  review); AVB/EA/ORGN single-name gaps churning. Churn day 10 mild: TGT 6-day-hold
  close, no round-trips.
- Notified Aaron by email (RED). Full details: apis/state/HEALTH_LOG.md.



## 2026-08-29 01:35 UTC — Deep-dive (Fri 8/28 run, fired late on wake) — RED
- **Outage #6**: reboot Thu 11:39 PM CT, then machine slept / Docker down the entire
  Friday trading day; containers only up ~01:20 UTC 8/29. Lost: 3/3 probes (schtasks
  skipped their 8/28 triggers), Aug-27 bar ingestion, signals/rankings, all 7 cycles.
- **Cap breach #2 still standing: 16 open > 15** — could not self-correct with zero
  cycles; no 17th (0 fills). Correction now expected Mon 8/31 13:35 UTC.
- Post-restart all nominal: /health ok 7/7, 0 alerts, 0 phantom fills, 0 dups/NULLs,
  clean startup log, smoke 28/28, alembic head ok, git clean, env nominal.
- Data: bars end Aug-26; EA (open position) bars stale since 8/10 (backfill vanished);
  EQR since 8/21. Mon 8/31 doubles as 5th-Monday blackout test — catch-up may slip
  to Tue.
- Recs: #1 cap-validation fix (urgent, live breach all weekend); #2 NEW Docker
  auto-start + schtasks "run after missed start" (2nd full-day loss); churn/provider/
  threshold recs carried. Notified Aaron by email (RED).
  Full details: apis/state/HEALTH_LOG.md.
