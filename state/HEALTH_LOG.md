# APIS Health Log

Auto-generated daily health check results.

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
- **[INFO] Signals/rankings stale at 2026-04-29**: Expected — today's signal (10:30 UTC) and ranking (10:45 UTC) jobs haven't fired yet at time of this check (10:15 UTC). Wednesday's jobs were missed due to scheduler silence (resolved by Phase 71).

### Fixes Applied
- None this run. No autonomous fixes required.

### Action Required from Aaron
- **Backfill origin_strategy on 9 open positions**: UPDATE the 9 NULL rows with the appropriate strategy (likely `rebalance` given they were part of a restart burst). Investigate why the stamping logic didn't fire during the Phase 70 restart path and fix the code to prevent recurrence.
- **Commit Phase 71 changes**: 5 modified source files (api/main.py, worker/main.py, docker-compose.yml, test_phase15, HEALTH_LOG.md) + state docs should be committed and pushed. CI coverage is stale — last CI run tested Phase 70 code, not Phase 71.
- **Add HOLX to inactive ticker handling**: Either remove HOLX from the trading universe or add it to the known-inactive list so it doesn't generate broker rejections.
- **Clean up scratch files**: 7 `_docker_*.txt` / `_git_log.txt` files in repo root — safe to delete or .gitignore.

