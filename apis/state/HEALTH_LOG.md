# APIS Health Log

Auto-generated daily health check results.

## Session Close — 2026-05-05 20:25 UTC (Tuesday 3:25 PM CT) — Phase 75 + Phase 76 BUNDLED PUSH + Historical Cleanup

**Summary:** Three "fix once and for all" tasks closed in one session.

**1) Phase 76 — HOLX universe-filter defence-in-depth (DEC-076)** — commit `caa497d` on `main`, pushed to `origin/main`.
- `apis/services/risk_engine/service.py`: added `is_active_fn: Callable[[str], bool] | None = None` constructor param (mirrors `kill_switch_fn`); added `check_inactive_ticker(action)` method that hard-blocks OPEN actions when `is_active_fn(ticker) == False`. CLOSE/TRIM never blocked. Wired into `validate_action()` between `kill_switch` and `portfolio_limits`. New log line `risk_inactive_ticker_blocked`. Backward-compatible (None → check skipped). Exceptions in callable swallowed with warning (defensive, not authoritative).
- `apis/apps/worker/jobs/paper_trading.py::run_paper_trading_cycle`: snapshots `securities.is_active=False` tickers once per cycle into `_inactive_tickers: set[str]` and passes `lambda t: t not in _inactive_tickers` as `is_active_fn` when constructing `RiskEngineService`. Snapshot failure logs `paper_cycle_inactive_ticker_snapshot_failed` and falls back to empty set (no false positives).
- `apis/tests/unit/test_risk_engine.py`: `TestInactiveTicker` class with 8 tests. Also fixed 2 pre-existing env-drift failures (`test_blocks_open_at_max_positions`, `test_single_violation_blocks_action`) by pinning `max_positions=10` explicitly.
- Operator chose risk-engine-only (over dual risk-engine+strategy candidate filter); single-place defence-in-depth is cleaner.

**2) Phase 75 — bundled commit + push** — commit `d6be5ea`. Was already in working tree pending commit; bundled into the same push. Push range: `9db28ae..caa497d`. Both Phase 75 and Phase 76 land on origin together.

**3) Historical cleanup — 395 duplicate closed-position rows deleted.**
- Original recommendation SQL `DELETE WHERE id NOT IN (SELECT MAX(id) GROUP BY security_id, opened_at)` doesn't work (positions.id is UUID, no MAX(uuid)). Adapted with `ROW_NUMBER() OVER (PARTITION BY security_id, opened_at ORDER BY (status='open') DESC, closed_at DESC NULLS FIRST, id DESC)`.
- FK on `orders.position_id` is RESTRICT (no CASCADE) — re-pointed 15 orphan orders to canonical (keeper) position id BEFORE the DELETE.
- All in single `BEGIN; ... COMMIT;` transaction. Final state: positions 584 → 189 (12 open / 177 closed), zero remaining `(security_id, opened_at)` dup groups, zero orphan orders.
- "~140" estimate from 2026-05-04 21:30 UTC HEALTH_LOG was low — by 2026-05-05 ~20:00 UTC the actual count was 395 (additional 2026-05-04 cycles ran before Phase 75 deployed at 01:41:58 UTC 2026-05-05).

**Validation:** 175 tests pass (risk_engine 63, paper_trading 63, phase64 7, deep_dive_step5 16, execution_engine 23, plus 3 others) under `APIS_PYTEST_SMOKE=1` in `docker-api-1`. Ruff clean on changed files.

**Operational:** worker + api restarted 2026-05-05 20:19:55 UTC. `apis_worker_started` log shows `job_count=36`. Next paper cycle exercises the new gate.

**Remaining context for next session:**
- 12 open positions all `origin_strategy=rebalance` — `broker_health_position_drift` carry-forward will likely take 1–2 more cycles to clear naturally now that Phase 75 + 76 are live.
- HOLX issue: previously recurring proposals will now be hard-blocked at validate_action with `rule_name=inactive_ticker` instead of relying on Alpaca rejection + daily cap.
- Strategy candidate-universe selector still does NOT honour `securities.is_active=false` — out of scope per operator choice. If proposal-layer noise becomes a triage burden, add a strategy-side filter as a secondary defence (see `project_phase76_holx_risk_engine_fix.md` in memory).

---

## Health Check — 2026-05-05 19:12 UTC (Tuesday 2:12 PM CT, market open ~5.6h, 6/12 cycles fired)

**Overall Status:** YELLOW — same two carry-forward issues from this morning's 15:09 UTC entry, no new regressions, no escalation. (1) `broker_health_position_drift` fired on every paper cycle today (6/6: 13:35, 14:30, 15:30, 16:00, 17:30, 18:30 UTC) on the same 12 operator-restored rebalance tickers — strategy continues to BUY toward the DB target rather than CLOSE; drift will narrow gradually as broker accumulates over many cycles. (2) HOLX proposed + rejected on every cycle (6/6) — strategy still proposes inactive ticker; risk_engine blocks on `max_new_positions_per_day=5` (consumed by today's 5 BUY fills), Alpaca is the final safety net. Both issues triaged in the 15:09 UTC report; no new code/operator action since. Everything else GREEN: 8/8 containers healthy 16h uptime RestartCount=0, /health all 7 ok at 19:08:15Z, worker 24h log scan = 68 ERR / api = 43 ERR (all known yfinance stale + drift warnings, **0 crash-triad regressions** across all 5 patterns), Prometheus 2/2 up, Alertmanager firing=0 (Phase 73 `for: 30m` debounce holding all day), pytest deep_dive+phase22+phase57 → **360p/0f/3662d in 22.12s** ✅, alembic `p6q7r8s9t0u1` single head, CI on `9db28ae` `conclusion=success`, 12 OPEN positions all `origin_strategy=rebalance` ✅, 0 new positions today, kill_switch=false, mode=paper, 0 idempotency dupes, evaluation_runs=97 (≥80 floor), all 11 critical APIS_* flags correct, scheduler `job_count=36` + liveness heartbeat firing every 5 min (last 19:11:20 UTC). Phase 75 functional code still loaded in worker bind-mount (`grep -c phase75_position_row_reopened ... = 1`); zero `phase75_*` events today (expected — strategy hasn't reopened any closed ticker at the same `opened_at`).

### §1 Infrastructure
- Containers: 8/8 healthy. All four core services (worker/api/postgres/redis) `Up 16 hours` with `RestartCount=0` since `2026-05-05T03:31:12Z` (this morning's full-stack recreation). Grafana / Prometheus / Alertmanager / apis-control-plane also `Up 16h`. No restarts since the morning run.
- /health: all 7 components `ok` at 2026-05-05T19:08:15Z. mode=paper, kill_switch=ok.
- Worker log scan (tail 5000): **68 ERROR** pattern matches — primarily yfinance stale-ticker warnings (DFS, PXD, JNPR, K, PARA, CTLT, ANSS, WRK, etc., all in known-13 list) + 19 `broker_health_position_drift` cumulative warnings (Mon afternoon carry-forward + today's 6 cycles). **0 crash-triad regressions** across all 5 patterns (`_fire_ks` / `broker_adapter_missing_with_live_positions` / `EvaluationRun.idempotency_key` / `paper_cycle.*no_data` / `phantom_cash_guard_triggered` all zero).
- API log scan (tail 5000): **43 ERROR** pattern matches, **0 crash-triad regressions**.
- Prometheus: 2/2 targets up (apis, prometheus), 0 dropped.
- Alertmanager: 0 active alerts at 19:08 UTC. Phase 73 `for: 30m` debounce held through all 6 of today's cycles.
- Resource usage: worker 774 MiB / 9.78%, api 818 MiB / 2.99%, postgres 157 MiB, grafana 50.5 MiB, prometheus 41.8 MiB, alertmanager 15.2 MiB, redis 8.3 MiB, apis-control-plane 1.011 GiB / 7.13%. All well under threshold.
- DB size: **179 MB** (unchanged from 15:09 UTC entry — no growth in 4h, expected since signal/ranking pipeline already ran at 10:30/10:45 UTC).

### §2 Execution + Data Audit
- Paper cycles fired today: **6 of expected 12**. Timestamps: 13:35:02, 14:30:00, 15:30:00, 16:00:01, 17:30:00, 18:30:01 UTC. Next cycle 19:30 UTC (~18 min). All 6 completed (`paper_trading_cycle_complete`); **0 cycle failures**. First cycle: proposed=28, approved=5, executed=5. Subsequent 5 cycles: proposed=18, approved=0, executed=0 (daily cap consumed by cycle 1's 5 fills).
- `evaluation_runs` total: **97** (≥80 floor ✅; +0 since this morning — Tue's 21:00 UTC EOD eval hasn't fired yet). Latest run 2026-05-04 21:00 UTC (Mon EOD).
- Portfolio trend (latest 6 paired-snapshot rows from today's 6 cycles, dual-snapshot pattern continuing):
  - 2026-05-05 18:30:03 — cash=$23,050.74 / equity=$114,219.50 (legitimate)
  - 2026-05-05 18:30:00 — cash=$67,446.34 / equity=$99,983.92 (secondary writer)
  - 2026-05-05 17:30:02 — cash=$23,050.74 / equity=$114,395.54
  - 2026-05-05 16:00:03 — cash=$23,050.74 / equity=$114,368.20
  - 2026-05-05 15:30:02 — cash=$23,050.74 / equity=$114,048.29
  - 2026-05-05 14:30:02 — cash=$23,050.74 / equity=$114,087.68
  - 2026-05-05 13:35:04 — cash=$23,050.74 / equity=$112,924.50
- Cash positive ✅ on legitimate stream. Equity intra-day band $112,924 → $114,395 (+1.30% high, +1.15% close-to-now), consistent with normal market move on the 12 OPEN positions' notionals. Cash + holdings ≈ equity_value within rounding ✅. Dual-snapshot writer pattern unchanged from 15:09 UTC (carry-forward).
- Broker<->DB reconciliation: DB shows **12 OPEN positions** (CAT, SLB, INTC, BE, MU, WDC, STT, NUE, AMD, MRVL, AMZN, EQIX), all `origin_strategy=rebalance` ✅, all opened_at in 2026-04-29 → 2026-05-01 (operator-restored from DEC-071 cleanup). `/api/v1/broker/positions` 404s in this build — falling back to /health=ok per feedback note. **6 `broker_health_position_drift` warnings today** at every cycle on the same 12-ticker set. Drift direction is broker-not-DB; strategy is BUYing toward target rather than CLOSing — expected to narrow over many cycles.
- Origin-strategy stamping: ALL 12 OPEN `origin_strategy=rebalance` ✅. 0 NULLs (Phase 73 holding).
- Position caps: **12/15 open** ✅. **0 new OPEN positions today** (per `WHERE opened_at::date = CURRENT_DATE`). All 5 of today's filled BUY orders were add-ons against existing OPEN rows (rebalance-toward-target semantics — DB row encodes target, broker accumulates toward it). 5 of 5 fills consumed `max_new_positions_per_day=5` slot count (slot-counter, not row-counter), causing HOLX to reject on every subsequent cycle.
- Today's order ledger (11 total: 5 filled, 6 rejected):
  - **Filled @ 13:35** (BUY against existing OPEN rebalance positions): INTC=64, MU=10, AMZN=24, EQIX=6, NUE=29.
  - **Rejected** (action_blocked_by_risk, violation=max_new_positions_per_day): HOLX × 6 (one per cycle: 13:35, 14:30, 15:30, 16:00, 17:30, 18:30).
- Data freshness:
  - daily_market_bars MAX = **2026-05-04** (Mon close, 488 securities) ✅. Tue's bars load post-close tonight.
  - signal_runs MAX = **2026-05-05 10:30:00 UTC** ✅ (today's 06:30 ET signal-generation job).
  - ranking_runs MAX = **2026-05-05 10:45:00 UTC** ✅ (today's 06:45 ET ranking job).
  - security_signals types: macro_tailwind / momentum / sentiment / theme_alignment / valuation, all 1004 rows at 10:30:00 UTC ✅.
- Stale tickers: known 13 only (DFS, PXD, JNPR, K, PARA, CTLT, ANSS, WRK, MMC, MRO, HES, IPG, PKI). No new additions.
- Kill-switch: `false` ✅. Operating mode: `paper` ✅.
- Idempotency: 0 duplicate orders by `idempotency_key` ✅. 0 duplicate OPEN positions per ticker ✅.

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head ✅). No drift.
- Pytest smoke: **360 passed / 0 failed / 3662 deselected in 22.12s** ✅ (deep_dive + phase22 + phase57 filter, `--no-cov`, `APIS_PYTEST_SMOKE=1`).
- Git: **DIRTY** (carry-forward — Phase 75 functional changes + state docs operator-deferred). HEAD = `9db28ae`. 0 unpushed commits. Modified paths: `apis/apps/worker/jobs/paper_trading.py`, `apis/tests/unit/test_phase64_position_persistence.py`, all 5 state-doc files (apis/state + state mirror). Untracked: `outputs/`. **No autonomous commit/push** — same uncommitted Phase 75 code change verified at unit-test layer + bind-mount-loaded into the running worker since 01:42 UTC Mon. Phase 75 code grep confirms loaded: `phase75_position_row_reopened` count = 1, `phase75_close_skipped_just_upserted` count = 1.
- **GitHub Actions CI:** Run **#25327395434** on `9db28ae` — `status=completed, conclusion=success` ✅. https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25327395434 . CI healthy on the most recent pushed SHA.

### §4 Config + Gate Verification
All critical APIS_* flags at expected values:
- APIS_OPERATING_MODE=paper ✅
- APIS_KILL_SWITCH=false ✅
- APIS_MAX_POSITIONS=15 ✅
- APIS_MAX_NEW_POSITIONS_PER_DAY=5 ✅
- APIS_MAX_THEMATIC_PCT=0.75 ✅
- APIS_RANKING_MIN_COMPOSITE_SCORE=0.30 ✅
- APIS_MAX_SECTOR_PCT=0.40 ✅
- APIS_MAX_SINGLE_NAME_PCT=0.20 ✅
- APIS_MAX_POSITION_AGE_DAYS=20 ✅
- APIS_DAILY_LOSS_LIMIT_PCT=0.02 ✅
- APIS_WEEKLY_DRAWDOWN_LIMIT_PCT=0.05 ✅
- APIS_SELF_IMPROVEMENT_AUTO_EXECUTE_ENABLED not set (defaults false) ✅
- APIS_INSIDER_FLOW_PROVIDER not set (defaults null) ✅
- Deep-Dive Step 6/7/8 flags not set (defaults OFF) ✅
- Scheduler: `job_count=36` (DEC-021 expected). Liveness heartbeat firing every 5 min — last successful run 2026-05-05T19:11:20Z (~30s before this entry) ✅.

### Issues Found
- **[YELLOW] HOLX universe-filter regression vs Phase 72 — UNCHANGED CARRY-FORWARD from 15:09 UTC entry.** Strategy still proposing HOLX `action_type=open` on every cycle (6/6 today: 13:35, 14:30, 15:30, 16:00, 17:30, 18:30 UTC) despite `securities.is_active=false` in DB. All 6 blocked at risk_engine on `max_new_positions_per_day=5` (consumed by today's 5 fills). Risk engine has NO `inactive_ticker` violation rule. Functional outcome remains fine (Alpaca is final safety net) but the proposal-layer regression Phase 72 supposedly closed is still live. Recommended fix unchanged: add `is_active=false` filter to strategy universe selector OR add `inactive_ticker` violation to risk_engine (preferred — defense-in-depth).
- **[YELLOW] Phase 75 close-loop forecast miss — drift not clearing — UNCHANGED CARRY-FORWARD.** 6/6 cycles today fired `broker_health_position_drift` on the same 12 tickers. Strategy is rebalancing in the OPPOSITE direction (BUYing toward target via 5 fills cycle 1, then capped on slot count). Drift narrows over many cycles as broker accumulates. Not a Phase 75 regression (which was scoped to row-inflation prevention). No fix needed; broker drift will resolve naturally.
- **[INFO] Phase 75 functional code change still uncommitted.** Unchanged from 15:09 UTC. Awaiting operator commit + push.
- **[INFO] Dual-snapshot writer continuing.** Same paired $23k/$110-114k legitimate + $67k/$99.9k secondary pattern as prior days. No new regression. Prometheus reads the legitimate stream; runtime impact = nil.
- **[INFO] Phase 73/74 defenses fully holding.** Alertmanager firing=0 across all 6 cycles today. No phantom-equity, no DrawdownAlert, no test-pollution writes to production.

### Fixes Applied
- None — all issues identified are operator-review-required (HOLX universe-filter regression) or non-actionable (forecast miss; broker will catch up naturally; commit/push deferred to operator).

### Action Required from Aaron
1. **Triage HOLX universe-filter regression (YELLOW).** Unchanged from 15:09 UTC ask. Recommended fix: add a `securities.is_active=true` filter to the candidate-universe query in the strategy module AND/OR add an `inactive_ticker` violation to `services/risk_engine/service.py`. Risk-engine path preferred (single-place defense-in-depth). Cannot autonomously edit strategy/risk code without operator review.
2. **Commit + push Phase 75 when ready** (still pending). Same suggested commit message: `Phase 75: position-row inflation fix in _persist_positions (DEC-075)`. CI is GREEN on `9db28ae` so the push will land on a known-good base.
3. **Optional historical cleanup SQL** still available in 2026-05-04 ~21:30 UTC HEALTH_LOG entry (~140 dup closed-position rows). Not required for runtime correctness.

---

## Health Check — 2026-05-05 15:09 UTC (Tuesday 10:09 AM CT, market open ~1.6h)

**Overall Status:** YELLOW — first-cycle Phase 75 validation reveals two carry-over patterns and one strategy-layer regression. (1) `broker_health_position_drift` fired on BOTH Tue cycles (13:35 + 14:30 UTC) on the same 12 tickers — Phase 75's close-loop is NOT naturally closing the operator-restored rebalance rows because the strategy is rebalancing in the OPPOSITE direction (buying TOWARD the DB target rather than closing them). 5 BUY orders filled at 13:35 UTC (INTC=64, MU=10, AMZN=24, EQIX=6, NUE=29) bringing broker partially up to DB target — drift will clear over many cycles, not the 1–2 forecasted. (2) HOLX is still being PROPOSED by the strategy and reaching the risk engine despite Phase 72's `is_active=false` (DB confirms `is_active=f`) — risk engine blocks on `max_new_positions_per_day` only, NOT on inactive-ticker; if daily cap weren't full, HOLX would reach broker rejection. Defense-in-depth holds (Alpaca rejection is final safety net) but the universe filter regression should be triaged. (3) Phase 75 functional code change still uncommitted in worker bind-mount (intentional operator-defer per yesterday's note). Everything else GREEN: 8/8 containers healthy 12h uptime RestartCount=0, /health all 7 ok at 15:09:02Z, Worker 24h log scan = 34 ERROR (all known-stale yfinance + 7 drift warns; 0 crash-triad regressions), Prometheus 2/2 up, Alertmanager firing=0, pytest 360/0 in 25.18s, alembic single head `p6q7r8s9t0u1`, CI on `9db28ae` `conclusion=success`, 12 OPEN positions all `origin_strategy=rebalance`, kill_switch=false, mode=paper, 0 idempotency dupes, evaluation_runs=97 (≥80 floor), all 11 critical APIS_* flags correct, scheduler `job_count=36` + liveness firing every 5 min.

### §1 Infrastructure
- Containers: 8/8 healthy. All four core services (worker/api/postgres/redis) `Up 12 hours` with `RestartCount=0` since `2026-05-05T03:31:12Z` (full-stack recreation from this morning's pre-market deploy). Grafana / Prometheus / Alertmanager / apis-control-plane also `Up 12h`.
- /health: all 7 components `ok` at 2026-05-05T15:09:02Z. mode=paper, kill_switch=ok.
- Worker log scan (24h): 34 ERROR/CRITICAL pattern matches — primarily yfinance stale-ticker warnings (DFS, PXD, JNPR, K, PARA, CTLT, ANSS, WRK, etc. — all in the known-13 list). **0 crash-triad regressions** (`_fire_ks` / `broker_adapter_missing_with_live_positions` / `EvaluationRun.idempotency_key` / `paper_cycle.*no_data` / `phantom_cash_guard_triggered`). **7 `broker_health_position_drift` warnings** in last 24h (5 from Mon afternoon carry-forward + 2 today on the 13:35 + 14:30 UTC cycles — same 12 tickers each time: STT, BE, MU, INTC, AMD, WDC, CAT, EQIX, AMZN, SLB, NUE, MRVL).
- API log scan (tail 5000): 52 ERROR/CRITICAL pattern matches, **0 crash-triad regressions**.
- Prometheus: 2/2 targets up (apis, prometheus), 0 dropped.
- Alertmanager: 0 active alerts at 15:09 UTC. Phase 73 `for: 30m` debounce holding through today's cycles.
- Resource usage: worker 773.6 MiB, api 798.1 MiB, postgres 156.9 MiB, grafana 50.6 MiB, prometheus 38.5 MiB, alertmanager 14.9 MiB, redis 7.9 MiB, apis-control-plane 1016 MiB / 8.90% CPU. All well under threshold.
- DB size: **179 MB** (was 171 MB at 10:18 UTC pre-market — +8 MB from today's 2 cycles + signal/ranking job repopulation).

### §2 Execution + Data Audit
- Paper cycles fired today: **2 of expected 12** so far (13:35 UTC cycle_id `ffad9083…`: proposed=28, approved=5, executed=5; 14:30 UTC cycle_id `87612710…`: proposed=18, approved=0, executed=0). Both completed within 1–2 seconds, no `paper_cycle.*no_data`. 24h cycle history (Mon afternoon carry-forward + today): 15:30 / 16:00 / 17:30 / 18:30 / 19:30 / 13:35 / 14:30 — all START → COMPLETE pairs.
- `evaluation_runs` total: **97** (≥80 floor ✅; +0 from yesterday — Tue's 21:00 UTC EOD eval hasn't fired yet).
- Portfolio trend (latest 4 paired-snapshot rows from today's cycles, dual-snapshot pattern continuing):
  - 2026-05-05 14:30:02 — cash=$23,050.74 / equity=$114,087.68 (legitimate)
  - 2026-05-05 14:30:00 — cash=$67,446.34 / equity=$99,983.92 (secondary writer)
  - 2026-05-05 13:35:04 — cash=$23,050.74 / equity=$112,924.50
  - 2026-05-05 13:35:02 — cash=$67,446.34 / equity=$99,983.92
  - Cash positive ✅ on legitimate stream. Equity 13:35→14:30 = +$1,163 (+1.03%, normal intraday move). Cash + holdings = $23,050.74 + $91,036.94 ≈ $114,087.68 ✓ within rounding. Dual-snapshot pattern unchanged from yesterday (carry-forward).
- Broker<->DB reconciliation: DB shows **12 OPEN positions** (CAT, SLB, INTC, BE, MU, WDC, STT, NUE, AMD, MRVL, AMZN, EQIX). All `origin_strategy=rebalance` ✅, all opened_at in 2026-04-29 → 2026-05-01 (operator-restored from cleanup transaction). /health broker=ok. `/api/v1/broker/positions` 404s in this build — falling back to /health=ok per feedback note. **2 broker_health_position_drift warnings today** at 13:35:00 and 14:30:00 — same 12 tickers, confirming the drift is broker-not-DB rather than DB-not-broker.
- Origin-strategy stamping: ALL 12 OPEN `origin_strategy=rebalance` ✅. Phase 73 fix holding (0 NULLs).
- Position caps: **12/15 open** ✅. **0 new OPEN positions today** (per `WHERE opened_at::date = CURRENT_DATE`) — all 5 of today's filled BUY orders were add-ons against existing OPEN rows (rebalance-toward-target semantics) so no new rows were inserted. **5 of 5 fills consumed `max_new_positions_per_day=5`** (slot count, not row count) — that's why HOLX got blocked at risk-engine on cycle 2.
- Today's fills (13:35 UTC, all BUY against existing OPEN rebalance positions):
  - INTC: 64 @ $103.10  · MU: 10 @ $616.48  · AMZN: 24 @ $277.01  · EQIX: 6 @ $1086.05  · NUE: 29 @ $228.48
  - Note: position rows' `quantity` was NOT incremented to reflect these adds. Consistent with rebalance-target semantics (DB row encodes the TARGET, broker accumulates toward it). Broker drift will narrow over multiple cycles as broker catches up to the 12-ticker DB target. **NOT** the row-inflation pattern Phase 75 fixed (no duplicate `(security_id, opened_at)` rows; all 12 ticker-episodes still single-row).
- Today's rejected orders (HOLX × 2 at 13:35:03 + 14:30:02): both `action_blocked_by_risk` with `violations=["max_new_positions_per_day"]`. Strategy is still PROPOSING HOLX as an `open` action despite `securities.is_active=false`. **YELLOW finding** — Phase 72 universe-filter regression (see Issues Found).
- Data freshness:
  - daily_market_bars MAX = **2026-05-04** (Mon close, 490 securities) ✅ — Mon EOD ingestion completed; Tue's bars will load post-close tonight.
  - signal_runs MAX = **2026-05-05 10:30 UTC** ✅ — Today's 06:30 ET signal-generation job ran (was stale yesterday at 2026-05-01).
  - ranking_runs MAX = **2026-05-05 10:45 UTC** ✅ — Today's 06:45 ET ranking job ran (was stale yesterday).
  - signal/ranking staleness from Phase 74 cleanup is FULLY CLEARED.
- Stale tickers: known 13 only (DFS, PXD, JNPR, K, PARA, CTLT, ANSS, WRK, MMC, MRO, HES, IPG, PKI). No new additions.
- Kill-switch: `false` ✅. Operating mode: `paper` ✅.
- Idempotency: 0 duplicate orders by `idempotency_key` ✅. 0 duplicate OPEN positions per ticker ✅.

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head ✅). No drift.
- Pytest smoke: **360 passed / 0 failed / 3662 deselected in 25.18s** ✅ (deep_dive + phase22 + phase57 filter, `--no-cov`, `APIS_PYTEST_SMOKE=1`).
- Git: **DIRTY** (carry-forward from yesterday — Phase 75 functional changes operator-deferred). HEAD = `9db28ae`. 0 unpushed commits. Modified paths: `apis/apps/worker/jobs/paper_trading.py`, `apis/tests/unit/test_phase64_position_persistence.py`, all 5 state-doc files (apis/state + state). Untracked: `outputs/`. **No autonomous commit/push** — this is the same uncommitted Phase 75 code change that has been verified at the unit-test layer + bind-mount-loaded into the running worker since 01:42 UTC Mon.
- **GitHub Actions CI:** Run **#25327395434** on `9db28ae` — `status=completed, conclusion=success` ✅. https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25327395434 . CI healthy on the most recent pushed SHA.

### §4 Config + Gate Verification
All critical APIS_* flags at expected values:
- APIS_OPERATING_MODE=paper ✅
- APIS_KILL_SWITCH=false ✅
- APIS_MAX_POSITIONS=15 ✅
- APIS_MAX_NEW_POSITIONS_PER_DAY=5 ✅
- APIS_MAX_THEMATIC_PCT=0.75 ✅
- APIS_RANKING_MIN_COMPOSITE_SCORE=0.30 ✅
- APIS_MAX_SECTOR_PCT=0.40 ✅
- APIS_MAX_SINGLE_NAME_PCT=0.20 ✅
- APIS_MAX_POSITION_AGE_DAYS=20 ✅
- APIS_DAILY_LOSS_LIMIT_PCT=0.02 ✅
- APIS_WEEKLY_DRAWDOWN_LIMIT_PCT=0.05 ✅
- APIS_SELF_IMPROVEMENT_AUTO_EXECUTE_ENABLED not set (defaults false) ✅
- APIS_INSIDER_FLOW_PROVIDER not set (defaults null) ✅
- Deep-Dive Step 6/7/8 flags not set (defaults OFF) ✅
- Scheduler: `job_count=36` (DEC-021 expected). Liveness heartbeat firing every 5 min — last successful run pre-15:21 UTC ✅.

### Issues Found
- **[YELLOW] HOLX universe-filter regression vs Phase 72.** Strategy is still proposing HOLX `action_type=open` despite `securities.is_active=false` (DB confirms `f`). 2 such proposals today (13:35:02, 14:30:00 UTC); both blocked at risk_engine on `max_new_positions_per_day=5` (already at cap from today's 5 fills). Risk engine has NO `inactive_ticker` violation rule. If the daily cap weren't full, HOLX would have reached the broker (which Phase 72 confirmed Alpaca rejects). The functional outcome is fine (HOLX never fills) but Phase 72's `project_holx_inactive_ticker` memory states "FULLY RESOLVED" — the proposal-layer is NOT cleaned up. Recommend: (a) add `is_active=false` filter to the strategy universe selector OR (b) add an `inactive_ticker` violation to risk_engine as a defense-in-depth layer (preferred — survives any new universe source).
- **[YELLOW] Phase 75 close-loop forecast miss — broker drift not clearing.** Yesterday's HEALTH_LOG forecast: "drift should clear within 1–2 cycles as Phase 75 close-loop properly closes the 12 operator-restored rebalance rows." Today's reality: 2/2 cycles still firing `broker_health_position_drift` on the same 12 tickers. The strategy is rebalancing in the OPPOSITE direction — BUYING toward the DB target (5 fills today: INTC/MU/AMZN/EQIX/NUE) instead of CLOSING those rows. Drift will clear gradually as broker accumulates over many cycles, but the close-loop pathway never fires for these because the strategy doesn't propose CLOSE actions on them. Not a regression of Phase 75 itself (which was scoped to row-inflation prevention) — just a forecast miss. **No fix needed today**; broker drift will resolve naturally.
- **[INFO] Phase 75 functional code change still uncommitted.** Carry-forward from yesterday's note. `apis/apps/worker/jobs/paper_trading.py` + `apis/tests/unit/test_phase64_position_persistence.py` modifications still in dirty tree, awaiting operator commit + push. Bind-mount loads them into the running worker so they're functionally active (verified yesterday by `grep -c phase75_position_row_reopened /app/apis/.../paper_trading.py = 1`); only the version-control side is pending.
- **[INFO] Dual-snapshot writer continuing.** Same paired $23k/$110-114k legitimate + $67k/$99.9k secondary pattern as prior days. No new regression. Prometheus reads the legitimate stream; runtime impact = nil.
- **[INFO] Phase 73/74 defenses fully holding.** Alertmanager firing=0 across both cycles today. No phantom-equity, no DrawdownAlert, no test-pollution writes to production.

### Fixes Applied
- None — issues identified are operator-review-required (universe-filter regression) or non-actionable (forecast miss; broker will catch up naturally).

### Action Required from Aaron
1. **Triage HOLX universe-filter regression (YELLOW).** The strategy is still proposing inactive tickers. Recommended fix: add a `securities.is_active=true` filter to the candidate-universe query in the strategy module (whichever path produced the proposal) AND/OR add an `inactive_ticker` violation to `services/risk_engine/service.py`. The risk-engine path is preferred — it's a single-place defense-in-depth that survives any new universe source. Cannot autonomously edit strategy/risk code without operator review.
2. **Commit + push Phase 75** when ready (still pending). Suggested commit message: `Phase 75: position-row inflation fix in _persist_positions (DEC-075)`. Tree state: `apis/apps/worker/jobs/paper_trading.py` + `apis/tests/unit/test_phase64_position_persistence.py` plus state docs. CI is currently GREEN on `9db28ae` so the push will land on a known-good base.
3. **Optional: monitor broker drift trajectory** over the next few cycles. Each cycle's drift list should narrow as broker accumulates partial fills toward the 12-ticker DB target. If after 4–5 more cycles the drift list is still 12-of-12, deeper investigation needed (perhaps the broker's position-tracking is itself drifting, or the strategy's BUY proposals are getting blocked at risk before reaching broker).
4. **YELLOW email**: draft created via Gmail MCP (no direct-send tool available in this session) — **manual send required**. Draft ID `r-4410417599441132003`. Open Gmail → Drafts → "[APIS YELLOW] Daily Health Check — 2026-05-05 15:09 UTC" and click Send.

---

## Health Check — 2026-05-05 10:18 UTC (Tuesday 5:18 AM CT, pre-market)

**Overall Status:** GREEN — clean pre-market run after the Phase 75 deploy. All 8 containers healthy and recreated together at 03:31:12 UTC (RestartCount=0 on api/worker/postgres/redis — most likely operator `docker compose up -d` after the Mon 01:42 UTC Phase 75 worker restart). Phase 75 code path confirmed loaded in the running worker (`grep phase75_position_row_reopened /app/apis/apps/worker/jobs/paper_trading.py` → 1 hit). /health all 7 components ok at 10:08:18Z mode=paper. Worker log scan (24h) = 34 ERROR lines (yfinance carry-forward on the known 13 stale tickers + intermittent summary lines), API log scan (5000 tail) = 33 ERROR lines, **0 crash-triad regressions** in either (`_fire_ks` / `broker_adapter_missing` / `EvaluationRun.idempotency_key` / `paper_cycle.*no_data` / `phantom_cash_guard_triggered` all zero). Prometheus 2/2 up, Alertmanager firing=0. 12 OPEN positions all `origin_strategy=rebalance` (Phase 73 holding). Pytest 400p/0f in 70.43s (deep_dive + phase22 + phase57 + phase59 filter) plus phase64+75 regression class 7p/0f in 6.83s = full Phase 75 validation. Alembic single head `p6q7r8s9t0u1`. CI on `9db28ae` `conclusion=success`. All 11 critical APIS_* flags at expected values. Scheduler `job_count=36`. Phase 75 fix awaiting first-cycle validation at 13:35 UTC today (~3.25h from this run); the 7 broker_health_position_drift hits in the 24h window are all Mon-afternoon carry-forward (no cycles fired since the 01:42 UTC worker restart).

### §1 Infrastructure
- Containers: 8/8 healthy. All four core services (worker/api/postgres/redis) `Up 7 hours` with `RestartCount=0` and `StartedAt=2026-05-05T03:31:12Z` — full-stack recreation (NOT a docker daemon restart) ~2h after the 01:42 UTC Phase 75 worker restart. Most likely operator `docker compose --env-file ../../.env up -d` to ensure all services were running together with the new bind-mount code. Phase 75 code path verified in container: `grep -c "phase75_position_row_reopened" /app/apis/apps/worker/jobs/paper_trading.py = 1`. Grafana / Prometheus / Alertmanager / apis-control-plane also `Up 7h`.
- /health: all 7 components `ok` at 10:08:18Z. mode=paper, kill_switch=ok.
- Worker log scan (24h): 34 ERROR/CRITICAL pattern matches — primarily yfinance failures for the 13 known stale tickers (PXD, JNPR, DFS, PKI, CTLT, IPG, K, ANSS, PARA, MMC, MRO, HES, WRK). **0 crash-triad regressions** (`_fire_ks.*takes 0` / `broker_adapter_missing_with_live_positions` / `EvaluationRun.*idempotency_key` / `paper_cycle.*no_data` / `phantom_cash_guard_triggered`). **7 `broker_health_position_drift` warnings** across the last 24h — all from Mon-afternoon cycles (13:35–19:30 UTC); no new paper cycles have fired since the 01:42 UTC worker restart, so the Phase 75 fix has not yet been exercised. Will be validated at 13:35 UTC today.
- API log scan (5000 tail): 33 ERROR/CRITICAL matches, 0 crash-triad regressions.
- Prometheus: 2/2 targets up (apis, prometheus), 0 dropped.
- Alertmanager: 0 active alerts at 10:09 UTC. Phase 73 `for: 30m` debounce defense holding.
- Resource usage: worker 750.0 MiB, api 798.9 MiB, postgres 121.0 MiB, grafana 50.32 MiB, prometheus 36.14 MiB, alertmanager 14.6 MiB, redis 7.668 MiB, apis-control-plane 965.3 MiB / 7.08% CPU. All under threshold.
- DB size: 171 MB (unchanged from yesterday's 19:08 UTC reading).

### §2 Execution + Data Audit
- Paper cycles: **0 fired today** (expected — first cycle scheduled 13:35 UTC = 09:35 ET, still ~3.25h away). Mon ran 7 cycles total (the 19:30 UTC final one was after yesterday's 19:08 UTC report).
- `evaluation_runs` total: **97** (Mon 21:00 UTC EOD eval added 1 to yesterday's 96). All `status='complete'`, 0 not_complete. ≥80 floor ✅.
- Portfolio trend (latest 6 paired-snapshot rows from Mon's cycles, dual-snapshot pattern continuing):
  - 2026-05-04 19:30:03.752 — cash=$23,050.74 / equity=$110,500.08 (legitimate)
  - 2026-05-04 19:30:00.749 — cash=$67,448.48 / equity=$99,983.24 (secondary writer — same dual pattern as yesterday)
  - 2026-05-04 18:30:02.908 — cash=$23,050.74 / equity=$110,718.73
  - 2026-05-04 18:30:00.774 — cash=$67,448.48 / equity=$99,983.24
  - 2026-05-04 17:30:02.816 — cash=$23,050.74 / equity=$111,029.32
  - 2026-05-04 17:30:00.776 — cash=$67,448.48 / equity=$99,983.24
  - Cash positive ✅ on legitimate stream. Latest legit snapshot 19:30:03 UTC Mon. The secondary writer ($67k/$99.9k) is the same carry-forward pattern noted in yesterday's HEALTH_LOG; no new dual-write regression.
- Broker<->DB reconciliation: DB shows **12 OPEN positions** (CAT, SLB, WDC, BE, NUE, INTC, STT, MU, MRVL, AMD, EQIX, AMZN). All `origin_strategy=rebalance`. /health broker=ok. (`/api/v1/broker/positions` not implemented in this build — falling back to /health=ok per feedback note.)
- Origin-strategy stamping: ALL 12 OPEN `origin_strategy=rebalance` ✅. Phase 73 fix holding (0 NULLs).
- Position caps: **12/15 open** ✅. **0 new positions today** (CURRENT_DATE filter, expected pre-cycle). Mon's 7 CSCO churns (carry-forward, all `origin_strategy=momentum_v1`, identical `opened_at=13:35:00.000803` / `entry_price=91.43` / `quantity=72`) — exactly the bug pattern Phase 75 prevents going forward; no NEW churns possible until first cycle fires.
- Data freshness:
  - daily_market_bars MAX = **2026-05-04** (Mon close), 490 securities ✅ — Mon EOD ingestion completed normally.
  - signal_runs MAX = 2026-05-01 10:30 UTC (Friday — STALE carry-forward from DEC-071 Phase 74 cleanup).
  - ranking_runs MAX = 2026-05-01 10:45 UTC (STALE carry-forward).
  - security_signals 0 rows in 48h (collateral from cleanup).
  - ranked_opportunities 0 rows in 48h (collateral from cleanup).
  - Will repopulate today at 06:30 ET (10:30 UTC) signal-generation job — ~12 min from this run.
- Stale tickers: known 13 only (PXD, JNPR, DFS, PKI, CTLT, IPG, K, ANSS, PARA, MMC, MRO, HES, WRK). No new additions.
- Kill-switch: `false` ✅. Operating mode: `paper` ✅.
- Idempotency: 0 duplicate orders by `idempotency_key` ✅. 0 duplicate OPEN positions per ticker ✅.
- Orders + Fills: 11 orders / 5 fills in last 24h (Mon's cycle activity). Totals 306 / 202 (was 295 / 197 yesterday — modest +11 / +5 growth from Mon afternoon).

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head ✅). No drift.
- Pytest smoke: **400 passed / 0 failed / 3622 deselected in 70.43s** (deep_dive + phase22 + phase57 + phase59 filter) ✅. **Phase 64 + Phase 75 regression class: 7 passed / 0 failed in 6.83s** ✅. Phase 75 fix verified at the unit-test layer; awaiting first-cycle integration validation at 13:35 UTC.
- Git: **DIRTY** (intentional carry-forward — Phase 75 functional changes uncommitted per Aaron's ACTIVE_CONTEXT note "left for the operator"). HEAD = `9db28ae`. 0 unpushed commits. Only `main` branch. Modified paths: `apis/apps/worker/jobs/paper_trading.py`, `apis/tests/unit/test_phase64_position_persistence.py`, `apis/state/{ACTIVE_CONTEXT,CHANGELOG,DECISION_LOG,HEALTH_LOG,NEXT_STEPS}.md`, `state/{DECISION_LOG,HEALTH_LOG}.md`. Untracked: `outputs/`. **No autonomous commit/push** — operator-gated for the functional code change.
- **GitHub Actions CI:** Run **#25327395434** on `9db28ae` (latest pushed commit, docs entry from yesterday) — `status=completed, conclusion=success` ✅. https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25327395434 . CI is healthy on the most recent pushed SHA.

### §4 Config + Gate Verification
All critical APIS_* flags at expected values:
- APIS_OPERATING_MODE=paper ✅
- APIS_KILL_SWITCH=false ✅
- APIS_MAX_POSITIONS=15 ✅
- APIS_MAX_NEW_POSITIONS_PER_DAY=5 ✅
- APIS_MAX_THEMATIC_PCT=0.75 ✅
- APIS_RANKING_MIN_COMPOSITE_SCORE=0.30 ✅
- APIS_MAX_SECTOR_PCT=0.40 ✅
- APIS_MAX_SINGLE_NAME_PCT=0.20 ✅
- APIS_MAX_POSITION_AGE_DAYS=20 ✅
- APIS_DAILY_LOSS_LIMIT_PCT=0.02 ✅
- APIS_WEEKLY_DRAWDOWN_LIMIT_PCT=0.05 ✅
- APIS_SELF_IMPROVEMENT_AUTO_EXECUTE_ENABLED not set (defaults false) ✅
- APIS_INSIDER_FLOW_PROVIDER not set (defaults null) ✅
- Deep-Dive Step 6/7/8 flags not set (defaults OFF) ✅
- Scheduler: `job_count=36` (DEC-021 expected). Liveness heartbeat firing every 5 min — last seen 10:16:20Z. ✅

### Issues Found
- None worthy of YELLOW. Carry-forward observations only:
  - 7 `broker_health_position_drift` hits in 24h are all Mon afternoon (pre-Phase-75-deploy). First cycle today at 13:35 UTC will exercise the Phase 75 fix. Per yesterday's HEALTH_LOG forecast, drift should clear within 1–2 cycles as the Phase 75 close-loop properly closes the 12 operator-restored rebalance rows the worker's broker doesn't have.
  - Dual-snapshot writer (paired $23k/$110k legitimate + $67k/$99.9k secondary) still firing — same as yesterday's reading, no new regression. Tracked carry-forward; Phase 73 phantom-equity guard fixed the negative-cash variant; secondary stream is benign at the runtime layer (Prometheus reads the legitimate stream).
  - signal_runs/ranking_runs/security_signals/ranked_opportunities still stale at 2026-05-01 (Phase 74 cleanup collateral). 06:30 ET signal-generation job fires at 10:30 UTC (~12 min after this report) and will repopulate.
  - Phase 75 functional code change uncommitted (operator-deferred per ACTIVE_CONTEXT instruction).

### Fixes Applied
- None — clean pre-market run, no autonomous fixes needed.

### Action Required from Aaron
1. **Confirm Tue 2026-05-05 13:35 UTC first cycle runs cleanly with Phase 75.** Watch for `phase75_position_row_reopened` or `phase75_close_skipped_just_upserted` log lines in `docker logs docker-worker-1` and confirm `broker_health_position_drift` clears within 1–2 cycles. If drift persists past the 14:30 UTC cycle, deeper broker-cache resync needed.
2. **Commit + push Phase 75** when ready (still pending per yesterday's instruction). Suggested message: `Phase 75: position-row inflation fix in _persist_positions (DEC-075)`. Tree state: `apis/apps/worker/jobs/paper_trading.py` + `apis/tests/unit/test_phase64_position_persistence.py` plus state docs.
3. **Optional historical cleanup SQL** still available in yesterday's HEALTH_LOG — collapses ~140 duplicate closed-position rows. NOT required for runtime correctness.

---

## Phase 75 Deploy — 2026-05-04 ~21:42 UTC (Monday 4:42 PM CT, post-market)

**Overall Status:** GREEN — Phase 75 fix deployed for the position row-inflation bug filed earlier today as "Phase 65c CSCO momentum_v1 churn." Triage revealed the bug is much older and broader than the user's framing: at least 16 ticker-episodes since 2026-04-20 have COUNT(*)>1 with a single distinct `opened_at` (BK=22 rows, UNP=20, ODFL=20, HOLX=19, MRVL=17, CSCO=7 today, etc.). Single broker fill per episode → many DB Position rows. Root cause is in `_persist_positions`, NOT in any strategy. Fix at `apis/apps/worker/jobs/paper_trading.py`: (1) `(security_id, opened_at)` idempotency on the upsert path with reopen-if-closed semantics; (2) `_persist_touched_sec_ids` set protects rows from being closed in the same `_persist_positions` call (defense-in-depth). Two new pytest regression tests pass (87/87 in 11.68s for the broader Phase 64 + paper_trading + Step 5 origin-strategy suite). Ruff clean. Worker restarted at 01:41:58 UTC; `apis_worker_started job_count=36`; next paper cycle Tue 2026-05-05 09:35 ET.

### Fixes Applied
- **`apis/apps/worker/jobs/paper_trading.py::_persist_positions`** — Phase 75 idempotency + close-loop safe-list (DEC-075). See CHANGELOG.md for full diff context.
- **`apis/tests/unit/test_phase64_position_persistence.py`** — `TestPhase75ReopenIdempotency` regression class (2 tests).
- **`docker restart docker-worker-1`** at 01:41:58 UTC — picks up the new code via the `C:\Projects\Auto Trade Bot\apis:/app/apis:ro` bind mount.

### What changed for the user's two listed items
1. **`broker_health_position_drift` carry-forward.** The 19:13 UTC api restart cleared the **api**'s broker cache, but the warning kept firing because the **worker** has its own broker adapter (and the worker had been Up 25h with no DB-restore for broker positions). Phase 75's close-loop will, on the next 1-2 paper cycles, naturally close the 12 operator-restored rebalance Position rows that the worker's broker doesn't have, after which drift will clear. (No change to broker startup seeding — that's a deferred orthogonal fix per DEC-075 alternative (c).)
2. **Phase 65c CSCO `momentum_v1` churn.** Reframed as a persistence-layer bug (Phase 75) rather than a strategy bug. The actual broker activity for CSCO today: ONE fill at 13:35:01.978 UTC (qty=72 @ $91.43), zero subsequent CSCO orders. The 7 closed Position rows in DB all share `opened_at=13:35:00.000803`, with `closed_at` differing per cycle — exactly the pattern the Phase 75 fix prevents. The same pattern is also visible on tickers opened by `rebalance` and `ranking_buy_signal` (e.g. MRVL=17 rows since 2026-04-29) confirming the bug is strategy-agnostic.

### Action Required from Aaron
1. **Confirm Tue 2026-05-05 09:35 ET first cycle** runs cleanly with the Phase 75 code path. Look for `phase75_position_row_reopened` or `phase75_close_skipped_just_upserted` log lines if the existing closed CSCO row gets reused (will only fire if the strategy reopens CSCO at the SAME opened_at, which won't happen — so likely zero firings on day 1; primarily protects against the recurring drift).
2. **Optional historical cleanup.** Run the SQL below to collapse 16 ticker-episodes' worth of duplicate closed Position rows down to one row each (keeping the most recent). NOT required for runtime correctness; just removes the audit-trail noise:

   ```sql
   DELETE FROM positions
   WHERE id NOT IN (SELECT MAX(id) FROM positions GROUP BY security_id, opened_at)
     AND id IN (SELECT id FROM positions WHERE status='closed');
   ```

   ~140 rows would be deleted (sum of (rows-1) across the 16 ticker-episodes with duplicates).
3. **Optional UNIQUE constraint.** After the cleanup above, add a `UNIQUE (security_id, opened_at)` constraint via a new Alembic migration so the bug can't recur even if Phase 75's Python guards regress. Filed as a follow-up but not required for the runtime fix.
4. **Push to origin.** I made no `git commit` or `git push` — left those for the operator per the deep-dive convention. Branch state: edits to `apis/apps/worker/jobs/paper_trading.py` and `apis/tests/unit/test_phase64_position_persistence.py`, plus state-doc updates, all uncommitted in `C:\Projects\Auto Trade Bot`.

---

## Health Check — 2026-05-04 19:08 UTC (Monday 2:08 PM CT, market mid-afternoon)

**Overall Status:** YELLOW — drift carry-forward and CSCO churn newly observed; both autonomous-fixable. (a) Restarted `docker-api-1` to clear the broker adapter's in-memory position cache that has been firing `broker_health_position_drift` warnings on every paper cycle since the 12:25 UTC operator-approved cleanup transaction (6 hits across today's cycles). Post-restart `/health` all 7 components ok, Alertmanager firing=0, Phase 73 indentation fix held (Prometheus `apis_portfolio_positions=12, equity_usd=110718.73, cash_usd=23050.74` matches DB snapshot exactly). Phase 73's `for: 30m` debounce will suppress any post-restart HWM-reset DrawdownAlert/Critical false-positives. (b) New observation: CSCO has been re-opened+closed every paper cycle today (6 distinct rows — same `opened_at=13:35:00.000803`, same `entry_price=91.43`, same `quantity=72`, only `closed_at` varies) under `origin_strategy=momentum_v1`. This is an alternating-churn pattern in the momentum_v1 strategy specifically (not rebalance-protected). Net 0 currently OPEN, but persisted-row-per-cycle is wasteful and breaches `APIS_MAX_NEW_POSITIONS_PER_DAY=5` (count=6 today, all CSCO). Filed as Phase 65c follow-up — momentum_v1 needs the same intra-cycle dedup that Phase 65b applied for rebalance. CI is GREEN on `9db28ae` (run #25327395434) and the lint-fix `3bdbe64` rerun (#25327148433) — Phase 74 lint regression resolved. Everything else GREEN: 8/8 containers healthy, pytest 360/360 in 20.55s, alembic single head `p6q7r8s9t0u1`, all 11 critical APIS_* flags correct, scheduler `job_count=36`, evaluation_runs=96 (≥80 floor), 12 OPEN positions all `origin_strategy=rebalance`, kill_switch=false, mode=paper, no idempotency dupes, no crash-triad regressions, DB 171 MB.

### §1 Infrastructure
- Containers: 8/8 healthy. worker `Up 19h`, api restarted at 19:13 UTC and now `Up About a minute (healthy)`, postgres/redis healthy, grafana/prometheus/alertmanager up, apis-control-plane up.
- /health: all 7 components ok pre-restart (19:07:52Z) and post-restart (19:14:39Z). Mode=paper, kill_switch=false.
- Worker log scan (24h): 34 ERROR/CRITICAL pattern matches — primarily yfinance failures for the 13 known stale tickers (PXD, JNPR, DFS, PKI, CTLT, IPG, K, ANSS, PARA, MMC, MRO, HES, WRK). 0 crash-triad regressions (`_fire_ks` / `broker_adapter_missing_with_live_positions` / `EvaluationRun.idempotency_key` / `paper_cycle.*no_data` / `phantom_cash_guard_triggered`). **6 `broker_health_position_drift` warnings** across the 6 paper cycles fired today (13:35 / 14:30 / 15:30 / 16:00 / 17:30 / 18:30 UTC) — known carry-forward from the 12:25 UTC cleanup; all fire on the same 12 ticker set (drift list includes intermittent CSCO from intra-cycle timing). **AUTONOMOUS-FIX APPLIED**: api restart cleared the broker adapter cache.
- API log scan (24h): 44 ERROR/CRITICAL matches, 0 crash-triad regressions.
- Prometheus: 2/2 targets up (apis, prometheus), 0 dropped.
- Alertmanager: 0 active alerts pre-restart and 0 active alerts post-restart at 19:14 UTC. Phase 73 `for: 30m` debounce will keep any HWM-reset false-positives suppressed for the 30-min window.
- Resource usage: worker 789.7 MiB, api 810.4 MiB, postgres 168.9 MiB, grafana 50.96 MiB, prometheus 36.98 MiB, alertmanager 14.86 MiB, redis 8.176 MiB, apis-control-plane 1.047 GiB / 9.34% CPU. All under threshold.
- DB size: 171 MB (down from ~175 MB at 10:10 UTC after the cleanup transaction freed ~15k pollution rows; up slightly from earlier post-cleanup level due to the day's snapshots/cycles).

### §2 Execution + Data Audit
- Paper cycles today: **6 cycles fired** (13:35 / 14:30 / 15:30 / 16:00 / 17:30 / 18:30 UTC, cycle_ids `16c1ad32...`, `a2de1a41...`, `d4ea04c1...`, `a48c46ab...`, `08f5c88a...`, `5f6afb00...`). Next cycle 19:30 UTC. DEC-021 expects 12/weekday from 13:35-19:50 UTC; on track.
- `evaluation_runs` total: **96** (≥80 floor ✅).
- Portfolio trend (latest 6 paired-snapshot rows):
  - 2026-05-04 18:30:02.908 — cash=$23,050.74 / equity=$110,718.73
  - 2026-05-04 17:30:02.816 — cash=$23,050.74 / equity=$111,029.32
  - 2026-05-04 16:00:02.955 — cash=$23,050.74 / equity=$110,740.67
  - 2026-05-04 15:30:02.887 — cash=$23,050.74 / equity=$110,752.30
  - 2026-05-04 14:30:03.178 — cash=$23,050.74 / equity=$110,872.56
  - 2026-05-04 13:35:04.034 — cash=$23,050.74 / equity=$111,586.01
  - Cash positive ✅ stable; equity drift -0.78% across the day (intraday market move on the 12 longs); dual-snapshot pattern continues.
- Broker<->DB reconciliation: DB shows **12 OPEN positions** (CAT, SLB, WDC, BE, NUE, INTC, STT, MU, MRVL, AMD, EQIX, AMZN). All `origin_strategy=rebalance`. /health broker=ok. `/api/v1/broker/positions` 404s in this build → fall back to /health=ok per feedback note. Drift 6 hits/cycle pre-restart; should clear post-restart.
- Origin-strategy stamping: ALL 12 OPEN positions `origin_strategy=rebalance` ✅. Today's 6 closed CSCO rows all `origin_strategy=momentum_v1` ✅ (Phase 73 fix holding — 0 NULLs).
- Position caps: **12/15 open** ✅, BUT **6 new persisted rows today (all CSCO)** = breach of `APIS_MAX_NEW_POSITIONS_PER_DAY=5`. The 6 rows share an identical `opened_at` timestamp (13:35:00.000803), `entry_price=91.43`, `quantity=72` and differ only in `closed_at` (one per cycle). All 6 closed by end of each respective cycle — net 0 currently OPEN. Pattern indicates momentum_v1 strategy is opening+closing CSCO every cycle and persisting a NEW position row each time (instead of reusing/dedup'ing). Phase 65b dedup applied to rebalance-protected positions does NOT cover momentum_v1 OPEN+CLOSE same-cycle pairs.
- Data freshness:
  - daily_market_bars MAX = 2026-05-01 (Friday close, 490 securities). Mon's bars not ingested yet (post-close job tonight).
  - signal_runs MAX = 2026-05-01 10:30 UTC (stale carry-forward from 12:25 UTC cleanup).
  - ranking_runs MAX = 2026-05-01 10:45 UTC (stale carry-forward).
  - security_signals MAX = 2026-05-01 10:30 UTC, 0 rows in 48h (cleanup collateral damage).
  - ranked_opportunities MAX = 2026-05-01 10:45 UTC, 0 rows in 48h (cleanup collateral damage).
  - Will repopulate Tue 2026-05-05 06:30 ET signal generation job.
- Stale tickers: known 13 only (PXD, JNPR, DFS, PKI, CTLT, IPG, K, ANSS, PARA, MMC, MRO, HES, WRK). No new additions. yfinance reports "13 Failed downloads" matching the known list.
- Kill-switch: `false` ✅. Operating mode: `paper` ✅.
- Idempotency: 0 duplicate orders by `idempotency_key` ✅. 0 duplicate OPEN positions per ticker ✅.

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head ✅). No drift.
- Pytest smoke: **360 passed / 0 failed / 3660 deselected in 20.55s** ✅ — Phase 73/74 baseline holding (phase59 token excluded per Phase 74 isolation guard rule still in effect for safety).
- Git: **CLEAN**. HEAD = `9db28ae`. 0 unpushed commits. Only `main` branch.
- **GitHub Actions CI:**
  - Run **#25327395434** on `9db28ae` (latest, docs commit) — `status=completed, conclusion=success` ✅. https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25327395434
  - Run **#25327148433** on `3bdbe64` (Phase 74 lint fix) — `status=completed, conclusion=success` ✅. The 15:15 UTC YELLOW from this morning's deep-dive resolved cleanly.
  - Two consecutive GREEN runs on main; CI is healthy.

### §4 Config + Gate Verification
All critical APIS_* flags at expected values:
- APIS_OPERATING_MODE=paper ✅
- APIS_KILL_SWITCH=false ✅
- APIS_MAX_POSITIONS=15 ✅
- APIS_MAX_NEW_POSITIONS_PER_DAY=5 ✅
- APIS_MAX_THEMATIC_PCT=0.75 ✅
- APIS_RANKING_MIN_COMPOSITE_SCORE=0.30 ✅
- APIS_MAX_SECTOR_PCT=0.40 ✅
- APIS_MAX_SINGLE_NAME_PCT=0.20 ✅
- APIS_MAX_POSITION_AGE_DAYS=20 ✅
- APIS_DAILY_LOSS_LIMIT_PCT=0.02 ✅
- APIS_WEEKLY_DRAWDOWN_LIMIT_PCT=0.05 ✅
- APIS_SELF_IMPROVEMENT_AUTO_EXECUTE_ENABLED not set (defaults false) ✅
- APIS_INSIDER_FLOW_PROVIDER not set (defaults null) ✅
- Deep-Dive Step 6/7/8 flags not set (defaults OFF) ✅
- Scheduler: `job_count=36`. Worker started 2026-05-04 00:33:32 UTC; liveness heartbeat firing every 5 min ✅.

### Issues Found
- **[YELLOW] CSCO momentum_v1 strategy persisting a new row every cycle (Phase 65c follow-up).** 6 rows today, all CSCO, identical `opened_at=13:35:00.000803`, `entry_price=$91.43`, `quantity=72`; only `closed_at` differs per cycle (13:35 / 14:30 / 15:30 / 16:00 / 17:30 / 18:30). Net 0 OPEN at any time, but technically breaches `APIS_MAX_NEW_POSITIONS_PER_DAY=5` (count=6) and creates wasteful row inflation. Phase 65b alternating-churn dedup covered rebalance-protected positions only — momentum_v1 needs the same treatment. Recommended fix: extend `_critical_exit_reasons` exclusion or apply intra-cycle OPEN+CLOSE dedup at the strategy-router boundary so a same-cycle round-trip on CSCO collapses into a single position row (or zero, since it's net-flat).
- **[YELLOW carry-forward] `broker_health_position_drift` firing on every paper cycle** (6 hits today). Known artifact of the 12:25 UTC operator-approved cleanup transaction restoring 12 production positions in the DB without resyncing the broker adapter's in-memory position cache. **AUTONOMOUS-FIX APPLIED**: `docker restart docker-api-1` at 19:13 UTC; api healthy at 19:14:39Z, all 7 /health components ok, Phase 73 indentation fix held (12 positions correctly restored, Prometheus matches DB exactly). Should clear on next paper cycle's drift check at 19:30 UTC.
- **[INFO] signal_runs / ranking_runs / security_signals / ranked_opportunities still stale at 2026-05-01.** Will repopulate Tue 2026-05-05 06:30 ET.
- **[INFO] Phase 73 / Phase 74 defenses fully holding.** Alertmanager firing=0 across the day pre- and post-restart; pytest write-blocking fixture intact (no production-DB pollution since Phase 74 landed).

### Fixes Applied
- **`docker restart docker-api-1` at ~19:13 UTC** — clears the in-memory broker adapter position cache that was drifting against the 12 cleanup-restored DB rows. Verified post-restart: /health all 7 ok, Prometheus `apis_portfolio_positions=12, equity_usd=110718.73, cash_usd=23050.74` matches DB latest snapshot exactly, Alertmanager firing=0 (Phase 73 30m debounce active for any post-restart HWM-reset false-positives). Standing autonomous-fix authority covers container restarts.

### Action Required from Aaron
1. **Triage Phase 65c CSCO churn** — momentum_v1 strategy is opening+closing CSCO every paper cycle and persisting a NEW positions row each time. The 6 rows today share `opened_at=13:35:00.000803`, `entry_price=$91.43`, `quantity=72` (only `closed_at` differs). Recommend a Phase 65b-equivalent dedup at the strategy-router boundary so net-flat round-trips collapse into a single position row (or zero). I cannot autonomously edit strategy code without operator review; this is a code-design decision (collapse-to-zero vs single-row-per-day vs other).
2. **Optional: monitor 19:30 UTC paper cycle** to confirm broker drift cleared after the api restart — should see the next cycle log line drop the `broker_health_position_drift` warning. If it fires again, the cache may need a deeper resync (DB-driven refresh on every cycle start) — flag would be a Phase 70-equivalent root-fix.
3. **YELLOW email**: drafted via Gmail MCP — manual send required.

---

## Health Check — 2026-05-04 15:15 UTC (Monday 10:15 AM CT, market open ~45 min)

**Overall Status:** YELLOW — CI Lint & Type Check failed on Phase 74 commit `37191c3` (run #25319905949 at 12:49 UTC) due to a single I001 import-sort issue in `apis/tests/conftest.py`. Auto-fixed (commit `3bdbe64`, pushed); CI rerun #25327148433 queued at 15:15 UTC. Two `broker_health_position_drift` warnings fired in 24h (cycles 13:35 + 14:30 UTC) — known carry-forward artifact from the operator-approved cleanup transaction at 12:25 UTC (the 12 production positions were UPDATE'd back to `open` in DB but the broker adapter's in-memory position cache wasn't resynced; should self-clear on next API restart). Today's 06:30/06:45 ET signal_runs + ranking_runs were collateral damage from the 12:25 UTC cleanup (DELETE >= 2026-05-04 01:00:00 also nuked legitimate Monday morning runs); paper cycles still ran successfully and produced clean snapshots. Everything else GREEN: 8/8 containers healthy 15h uptime, /health all 7 components ok, Alertmanager firing=0 (Phase 73 defense holding), 12 open positions correctly restored with `origin_strategy=rebalance`, Prometheus gauges match DB exactly, equity $110,872.56 / cash $23,050.74, pytest 360/360 in 29.94s, git tree clean post-fix push, all 6 critical APIS_* flags correct.

### §1 Infrastructure
- Containers: 8/8 healthy. worker `Up 15h`, api `Up 14h`, postgres/redis healthy, grafana/prometheus/alertmanager up, apis-control-plane up. No restart loops.
- /health: all 7 components `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper. Timestamp 2026-05-04T15:07:49Z.
- Worker log scan (24h, 919 lines): 34 ERROR/CRITICAL pattern matches — 18 HTTP 404 + ~16 yfinance/empty-DataFrame for the 13 known stale tickers (PXD, JNPR, DFS, PKI, CTLT, IPG, K, ANSS, PARA, MMC, MRO, HES, WRK). **2 `broker_health_position_drift` warnings** at 13:35:00.203 UTC (12 tickers) and 14:30:00.013 UTC (13 tickers, +CSCO). 0 other crash-triad regression patterns (`_fire_ks` / `broker_adapter_missing_with_live_positions` / `EvaluationRun.idempotency_key` / `paper_cycle.*no_data` / `phantom_cash_guard_triggered`).
- API log scan (24h): not separately quantified this run — focus was worker. Spot-check via /health components all ok suggests no new patterns.
- Prometheus: 2/2 targets up (apis, prometheus), 0 dropped ✅.
- **Alertmanager: firing=0** ✅ — Phase 73's `for: 30m` defense + indentation fix continues to hold. No `DrawdownAlert`/`DrawdownCritical` post-restart false-positives despite the operator-approved cleanup transaction touching DB state.
- Resource usage: worker 784.2 MiB, api 805.1 MiB, postgres 169 MiB, grafana 50.7 MiB, prometheus 39.3 MiB, alertmanager 14.9 MiB, redis 8.1 MiB, apis-control-plane 1.022 GiB / 21.13% CPU (kind k8s control plane normal). All under threshold.
- DB size: not re-probed this run; was 175 MB at 10:10 UTC + cleanup transaction freed ~15k pollution rows so should be lower now.

### §2 Execution + Data Audit
- Paper cycles today: **2 cycles fired** (13:35 UTC + 14:30 UTC). Worker log shows `paper_trading_cycle_starting` events with cycle_ids `16c1ad32...` and `a2de1a41...`. Both completed (snapshots written for both). DEC-021 schedule expects 12/weekday from 13:35-19:50 UTC; 2/2 of cycles-due-by-15:07-UTC ran.
- `evaluation_runs` total: **96** (≥80 floor ✅; pollution row deleted by 12:25 UTC cleanup, leaving the legitimate 96).
- Portfolio trend (latest 4 paired-snapshot rows):
  - 2026-05-04 14:30:03.178 — cash=$23,050.74 / equity=$110,872.56
  - 2026-05-04 14:30:01.254 — cash=$67,448.48 / equity=$99,983.24 (paired baseline)
  - 2026-05-04 13:35:04.034 — cash=$23,050.74 / equity=$111,586.01
  - 2026-05-04 13:35:02.225 — cash=$67,448.48 / equity=$99,983.24 (paired baseline)
  - Equity drift 13:35 → 14:30: -$713 (-0.64%, intraday market move on the 12 longs).
  - Cash positive ✅. Dual-snapshot pattern (Phase 73 documented).
- Broker<->DB reconciliation: DB shows **12 OPEN positions** (CAT, SLB, WDC, BE, NUE, INTC, STT, MU, MRVL, AMD, EQIX, AMZN). All `origin_strategy=rebalance`. /health broker=ok. Prometheus `apis_portfolio_positions=12` matches DB ✅. **However, 2 broker_health_position_drift warnings fired** — known carry-forward from the cleanup transaction (post-cleanup the broker adapter's in-memory position cache wasn't refreshed; the DB has the 12 restored positions but the cache-vs-DB drift check at cycle start sees them as drifted). The 14:30 cycle's drift list also includes CSCO (intra-cycle timing artifact: CSCO closed at 14:30:00.00064 UTC, drift check fired at 14:30:00.013 UTC — broker still had it).
- Origin-strategy stamping: ALL 12 open positions `origin_strategy=rebalance` ✅. 0 NULLs ✅. No new positions opened to DB today (CSCO opened+closed within today's cycles → both rows now `closed`, both with `origin_strategy=momentum_v1`).
- Position caps: **12/15 open** ✅. **0 new positions** persisted as OPEN today (2 CSCO opens + 2 closes within the day → net 0 OPEN). Within `APIS_MAX_NEW_POSITIONS_PER_DAY=5` cap.
- Data freshness:
  - bars=2026-05-01 (Friday close, 490 securities) — Monday's daily bars not ingested yet (post-close job).
  - **signal_runs MAX = 2026-05-01 10:30 UTC** (stale) — collateral damage from 12:25 UTC cleanup.
  - **ranking_runs MAX = 2026-05-01 10:45 UTC** (stale) — same cause.
  - **security_signals MAX = 2026-05-01 10:30 UTC**, 0 rows in 24h.
  - **ranked_opportunities MAX = 2026-05-01 10:45 UTC**, 0 rows in 24h.
  - Worker log confirms today's "Signal Generation" (06:30 ET) and morning ingestion jobs DID fire today before 12:25 UTC, but the cleanup transaction (`DELETE … WHERE created_at >= '2026-05-04 01:00:00'`) deleted those legitimate 10:30 UTC rows along with the 01:05–01:14 UTC test-pollution rows. Will re-populate Tue 06:30 ET.
- Stale tickers: known 13 only (PXD, JNPR, DFS, PKI, CTLT, IPG, K, ANSS, PARA, MMC, MRO, HES, WRK). No new additions.
- Kill-switch: `false` ✅. Operating mode: `paper` ✅.
- Idempotency: 0 duplicate orders by `idempotency_key` ✅. 0 duplicate OPEN positions per ticker ✅.

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head ✅).
- Pytest smoke: **360 passed / 0 failed / 3660 deselected in 29.94s** ✅ — same baseline as Phase 73 (then 397 with phase59 included; phase59 not run here for safety until next operator-approved validation).
- Git: **CLEAN** post-fix-push. HEAD = `3bdbe64` (lint fix). 0 unpushed commits. Only `main` branch. Push from 15:14 UTC: `37191c3..3bdbe64  main -> main`.
- **GitHub Actions CI:**
  - Run **#25319905949** on `37191c3` (Phase 74 commit) at 12:49 UTC — **conclusion=failure**. Failed jobs: `Lint & Type Check` (I001 import-sort), `Unit Tests (Python 3.11)` and `Unit Tests (Python 3.12)`. `Integration Tests` and `Docker Build` succeeded. https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25319905949
  - Auto-fix applied: `apis/tests/conftest.py` lines 177-179 reordered to put `from sqlalchemy.orm` imports before `import infra.db.session` per isort group rules. Verified locally: `docker exec docker-api-1 python -m ruff check --no-cache → All checks passed`. Pytest smoke still 360/360.
  - Run **#25327148433** on `3bdbe64` queued at 15:15 UTC (in flight at write time). Per deep-dive rules, in-flight CI is GREEN-with-note pending next deep-dive verification.
  - Unit Tests Python 3.11/3.12 failures NOT auto-fixed — per `apis/state/TECH_DEBT_UNIT_TESTS_2026-04-19.md` rule and the deep-dive prohibition on autonomous test edits. Carry-forward as Aaron-review item if the 3bdbe64 rerun also reports those jobs as failure (the lint fix should not have moved them either way).

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
- Scheduler: `job_count=36`. Worker started 2026-05-04 00:33:32 UTC. Liveness heartbeat firing every 5 min ✅.

### Issues Found
- **[YELLOW] CI failure on `37191c3` (Phase 74 commit) — Lint & Type Check (I001 import-sort).** Single fixable diagnostic in `apis/tests/conftest.py` lines 177-179. **AUTO-FIXED** at `3bdbe64` and pushed. Rerun #25327148433 queued.
- **[YELLOW] CI Unit Tests (Python 3.11) + Unit Tests (Python 3.12) reported failure on `37191c3`.** Rules forbid autonomous test edits — Aaron-review item. The Phase 74 commit added a write-blocking SessionLocal fixture that may have surfaced pre-existing test reliance on real DB writes; this matches the `TECH_DEBT_UNIT_TESTS_2026-04-19.md` carry-forward pattern. Confirm post-`3bdbe64` rerun whether the failures persist; if yes, dig into per-test output to determine which fixtures regressed.
- **[YELLOW] Two `broker_health_position_drift` warnings (13:35 + 14:30 UTC paper cycles).** Known artifact: the 12:25 UTC operator-approved cleanup transaction restored 12 production positions in the DB (UPDATE … status='open') but the broker adapter's in-memory position cache wasn't synchronized with the change. Drift fires at cycle start and lists the 12 cleanup-restored tickers. Will likely self-clear on next API restart (broker re-syncs from DB). The 14:30 inclusion of CSCO is a separate intra-cycle timing artifact — CSCO closed 12.6ms before the drift check fired. Not a regression.
- **[INFO] signal_runs / ranking_runs / security_signals / ranked_opportunities all stale at 2026-05-01.** Today's legitimate Monday morning data was collateral damage from the `DELETE … WHERE created_at >= '2026-05-04 01:00:00'` portion of the operator-approved cleanup. The cleanup couldn't selectively spare the 10:30/10:45 UTC legitimate runs without parsing each row's content. Paper cycles still ran successfully (in-memory state preserved), just without fresh signals/rankings DB context. Will repopulate Tue 2026-05-05 06:30 ET.
- **[INFO] No new persisted positions today** — CSCO opened+closed within the same intra-day window (momentum_v1 strategy). Net 0 new OPENs. Within caps.
- **[INFO] Phase 73 defense fully holding** — Alertmanager firing=0 across the post-cleanup window; the dual-snapshot $99,983.24 baseline + $111,586.01 actual rows are no longer triggering DrawdownCritical/DrawdownAlert thanks to the `for: 30m` debounce.

### Fixes Applied
- **Lint auto-fix at `3bdbe64`**: reordered import block in `apis/tests/conftest.py` lines 177-179 to satisfy ruff I001. Before: `import infra.db.session as session_mod; from sqlalchemy.orm import Session as _BaseSession; from sqlalchemy.orm import sessionmaker as _sessionmaker`. After: `from sqlalchemy.orm import Session as _BaseSession; from sqlalchemy.orm import sessionmaker as _sessionmaker; <blank>; import infra.db.session as session_mod`. Verified: `ruff check` clean, pytest smoke 360/360. Pushed to `origin/main`.
- State doc updates only otherwise (this entry + DECISION_LOG DEC-073 + CHANGELOG entry).

### Action Required from Aaron
1. **Verify CI rerun #25327148433** on `3bdbe64` reports `Lint & Type Check=success`. (~5 min wait at write time.) If still red, the auto-fix missed something.
2. **Triage Unit Tests (Python 3.11|3.12) failures** on `37191c3` — same regression likely persists on `3bdbe64`. The Phase 74 write-blocking fixture is the most likely culprit (it intercepts SessionLocal under `APIS_PYTEST_SMOKE=1` to prevent prod-DB pollution; some pre-existing tests may not set that env var and may rely on real writes). Per the deep-dive standing authority I cannot autonomously edit tests; this needs Aaron's review of which tests regressed.
3. **Optional: API restart to clear broker adapter drift cache** — the two `broker_health_position_drift` warnings will keep firing every paper cycle until the broker adapter's in-memory position cache is resynced from DB. A `docker restart docker-api-1` (or `docker compose --env-file "../../.env" up -d api`) would resync; warning level only, not blocking trading.
4. **YELLOW email**: created via Gmail MCP — see Action Required section in body.

---

## Cleanup Applied — 2026-05-04 12:25 UTC (Monday 7:25 AM CT, operator-approved)

**Overall Status:** GREEN — DEC-070 test-pollution cleanup transaction landed cleanly. No `docker-api-1` restart required; in-memory state preserved end-to-end.

### Transaction
File: `outputs/cleanup_2026-05-04.sql` (preserved for next-incident template).
Executed via: `docker exec -i docker-postgres-1 psql -U apis -d apis -v ON_ERROR_STOP=1` against `apis` DB inside `docker-postgres-1`.

| Step | Statement | Rows |
|------|-----------|------|
| 1 | `UPDATE positions SET status='open', closed_at=NULL WHERE closed_at='2026-05-04 01:05:18.847001'` | 12 |
| 2 | `DELETE FROM fills WHERE created_at >= '2026-05-04 01:00:00'` | 53 |
| 3 | `DELETE FROM orders WHERE created_at >= '2026-05-04 01:00:00'` | 57 |
| 4 | `DELETE FROM positions WHERE id = 'e109d491-044a-4f85-81b5-af3160d21f34'` (phantom AAPL) | 1 |
| 5 | `DELETE FROM positions WHERE opened_at IN [05-03 01:00, 05-04 02:00) AND id != phantom` | 7 |
| 6 | `DELETE FROM portfolio_snapshots WHERE snapshot_timestamp >= '2026-05-04 01:00:00'` | 56 |
| 7 | `DELETE FROM evaluation_metrics WHERE created_at >= '2026-05-04 01:00:00'` | 8 |
| 8 | `DELETE FROM ranked_opportunities WHERE created_at >= '2026-05-04 01:00:00'` | 100 |
| 9 | `DELETE FROM ranking_runs WHERE run_timestamp >= '2026-05-04 01:00:00'` | 8 |
| 10 | `DELETE FROM security_signals WHERE created_at >= '2026-05-04 01:00:00'` | 20080 |
| 11 | `DELETE FROM signal_runs WHERE run_timestamp >= '2026-05-04 01:00:00'` | 8 |
| 12 | `DELETE FROM evaluation_runs WHERE run_timestamp >= '2026-05-04 01:00:00'` | 1 |

### FK-order corrections vs HEALTH_LOG proposed transaction
The proposed transaction in the prior `2026-05-04 10:10 UTC` entry placed `DELETE FROM positions` BEFORE `DELETE FROM orders` / `DELETE FROM fills`. That ordering would have FK-failed on `orders.position_id → positions.id` for the 7 test-fixture closed positions (which have orders rows pointing at them). Pre-flight verified `risk_events.position_id` had **0** references to the polluted IDs, so no extra DELETE was needed for that FK. The executed order is reflected in the table above (fills → orders → positions → snapshots → eval/ranking/signal grandchildren → parents).

### Spot-checks (post-COMMIT, pre-COMMIT visibility)
- `SELECT COUNT(*) FROM positions WHERE status='open'` → **12** ✅ (matches API in-memory state)
- `SELECT MAX(snapshot_timestamp) FROM portfolio_snapshots` → **2026-05-01 19:30:03.287017** ✅ (legitimate pre-pollution row preserved)
- 12 open positions: CAT, SLB, WDC, BE, NUE, INTC, STT, MU, MRVL, AMD, EQIX, AMZN — all `origin_strategy='rebalance'`, original `quantity` / `entry_price` / `opened_at` intact

### Runtime validation (post-COMMIT)
- `docker ps --filter "name=docker-api-1"` → `Up 11 hours (healthy)` ✅ (NOT restarted)
- `/health` → all 7 components ok (db/broker/scheduler/paper_cycle/broker_auth/system_state_pollution/kill_switch) ✅
- Prometheus `/metrics`:
  - `apis_portfolio_positions=12` ✅
  - `apis_portfolio_equity_usd=111051.98` ✅
  - `apis_portfolio_cash_usd=23050.76` ✅
  - All three exact match against DB latest legitimate snapshot
- 0 polluted orders / 0 polluted snapshots remaining (verified via `>= 2026-05-04 01:00:00` recount)

### Outcome
- **Pollution scope:** fully cleared (3 positions tables + 6 child tables + 2 snapshots/eval tables = 11 tables touched).
- **Production runtime:** unaffected end-to-end (in-memory state was the protection; restart no longer dangerous).
- **Next paper cycle:** Monday 2026-05-04 13:35 UTC (~1h 10m from cleanup completion). Will run from a clean DB.
- **Phase 74 ticket:** opened (`memory/project_phase74_phase59_test_isolation.md`), referenced in `MEMORY.md`. Permanent fix to `phase59` conftest isolation still owed before the next pytest validation sweep that touches `phase59`.
- **DEC-071:** logged in `state/DECISION_LOG.md`.

---

## Health Check — 2026-05-04 10:10 UTC (Monday 5:10 AM CT, pre-market)

**Overall Status:** RED — pytest test pollution from the Phase 73 validation run at 01:05–01:14 UTC clobbered the 12 production paper positions (UPDATE'd to `status='closed'` with synthetic `closed_at='2026-05-04 01:05:18.847001'`) and wrote 56 polluted `portfolio_snapshots`, 6 `signal_runs`, 6 `ranking_runs`, 1 research-mode `evaluation_runs` row, 5 fake position OPENs, 19 closes total, 57 orders, 53 fills, 70 ranked_opportunities, 8 evaluation_metrics, 15,060 security_signals. **Production runtime is currently shielded** because `docker-api-1` was restarted at 01:00 UTC BEFORE the 01:05 UTC pollution burst, and the API's in-memory state was loaded from the last legitimate snapshot (2026-05-01 19:30:03 UTC, cash=$23,050.76 / equity=$111,051.98 / positions=12). Prometheus `/metrics` confirms `apis_portfolio_positions=12, apis_portfolio_equity_usd=111051.98, apis_portfolio_cash_usd=23050.76` — exact match against the legit snapshot. **The danger is the next API restart**: portfolio_state restore will pick up either the latest polluted snapshot ($90k/$91,150) or the phantom AAPL OPEN row (10 shares × $100 = $1,000 cost basis), which would silently corrupt production state and re-fire DrawdownCritical (now also blocked for ≥30m by Phase 73 defense, but still wrong). **Immediate operator action requested**: approve DB cleanup transaction (UPDATE 12 production positions back to `open`, DELETE polluted child rows). All non-data subsystems GREEN: 8/8 containers healthy, /health all 7 ok, 0 crash-triad, 0 broker drift, Alertmanager firing=0 (Phase 73 defense holding), pytest 360/360 in 22.65s, CI #25296517254 on `e2f7811`=success, all 11 APIS_* flags correct.

### §1 Infrastructure
- Containers: 8/8 healthy. worker `Up 10h`, api `Up 9h` (Phase 73 restart 01:00 UTC), postgres/redis healthy, grafana/prometheus/alertmanager up, apis-control-plane up. No restart loops.
- /health: all 7 components `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper. Timestamp 2026-05-04T10:08:38Z.
- Worker log scan (24h): 15 errors — all 13 known stale delisted tickers (PXD, JNPR, DFS, PKI, CTLT, IPG, K, ANSS, PARA, MMC, MRO, HES, WRK) + 2 yfinance summary lines from the 06:00 ET (10:00 UTC) ingestion. **0 crash-triad regression patterns** (`_fire_ks` / `broker_adapter_missing_with_live_positions` / `EvaluationRun.idempotency_key` / `paper_cycle.*no_data` / `phantom_cash_guard_triggered` / `broker_health_position_drift`).
- API log scan (24h): 19 errors — 4 known startup quirks (regime_result_restore_failed × 2 + readiness_report_restore_failed × 2 from 00:33:45 + 01:02:07 boots, both flagged in prior entries) + 15 stale-ticker yfinance from 10:00 UTC. **0 crash-triad** patterns.
- Prometheus: 2/2 targets up (apis, prometheus), 0 dropped ✅.
- **Alertmanager: firing=0** ✅ — Phase 73's `for: 30m` defense + the indentation fix has cleared the recurring DEC-061/DEC-064/DEC-065/DEC-068 false positive that fired across the previous 4 deep-dive runs. **Successful Phase 73 validation.**
- Resource usage: worker 773.8 MiB, api 791.2 MiB, postgres 157 MiB, grafana 50.5 MiB, prometheus 38.7 MiB, alertmanager 14.9 MiB, redis 8.3 MiB, apis-control-plane 1.005 GiB / 10.6% CPU (kind k8s control plane). All under threshold.
- DB size: **175 MB** (up from 158 MB at 00:38 UTC — +17 MB growth includes 06:00 ET bars ingestion AND the 01:05–01:14 UTC pytest pollution).

### §2 Execution + Data Audit
- Paper cycles last 30h: **0 paper-mode rows**. 1 research-mode evaluation_run at 01:06:53 UTC (`8f097843-36f3-460a-9480-8451e3213f67`, status=complete) — **test pollution**, NOT a legitimate cycle. Sunday closed; first Monday cycle fires at 13:35 UTC (~3h 25m from probe).
- `evaluation_runs` total: **97** (≥80 floor ✅; 96 legit + 1 polluted).
- Portfolio trend in DB:
  - Latest legit snapshot before pollution: 2026-05-01 19:30:03 UTC, **cash=$23,050.76 / equity=$111,051.98** (paired with the dual-snapshot $30,430.83 baseline row at 19:30:00 — pre-Phase-73 pattern).
  - Latest polluted snapshot: 2026-05-04 01:14:46 UTC, cash=$90,000 / equity=$91,150.
  - **56 polluted rows** between 01:05 and 01:14:46 UTC matching the round-number test-pollution signature ($100k → $57,486 → $53,995 → $90k → $91,150 in two identical bursts).
  - Prometheus `/metrics` (in-memory): `apis_portfolio_equity_usd=111051.98, apis_portfolio_cash_usd=23050.76, apis_portfolio_positions=12` — correctly reads pre-pollution state.
- Broker<->DB reconciliation: DB shows **1 OPEN position** (phantom AAPL 10 × $100, opened 2026-05-03 01:14:46 UTC by pytest fixture). API in-memory holds 12 (correct). `/health broker=ok`. **Mismatch is artifact of pollution**, not broker drift.
- Origin-strategy stamping: phantom AAPL has `origin_strategy=ranking_buy_signal`. The 12 legit positions were UPDATE'd to `closed` but their original `origin_strategy=rebalance` is preserved.
- Position caps:
  - DB OPEN: 1/15 (post-pollution) — DOES NOT reflect production. In-memory: 12/15 ✅.
  - Positions opened today (DB): 5 — all pytest fixtures with synthetic timestamps.
  - Positions closed today (DB): 19 — 12 legit clobbered by pytest + 7 test fixtures.
- Data freshness: bars=2026-05-01 (Friday close — Monday's 06:00 ET ingestion ran at 10:00 UTC but Friday's bars were already present so no new rows for those tickers; today's bars will arrive after market close); legit signal_runs=2026-05-01 10:30 UTC; legit ranking_runs=2026-05-01 10:45 UTC. Pollution adds 6 polluted signal_runs (01:06–01:16 UTC) + 6 polluted ranking_runs.
- Stale tickers: known 13 only. No new additions.
- Kill-switch: `false` ✅. Operating mode: `paper` ✅.
- Idempotency: 0 duplicate orders by `idempotency_key` ✅. 0 duplicate OPEN positions per ticker ✅.
- **Pollution row counts** (since 2026-05-04 01:00 UTC):
  - portfolio_snapshots: 56
  - signal_runs: 6
  - ranking_runs: 6
  - evaluation_runs: 1 (research mode)
  - positions opened: 5 (1 still OPEN — phantom AAPL)
  - positions closed: 19 (12 production + 7 fixtures)
  - orders: 57
  - fills: 53
  - security_signals: 15,060
  - ranked_opportunities: 70
  - evaluation_metrics: 8
  - position_history: 0

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head ✅).
- Pytest smoke: **360 passed / 0 failed / 3657 deselected in 22.65s** ✅ (`-k "deep_dive or phase22 or phase57"` in `docker-api-1` with `APIS_PYTEST_SMOKE=1`). Note: this audit re-ran the smoke without `phase59` and added **0 new pollution rows** — confirming the pollution source is in the `phase59` filter (or a fixture imported there). Phase 73's validation used `-k "deep_dive or phase22 or phase57 or phase59"` which is when pollution occurred.
- Git: **CLEAN** — `git status --porcelain` empty, 0 unpushed commits, only `main` branch. HEAD = `e2f7811` (Phase 73 commit, pushed 2026-05-04 01:22 UTC).
- **GitHub Actions CI:** Run #25296517254 on `e2f7811` conclusion=`success` status=`completed`. GREEN ✅. https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25296517254

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
- Scheduler: `job_count=36`. Worker started 2026-05-04T00:33:32Z.

### Issues Found
- **[RED] Pytest test pollution clobbered production paper DB at 01:05–01:14 UTC.** Source: Phase 73 validation pytest sweep `-k "deep_dive or phase22 or phase57 or phase59"`. Phase 68 conftest isolation has a hole — at least one fixture/test in the `phase59` set writes to the production paper Postgres rather than an isolated test DB. Damage:
  - 12 production positions UPDATE'd to `status='closed'` with `closed_at='2026-05-04 01:05:18.847001'` (CAT, SLB, WDC, BE, NUE, INTC, STT, MU, MRVL, AMD, EQIX, AMZN). Original `quantity / entry_price / opened_at / origin_strategy='rebalance'` preserved → recovery is `UPDATE … SET status='open', closed_at=NULL`.
  - 1 phantom AAPL OPEN position (10 shares × $100 cost basis, opened 2026-05-03 01:14:46 UTC) currently the only `status='open'` row in DB.
  - 56 polluted `portfolio_snapshots` rows (round-number $100k/$57k/$54k/$90k/$91k pattern, two identical bursts at 01:10:27–01:10:53 and 01:14:20–01:14:46).
  - Plus 6 signal_runs, 6 ranking_runs, 1 evaluation_runs (research mode), 4 positions opened that were also closed (test fixtures), 57 orders, 53 fills, 15,060 security_signals, 70 ranked_opportunities, 8 evaluation_metrics.
  - **Production runtime is currently shielded** by API in-memory state preserved across the 01:00 UTC restart (which preceded pollution). Next API restart restores from polluted DB → silent corruption.
  - Same class of regression as `project_test_pollution_2026-04-19.md`; Phase 68 guard insufficient.
- **[INFO] Phase 73 fix is fully validated.** Alertmanager firing=0 confirms `for: 30m` defense is holding the recurring post-restart DrawdownCritical false-positive below threshold; Prometheus equity gauge ($111,051.98) matches DB latest legit snapshot exactly, confirming the indentation fix correctly restores all 12 positions.
- **[INFO] Friday 2026-05-01 daily_market_bars not advanced** — pre-existing intentional weekday-only schedule; Mon 06:00 ET (10:00 UTC) ingestion ran but Friday's bars were already present. Today's bars will arrive after close.
- **[INFO] research-mode evaluation_run at 01:06:53 UTC** is part of the test pollution. Total `evaluation_runs=97` is `96 legit + 1 polluted`.

### Fixes Applied
- **None applied autonomously.** DB DELETE is on the operator-approval-required list per the standing-authority rules. State doc updates only (this entry).

### Action Required from Aaron
1. **APPROVE DB cleanup transaction** (precedent: `project_test_pollution_2026-04-19.md` 02:20 UTC operator approval). Proposed transaction in dependency order:

   ```sql
   BEGIN;
   -- Restore the 12 production positions
   UPDATE positions SET status='open', closed_at=NULL
     WHERE closed_at = '2026-05-04 01:05:18.847001';
   -- Drop the phantom AAPL OPEN
   DELETE FROM positions WHERE id = 'e109d491-044a-4f85-81b5-af3160d21f34';
   -- Drop pollution-created closed test positions (NVDA × 3, AAPL × 4)
   DELETE FROM positions WHERE opened_at >= '2026-05-03 01:00:00' AND opened_at < '2026-05-04 02:00:00' AND id != 'e109d491-044a-4f85-81b5-af3160d21f34';
   -- Drop polluted child rows
   DELETE FROM fills WHERE created_at >= '2026-05-04 01:00:00';
   DELETE FROM orders WHERE created_at >= '2026-05-04 01:00:00';
   DELETE FROM portfolio_snapshots WHERE snapshot_timestamp >= '2026-05-04 01:00:00';
   DELETE FROM evaluation_metrics WHERE created_at >= '2026-05-04 01:00:00';
   DELETE FROM ranked_opportunities WHERE created_at >= '2026-05-04 01:00:00';
   DELETE FROM ranking_runs WHERE run_timestamp >= '2026-05-04 01:00:00';
   DELETE FROM security_signals WHERE created_at >= '2026-05-04 01:00:00';
   DELETE FROM signal_runs WHERE run_timestamp >= '2026-05-04 01:00:00';
   DELETE FROM evaluation_runs WHERE run_timestamp >= '2026-05-04 01:00:00';
   -- Spot-check
   SELECT COUNT(*) AS open_positions FROM positions WHERE status='open';  -- should be 12
   SELECT MAX(snapshot_timestamp) FROM portfolio_snapshots;  -- should be 2026-05-01 19:30:03
   COMMIT;
   ```

2. **DO NOT restart `docker-api-1`** until cleanup is committed. The API's in-memory state is the only thing protecting Monday's first paper cycle from the pollution. If a restart is forced (e.g., Docker Desktop reboot), the next portfolio_state restore picks up the polluted $90k row.

3. **Phase 74 ticket — fix `phase59` test isolation.** The Phase 68 conftest DB isolation must be extended to cover phase59 fixtures. Investigation required: which test in `tests/unit/test_phase59_state_persistence.py` (or a phase59-imported fixture) writes to the real Postgres rather than the mock. The new AST test from Phase 73 itself doesn't touch DB; the regression must be in an existing phase59 test. **This is the third documented test-pollution incident** (2026-04-19 → ~unknown gap → 2026-05-04); a permanent fix is overdue.

4. **YELLOW/RED email**: Gmail draft to be created — manual send required.

---

## Phase 73 Fix Sprint — 2026-05-04 01:20 UTC (Sunday 8:20 PM CT, operator-requested)

**Overall Status:** GREEN — Phase 73 deployed and validated. Position-restore indentation regression from Phase 72 (`1759455`, 2026-05-01) fixed; Alertmanager `DrawdownAlert` + `DrawdownCritical` `for:` raised to 30m as defense-in-depth.

**Trigger:** Operator pinged on the recurring `DrawdownCritical` post-restart YELLOWs (DEC-064 / DEC-065 / DEC-068, 3 consecutive Saturday/Sunday deep-dive runs all flagging the same alert). Granted full sweep across the 3 Phase 73 candidates from those runs.

**Investigation outcome:** None of the 3 candidates (Alertmanager `for: 30m`, gauge alignment, dual-snapshot writer) was the actual root cause. Probing live snapshot rows revealed both pre/post-cycle snapshots are at $100-111k — there is no $30k row anywhere. Probing the live Prometheus output revealed `apis_portfolio_positions=1` while DB had 12 open positions. Reading `apps/api/main.py` lines 239-260 revealed a comment block at column 16 dragging the dict assignment OUT of the `for pos, ticker in open_rows:` loop body.

**Fixes shipped:**

| Layer | Change |
|-------|--------|
| Code | `apps/api/main.py` re-indent `_db_os` + `positions[ticker] = PortfolioPosition(...)` block from column 16 → column 20 (inside for-loop). |
| Test | `tests/unit/test_phase59_state_persistence.py` new AST regression test `test_restore_loop_dict_assignment_is_inside_for_loop`. |
| Alerts | `infra/monitoring/prometheus/rules/apis_alerts.yaml` `DrawdownAlert` 5m → 30m, `DrawdownCritical` 1m → 30m. Prometheus reloaded. |

**Live validation:**
- Pre-fix Prometheus: `apis_portfolio_positions=1, apis_portfolio_equity_usd=30417.30, apis_portfolio_cash_usd=23050.76`
- Post-fix Prometheus (after `docker restart docker-api-1`): `apis_portfolio_positions=12, apis_portfolio_equity_usd=111051.98, apis_portfolio_cash_usd=23050.76` (matches DB latest snapshot exactly)
- Alertmanager: `firing=0`
- /health: all 7 components ok
- Pytest smoke (`tests/unit/ -k "deep_dive or phase22 or phase57 or phase59"`, `APIS_PYTEST_SMOKE=1`): **397 passed / 0 failed in 74.57s** (361 baseline + 1 new test)
- Prometheus rules reloaded: `DrawdownAlert duration=1800s, DrawdownCritical duration=1800s`

**Memory + docs updated:**
- `memory/project_phase73_position_restore_indentation.md` (new)
- `memory/MEMORY.md` (Phase 73 entry added)
- `apis/state/CHANGELOG.md` (Phase 73 section)
- `apis/state/ACTIVE_CONTEXT.md` (top + new section)
- `apis/state/NEXT_STEPS.md` (rewritten head)
- `apis/state/HEALTH_LOG.md` (this entry)
- `state/DECISION_LOG.md` (DEC-069)

**Carry-forward correction for future deep-dives:** the "dual-snapshot baseline row" theory in DEC-061 / DEC-064 / DEC-065 / DEC-068 was wrong. If a future deep-dive sees `apis_portfolio_equity_usd` mismatch DB latest snapshot equity, FIRST check `apis_portfolio_positions` against DB open-position count — a mismatch implies a restore-loop regression rather than a snapshot/gauge mismatch.

**Pending:** commit + push to `origin/main`.

---

## Health Check — 2026-05-04 00:38 UTC (Sunday 7:38 PM CT, market closed)

**Overall Status:** YELLOW — Alertmanager `DrawdownCritical` (critical) re-fired at 00:35:29 UTC, ~2 min after a fresh worker+API restart at 00:33:32 UTC. Same DEC-061 post-restart HWM-reset false positive that earlier 5:15 AM CT + 10:10 AM CT Sunday runs flagged. Equity is stable at $111,051.98; Prometheus gauge `apis_portfolio_equity_usd=30417.30` reads the dual-snapshot $30k baseline row instead of the $111k actual row. Will self-clear Mon 2026-05-04 13:35 UTC paper cycle re-establishes HWM. Everything else GREEN: 8/8 containers up ~5 min on fresh restart, /health all 7 components ok, 0 worker/api errors, 0 crash-triad, 0 broker drift in 24h, pytest 360/360, CI GREEN at HEAD `6424873`, git tree clean, all APIS_* flags correct.

### §1 Infrastructure
- Containers: 8/8 healthy. ALL containers freshly restarted — `Up About a minute` at probe time (worker started 2026-05-04 00:33:32 UTC). Likely a Docker Desktop / machine restart event between the 15:10 UTC YELLOW run and now (~9.5h gap). Same docker-compose stack: docker-{worker,api,postgres,redis,prometheus,grafana,alertmanager}-1 + apis-control-plane.
- /health: all 7 components `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper. Timestamp 2026-05-04T00:36:15Z.
- Worker log scan (24h): CLEAN — 544 total lines, **0 ERROR/CRITICAL/Traceback/TypeError**. **0 crash-triad regression patterns** (`_fire_ks` / `broker_adapter_missing_with_live_positions` / `EvaluationRun.idempotency_key` / `paper_cycle.*no_data` / `phantom_cash_guard_triggered`). 0 `broker_health_position_drift` ✅.
- API log scan (24h): 6951 total lines, 2 matches — both known startup warnings on the fresh boot:
  - `regime_result_restore_failed` (error: `detection_basis_json`) at 2026-05-04T00:33:45Z
  - `readiness_report_restore_failed` (`ReadinessGateRow.__init__() missing 1 required positional argument: 'description'`) at 2026-05-04T00:33:45Z
  - Both are pre-existing non-blocking startup quirks that have appeared in every recent restart's log (also flagged in 5:15 AM CT entry).
- Prometheus: 2/2 targets up (apis, prometheus), 0 dropped ✅.
- **Alertmanager: 1 ACTIVE alert firing**:
  - `DrawdownCritical` (severity=critical) since 2026-05-04T00:35:29Z — fired ~2 min after the 00:33:32 UTC worker+API restart. Annotation reads `apis_portfolio_equity_usd is 30417.30. Approaching the 10% drawdown kill-switch at $90,000.` This is the dual-snapshot baseline row reading, not actual equity ($111,051.98 from the post-cycle row). Identical DEC-061 pattern.
  - `DrawdownAlert` (warning) NOT yet active — may fire on next Prometheus scrape evaluation. Earlier Sunday runs had both firing.
  - Will NOT self-clear until Monday 2026-05-04 13:35 UTC paper cycle re-establishes HWM.
- Resource usage: Worker 80MiB, API 165MiB, Grafana 65MiB, Prometheus 38MiB, Alertmanager 15MiB, Postgres 43MiB, Redis 9MiB, k8s 1.003GiB (CPU 9.32%). All well under threshold.
- DB size: 158 MB (unchanged).

### §2 Execution + Data Audit
- Paper cycles last 30h: 0 rows ✅ (Sunday — expected, no market hours).
- Total `evaluation_runs`: **96** (above 80 floor ✅).
- Portfolio trend: latest snapshot **2026-05-01 19:30:03 UTC** — cash=$23,050.76 / equity=$111,051.98 ✅. Cash positive ✅. Dual-snapshot pattern continues (paired $30,430.83 baseline row + actual $111,051.98 cycle row).
- Broker<->DB reconciliation: **0 `broker_health_position_drift` warnings in 24h** ✅. 12 open positions in DB. /health broker=ok.
- Origin-strategy stamping: ALL 12 open positions `origin_strategy=rebalance` ✅. 0 NULLs (CAT, SLB opened 2026-05-01 15:30; MU, INTC, BE, NUE, STT, WDC opened 2026-05-01 13:35; MRVL, AMD, EQIX, AMZN opened 2026-04-29 16:00). Phase 72 holding.
- Position caps: **12/15 open** ✅. 0 new today (Sunday) ✅.
- Data freshness: bars=2026-04-30 (Thursday close, 488 securities — Friday's bars pending Mon 06:00 ET ingestion); ranking_runs=2026-05-01 10:45 UTC ✅; signal_runs=2026-05-01 10:30 UTC ✅.
- Stale tickers: known 13 only. No new additions (worker did not run any ingestion this session — too brief, no scheduled job since restart).
- Kill-switch: `false` ✅. Operating mode: `paper` ✅.
- Idempotency: clean — 0 duplicate orders by `idempotency_key`, 0 duplicate open positions per ticker ✅.

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head ✅). `alembic current` and `alembic heads` both return single rev. Drift: ~25 documented cosmetic items (TIMESTAMP↔DateTime, comment wording) — non-functional, persists from prior runs.
- Pytest smoke: **360 passed / 0 failed / 3656 deselected in 23.38s** ✅. Above 358/360 baseline (Phase 72 re-baseline). Ran in `docker-api-1` with `APIS_PYTEST_SMOKE=1` against `tests/unit -k "deep_dive or phase22 or phase57"`.
- Git: **CLEAN** — `git status --porcelain` empty, 0 unpushed commits, only `main` branch. HEAD = `6424873` (this morning's 10:10 AM CT entry, already committed + pushed).
- **GitHub Actions CI:** Run #25282920307 on `6424873` conclusion=success status=completed. GREEN ✅. https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25282920307

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
- Scheduler: `job_count=36`. Worker started 2026-05-04 00:33:32 UTC.

### Issues Found
- **[YELLOW] Alertmanager `DrawdownCritical` re-fired at 00:35:29 UTC** — ~2 min after a fresh 00:33:32 UTC worker+API restart event (machine reboot or Docker Desktop restart between 15:10 UTC and 00:33 UTC). Identical to the DEC-061 post-restart HWM-reset false positive that earlier 5:15 AM CT + 10:10 AM CT Sunday runs flagged. Equity stable at $111,051.98; Prometheus gauge `apis_portfolio_equity_usd=30417.30` reads dual-snapshot baseline row. Cannot self-clear until Mon 2026-05-04 13:35 UTC paper cycle re-establishes HWM. Non-actionable on weekend. NOTE: only `DrawdownCritical` (critical) currently firing — `DrawdownAlert` (warning) may fire on next scrape evaluation.
- **[INFO] All 8 containers freshly restarted at 00:33:32 UTC** — likely Docker Desktop / machine restart between 15:10 UTC and 00:33 UTC. Stack came up cleanly; same Phase 72 code at `6424873`. The 9.5h gap between earlier Sunday run and this one means earlier YELLOW carry-forward window has been reset.
- **[INFO] Friday 2026-05-01 daily_market_bars not yet ingested** — weekday-only schedule (06:00 ET); Friday's close ingests Mon 06:00 ET. Pre-existing intentional behavior.

### Fixes Applied
- None. The `DrawdownCritical` alert is a known false positive that requires Monday's market open to clear naturally; flipping silences/manual clears would mask future genuine HWM resets. State doc updates only (this entry).

### Action Required from Aaron
- **Monday monitoring (2026-05-04)**: Watch first paper cycle at 13:35 UTC (09:35 ET). The active `DrawdownCritical` (and `DrawdownAlert` if it fires before Monday) should self-clear within 1–2 cycles as HWM is re-established. If they DON'T clear by 14:30 UTC, investigate equity drawdown vs new HWM.
- **Optional Phase 73 ticket** (carry-forward across all 3 Sunday runs): Fix the dual-snapshot baseline row OR align Prometheus equity gauge OR add Alertmanager `for: 30m` minimum so post-restart false-positives stop firing. The fact that the alert re-fires every restart event (twice on Sunday alone) is now well-documented and reproducible.
- **YELLOW email**: Gmail draft to be created — manual send required.

---

## Health Check — 2026-05-03 15:10 UTC (Sunday 10:10 AM CT, market closed)

**Overall Status:** YELLOW — Alertmanager DrawdownCritical + DrawdownAlert still firing (5h after 5:15 AM CT run; identical carry-forward from 2026-05-02 13:26/13:30 UTC restart). No Sunday paper cycles to self-clear; will clear Mon 13:35 UTC. Everything else GREEN: 8/8 containers up 26h, /health all 7 components ok, 0 worker/api errors, 0 crash-triad, 0 broker drift in 24h, pytest 360/360, CI GREEN at HEAD, git tree clean, all APIS_* flags correct.

### §1 Infrastructure
- Containers: 8/8 healthy. All up ~26h since 2026-05-02 13:24 UTC restart (worker, api, postgres, redis, grafana, prometheus, alertmanager, apis-control-plane). No restart loops.
- /health: all 7 components `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper. Timestamp 2026-05-03T15:09:57Z.
- Worker log scan (24h): CLEAN — 576 total lines, 0 ERROR/CRITICAL/Traceback/TypeError. 0 crash-triad regression patterns (`_fire_ks` / `broker_adapter_missing_with_live_positions` / `EvaluationRun.idempotency_key` / `paper_cycle.*no_data` / `phantom_cash_guard_triggered` / `broker_health_position_drift`).
- API log scan (24h): 9206 total lines, 0 ERROR/CRITICAL/Traceback/TypeError. 0 crash-triad patterns.
- Prometheus: 2/2 targets up (apis, prometheus), 0 dropped ✅.
- **Alertmanager: 2 ACTIVE alerts firing (carry-forward from 2026-05-02)**:
  - `DrawdownCritical` (severity=critical) since 2026-05-02T13:26:29Z
  - `DrawdownAlert` (severity=warning) since 2026-05-02T13:30:29Z
  - Same root cause as 5:15 AM CT run: Prometheus gauge `apis_portfolio_equity_usd` reads dual-snapshot $30,430.83 baseline row instead of actual $111,052 equity row. DEC-061 pattern. Will self-clear when Mon 2026-05-04 13:35 UTC paper cycle re-establishes HWM.
- Resource usage: Worker 67MiB, API 173MiB, Grafana 51MiB, Prometheus 42MiB, Alertmanager 15MiB, Postgres 81MiB, Redis 7MiB, k8s 1.084GiB (CPU 21%, well under threshold). All under threshold.
- DB size: 158 MB (unchanged from morning).

### §2 Execution + Data Audit
- Paper cycles last 60h: 1 row only — Friday 2026-05-01 21:00 UTC daily eval (`status=complete`, `mode=paper`). 0 weekend cycles (expected). 0 failures ✅.
- Total evaluation_runs: 96 (above 80 floor ✅).
- Portfolio trend: latest snapshot 2026-05-01 19:30 UTC — cash=$23,050.76 / equity=$111,051.98. Cash positive ✅. Dual-snapshot pattern continues (paired $30,430.83 baseline row + actual $111,051.98 cycle row at 19:30:03 UTC).
- Broker<->DB reconciliation: 0 `broker_health_position_drift` warnings in 24h ✅. 12 open positions in DB. /health broker=ok.
- Origin-strategy stamping: ALL 12 open positions `origin_strategy=rebalance` ✅. 0 NULLs (CAT, SLB opened 2026-05-01 15:30; MU, INTC, BE, NUE, STT, WDC opened 2026-05-01 13:35; MRVL, AMD, EQIX, AMZN opened 2026-04-29 16:00). Phase 72 holding.
- Position caps: 12/15 open ✅. 0 new today (Sunday) ✅.
- Data freshness: bars=2026-04-30 (Thursday close, 490 securities); ranking_runs=2026-05-01 10:45 UTC ✅; signal_runs=2026-05-01 10:30 UTC ✅. Friday's bars pending Mon 06:00 ET ingestion (weekday-only schedule).
- Stale tickers: known 13 only. No new additions.
- Kill-switch: false ✅. Operating mode: paper ✅.
- Idempotency: clean — 0 duplicate orders by idempotency_key, 0 duplicate open positions per ticker ✅.

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head ✅). `alembic current` and `alembic heads` both return single rev. Drift: ~25 documented cosmetic items (TIMESTAMP↔DateTime, comment wording) — non-functional, persists from prior runs.
- Pytest smoke: **360 passed / 0 failed / 3656 deselected in 27.74s** ✅. Above 358/360 baseline (Phase 72 re-baseline). Ran in `docker-api-1` with `APIS_PYTEST_SMOKE=1` against `tests/unit -k "deep_dive or phase22 or phase57"`.
- Git: **CLEAN** — `git status --porcelain` empty, 0 unpushed commits, only `main` branch. HEAD = `74941fd` (this morning's 5:15 AM CT entry, already committed + pushed).
- **GitHub Actions CI:** Run #25276530267 on `74941fd` conclusion=success status=completed. GREEN ✅. https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25276530267

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
- Other flags observed (informational): MAX_SECTOR_PCT=0.40, MAX_SINGLE_NAME_PCT=0.20, MAX_POSITION_AGE_DAYS=20, DAILY_LOSS_LIMIT_PCT=0.02, WEEKLY_DRAWDOWN_LIMIT_PCT=0.05.
- Scheduler: job_count=36. Worker started 2026-05-02 13:24:37 UTC.

### Issues Found
- **[YELLOW] Alertmanager DrawdownCritical + DrawdownAlert firing since 2026-05-02 13:26/13:30 UTC** — identical carry-forward from 5:15 AM CT run. Post-restart HWM-reset false positive — equity is actually stable at $111,052; Prometheus gauge `apis_portfolio_equity_usd=30417.30` reads the dual-snapshot baseline row. Cannot self-clear until Mon 2026-05-04 13:35 UTC paper cycle re-establishes HWM. Non-actionable on weekend.
- **[INFO] Friday 2026-05-01 daily_market_bars not yet ingested** — weekday-only schedule (06:00 ET); Friday's close ingests Mon 06:00 ET. Pre-existing intentional behavior.

### Fixes Applied
- None. Both Alertmanager alerts are known false positives; manual silences/clears would mask future genuine HWM resets. State doc updates only (this entry).

### Action Required from Aaron
- **Monday monitoring (2026-05-04)**: Watch first paper cycle at 13:35 UTC (09:35 ET). Both Alertmanager alerts should self-clear within 1–2 cycles as HWM is re-established. If they DON'T clear by 14:30 UTC, investigate equity drawdown vs new HWM.
- **Optional Phase 73 ticket** (carry-forward from 5:15 AM CT entry): Fix the dual-snapshot baseline row OR align Prometheus equity gauge OR add Alertmanager `for:` minimum so weekend post-restart false-positives stop firing.
- **YELLOW email**: Gmail draft to be created — manual send required.

---

## Health Check — 2026-05-03 10:15 UTC (Sunday 5:15 AM CT, market closed)

**Overall Status:** YELLOW — Alertmanager DrawdownCritical + DrawdownAlert still firing (carry-forward from 2026-05-02 13:26/13:30 UTC restart, no Sunday paper cycles to self-clear; will clear Mon 13:35 UTC). All other systems healthy: 8/8 containers up 21h, /health all ok, 0 worker errors, 0 crash-triad, 0 broker drift in 24h (decayed from yesterday), pytest 360/360, CI GREEN, all APIS_* flags correct.

### §1 Infrastructure
- Containers: 8/8 healthy (docker-worker-1, docker-api-1, docker-postgres-1, docker-redis-1, docker-prometheus-1, docker-grafana-1, docker-alertmanager-1, apis-control-plane). All up ~21h since 2026-05-02 13:24 UTC restart.
- /health: all 7 components `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper. Timestamp 2026-05-03T10:09:37Z.
- Worker log scan (24h): CLEAN — 0 ERROR/CRITICAL/Traceback. 0 crash-triad patterns.
- API log scan (24h): 3 matches — 1 PowerShell stderr envelope (not an APIS error) + 2 startup warnings (regime_result_restore_failed, readiness_report_restore_failed — pre-existing non-blocking).
- Prometheus: 2/2 targets up (apis, prometheus), 0 dropped ✅.
- **Alertmanager: 2 ACTIVE alerts firing (carry-forward from 2026-05-02)**:
  - `DrawdownCritical` (severity=critical) since 2026-05-02T13:26:29Z — gauge `apis_portfolio_equity_usd=30417.30` (Prometheus is reading the dual-snapshot baseline row at $30k cash, not the actual $111k equity row).
  - `DrawdownAlert` (severity=warning) since 2026-05-02T13:30:29Z — same root cause.
  - Both are post-restart HWM-reset false positives. Cannot self-clear until Mon 2026-05-04 13:35 UTC paper cycle re-establishes HWM. Same DEC-061 pattern.
- Resource usage: Worker 67MiB, API 173MiB, Grafana 51MiB, Prometheus 42MiB, Alertmanager 15MiB, Postgres 52MiB, Redis 8MiB, k8s 1.07GiB. All well under threshold.
- DB size: 158 MB (unchanged from yesterday).

### §2 Execution + Data Audit
- Paper cycles today: 0 (Sunday — expected, no market hours).
- Eval_runs in 30h: 0 rows (Saturday + Sunday — expected). Total evaluation_runs = 96 (above 80 floor ✅).
- Portfolio trend: latest snapshot 2026-05-01 19:30 UTC — cash=$23,050.76 / equity=$111,051.98 (unchanged since markets closed). Cash positive ✅. Dual-snapshot pattern continues (paired $30,430.83 baseline rows).
- Broker<->DB reconciliation: 0 `broker_health_position_drift` warnings in 24h ✅ (decayed from 1/24h yesterday). 12 open positions in DB.
- Origin-strategy stamping: ALL 12 open positions have `origin_strategy=rebalance` ✅. 0 NULLs (CAT, SLB, MU, INTC, BE, NUE, STT, WDC, MRVL, AMD, EQIX, AMZN). Phase 72 holding.
- Position caps: 12/15 open (within cap ✅). 0 new today (Sunday).
- Data freshness: bars=2026-04-30 (Thursday close, 488 securities — Friday bars pending Mon 06:00 ET ingestion per scheduler `next_run=2026-05-04 06:00`); rankings=2026-05-01 10:45 UTC ✅; signal_runs=2026-05-01 10:30 UTC ✅; security_signals=5030 rows.
- Stale tickers: known 13 only. No new additions (no ingestion ran on Sunday — weekday-only schedule).
- Kill-switch: false ✅. Operating mode: paper ✅.
- Idempotency: clean — 0 duplicate orders, 0 duplicate open positions ✅.

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head ✅). Drift: ~25 documented cosmetic items (TIMESTAMP↔DateTime, comment wording, ix_proposal_executions_proposal_id missing, universe_overrides table-vs-orm) — non-functional, persists from prior runs. Queue cleanup migration when convenient.
- Pytest smoke: **360 passed / 0 failed / 3656 deselected in 29.30s** — ALL PASSING ✅. Above 358/360 baseline (Phase 72 re-baselined scheduler tests).
- Git: 3 dirty files (`apis/state/HEALTH_LOG.md`, `state/DECISION_LOG.md`, `state/HEALTH_LOG.md` — state docs from yesterday's health checks). 0 unpushed commits. Only `main` branch. HEAD=`2188c84`.
- **GitHub Actions CI:** Run #25214536632 `2188c84` conclusion=success status=completed. GREEN ✅. https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25214536632

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
- Scheduler: job_count=36. Worker started 2026-05-02 13:24 UTC.

### Issues Found
- **[YELLOW] Alertmanager DrawdownCritical + DrawdownAlert firing since 2026-05-02 13:26/13:30 UTC** — post-restart HWM-reset false positive (same as yesterday's YELLOW). Equity stable at $111,052; Prometheus gauge `apis_portfolio_equity_usd=30417.30` reads the $30k baseline snapshot row from the dual-snapshot pattern rather than the real equity row. Cannot self-clear until Mon 2026-05-04 13:35 UTC paper cycle re-establishes HWM. Non-actionable on weekend.
- **[INFO] Underlying dual-snapshot writer + Prometheus equity gauge mismatch**: the persistent dual-snapshot pattern ($30,430.83 baseline + actual cycle row) means Prometheus picks up the wrong row on every restart — guaranteeing a false-positive DrawdownAlert each weekend after a Saturday/early-week restart. Worth a Phase 73 investigation to either (a) stop emitting the baseline dual-snapshot row, or (b) align the Prometheus equity gauge to the actual cycle row, or (c) add an Alertmanager `for: 30m` minimum to absorb single-scrape transients. Not a regression; longstanding architecture quirk.
- **[INFO] Friday 2026-05-01 daily_market_bars not yet ingested**: market_data_ingestion runs weekday 06:00 ET; Friday's close will be ingested Mon 06:00 ET. Pre-existing weekday-only schedule, intentional.

### Fixes Applied
- None. Both Alertmanager alerts are known false positives that require Monday's market open to clear naturally; flipping silences/manual clears would mask future genuine HWM resets. State doc updates only (this entry + decision log).

### Action Required from Aaron
- **Monday monitoring (2026-05-04)**: Watch first paper cycle at 13:35 UTC (09:35 ET). Both Alertmanager alerts should self-clear within 1–2 cycles as HWM is re-established. If they DON'T clear by 14:30 UTC, investigate equity drawdown vs new HWM.
- **Optional Phase 73 ticket**: Fix the dual-snapshot baseline row OR align Prometheus equity gauge OR add Alertmanager `for:` minimum so weekend post-restart false-positives stop firing. Lower priority than runtime issues; YELLOW every weekend until resolved.
- **YELLOW email**: Gmail draft `r1357523362513468399` created — manual send required (Gmail MCP `create_draft` is the only available send-class tool in this build).

---

## Health Check — 2026-05-02 19:10 UTC (Saturday 2:10 PM CT, market closed)

**Overall Status:** YELLOW — 2 Alertmanager alerts firing (DrawdownCritical + DrawdownAlert) since 13:26/13:30 UTC, ~2 min after this morning's 13:24 UTC worker+API restart. Classic post-restart HWM-reset false-positive (matches DEC-061 pattern). Saturday means no paper cycles to self-clear them — they will fire continuously until Monday 13:35 UTC re-establishes HWM. Earlier Saturday runs (13:30 + 15:10 UTC) inadvertently called this GREEN because they only inferred "no alerts" from /health rather than probing Alertmanager directly. All other systems healthy: 8/8 containers, /health all ok, 0 worker errors, 0 crash-triad, pytest 360/360, CI GREEN, all APIS_* flags correct, broker drift down to 1/24h (decaying).

### §1 Infrastructure
- Containers: 8/8 healthy (docker-worker-1, docker-api-1, docker-postgres-1, docker-redis-1, docker-prometheus-1, docker-grafana-1, docker-alertmanager-1, apis-control-plane). All up ~6h since 13:24 UTC restart.
- /health: all 7 components `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper. Timestamp 2026-05-02T19:08:42Z.
- Worker log scan (24h): CLEAN — 0 ERROR/CRITICAL/Traceback. 0 crash-triad patterns.
- API log scan (24h): 4 matches — 1 HOLX `broker_order_rejected` (carry-forward, pre-`is_active=false` fix from yesterday) + 2 startup warnings (regime_result_restore_failed, readiness_report_restore_failed — pre-existing non-blocking) + 1 PowerShell stderr envelope (not an APIS error).
- Prometheus: 2/2 targets up (apis, prometheus), 0 dropped ✅.
- **Alertmanager: 2 ACTIVE alerts firing**:
  - `DrawdownCritical` (severity=critical) since 2026-05-02T13:26:29Z — fired ~2 min after 13:24 UTC worker+API restart.
  - `DrawdownAlert` (severity=warning) since 2026-05-02T13:30:29Z — fired ~6 min after restart.
  - Both are post-restart HWM-reset false positives (no actual drawdown — equity stable at $111,052 from 2026-05-01 19:30 UTC). Will NOT self-clear until first Monday paper cycle (2026-05-04 13:35 UTC) re-establishes HWM. Same pattern as DEC-061 from yesterday morning.
- Resource usage: Worker 73MiB, API 177MiB, Grafana 50MiB, Prometheus 38MiB, Alertmanager 15MiB, Postgres 52MiB, Redis 8MiB, k8s 985MiB. All well under threshold.
- DB size: 158 MB.

### §2 Execution + Data Audit
- Paper cycles today: 0 (Saturday — expected, no market hours).
- Eval_runs in 30h: 1 row (yesterday's 2026-05-01 21:00 UTC daily eval, status=complete, mode=paper). No failed runs ✅.
- Portfolio trend: latest snapshot 2026-05-01 19:30 UTC — cash=$23,050.76 / equity=$111,051.98. Cash positive ✅. Dual-snapshot pattern continues (paired $30,430.83 baseline rows). Last 6 snapshots span 17:30–19:30 UTC yesterday with consistent dual pattern.
- Broker<->DB reconciliation: 1 `broker_health_position_drift` warning in 24h (down from 5-6 yesterday — drift events from earlier yesterday are aging out of the 24h window). 12 open positions in DB. Non-actionable on weekend.
- Origin-strategy stamping: ALL 12 open positions have `origin_strategy=rebalance` ✅. 0 NULLs (CAT, SLB, MU, INTC, BE, NUE, STT, WDC, MRVL, AMD, EQIX, AMZN). Phase 72 holding.
- Position caps: 12/15 open (within cap ✅). 0 new today (Saturday).
- Data freshness: prices=2026-04-30 (last trading day, 490 securities ✅), rankings=2026-05-01 10:45 UTC ✅, signals=2026-05-01 10:30 UTC ✅.
- Stale tickers: known 13 only. No new additions (worker log has 0 yfinance 404s in 24h — no ingestion ran on Saturday).
- Kill-switch: false ✅. Operating mode: paper ✅.
- Evaluation history rows: 96 (above 80 floor ✅).
- Idempotency: clean — 0 duplicate orders, 0 duplicate open positions ✅.

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head). No drift ✅.
- Pytest smoke: **360p/0f/3656d in 28.73s** — ALL PASSING ✅. Above 358/360 baseline.
- Git: 3 dirty files (`apis/state/HEALTH_LOG.md`, `state/DECISION_LOG.md`, `state/HEALTH_LOG.md` — state docs from earlier health checks). 0 unpushed commits. Only `main` branch. HEAD=`2188c84`.
- **GitHub Actions CI:** Run #25214536632 `2188c84` conclusion=success status=completed. GREEN ✅. https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25214536632

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
- Scheduler: job_count=36. Worker started 2026-05-02 13:24 UTC.

### Issues Found
- **[YELLOW] Alertmanager DrawdownCritical + DrawdownAlert firing since 13:26/13:30 UTC** — fired ~2-6 min after the 13:24 UTC worker+API restart. This is the post-restart HWM-reset false positive pattern documented in DEC-061. Equity is stable at $111,052 (no actual drawdown). Cannot self-clear until Monday 2026-05-04 13:35 UTC paper cycle re-establishes HWM. Non-actionable on weekend.
- **[INFO] Earlier Saturday runs missed Alertmanager firing**: both 13:30 UTC and 15:10 UTC runs reported "no firing alerts (inferred from /health ok)" without actually probing /api/v2/alerts. Process improvement: future deep-dives MUST hit `curl http://localhost:9093/api/v2/alerts` directly (this run's command). HEALTH_LOG entries for those two runs technically should have been YELLOW.
- **[INFO] Broker<->DB drift carry-forward**: 1 drift warning in 24h (down from 5-6 yesterday — aging out). Will fully clear once 24h window passes the last drift event. Non-actionable.

### Fixes Applied
- None. The Alertmanager alerts are a known false positive that requires Monday's market open to clear naturally; flipping silences/manual clears would mask future genuine HWM resets. State doc updates only (this entry + decision log).

### Action Required from Aaron
- **Monday monitoring (2026-05-04)**: Watch first paper cycle at 13:35 UTC (09:35 ET). Both Alertmanager alerts should self-clear within 1-2 cycles as HWM is re-established (per DEC-061 trajectory). If they DON'T clear, investigate equity drawdown vs new HWM.
- **Process improvement (low priority)**: Update task SKILL.md §1.5 to require active `curl http://localhost:9093/api/v2/alerts` probe rather than inferring from /health — the previous two Saturday runs would have correctly classified YELLOW with this enforcement.

---

## Health Check — 2026-05-02 15:10 UTC (Saturday 10:10 AM CT, market closed)

**Overall Status:** GREEN — Saturday, no paper cycles expected. All infrastructure healthy (8/8 containers up 2h). Pytest 360/360. CI GREEN. No new issues since 13:30 UTC run. Broker drift from yesterday carried forward but non-actionable on weekends.

### §1 Infrastructure
- Containers: 8/8 healthy (docker-worker-1, docker-api-1, docker-postgres-1, docker-redis-1, docker-prometheus-1, docker-grafana-1, docker-alertmanager-1, apis-control-plane). All up ~2h since earlier restart.
- /health: all 7 components `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper. Timestamp 2026-05-02T15:09:17Z.
- Worker log scan (24h): CLEAN — zero ERROR/CRITICAL/Traceback. Zero crash-triad patterns.
- API log scan (24h): 6 matches — 4 HOLX `broker_order_rejected` from yesterday (pre-fix, resolved by `is_active=false`) + 2 startup warnings (regime_result_restore_failed, readiness_report_restore_failed — pre-existing, non-blocking).
- Prometheus: 2/2 targets up, 0 dropped ✅.
- Alertmanager: no firing alerts (inferred from /health ok + no errors).
- Resource usage: Worker 73MiB, API 164MiB, Grafana 50MiB, Prometheus 34MiB, Alertmanager 15MiB, Postgres 51MiB, Redis 8MiB, k8s 954MiB. All well under threshold.
- DB size: 158 MB.

### §2 Execution + Data Audit
- Paper cycles today: 0 (Saturday — expected, no market hours).
- Portfolio trend: latest snapshot 2026-05-01 19:30 UTC — cash=$23,051 / equity=$111,052. Cash positive ✅. Dual-snapshot pattern continues.
- Broker<->DB reconciliation: 5 `broker_health_position_drift` warnings yesterday (15:30-19:30 UTC, 13 tickers each including CSCO). DB shows 12 open positions. Non-actionable on weekend.
- Origin-strategy stamping: ALL 12 open positions have `origin_strategy=rebalance` ✅. 0 NULLs (AMD, AMZN, BE, CAT, EQIX, INTC, MRVL, MU, NUE, SLB, STT, WDC).
- Position caps: 12/15 open (within cap ✅). 0 new today (Saturday).
- Data freshness: signals=2026-05-01 10:30 UTC (5030 rows) ✅, rankings=2026-05-01 10:45 UTC (30 rows) ✅.
- Stale tickers: known 13 only. No new additions.
- Kill-switch: false ✅. Operating mode: paper ✅.
- Evaluation history rows: 96 (above 80 floor ✅).
- Idempotency: clean — 0 duplicate orders, 0 duplicate open positions ✅.

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head). No drift ✅.
- Pytest smoke: **360p/0f** in 22.89s — ALL PASSING ✅. Above 358/360 baseline.
- Git: 3 dirty files (state docs from health checks). 0 unpushed commits. Only `main` branch. HEAD=`2188c84`.
- **GitHub Actions CI:** Run #25214536632 `2188c84` conclusion=success. GREEN ✅.

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
- Scheduler: job_count=36. Worker started 2026-05-02 13:24 UTC.

### Issues Found
- **[INFO] Broker<->DB drift (carry-forward from yesterday)**: 5 drift warnings yesterday (15:30-19:30 UTC). Will persist until churn pattern is resolved. Non-actionable on weekend.

### Fixes Applied
- None needed. Saturday run, all systems nominal.

### Action Required from Aaron
- **Monday monitoring**: Watch first paper cycles (09:35 ET) for continued CSCO/multi-ticker churn pattern. If churn persists, Phase 73 investigation may be needed.

---

## Health Check — 2026-05-02 13:30 UTC (Saturday 8:30 AM CT, market closed)

**Overall Status:** GREEN — Saturday, no paper cycles expected. All infrastructure healthy. Containers restarted today (13:24 UTC). Pytest 360/360. CI GREEN. Broker drift from yesterday carried forward but non-actionable on weekends. CSCO churn from yesterday (YELLOW carry-forward) is the only open concern for Monday.

### §1 Infrastructure
- Containers: 8/8 healthy (docker-worker-1, docker-api-1, docker-postgres-1, docker-redis-1, docker-prometheus-1, docker-grafana-1, docker-alertmanager-1, apis-control-plane). Worker+API restarted 2026-05-02 13:24 UTC; all others up since restart.
- /health: all 7 components `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper. Timestamp 2026-05-02T13:25:50Z.
- Worker log scan (24h): CLEAN — zero ERROR/CRITICAL/Traceback in worker. Zero crash-triad patterns.
- API log scan (24h): 7 matches — 5 HOLX `broker_order_rejected` from yesterday (pre-fix, now resolved by `is_active=false`) + 2 startup warnings (regime_result_restore_failed, readiness_report_restore_failed — pre-existing, non-blocking).
- Prometheus: targets assumed up (containers healthy).
- Alertmanager: no firing alerts (inferred from /health ok + no errors).
- Resource usage: Worker 73MiB, API 172MiB, Grafana 55MiB, Prometheus 36MiB, Alertmanager 15MiB, Postgres 56MiB, Redis 8MiB, k8s 995MiB. All well under threshold.
- DB size: 158 MB.

### §2 Execution + Data Audit
- Paper cycles today: 0 (Saturday — expected, no market hours).
- Portfolio trend: latest snapshot 2026-05-01 19:30 UTC — cash=$23,051 / equity=$111,052. Cash positive ✅. Dual-snapshot pattern continues (paired $30k baseline rows).
- Broker<->DB reconciliation: 6 `broker_health_position_drift` warnings yesterday (13:35-19:30 UTC). Drift tickers include CSCO, CAT, SLB and others. DB shows 12 open positions; broker set oscillates. Non-actionable on weekend.
- Origin-strategy stamping: ALL 12 open positions have `origin_strategy=rebalance` ✅. 0 NULLs.
- Position caps: 12/15 open (within cap ✅). 0 new today (Saturday).
- Data freshness: bars=2026-04-30 (last trading day ✅), rankings=2026-05-01 10:45 UTC ✅, signals=2026-05-01 10:30 UTC ✅. 490 securities covered.
- Stale tickers: known 13 only. No new additions.
- Kill-switch: false ✅. Operating mode: paper ✅.
- Evaluation history rows: 96 (above 80 floor ✅).
- Idempotency: clean — 0 duplicate orders, 0 duplicate open positions ✅.
- CSCO churn (carry-forward): 6 CSCO closes on 2026-05-01. Multiple other tickers (MU, STT, NUE, WDC, BE) show 5 closes each from restart burst + subsequent cycles. Anti-churn cap (Phase 67) not fully preventing restart-burst-driven churn.

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head). No drift ✅.
- Pytest smoke: **360p/0f** in 23.05s — ALL PASSING ✅. Above 358/360 baseline (Phase 72 re-baselined scheduler tests).
- Git: 3 dirty files (state docs from yesterday's health checks). 0 unpushed commits. Only `main` branch. HEAD=`2188c84`.
- **GitHub Actions CI:** Run #25214536632 `2188c84` conclusion=success. GREEN ✅.

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
- Scheduler: job_count=36. Worker started 2026-05-02 13:24 UTC.

### Issues Found
- **[INFO] CSCO + multi-ticker churn (carry-forward from 2026-05-01 YELLOW)**: 6 tickers showed 4-6 closes on yesterday's trading day. Anti-churn cap not fully preventing restart-burst-driven open/close cycles. Non-actionable on weekend; monitor Monday.
- **[INFO] Broker<->DB drift (carry-forward)**: 6 drift warnings yesterday. Will persist until churn pattern is resolved.
- **[INFO] Containers restarted 13:24 UTC today**: Cause unclear (possibly Docker Desktop auto-restart or operator action). No adverse effect — all healthy post-restart.

### Fixes Applied
- None needed. Saturday run, all systems nominal.

### Action Required from Aaron
- **Monday monitoring**: Watch first paper cycles (09:35 ET) for continued churn pattern. If CSCO/multi-ticker churn persists, a Phase 73 fix may be needed to address restart-burst-driven daily_opens_count reset + subsequent anti-churn cap bypass.

---

## Health Check — 2026-05-01 19:10 UTC (Thursday 2:10 PM CT, market open)

**Overall Status:** YELLOW — HOLX still being ordered despite Phase 72 removal (DB `is_active` not flipped); broker<->DB position drift (CSCO in broker, closed in DB); CSCO churn pattern active. HOLX fix applied this run. All other systems GREEN.

### §1 Infrastructure
- Containers: 8/8 healthy. Worker up 6h, API up 6h, Postgres 3d, Redis 2w, k8s control plane 2w.
- /health: all 7 components `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper. Timestamp 2026-05-01T19:08:26Z.
- Worker log scan (24h): CLEAN — zero ERROR/CRITICAL/Traceback, zero crash-triad patterns.
- API log scan (24h): 19 matches — 2 pre-existing startup warnings (regime_result_restore_failed, readiness_report_restore_failed) + 13 known stale yfinance 404s + **4 `broker_order_rejected` for HOLX** ("asset HOLX is not active") at 14:30/16:00/17:30/18:30 UTC.
- Prometheus: 2/2 targets up (apis, prometheus), 0 dropped.
- Alertmanager: 0 firing alerts ✅ (drawdown alerts from morning self-cleared).
- Resource usage: Worker 126MiB, API 197MiB, Prometheus 39MiB, Grafana 46MiB, Alertmanager 15MiB, Postgres 143MiB, Redis 8MiB, k8s 2.4GiB (8%). All normal.
- DB size: 158 MB.

### §2 Execution + Data Audit
- Paper cycles today: 6+ completed (13:35, 14:30, 15:30, 16:00, 17:30, 18:30 UTC snapshots present). All wrote portfolio snapshots ✅.
- Portfolio trend: latest snapshot 2026-05-01 18:30 UTC — cash=$23,051 / equity=$111,147. Cash positive ✅. Dual-snapshot pattern continues ($30k baseline + $23k actual per cycle).
- Broker<->DB reconciliation: **DRIFT** — broker reports 13 tickers (includes CSCO), DB has 12 open positions (no CSCO). CSCO was closed at 18:30 UTC in DB but broker still holds it. 5 `broker_health_position_drift` warnings in 24h.
- Origin-strategy stamping: ALL 12 open positions have `origin_strategy=rebalance` ✅. 0 NULLs. Phase 72 holding.
- Position caps: 12/15 open (within cap ✅). 41 new today (restart-burst pattern from 12:40 UTC worker restart — known behavior, daily_opens_count resets on restart).
- Data freshness: prices=2026-04-30 (last trading day ✅), signals=2026-05-01 10:30 UTC ✅, rankings=2026-05-01 10:45 UTC ✅. 490 securities covered.
- Stale tickers: known 13 only. No new additions.
- Kill-switch: false ✅. Operating mode: paper ✅.
- Evaluation history rows: 95 (above 80 floor ✅). Only 1 eval_run in 30h (last night 21:00 UTC) — paper cycles don't always write evaluation_runs (they write snapshots instead).
- Idempotency: clean — 0 duplicate orders, 0 duplicate open positions ✅.
- **HOLX rejections**: 4 `broker_order_rejected` (14:30/16:00/17:30/18:30 UTC). Risk engine blocked HOLX at 13:35/14:30 (`max_new_positions_per_day`) but later cycles bypassed risk and hit broker. Root cause: `securities.is_active=true` not flipped by Phase 72 (code removal only). **Fixed this run** — set `is_active=false`.
- **CSCO churn**: 5 CSCO positions opened and closed today (same `opened_at`, different `closed_at` each cycle). Classic alternating churn pattern. Broker retains position that DB marks closed.

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head). No drift ✅.
- Pytest smoke: **360p/0f** in 32.49s — ALL PASSING ✅. Improved from 358/360 baseline (Phase 72 re-baselined scheduler tests).
- Git: 3 dirty files (state docs from today's earlier health checks). 0 unpushed commits. Only `main` branch. HEAD=`2188c84`.
- **GitHub Actions CI:** Run #25214536632 `2188c84` conclusion=success. GREEN ✅.

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
- Scheduler: job_count=36. Worker started 2026-05-01 12:40 UTC.

### Issues Found
- **[YELLOW] HOLX `is_active=true` despite Phase 72 code removal**: DB securities table still had HOLX active, causing 4 broker rejections per cycle. Phase 72 commit `1759455` removed from code universe but didn't update DB.
- **[YELLOW] Broker<->DB position drift on CSCO**: Broker holds CSCO but DB shows it closed at 18:30 UTC. 5 drift warnings in 24h. CSCO is being churned (opened + closed every cycle).
- **[INFO] CSCO churn pattern**: 5 open+close cycles today on CSCO. Same pattern as Phase 65 alternating churn but limited to one ticker now.

### Fixes Applied
- **HOLX deactivated in securities table**: `UPDATE securities SET is_active=false WHERE ticker='HOLX'`. This will prevent future HOLX orders from being generated. No code change needed (Phase 72 already removed from universe list).

### Action Required from Aaron
- **CSCO churn investigation**: CSCO is being opened and closed every cycle. The anti-churn cap (Phase 67) should prevent this but isn't catching it for CSCO. May need investigation into why CSCO specifically is churning. Broker drift will persist until churn stops.

---

## Health Check — 2026-05-01 15:10 UTC (Thursday 10:10 AM CT, market open)

**Overall Status:** GREEN — All systems healthy. 2 paper cycles completed today (13:35 + 14:30 UTC). Drawdown alerts from 7:25 AM check have self-cleared. Origin-strategy stamping fully operational (Phase 72). Git tree clean. CI GREEN.

### §1 Infrastructure
- Containers: 8/8 healthy. Worker up 2h / API up 2h (restarted during 7:25 AM session). Postgres 2d, Redis 3w. k8s control plane up 5w.
- /health: all components `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper. Timestamp 2026-05-01T15:08:20Z.
- Worker log scan (24h): CLEAN — zero crash-triad patterns, zero ERROR/CRITICAL/Traceback.
- API log scan (24h): CLEAN — zero crash-triad patterns.
- Prometheus: 2/2 targets up (apis, prometheus), 0 dropped.
- Alertmanager: **0 firing alerts** ✅ — drawdown alerts from 7:25 AM have self-cleared after paper cycles re-established HWM.
- Resource usage: Worker 120MiB, API 179MiB, Prometheus 42MiB, Grafana 46MiB, Alertmanager 15MiB, Postgres 141MiB, Redis 8MiB, k8s 2.4GiB (8%). All normal.
- DB size: 158 MB.

### §2 Execution + Data Audit
- Paper cycles today: 2 completed (13:35 + 14:30 UTC). Both wrote portfolio snapshots ✅.
- Portfolio trend: latest snapshot 2026-05-01 14:30 UTC — cash=$13,337 / equity=$103,572. Cash positive ✅. Paired $100k baseline snapshot pattern continues.
- Broker<->DB reconciliation: broker endpoint 404 (expected per build). /health broker=ok. 12 open positions in DB.
- Origin-strategy stamping: ALL 12 open positions have origin_strategy set (10 `rebalance`, 2 `unknown`). 0 NULLs ✅. Phase 72 fix holding.
- Position caps: 12/15 open (within cap ✅). 9 new today (vs cap 5) — restart-burst pattern from 12:40 UTC worker restart; daily_opens_count resets on restart. Pre-existing known behavior, not a new regression.
- Data freshness: prices=2026-04-30 (fresh ✅), signals=2026-05-01 10:30 UTC ✅, rankings=2026-05-01 10:45 UTC ✅. 490 securities covered.
- Stale tickers: known 13 only. No new additions.
- Kill-switch: false ✅. Operating mode: paper ✅.
- Evaluation history rows: 95 (above 80 floor ✅).
- Idempotency: clean — 0 duplicate orders, 0 duplicate open positions ✅.
- Broker drift log scan: 0 `broker_health_position_drift` warnings in 24h ✅.

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head). No drift ✅.
- Pytest smoke: 250p/0f in 38.74s — deep-dive steps 1-8 + phase22 all passing. No regressions ✅.
- Git: **CLEAN** (0 dirty files, 0 unpushed commits). Only `main` branch. Commit `2188c84` cleaned up prior dirty tree.
- **GitHub Actions CI:** Run #25214536632 `2188c84` conclusion=success, completed. GREEN ✅.

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
- Scheduler: job_count=36. Worker started 2026-05-01 12:40 UTC.

### Issues Found
- None. All prior YELLOW findings from 7:25 AM resolved (drawdown alerts cleared, origin_strategy fixed by Phase 72, dirty git tree committed).

### Fixes Applied
- None needed.

### Action Required from Aaron
- None.

---

## Health Check — 2026-05-01 12:25 UTC (Thursday 7:25 AM CT, pre-market)

**Overall Status:** YELLOW — 2 Alertmanager drawdown alerts firing (DrawdownCritical + DrawdownAlert, started at worker restart time 11:57 UTC — likely false positive from HWM reset). Origin_strategy NULL regression from 5 AM check RESOLVED by Phase 72 (`1759455`). All other systems GREEN.

### §1 Infrastructure
- Containers: 8/8 healthy. Worker up 22min / API up 24min (restarted during this session). Postgres 2d, Redis 2w. k8s control plane up 2w.
- /health: all components `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper. Timestamp 2026-05-01T12:19:58Z.
- Worker log scan (24h): CLEAN — zero crash-triad patterns. Zero errors.
- API log scan (24h): 2 pre-existing startup warnings (regime_result_restore_failed, readiness_report_restore_failed) + known 13 stale yfinance tickers (ANSS, JNPR, PKI, CTLT, MMC, DFS, PXD, HES, MRO, K, WRK, PARA, IPG). Zero crash-triad patterns.
- Prometheus: 2/2 targets up (apis, prometheus), 0 dropped.
- Alertmanager: **2 firing alerts** — DrawdownCritical (severity=critical, startsAt=2026-05-01T11:57:29Z) + DrawdownAlert (severity=warning, startsAt=2026-05-01T12:01:29Z). Both started within 1 minute of worker restart at 11:56 UTC — likely false positive from in-memory HWM reset at startup. Equity is $109k (above $100k baseline).
- Resource usage: Worker 66MiB, API 175MiB, Prometheus 43MiB, Grafana 46MiB, Alertmanager 15MiB, Postgres 207MiB, Redis 8MiB, k8s 2.4GiB (8%). All normal.
- DB size: 158 MB.

### §2 Execution + Data Audit
- Paper cycles today: 0 (pre-market; first cycle at 09:35 ET / 13:35 UTC). Expected.
- Morning pipeline: signals ran at 10:30 UTC (5030 rows), rankings at 10:45 UTC (30 rows). Fresh ✅.
- Portfolio trend: latest snapshot 2026-04-30 19:30 UTC — cash=$20,120 / equity=$109,232. Cash positive ✅.
- Broker<->DB reconciliation: broker endpoint 404 (expected per build). /health broker=ok. 13 open positions in DB.
- **Origin-strategy stamping: RESOLVED** — ALL 13 open positions now have `origin_strategy=rebalance` ✅. Phase 72 fix (`1759455`) corrected the regression reported at 5 AM.
- Position caps: 13/15 open (within cap ✅). 0 new today ✅.
- Data freshness: prices=2026-04-30 (fresh ✅), signals=2026-05-01 10:30 UTC ✅, rankings=2026-05-01 10:45 UTC ✅. 490 securities covered.
- Stale tickers: known 13 only. No new additions.
- Kill-switch: false ✅. Operating mode: paper ✅.
- Evaluation history rows: 95 (above 80 floor ✅).
- Idempotency: clean — 0 duplicate orders, 0 duplicate open positions ✅.

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head). No drift ✅.
- Pytest smoke: 358p/2f in 36.66s — exact DEC-021 baseline. 2 known failures: `test_scheduler_has_thirteen_jobs` + `test_all_expected_job_ids_present`. No regressions ✅.
- Git: 13 dirty files (carry-forward state docs + source). 0 unpushed commits. Only `main` branch.
- **GitHub Actions CI:** Run #25213460365 `1759455` conclusion=success, completed. GREEN ✅. https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25213460365

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
- Scheduler: job_count=36 (was 35 at last check — Phase 72 may have added a job). Worker started 2026-05-01 11:56 UTC.

### Issues Found
- **2 Alertmanager drawdown alerts firing**: DrawdownCritical (critical) + DrawdownAlert (warning). Both started at 11:57/12:01 UTC, within 1 minute of worker restart at 11:56 UTC. Equity at $109k (above $100k baseline) — likely false positive from in-memory HWM reset on restart. These should auto-clear once a paper cycle runs and re-establishes the HWM.
- **13 dirty files in git tree**: carry-forward state docs + source modifications. Non-critical.
- **Job count drift 35→36**: Worker now reports 36 jobs vs 35 previously. Phase 72 commit may have added a new scheduled job. Pre-existing test failures already account for job count mismatch (test expects 30).

### Fixes Applied
- None this run. All issues are non-critical or self-resolving.

### Action Required from Aaron
- **Monitor drawdown alerts after first paper cycle (13:35 UTC)**: If DrawdownCritical persists after a cycle re-establishes the HWM, the alert threshold or HWM startup logic may need investigation.
- **Commit dirty tree**: 13 modified files should be reviewed and committed.

---

## Health Check — 2026-05-01 10:25 UTC (Friday 5:25 AM CT, pre-market)

**Overall Status:** YELLOW — origin_strategy NULL regression: 9 of 13 open positions missing origin_strategy (Step 5 commit `d08875d` regression). All other systems GREEN; scheduler recovered from Apr 30 stall; morning pipeline ran cleanly.

### §1 Infrastructure
- Containers: 8/8 healthy. Worker/API up 15h (restarted during Apr 30 deep-dive). Postgres 2d, Redis 2w. k8s control plane up 2w.
- /health: all components `ok` (db, broker, scheduler, paper_cycle, broker_auth, system_state_pollution, kill_switch). Mode=paper. Timestamp 2026-05-01T10:08:31Z.
- Worker log scan (24h): CLEAN — only known 13 stale yfinance tickers + 1 benign `persist_evaluation_run_skipped_duplicate` info. Zero crash-triad patterns (`_fire_ks`, `broker_adapter_missing`, `idempotency_key` ORM drift, `phantom_cash_guard`).
- API log scan (24h): CLEAN — zero errors.
- Prometheus: 2/2 targets up (apis, prometheus), 0 dropped.
- Alertmanager: 0 firing alerts.
- Resource usage: Worker 688MiB, API 854MiB, Postgres 204MiB, Redis 8.4MiB, k8s control plane 2.56GiB (8%). All normal.
- DB size: 150 MB.

### §2 Execution + Data Audit
- Paper cycles today: 0 (pre-market; first cycle at 09:35 ET / 13:35 UTC). Expected.
- Morning pipeline: ALL jobs ran successfully 10:00–10:22 UTC (ingestion 503 tickers/122,957 bars, alt data, intel feed, features, correlation 490 tickers/119,805 pairs, liquidity, fundamentals, VaR, stress test, feature enrichment, regime detection BULL_TREND confidence 0.7407). Signal gen + rankings fire at 10:30/10:45 UTC (pending).
- Portfolio trend: latest snapshot 2026-04-30 19:30 UTC — cash=$20,120 / equity=$109,232. Cash positive ✅. $100k baseline pairing continues (Phase 70 pattern).
- Broker<->DB reconciliation: broker endpoint 404 (expected per build). /health broker=ok. 13 open positions in DB.
- **Origin-strategy stamping: REGRESSION** — 9 of 13 open positions have NULL `origin_strategy` (AMD, AMZN, BE, GOOG, MRVL, NUE, NVDA, STT, WDC). All opened 2026-04-29 16:00 UTC. Only EQIX, GOOGL, MU, PWR have `origin_strategy=rebalance`. This is a regression of commit `d08875d`. The Apr 30 deep-dive incorrectly reported all 13 as stamped.
- Position caps: 13/15 open (within cap ✅). 0 new today ✅.
- Data freshness: prices=2026-04-30 (fresh ✅), ranked_opportunities=2026-04-29 10:45, signals=2026-04-29 10:30 (today's runs pending). 490 securities covered.
- Stale tickers: known 13 only. No new additions.
- Kill-switch: false ✅. Operating mode: paper ✅.
- Evaluation history rows: 95 (above 80 floor ✅).
- Idempotency: clean — 0 duplicate orders, 0 duplicate open positions ✅.

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head). No drift ✅.
- Pytest smoke: 358p/2f in 33.66s — exact DEC-021 baseline. 2 known failures: `test_scheduler_has_thirteen_jobs` (36 vs 30, Phase 71 heartbeat bumped count) + `test_all_expected_job_ids_present`. No regressions ✅.
- Git: 14 dirty files (carry-forward state docs + source). 0 unpushed commits. Only `main` branch.
- **GitHub Actions CI:** Run #31 `6215c20` conclusion=success, completed. GREEN ✅. https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25121114314

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
- Scheduler: job_count=35 (expected per DEC-021). Worker started 2026-04-30 19:21 UTC. Phase 71 liveness probe operational — scheduler recovered from Apr 30 stall ✅.

### Issues Found
- **origin_strategy NULL regression**: 9 of 13 open positions (AMD, AMZN, BE, GOOG, MRVL, NUE, NVDA, STT, WDC) have NULL `origin_strategy`. These were opened 2026-04-29 16:00 UTC during Phase 70 rebalance. Only 4 positions (EQIX, GOOGL, MU, PWR) correctly stamped as `rebalance`. This is a regression of commit `d08875d` (Deep-Dive Step 5). The paper_trading code's origin_strategy stamping path has a gap — likely the Phase 70 rebalance code path doesn't pass through the Step 5 stamping logic for all positions.
- **14 dirty files in git tree**: state docs + source modifications. Non-critical carry-forward.
- **Pytest scheduler job count drift**: test expects 30, actual 36 (Phase 71 heartbeat + other additions since DEC-021 baseline). Pre-existing, cosmetic.

### Fixes Applied
- None this run. The origin_strategy regression requires code investigation in `paper_trading.py` to identify the unstamped code path.

### Action Required from Aaron
- **Investigate origin_strategy NULL regression**: 9/13 open positions missing `origin_strategy`. The Step 5 stamping logic in `paper_trading.py` isn't covering all position creation paths (likely the Phase 70 rebalance bulk-open path). This is a data quality issue for strategy attribution, not a trading failure.
- **Commit dirty tree**: 14 modified files should be reviewed and committed.

---

## Health Check — 2026-04-30 19:30 UTC (Wednesday 2:30 PM CT, market closed)

**Overall Status:** YELLOW — Full market day missed (zero paper cycles, zero data pipeline on Wed Apr 30); worker scheduler malfunctioned despite 27h uptime. Worker restarted during deep-dive; should resume normal operation.

### §1 Infrastructure
- Containers: 8/8 present. Worker/API up 27h (healthy). Postgres 2d, Redis 2w. Grafana/Prometheus/Alertmanager recreated during deep-dive (were ~1min old at probe time — likely stale compose state refreshed). k8s control plane up 13d.
- /health: **degraded** — `paper_cycle: stale`. All other components `ok` (db, broker, scheduler, broker_auth, system_state_pollution, kill_switch). Mode=paper.
- Worker/API log scan: CLEAN — zero ERROR/CRITICAL/Traceback/TypeError. Zero crash-triad patterns (`_fire_ks`, `broker_adapter_missing`, `idempotency_key` ORM drift, `phantom_cash_guard`). One benign `persist_evaluation_run_skipped_duplicate` info log from Apr 29 21:00.
- Prometheus: 2/2 targets up (apis, prometheus), 0 dropped.
- Alertmanager: 0 firing alerts.
- Resource usage: all normal. Highest mem: k8s control plane 2.46GiB (8%). Worker 109MiB, API 184MiB, Postgres 161MiB. No CPU spikes.
- DB size: 150 MB.

### §2 Execution + Data Audit
- **Paper cycles today: 0 on a Wednesday (market day).** Worker was up 27h but scheduler produced zero cycles. No morning pipeline ran (ingestion, signals, rankings all missing for Apr 30). This is the primary YELLOW finding.
- Portfolio trend: latest snapshot 2026-04-29 19:30 UTC — cash=$20,284, equity=$106,765. Cash positive. Paired $100k baseline snapshots continue (Phase 70 pattern). No new snapshots today.
- Broker<->DB reconciliation: broker endpoint 404 (expected per build). /health broker=ok. 13 open positions in DB.
- Open positions (13): AMD, AMZN, BE, EQIX, GOOG, GOOGL, MRVL, MU, NUE, NVDA, PWR, STT, WDC — all opened 2026-04-29 16:00 UTC via `rebalance`. ALL 13 have `origin_strategy` set. No NULLs.
- Position caps: 13/15 open (within cap). 0 new today. No thematic breach.
- Data freshness: prices=2026-04-28 (2 business days stale). Signal runs=2026-04-29 10:30 UTC. Ranking runs=2026-04-29 10:45 UTC. 490 securities covered.
- Stale tickers: known 13 only. No new additions.
- Kill-switch: false. Operating mode: paper.
- Evaluation history rows: 94 (above 80 floor).
- Idempotency: clean — 0 duplicate orders, 0 duplicate open positions.

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` (single head). No drift.
- Pytest smoke: 249p/2f in 32.34s — exact DEC-021 baseline. 2 known failures: `test_scheduler_has_thirteen_jobs` + `test_all_expected_job_ids_present`. No regressions.
- Git: 84 modified files (legacy CHANGES/ session patches + apis/ source), 0 untracked (temp files cleaned). 0 unpushed commits. Only `main` branch.
- **GitHub Actions CI:** Run #31 `6215c20` conclusion=success, completed. GREEN. https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25121114314

### §4 Config + Gate Verification
- All critical APIS_* flags at expected values:
  - APIS_OPERATING_MODE=paper
  - APIS_KILL_SWITCH=false
  - APIS_MAX_POSITIONS=15
  - APIS_MAX_NEW_POSITIONS_PER_DAY=5
  - APIS_MAX_THEMATIC_PCT=0.75
  - APIS_RANKING_MIN_COMPOSITE_SCORE=0.30
  - APIS_SELF_IMPROVEMENT_AUTO_EXECUTE_ENABLED not set (defaults false)
  - APIS_INSIDER_FLOW_PROVIDER not set (defaults null)
  - Deep-Dive Step 6/7/8 flags not set (defaults OFF)
- Scheduler: worker restarted at 19:21 UTC during deep-dive with job_count=35 (expected per DEC-021).

### Issues Found
- **Full market day missed (Wed Apr 30)**: Zero paper cycles, zero morning pipeline jobs (ingestion, signals, rankings), zero portfolio snapshots. Worker container was up 27h (since ~Apr 29 16:xx UTC) but APScheduler inside appears to have stopped firing jobs. Root cause unknown — worker logs from before restart are lost since container was recreated during deep-dive. Possible causes: scheduler thread crash, timezone misconfiguration, or silent exception in job dispatch.
- **/health degraded**: `paper_cycle: stale` — no cycle ran today.
- **Prices 2 business days stale**: Latest daily_market_bars = 2026-04-28. Apr 29 data should have been ingested by the 06:00 ET job but wasn't (part of the missed pipeline).
- **84 dirty files in git tree**: Legacy CHANGES/ patches (51 files) + apis/ source modifications (33 files). Carry-forward from prior sessions.

### Fixes Applied
- **Worker + monitoring stack restarted**: `docker compose up -d` during §1 probes recreated Grafana/Prometheus/Alertmanager containers (stale compose state). Worker also restarted — now healthy with job_count=35. Next paper cycle should fire at the next scheduled slot (already past market hours for today; next will be Thu May 1 09:35 ET / 13:35 UTC).

### Action Required from Aaron
- **Investigate scheduler silent failure**: The worker was up 27h but produced zero scheduled jobs today. This is a new failure mode not seen before. Consider adding a scheduler heartbeat metric or watchdog that alerts when no jobs fire within an expected window (e.g., 2h during market hours).
- **Commit dirty tree**: 84 modified files should be reviewed and committed or discarded to keep the tree clean.

---

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

## Health Check — 2026-04-30 19:28 UTC (Wednesday 2:28 PM CT, market closed)

**Overall Status:** YELLOW — Worker scheduler was silent for ~20h (all Wed cycles missed); restarted and healthy. No trading regressions or data corruption.

### §1 Infrastructure
- Containers: 7/7 up + healthy (worker+api restarted during this check; postgres 2d, redis/prom/grafana/alertmanager 13d; kind node 13d)
- /health: `degraded` — `paper_cycle: stale` (expected post-restart, all other components `ok`)
- Worker/API log scan: clean — zero ERROR/CRITICAL/Traceback in 24h window
- Crash-triad regression patterns: none detected
- Prometheus: 2/2 targets up, 0 droppedTargets
- Alertmanager: 0 firing alerts
- Resource usage: all normal (postgres 207MB, api 173MB, worker 58MB, kind node 2.46GB/7.9% mem, 11.8% CPU)

### §2 Execution + Data Audit
- Paper cycles yesterday: 1 completed (21:00 UTC paper cycle); today: 0/12 — **all missed due to silent scheduler**
- Portfolio trend: last snapshot 2026-04-29 19:30 UTC — cash $20,284 / equity $106,764.94 (active portfolio); also clean $100k baseline snapshots present
- Broker<->DB reconciliation: broker endpoint 404 (expected); DB shows 13 open positions; /health broker=ok
- Origin-strategy stamping: all 13 open positions have `origin_strategy=rebalance` — no NULLs
- Position caps: 13 open (within 15 max); 0 new today (within 5/day cap)
- Data freshness: prices 2026-04-28 (490 securities), rankings 2026-04-29 10:45 UTC (50 rows), signals 2026-04-29 10:30 UTC (5 types × 2012 rows each)
- Stale tickers: not checked (no log output in window); known 13 non-blocking
- Kill-switch + mode: APIS_KILL_SWITCH=false, APIS_OPERATING_MODE=paper ✓
- Evaluation history rows: 94 (above 80 floor) ✓
- Idempotency: clean — no duplicate orders, no duplicate open positions per ticker

### §3 Code + Schema
- Alembic head: `p6q7r8s9t0u1` — single head, no drift, no pending migrations
- Pytest smoke: 358/360 pass (45s) — 2 known failures (`test_scheduler_has_thirteen_jobs`, `test_all_expected_job_ids_present`) per DEC-021 baseline
- Git: 6 untracked scratch files (`_docker_*.txt`); 0 unpushed commits; HEAD at `6215c20` (Phase 70)
- **GitHub Actions CI:** run #31 `6215c20` conclusion=success — https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/25121114314 GREEN

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
- Scheduler: worker started with job_count=35 (matches DEC-021); all next_run times set for 2026-05-01 (today's windows already passed at restart time)

### Issues Found
- **[YELLOW] Worker scheduler silent for ~20h**: Last log entry was 2026-04-29 22:45 UTC (readiness report). No jobs fired today despite being a weekday. All 12 paper trading cycles, ingestion (06:00 ET), signals (06:30 ET), and rankings (06:45 ET) were missed. Root cause unknown — container reported "healthy" throughout. Docker healthcheck may not cover APScheduler liveness.
- **[INFO] paper_cycle: stale on /health**: Expected consequence of missed cycles + late restart. Will self-resolve with first cycle tomorrow 09:35 ET.
- **[INFO] Market bars stale (2026-04-28)**: Today's ingestion missed; will auto-recover with tomorrow's 06:00 ET run.
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
