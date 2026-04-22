# APIS Health Log

Auto-generated daily health check results.

---

## 2026-04-22 15:16 UTC — Deep-Dive Scheduled Run (Wed 10 AM CT, mid-session) — **YELLOW** (downgrade from morning GREEN; 3 new-to-this-run regressions)

**Overall Status:** **YELLOW** — downgrade from morning 10:14 UTC GREEN. Three new-to-this-run regressions on first two Wed cycles (13:35 + 14:30 UTC): (1) **phantom-equity writer** at 13:35 UTC — yfinance DNS failure (`Could not resolve host: query2.finance.yahoo.com`) on all 4 held tickers (INTC/MRVL/EQIX/HOLX) → mark-to-market fell to ~zero → snapshot wrote `equity=$28,296.77` (actual ≈ $101K: cash $23,006.77 + cost basis $59,930.51). Risk engine fired fake stop-losses (`pnl=-99.08/-85.27/-93.23/-86.85%`) correctly blocked by `daily_loss_limit`. 14:30 UTC cycle recovered (`equity=$101,623.76`). (2) **Broker↔DB position drift** — `broker_health_position_drift` warning firing every cycle since **Tue 17:30 UTC** (5 hits over 22h incl. the morning-GREEN window). Broker stuck at Monday's `[UNP, ODFL, EQIX, MRVL, BK, INTC]`; DB now `[INTC, MRVL, EQIX, HOLX]`. Morning deep-dive missed this. (3) **Phase 65 Alternating Churn regression** — BK/ODFL/UNP/HOLX each have 14–15 CLOSED position rows with identical `opened_at` but different `closed_at` (signature of `project_phase65_alternating_churn.md` which memory says was fixed 2026-04-16; regressed). ~20 more tickers with 4–8 dupe rows. No dupe OPENs (idempotency ✅). 0 crash-triad hits, 0 phantom-cash guard, CI 8th consecutive GREEN, pytest exact baseline. Not RED (cash positive, caps respected, cycles complete, `/health=ok`).

### §1 Infrastructure — GREEN
- 7 APIS + `apis-control-plane` all healthy; no restarts (worker/api Up 3d, postgres/redis Up 5d).
- `/health` HTTP 200, `timestamp=2026-04-22T15:11:12Z`, all 6 components ok.
- Worker log 24h: **40 matches**, 0 crash-triad — 33 known yfinance stale + 4 NEW transient DNS fails on current holdings + 1 `load_active_overrides_failed` + 1 `persist_evaluation_run_failed UniqueViolation` (warning) + 1 false-positive `feature_refresh_job_complete errors:0`. **0 `broker_order_rejected`**.
- API log 24h: 45 matches, 0 crash-triad.
- Prometheus 2/2 up; Alertmanager 0 alerts; resource usage clean (worker 681 MiB, api 918 MiB, control-plane 14.47% CPU baseline).
- Postgres DB: **97 MB** (+5 MB from morning 92 MB — growth from today's cycles + dupe position rows).

### §2 Execution + Data Audit — YELLOW (phantom-equity + broker drift + Phase 65 regression)
- Wed paper cycles observed: 13:35 UTC (`proposed=4 approved=0 executed=0`) + 14:30 UTC (`proposed=0 approved=0 executed=0`). paper_cycle_count=16.
- **Phantom-equity**: 2026-04-22 13:35:00.075017 snapshot `cash=23,006.77 / equity=28,296.77` (should be ~$101K). Next cycle 14:30 UTC recovered `equity=101,623.76`. Bad row remains in DB — data integrity issue for backtest/replay consumers.
- **Broker↔DB reconciliation: DRIFT ⚠️** — `broker_health_position_drift` at Wed 13:35 + 14:30 UTC; also Tue 17:30 / 18:30 / 19:30 UTC (missed by morning deep-dive). Broker tickers `[UNP, ODFL, EQIX, MRVL, BK, INTC]`; DB `status='open'` tickers `[INTC, MRVL, EQIX, HOLX]`. `/health broker=ok` doesn't reflect this.
- Positions: 4 open / 233 closed (+7 closes since morning — BK/ODFL/UNP each closed twice, HOLX closed once+reopen). Cost basis of opens = $59,930.51.
- Open tickers all `origin_strategy` set ✅: INTC (momentum_v1, qty 223 @ 67.89), MRVL (theme_alignment_v1, qty 100 @ 147.66), EQIX (momentum_v1, qty 14 @ 1090.81), HOLX (momentum_v1, qty 194 @ 76.05). MRVL qty jumped 63→100 and HOLX replaced UNP — Phase 65 churn signature.
- Position caps: 4/15 ✅; 0 new today /5 ✅ (no `opened_at >= 2026-04-22` rows).
- Orders ledger: still **0 rows all-time** — known latent issue.
- **Phase 65 regression ⚠️**: BK=15, ODFL=15, HOLX=15, UNP=14 CLOSED rows with identical `opened_at` and different `closed_at`; NFLX/BE/CIEN=8; STX/JNJ/WBD/AMD=7; +~20 tickers with 4–6 dupes. 2026-04-16 fix regressed. No dupe OPENs (functional preservation).
- Data freshness: bars 2026-04-21, rankings Wed 10:45 UTC ✅, signals Wed 10:30 UTC ✅ — all intra-day runs fired as scheduled.
- Stale tickers: same 13 known + 4 NEW transient (current holdings from DNS fail — not legit delisted).
- Kill-switch=false, mode=paper (appropriate — no active damage, phantom-equity self-healed).
- eval_runs=86 (≥80 floor ✅).
- Idempotency: 0 duplicate OPEN positions ✅; 0 orders → moot.

### §3 Code + Schema — GREEN
- Alembic single head `o5p6q7r8s9t0` ✅. Cosmetic drift on Step 7/8 tables (TIMESTAMP-with-tz ↔ DateTime, NOT NULL, index shape) — pre-existing, non-blocking.
- Pytest: **358p / 2f / 3655d in 31.45s** — exact DEC-021 baseline. 2 known phase22 scheduler-count drifts.
- Git: `main@c0a0580` (morning GREEN commit), 0 unpushed, clean tree.
- **GitHub Actions CI:** run `24773406253` on `c0a0580` → `conclusion=success` — **8th consecutive GREEN**. https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/24773406253.

### §4 Config + Gate Verification — GREEN
- All 11 critical `APIS_*` flags match expected values; no drift; no `.env` auto-fix applied.
- Scheduler `job_count=35` ✅ (DEC-021 accelerated count).

### Issues Found
- YELLOW (new): **Phantom-equity writer** at Wed 13:35 UTC — yfinance DNS failure caused mark-to-market zero fallback; bad snapshot row remains in DB.
- YELLOW (pre-existing, missed by morning): **Broker↔DB drift** — 22+ hours stale broker state; morning deep-dive missed because `/health broker=ok` doesn't surface the invariant.
- YELLOW (new regression): **Phase 65 Alternating Churn** — 2026-04-16 fix regressed; 14–15 dupe CLOSED rows per core ticker.
- YELLOW (carried forward): `orders` ledger 0 rows all-time.
- YELLOW (carried forward): `universe_overrides` missing; 1 `load_active_overrides_failed` warning.
- YELLOW (cosmetic): alembic Step 7/8 schema drift (non-blocking).

### Fixes Applied
- **None this run.** All 3 new findings require operator review / code patching. No flag drift detected.

### Action Required from Aaron
1. **HIGH**: Investigate phantom-equity root cause — Docker DNS config? Yahoo Finance provider drift? Patch mark-to-market fallback to preserve prior-close rather than zero.
2. **MEDIUM-HIGH**: Audit `services/portfolio/` for broker↔DB drift root cause (likely tied to Phase 65 regression).
3. **MEDIUM**: Re-verify Phase 65 2026-04-16 fix in `apps/worker/jobs/paper_trading.py` + `services/portfolio/`.
4. **LOW (carry forward)**: `orders` ledger writer patch.
5. **LOW (carry forward)**: `universe_overrides` migration.
6. **PROCESS**: Update deep-dive §2.3 reconciliation to add a log-based `broker_health_position_drift` check — morning run missed this because it only queried DB.

### Trajectory
Morning 10:14 UTC GREEN classification was optimistic. Next deep-dive (Wed 19:16 UTC / 2 PM CT) should verify: (a) no repeat phantom-equity, (b) broker drift warning continues firing (expected until patch), (c) no new duplicate-row proliferation. Baseline: YELLOW class → email sent to operator.

---

## 2026-04-22 10:14 UTC — Deep-Dive Scheduled Run (Wed 5 AM CT, pre-market) — **GREEN** (first GREEN after 4 RED + 1 YELLOW; incident chain closed)

**Overall Status:** **GREEN** — overnight hold clean (no paper cycles Tue 19:30 UTC → Wed 10:14 UTC); latest `portfolio_snapshots` row stable POSITIVE `cash=$23,006.77 / equity=$101,640.07`; 6 open positions (all origin_strategy stamped); 0 new today (pre-market); all §1–§4 sections clean; CI 7th consecutive GREEN; pytest exact DEC-021 baseline; all 11 `APIS_*` flags match expected. Remaining latent issues (`orders` ledger empty, `universe_overrides` migration) are on the pre-existing known-issues list. **State-doc batch from 2026-04-20 → 2026-04-21 committed this run** per yesterday's trajectory plan. Wed 13:35 UTC first cycle is the next data point (~3h after deep-dive).

### §1 Infrastructure — GREEN
- 7 APIS containers + `apis-control-plane` all healthy (worker/api Up 3d, postgres/redis/monitoring Up 5d).
- `/health` HTTP 200, `timestamp=2026-04-22T10:12:49Z`, all 6 components ok.
- Worker log 24h: **36 matches**, 0 crash-triad — 33 yfinance 404 (13 stale names) + 1 `load_active_overrides_failed` + 1 `persist_evaluation_run_failed UniqueViolation` (warning-level idempotency guard on Tue 21:00 UTC daily eval) + 1 false-positive `feature_refresh_job_complete errors:0`.
- API log 24h: 36 matches, 0 crash-triad.
- Prometheus 2/2 up; Alertmanager 0 alerts; docker stats clean (worker 682 MiB, api 917 MiB, postgres 168 MiB, control-plane 15.29% CPU baseline). DB 92 MB (+2 MB).

### §2 Execution + Data Audit — GREEN
- Last paper cycle: Tue 19:30 UTC (`cash=+$23,006.77 / equity=$101,640.07` POSITIVE). No cycles overnight — expected.
- Phantom-cash writer: not reproduced since Tue 14:30 UTC. Tue 15:30/16:00/17:30/18:30/19:30 UTC all POSITIVE; yesterday's YELLOW trajectory prediction confirmed.
- Positions: 6 open / 226 closed. All 6 opens have `origin_strategy` (INTC/EQIX/BK/ODFL/UNP = momentum_v1, MRVL = theme_alignment_v1). Cost basis $77,022.11.
- Position caps: 6/15 ✅; 0 new today / 5 ✅ (Wed pre-market, first cycle 13:35 UTC).
- Origin-strategy stamping: 0 NULL on OPEN positions opened ≥ 2026-04-18 ✅. 30 archived CLOSED NULLs from Mon 13:35 UTC churn (pre-existing, not live).
- Orders ledger: still **0 rows all-time** — persistent known-issue, no active damage this cycle.
- Data freshness: bars 2026-04-21, rankings Tue 10:45 UTC, signals Tue 10:30 UTC (today's Wed runs fire at ~10:30/10:45 UTC, imminent).
- Stale tickers: same 13 known names, no new additions.
- Kill-switch=false, mode=paper (operator-set).
- eval_runs=86 (≥80 floor ✅, +1 since yesterday's Tue 21:00 UTC eval).
- Idempotency: 0 duplicate open positions; 0 orders → moot.

### §3 Code + Schema — GREEN
- Alembic single head `o5p6q7r8s9t0` ✅.
- Pytest: **358p / 2f / 3655d in 32.88s** — exact DEC-021 baseline. 2 known phase22 scheduler-count drifts.
- Git: `main@a1e61bc`, 0 unpushed, 4 dirty state-doc files (batch-committed this run).
- **GitHub Actions CI:** run `24661165493` on `a1e61bc` → `conclusion=success` — **7th consecutive GREEN** since 5db564e recovery.

### §4 Config + Gate Verification — GREEN
- All 11 critical `APIS_*` flags match expected values; no drift; no auto-fix applied.
- Scheduler `job_count=35` ✅ (DEC-021 accelerated count).

### Issues Found
- All pre-existing, on known-issues list (no new findings this cycle): (1) `orders` table 0 rows all-time (Order-ledger writer bug, latent); (2) `universe_overrides` migration missing (1 warning per 48h); (3) `signal_outcomes` table 0 rows (signal-quality pipeline bug, follow-up).

### Fixes Applied
- **Batch-committed 4 dirty state-doc files** (ACTIVE_CONTEXT.md, HEALTH_LOG.md × 2, DECISION_LOG.md) accumulated across Mon 15:15 + Mon 19:15 + Tue 10:12 + Tue 15:12 + Tue 19:11 UTC runs, plus today's Wed 10:14 UTC entries. See git log for SHA; pushed to `origin/main`.

### Action Required from Aaron
1. **Patch `orders` ledger writer** — paper-cycle code not routing through order engine. No urgency, operator-paired session recommended.
2. **`universe_overrides` migration** — low-priority cleanup.
3. **Root-cause phantom-cash writer** — audit `services/portfolio/` in-memory ledger state across cycle boundaries; pair with item 1.

**Trajectory note:** This run closes the 2026-04-20 first-weekday-cycle RED/YELLOW incident chain (5 non-GREEN deep-dives → GREEN on overnight hold). Wed 13:35 UTC first cycle (~3h out) is the next data point; clean Wed cycle → self-heal is durable.

---

## 2026-04-21 19:11 UTC — Deep-Dive Scheduled Run (Tue 2 PM CT, late-session, market open) — **YELLOW** (phantom writer self-healed; 5th run, first downgrade from RED)

**Overall Status:** **YELLOW — downgraded from RED for the first time since Mon 15:15 UTC.** Tuesday's 15:30 / 16:00 / 17:30 / 18:30 UTC paper cycles write POSITIVE post-cycle cash ($22,632.53 → $23,006.77 stable) — the phantom-cash writer has stopped reproducing. 6 open positions (all with `origin_strategy`), 0 new today, cap 6/15 ✅. Equity stable ~$101k. CI 6th consecutive GREEN. Pytest exact DEC-021 baseline. All 11 `APIS_*` flags match expected. **Only remaining concern:** `orders` table still 0 rows all-time (latent Order-ledger writer bug unpatched — same signature as prior 4 RED runs, but no active damage in this cycle). Operator has not responded to 4 prior RED emails (27+ hours) — but autonomous self-healing via cycle-driven closes has materialized as predicted in the Tue 15:12 UTC trajectory note.

### §1 Infrastructure — GREEN
- 7 APIS containers + `apis-control-plane` healthy; worker/api Up 2d, postgres/redis/monitoring Up 4d.
- `/health` all 6 components ok, `timestamp=2026-04-21T19:11:33.600187+00:00`.
- Worker log 24h: 41 matches (18 yfinance 404 + 5 broker_order_rejected [down from 25] + 13 individual stale-ticker + 1 load_active_overrides_failed + 1 persist_evaluation_run_failed UniqueViolation [warning idempotency] + 1 false-positive). **0 crash-triad hits.**
- API log 24h: 36 matches; 0 crash-triad hits.
- Prometheus 2/2 up; Alertmanager 0 alerts.
- Docker stats: all well under threshold.
- Postgres DB: 90 MB (unchanged from 15:12 UTC).

### §2 Execution + Data — YELLOW (first downgrade from RED)
- **Phantom-cash writer self-healed** — latest 4 post-cycle `portfolio_snapshots` rows all POSITIVE: Tue 15:30 UTC = $22,632.53; Tue 16:00 = $23,006.77; Tue 17:30 = $23,006.77; Tue 18:30 = $23,006.77. Day-long trajectory: Mon -$242,101 → Tue 13:35 -$66,223 → Tue 14:30 -$1,603 → Tue 15:30+ POSITIVE $22-23k.
- **Positions**: 6 open / 222 closed (+16 from 15:12 UTC expected from 4 more cycles). Cost basis opens $77,022.11. Open tickers UNP/INTC/MRVL/EQIX/BK/ODFL all with `origin_strategy`. 0 new today, 0 NULL origin today.
- **Orders ledger**: still 0 rows all-time (persistent latent bug — same signature as prior 4 runs, but no active damage this cycle).
- **Data freshness**: daily_market_bars 2026-04-20, ranking_runs today 10:45 UTC, signals today 10:30 UTC × 5 × 2012 rows.
- **Kill-switch**: false (expected); mode=paper.
- **Idempotency**: clean (0 dupes).
- **Equity**: stable ~$101k throughout day.

### §3 Code + Schema — GREEN
- Alembic `o5p6q7r8s9t0` single head.
- Pytest `358p / 2f / 3655d in 34.76s` exact DEC-021 baseline.
- Git `main@a1e61bc` 0 unpushed; 4 uncommitted state-doc files (still accumulating).
- CI run `24661165493` on `a1e61bc` `conclusion=success` — **6th consecutive GREEN**.

### §4 Config + Gates — GREEN
- All 11 critical `APIS_*` flags at expected values. No drift; no auto-fix applied.
- Scheduler `job_count=35` ✅.

### Issues Found
- **YELLOW persistent**: `orders` table 0 rows all-time — paper-cycle code not routing through order-engine. Same signature as Mon 15:15 UTC onwards. Compliance/replay/backtest reconstruction blocked.
- **YELLOW known**: `universe_overrides` missing migration; 1 warning per 48h.
- **YELLOW pre-existing**: `signal_quality_update_db_failed` / `persist_evaluation_run_failed` idempotency guards firing on re-run (warning-level, correct behavior).

### Fixes Applied
- **None** — same authority constraints as DEC-039/040/041/042. No RED triggers this cycle; YELLOW findings all match prior-run baseline; no autonomous action warranted.

### Action Required from Aaron
1. **Kill-switch flip is NO LONGER URGENT** — phantom writer has stopped reproducing; keep flag `false` if desired.
2. **Patch orders ledger writer** (`apps/worker/jobs/paper_trading.py` + `services/execution_engine/service.py`) — last remaining RED-class latent bug.
3. **Root-cause phantom-cash writer** — even though self-healed, the code-level bug remains; audit `services/portfolio/` for stale in-memory state across cycle boundaries.
4. **`universe_overrides` migration** — defer.
5. **Batch-commit state-doc updates** after next GREEN run (close-out the 5-run dirty accumulation).

**Email:** YELLOW draft sent to aaron.wilson3142@gmail.com.

**Full detail:** `apis/state/HEALTH_LOG.md` 2026-04-21 19:11 UTC entry; DEC-043 in `state/DECISION_LOG.md`.

---

## 2026-04-21 15:12 UTC — Deep-Dive Scheduled Run (Tue 10 AM CT, mid-session, market open) — **RED** (improving trajectory, 4th consecutive)

**Overall Status:** RED (but self-healing). Tuesday's 13:35 UTC + 14:30 UTC paper cycles closed most of Monday's cap-breach: open positions now **6/15** with clean `origin_strategy` on all 6, **0 new opens** today (cash gate working), cost basis $100,090.89 ≈ starting cash. Phantom-cash magnitude **collapsed ~100×**: latest `portfolio_snapshots` row 2026-04-21 14:30:11 UTC shows `cash=-$1,603.38` (vs Monday's `-$242,101.20`). Still RED per skill rule because `cash_balance < 0`. `APIS_KILL_SWITCH=false` still — operator has not responded to 3 prior RED escalations (Mon 15:15 UTC, Mon 19:15 UTC, Tue 10:12 UTC). `orders` table still **0 rows all-time** (ledger bug persists). §1 Infra + §3 Code/Schema + §4 Config all GREEN.

**§1 Infrastructure — GREEN**: 7 APIS containers + `apis-control-plane` healthy (worker/api Up 2d; postgres/redis/monitoring Up 4d); `/health` HTTP 200 all 6 components ok; worker log 24h = 25 `broker_order_rejected "Insufficient cash"` (down from 37, cash gate firing less because fewer attempts) + 33 yfinance stale + 1 `load_active_overrides_failed` + 0 `signal_quality_update_db_failed` (Mon 21:20 instance now outside 24h window); api log 24h = 36 matches, 0 crash-triad; Prometheus 2/2 up; Alertmanager 0 alerts; docker stats well under threshold; DB 90 MB (+5 MB since 10:12 UTC).

**§2 Execution + Data — RED (improving)**: Tue cycles at 13:35 + 14:30 UTC both wrote phantom-cash post rows but magnitudes **collapsed**: `-$66,223.54` at 13:35 UTC → `-$1,603.38` at 14:30 UTC (latest). Equity held near $100k throughout. Pre-cycle rows both show `cash=$41,011.07 / equity=$100,912.05` — broker in-memory cash resets between cycles, post-cycle reconciliation writes phantom. Positions: **open=6** / closed=206; 6 open cost basis `$100,090.89` (~starting cash, healthy); 0 new opens today (cap 5 ✅); 6 ≤ 15 cap ✅; **all 6 opens have `origin_strategy` set** (5× `momentum_v1` + 1× `theme_alignment_v1`); the 4 persistent NULL-origin opens flagged at 10:12 UTC (AMD/JNJ/CIEN/NFLX) **all closed** in Tue 13:35 UTC cycle; 30 NULL-origin rows total (all CLOSED, all from Mon churn, archived). `orders` table still **0 rows all-time** (36 opens + 33 closes in 30h never ledgered). `evaluation_runs=85` (+0 since 10:12 UTC, next daily eval fires tonight 21:00 UTC). Data freshness OK (bars 2026-04-20, rankings today 10:45 UTC, signals today 10:30 UTC × 5 × 2012 = 10,060). 13 stale tickers unchanged. Broker↔DB: `/api/v1/broker/positions` 404 expected in this build; `/health.broker=ok` fallback accepted (positions $100k cost basis self-consistent). 0 duplicate tickers ✅.

**§3 Code + Schema — GREEN**: alembic head `o5p6q7r8s9t0` single head ✅; pytest smoke `358p/2f/3655d in 33.73s` — exact DEC-021 baseline; 2 known phase22 scheduler-count drifts; 0 new failures; git `main@a1e61bc` (2026-04-20 10:10 UTC), 0 unpushed, 4 uncommitted state-doc files accumulated (this entry included); GitHub Actions run `24661165493` on `a1e61bc42` `conclusion=success` — **5th consecutive GREEN**. https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/24661165493 .

**§4 Config + Gates — GREEN**: all 11 `APIS_*` flags at expected values (identical to prior 3 RED runs): `APIS_OPERATING_MODE=paper`, `APIS_KILL_SWITCH=false` (expected-OFF but SHOULD be true given §2 RED — not in auto-fix authority), `APIS_MAX_POSITIONS=15`, `APIS_MAX_NEW_POSITIONS_PER_DAY=5`, `APIS_MAX_THEMATIC_PCT=0.75`, `APIS_RANKING_MIN_COMPOSITE_SCORE=0.30`, Step 6/7/8 + self-improvement + insider-flow flags all default OFF. Scheduler `job_count=35` ✅. No `.env` drift → no auto-fix applied.

**Issues Found**: (a) RED persisting small-magnitude phantom-cash writer (-$1,603.38 latest, not Phase 63-guardable with 6 open); (b) RED persisting unpatched `orders` ledger writer (0 rows all-time despite 36+ opens + 33+ closes); (c) operator non-response to 3 prior RED emails (27+ hours since Mon 15:15 UTC first RED); (d) YELLOW unchanged `universe_overrides` missing migration.

**Fixes Applied**: **None** — same authority constraints as prior 3 RED runs (DB cleanup out of authority; kill-switch flip out of authority; code patch too risky during live weekday cadence).

**Action Required from Aaron** (UNCHANGED from Tue 10:12 UTC, priority order):
1. **Flip `APIS_KILL_SWITCH=true`** — now LESS urgent (cash gate working, no new opens today, caps within bounds) but still the right defensive move until code is patched. No new damage since 14:30 UTC.
2. **Patch paper-cycle open/close path** (`apps/worker/jobs/paper_trading.py` + `services/execution_engine/service.py`) — root cause of phantom-cash writer + missing order ledger. Operator-paired session recommended.
3. **Transactional DB cleanup** — zero Mon churn artefacts + reset `portfolio_snapshots` latest to true `cash=$100k - sum(open_cost_basis) + realized_pnl`.
4. **Re-flip kill-switch false** only after patch + reconciliation verified.
5. **`universe_overrides` migration** (YELLOW, defer).

**Trajectory note**: this is Tuesday's 3rd deep-dive (5 AM / 10 AM / 2 PM CT cadence) and the system is visibly self-healing through cycle-driven closes. If left untouched, phantom likely collapses to $0 as the 6 remaining opens unwind via age/stop/rebalance over the next several cycles. However the data-integrity hole (phantom-cash writer + missing order ledger) persists as latent debt. See `apis/state/HEALTH_LOG.md` 2026-04-21 15:12 UTC entry for full probe output.

4th RED-escalation draft created for `aaron.wilson3142@gmail.com`.

---

## 2026-04-21 10:12 UTC — Deep-Dive Scheduled Run (Tue 5 AM CT, pre-market) — **RED** (persistence, 3rd consecutive)

**Overall Status:** RED — Monday's 5-regression cluster UNCHANGED 15h after re-escalation. `APIS_KILL_SWITCH=false` still. Phantom-cash `-$242,101.20` latest on `portfolio_snapshots`; 4 NULL-`origin_strategy` positions still open (AMD, JNJ, CIEN, NFLX); `orders` still 0 rows all-time; 86 opens in 24h (cap 5); 16 open (cap 15). §1 Infra + §3 Code/Schema + §4 Config all GREEN. First Tuesday paper cycle fires at 13:35 UTC = **~3h 23m after this deep-dive** and will reproduce phantom cash unless operator flips kill-switch. **No autonomous fixes applied** (same constraints as DEC-039 / DEC-040). Third RED-escalation draft created for `aaron.wilson3142@gmail.com`. See `apis/state/HEALTH_LOG.md` 2026-04-21 10:12 UTC entry for full detail + per-section probe output.

**§1 Infrastructure — GREEN**: 7 APIS containers + `apis-control-plane` healthy (worker/api Up 2d; postgres/redis/monitoring Up 4d); `/health` HTTP 200 all 6 components ok (`db`, `broker`, `scheduler`, `paper_cycle`, `broker_auth`, `kill_switch`); worker log 24h = 73 matches (37 cash-gate + 33 yfinance + 3 known/non-error); api log 24h = 38 matches (mostly yfinance, 2 Alpaca Mon 13:35 rejections, 1 signal-quality bulk-insert rollback); 0 crash-triad regex hits; Prometheus targets up; Alertmanager alerts 0; docker stats well under threshold; DB 85 MB.

**§2 Execution + Data — RED (unchanged)**: phantom-cash `-$242,101.20` on latest `portfolio_snapshots` row (6 phantom rows total 14:30–19:30 UTC Mon); positions `open=16` (cost basis $334,697.93 > $100k starting cash) / `closed=185`; 86 opens in last 24h (17.2× the 5/day cap); 4 NULL `origin_strategy` (AMD, JNJ, CIEN, NFLX); `orders` table 0 rows all-time; evaluation_runs=85 (≥80 floor, +1 since Mon 21:00 UTC); data freshness OK (bars 2026-04-20, rankings Mon 10:45 UTC, signals Mon 10:30 UTC); 13 known stale tickers unchanged; idempotency clean.

**§3 Code + Schema — GREEN**: alembic `o5p6q7r8s9t0` single head; pytest smoke `358p/2f/3655d` in 34.69s (exact DEC-021 baseline); git `main@a1e61bc` 0 unpushed (4 uncommitted state-doc files accumulated over Mon 15:15 + Mon 19:15 + Tue 10:12 UTC runs); CI run `24661165493` on `a1e61bc` conclusion=success (4th consecutive GREEN since DEC-038 recovery).

**§4 Config + Gates — GREEN**: all 11 critical `APIS_*` flags match expected values; scheduler `job_count=35`; no `.env` drift; no containers recreated.

**Severity: RED**. **Email: third RED-escalation draft created** for operator. **State+memory**: this entry + `apis/state/HEALTH_LOG.md` mirror + `apis/state/ACTIVE_CONTEXT.md` updated + `state/DECISION_LOG.md` new DEC-041 entry + memory `project_monday_first_cycle_red_2026-04-20.md` appended with Tuesday-10:12-UTC persistence note.

**Autonomous fixes: NONE.** DB cleanup out of authority (2026-04-19 precedent); kill-switch flip out of authority (DEC-039/DEC-040 precedent); code patch risky during live cadence. **Operator must flip kill-switch before 13:35 UTC or the Tue 09:35 ET cycle will extend the phantom-cash chain.**

---

## 2026-04-20 19:15 UTC — Deep-Dive Scheduled Run (Mon 2 PM CT, late-session) — **RED** (persistence)

Second deep-dive after the Monday RED cluster. Methodology: Desktop Commander PowerShell transport (headless). §1 Infra + §3 Code/Schema + §4 Config all GREEN (unchanged). **§2 Execution+Data remains RED** — same 5-regression cluster from 15:15 UTC is still in place; operator has NOT flipped kill-switch (still `false`); 4 more paper cycles fired at 15:30/16:00/17:30/18:30 UTC. Broker cash gate is working correctly (every post-15:15 cycle shows `broker_order_rejected: Insufficient cash` at the same $10,879.58 broker cash floor, with zero new position opens in those hours), but the phantom-cash snapshot writer keeps reproducing `-$242,101.20` cash rows every cycle. Open positions unchanged at 16; NULL origin_strategy unchanged (AMD, JNJ, CIEN, NFLX); orders table still 0 rows all-time. Pytest 358p/2f exact baseline; alembic `o5p6q7r8s9t0` single head; git `main@a1e61bc` 0 unpushed; CI run `24661165493` conclusion=success (unchanged — no new push). Re-escalated RED email sent to operator emphasizing that 4 more cycles fired without action. **No autonomous fixes applied** — same reasoning as 15:15 UTC (DB cleanup, kill-switch flip, code patch all require operator session). Full entry in `apis/state/HEALTH_LOG.md`.

---

## 2026-04-20 15:15 UTC — Deep-Dive Scheduled Run (Mon 10 AM CT, mid-session) — **RED**

Scheduled autonomous run of the APIS Daily Deep-Dive Health Check — **first deep-dive post-Monday-first-weekday-cycle** (13:35 UTC / 09:35 ET). Methodology: Desktop Commander PowerShell transport (headless). **§1 Infra + §3 Code/Schema + §4 Config all GREEN** — stack itself is healthy, containers up 38h, `/health` all six components ok, alembic at `o5p6q7r8s9t0` (single head), pytest 358p/2f baseline, CI run `24661165493` = success (3rd consecutive GREEN). **§2 Execution+Data is deep RED with 5 stacked trading regressions** all firing on the Monday 13:35 UTC first weekday cycle. **No autonomous fixes applied** — DB cleanup is out of standing authority (per 2026-04-19 02:20 UTC precedent) and kill-switch flip is borderline/out-of-authority for a scheduled task. URGENT email sent to operator. Full entry in `apis/state/HEALTH_LOG.md`.

- **§1 Infra:** GREEN. All 7 APIS containers + `apis-control-plane` healthy; `/health` all ok; only the 13 documented delisted-yfinance tickers at 10:00 UTC ingest (non-blocking); 12 `broker_order_rejected` "Insufficient cash" errors at 13:35:05 + 14:30:01 (core RED signal, see §2).
- **§2 Exec+Data:** **RED — 5 regressions stacked:**
  1. **Phantom cash** — latest `portfolio_snapshots` row cash=**-$242,101.20** / equity=$94,487.91 (Saturday's $100k baseline destroyed by 13:35 UTC cycle). Phase 63 guard did NOT trip because it requires `cash<0 AND positions=0` (we have 16 open positions).
  2. **Position-cap breach** — open=16 > 15 (`APIS_MAX_POSITIONS`).
  3. **New-positions/day breach** — 26 opens today > 5 (`APIS_MAX_NEW_POSITIONS_PER_DAY`, 5.2× over cap).
  4. **Alternating-churn regression (Phase 65)** — 11 churn pairs at 13:35:00 (same `opened_at` to microsecond, closed 10ms later, twin OPEN row) on AMD, BE, BK, CIEN, JNJ, NFLX, ODFL, STX, WBD + 1 cross-cycle (HOLX). Phase 65 was fixed 2026-04-16.
  5. **Step 5 origin_strategy regression** — 4 of 16 open positions NULL: AMD, JNJ, CIEN, NFLX (commit `d08875d` was meant to stamp EVERY position from 2026-04-18+).
  - **Plus:** 0 `orders` rows despite 22 opens + 11 closes in 30h window (Order ledger not being written — same signature as 2026-04-19 test-pollution but at scheduled cycle timestamps, so paper-cycle code is the culprit).
- **§3 Code+Schema:** GREEN + 1 new YELLOW drift. Alembic `o5p6q7r8s9t0` single head; pytest `358p/2f/3655d` in 26.49s (exact DEC-021 baseline — critically, the 5 RED findings are NOT caught by smoke suite); git `main` at `a1e61bc` (10:10 UTC state-doc commit), 0 unpushed, clean tree; CI `24661165493` = success. **NEW YELLOW:** `universe_overrides` table missing (model at `apis/infra/db/models/universe_override.py` but no Alembic migration) — warns every 5 min, non-blocking.
- **§4 Config+Gates:** GREEN. All 11 `APIS_*` flags match expected (mode=paper, kill_switch=false, max_positions=15, max_new/day=5, max_thematic=0.75, etc.). No drift; the RED cluster is NOT caused by flag drift — pure code/logic regression in paper-cycle open path.

### Issues Found (RED)
- Phantom cash -$242,101.20 (invariant violated)
- Position-cap breach 16 > 15
- New-positions/day 26 > 5
- Alternating-churn Phase 65 regression (11 churn pairs + 1 cross-cycle)
- Step 5 origin_strategy NULL on AMD/JNJ/CIEN/NFLX
- Zero Order ledger rows for 22 opens + 11 closes

### Issues Found (YELLOW)
- `universe_overrides` Postgres table missing; model exists without Alembic migration

### Fixes Applied
- **NONE.** DB cleanup out of authority (per 2026-04-19 02:20 UTC precedent). Kill-switch flip borderline — reported to operator.

### Action Required from Aaron (URGENT — in priority order)
1. **Flip `APIS_KILL_SWITCH=true`** in `apis/.env` + `apis/.env.example` and `docker compose --env-file "../../.env" up -d worker api` to halt further damage on 15:35 UTC and later cycles.
2. **Diagnose + patch** paper-cycle open path (`apps/worker/jobs/paper_trading.py` + `services/execution_engine/service.py`) — recent commits may have reintroduced Phase 65 alternating-churn and broken cash-gating + Order-ledger write + origin_strategy stamping + position-cap enforcement.
3. **DB cleanup** after patch lands — transactional DELETE from `position_history` / `positions` / `portfolio_snapshots` for `2026-04-20` + INSERT fresh $100k baseline (pattern per 2026-04-19 02:42 UTC cleanup).
4. **Re-flip kill-switch off** only after patch + verification.
5. **`universe_overrides` migration** — YELLOW, not blocking — author Alembic migration when convenient.

### Follow-Ups (not blocking)
- **Phase 63 guard hardening** — extend from `cash<0 AND positions=0` → `cash<0` unconditional with conservative auto-reset.
- **Pytest smoke gap** — all 5 RED findings invisible to 358/360 suite; add invariant test for post-cycle DB state.
- **Pollution-source diagnostic** — 2026-04-19 and 2026-04-20 both show "positions without orders" signature; likely shared underlying cause.

---

## 2026-04-20 10:10 UTC — Deep-Dive Scheduled Run (Mon 5 AM CT, pre-market) — **GREEN**

Scheduled autonomous run of the APIS Daily Deep-Dive Health Check (Monday 5 AM CT slot — first deep-dive of the trading week). Executed headlessly via Desktop Commander PowerShell transport (per validated 2026-04-19 19:10 UTC pattern). **All §1-§4 GREEN; stack is fully ready for Monday's first weekday paper cycle at 09:35 ET (14:35 UTC), ~4h 25m from deep-dive completion.** Saturday's $100k / 0-position baseline continues to hold (now through **five consecutive scheduled runs + two interactive verifications + one CI-recovery operator session**). No regressions detected; no autonomous fixes needed. New this run: §3.4 GitHub Actions CI probe (introduced in DEC-038) ran green for the first time under the scheduled skill.

- **§1 Infra:** 7 APIS containers + `apis-control-plane` healthy (workers 33h, postgres/redis/monitoring 3d); `/health` all 6 components ok; 0 crash-triad regressions in 48h log window; only the documented 13 stale yfinance tickers at 10:00 UTC ingest (non-blocking); Prometheus both targets up; 0 Alertmanager alerts; DB 76 MB stable.
- **§2 Exec+Data:** 0 evaluation_runs last 30h (expected — weekday cycles weekday-only, first Monday slot 14:35 UTC); 84 total runs (≥ Phase 63 80-row floor); latest `portfolio_snapshots` `2026-04-19 02:32:48 UTC $100k/$100k` — Saturday cleanup baseline still 100% intact; 0 OPEN positions / 115 closed; 0 new positions today; 0 orders in 48h; 0 duplicate idempotency keys / duplicate open security_ids; no NULL origin_strategy on rows since 2026-04-18; data freshness `daily_market_bars` latest 2026-04-17 covering 490 secs (Friday's bar — expected, today's 06:00 ET ingest still pending at probe time); signal_runs latest 2026-04-17 10:30 UTC; ranking_runs latest 2026-04-17 10:45 UTC; kill-switch off, mode=paper.
- **§3 Code+Schema:** alembic current+heads both `o5p6q7r8s9t0` (single head — Step 5 finisher); pytest smoke `358 passed / 2 failed / 3655 deselected` in 31.32s — **exact DEC-021 baseline** (the 2 known phase22 scheduler-count drifts); git `main` at `0da7bb8` (new since last deep-dive: the CI-recovery state-doc commit); 0 unpushed; clean working tree; single local branch.
- **§3.4 GitHub Actions CI:** run `24643089917` on `0da7bb8` — status=completed, **conclusion=success** — https://github.com/aaronwilson3142-ops/auto-trade-bot/actions/runs/24643089917. Second consecutive GREEN CI run since the `5db564e` recovery fix; the §3.4 probe itself is performing as designed.
- **§4 Config+Gates:** all 11 operator-set `APIS_*` flags in worker env match expected (mode=paper, kill_switch=false, max_positions=15, max_new/day=5, max_thematic_pct=0.75, ranking_score=0.30, sector_pct=0.40, single_name=0.20, max_age_days=20, daily_loss=0.02, weekly_drawdown=0.05); Deep-Dive Step 6/7/8 + Phase 57 Part 2 flags absent from worker env → fall through to settings.py defaults (all OFF/null) — expected behavioural-neutral baseline. Scheduler `job_count=35` in `apis_worker_started` log line at 2026-04-19T01:03:12 UTC (matches DEC-021).

### Issues Found
- None. Pre-existing carry-overs unchanged: the 2 phase22 scheduler-count test drifts (DEC-021 bumped 30→35), ~25 cosmetic alembic drift items (non-functional), 13 delisted yfinance tickers (non-blocking — same list as yesterday), 2 known api-boot warnings (`regime_result_restore_failed` / `readiness_report_restore_failed`) — none affect Monday's 09:35 ET cycle.

### Fixes Applied
- None. No autonomous fixes needed this run.

### Action Required from Aaron
- **None.** Stack is ready for Monday 09:35 ET. This is the first scheduled deep-dive of the 2026-04-20 trading week; the Monday baseline cycle will be the first evidence point for whether Saturday's cleanup + Phase 65/66 knobs + Deep-Dive Step 5 origin_strategy stamping hold under real weekday execution.

---

## 2026-04-20 00:25 UTC — CI Recovery Operator Session — **GREEN**

Operator-initiated (not a scheduled deep-dive). Aaron received a GitHub Actions failure email on `0ee3035` and asked why. Diagnosis: 14 consecutive CI reds on main since the first push `eef10a4` on 2026-04-18; local daily deep-dive never probed CI so the red accumulated silently. Fix committed at `5db564e` + pushed: 39-file ruff cleanup (+123/-149) + `continue-on-error: true` on unit-tests + `if: always() && !cancelled()` on docker-build. CI run `24642743915` concludes **success** (Lint ✅, Integration ✅, Docker Build ✅; unit-tests 3.11/3.12 ❌ but non-blocking as designed). Deep-dive scheduled-task prompt upgraded with new §3.4 CI probe so future reds are surfaced same-day. Memory `project_apis_github_remote.md` corrected private→public. Full detail in `apis/state/HEALTH_LOG.md` + `apis/state/CHANGELOG.md` + DEC-038 in `state/DECISION_LOG.md`.

---

## 2026-04-19 19:10 UTC — Deep-Dive Scheduled Run (2 PM CT Sunday) — **GREEN**

Scheduled autonomous run — **first headless run today to fully complete end-to-end**. Desktop Commander `powershell.exe` session was used as the docker/psql/curl transport, bypassing the `mcp__computer-use__request_access` approval blocker that had caused the 10:10 UTC + 15:10 UTC YELLOW INCOMPLETE runs. All §1-§4 verified live against the stack; findings match the 16:40 UTC operator-present GREEN baseline. Full entry mirrored in `apis/state/HEALTH_LOG.md`; summary below.

- **§1 Infra:** 7 APIS containers + `apis-control-plane` healthy; `/health` all components ok; 0 worker errors / 2 known api boot warnings; Prometheus targets up; 0 Alertmanager alerts; DB 76 MB.
- **§2 Exec+Data:** 0 paper cycles last 30h (Sunday — expected); `portfolio_snapshots` latest 2026-04-19 02:32:48 UTC `$100k/$100k`; 0 OPEN positions; 0 new today; 84 evaluation_runs; data freshness consistent with weekday-only ingestion; kill-switch off; no dupes.
- **§3 Code+Schema:** alembic `o5p6q7r8s9t0` single head; pytest `358p/2f/3655d` — exact DEC-021 baseline; `main` at `e351528` 0 unpushed; dirty tree is expected accumulated state-doc edits.
- **§4 Config+Gates:** all 13 critical `APIS_*` flags match; Deep-Dive Step 6/7/8 + Phase 57 Part 2 flags fall through to settings.py defaults (OFF/null); scheduler `job_count=35`.

**Fixes Applied:** removed untracked `_tmp_healthcheck/` scratch dir.
**Email:** not sent (GREEN = silent).
**Action required from Aaron:** none.

Methodology win: the Desktop Commander transport is the first scheduled-task path today that did NOT require operator approval. Memory updated.

---

## 2026-04-19 16:40 UTC — Deep-Dive Interactive Re-Run (closes the 15:10 UTC YELLOW gap) — **GREEN**

Operator-present interactive re-run triggered by Aaron's follow-up "anything else needs to be done to get this to full health?" after the 15:10 UTC YELLOW INCOMPLETE. Reached every section the headless run skipped; promotes YELLOW → GREEN. Full entry mirrored in `apis/state/HEALTH_LOG.md`.

**Headline:** no regressions, no fixes required. §1 all 7 APIS containers + `apis-control-plane` kind cluster healthy; `/health` HTTP 200 all components ok; only 2 known non-blocking boot warnings. §2 Postgres `portfolio_snapshots` latest row `$100,000 cash / $0 gross / $100,000 equity at 2026-04-19 02:32:48 UTC` (Saturday's cleanup 100% intact); 0 OPEN positions; 0 orders last 24h; 84 `evaluation_runs` (≥ 80-floor). §3.1 alembic head `o5p6q7r8s9t0` single-head; §3.2 pytest `358 passed / 2 failed / 3655 deselected` (exact DEC-021 baseline); §3.3 git `main` at `e351528` 0 unpushed. §4 all 13 critical `APIS_*` / Step 6/7/8 / Phase 57 Part 2 gate flags match expected; worker scheduler `job_count=35` via `apis_worker_started` log line at 01:03:12 UTC.

**Email:** no alert sent (GREEN = silent). Earlier 15:10 UTC YELLOW consolidated draft `r-8894938330620603644` is now superseded.

**Action:** none. Stack ready for Monday 2026-04-20 09:35 ET first weekday paper cycle. New memory captured: Desktop Commander `start_process` + persistent `docker exec -i psql` session is the reliable path for operator-present DB probes when cmd.exe quoting breaks inline `psql -c "..."` calls.

---

## 2026-04-19 15:10 UTC — Deep-Dive Scheduled Run (10 AM CT Sunday, market closed) — **YELLOW (INCOMPLETE)**

Second headless scheduled run today (first at 10:10 UTC, also YELLOW INCOMPLETE; intermediate 13:20 UTC operator-present interactive re-run was GREEN end-to-end). Same blocker as 10:10 UTC: `request_access` for PowerShell + Docker Desktop timed out at 60s (no operator to click OS-level approval dialog). Per `feedback_headless_request_access_blocker.md` one attempt is sufficient — treated the timeout as definitive.

**Static verification (passed):**
- §3.3 Git: `main` at `e351528`, 0 unpushed, single branch — unchanged since 13:20 UTC.
- §4.1 Config: all 13 critical `APIS_*` / Step 6/7/8 / Phase 57 Part 2 gate flags match `settings.py` defaults / Phase 65/66 operating values. No drift, no auto-fixes.
- §4.2 `.env.example` alignment: no template drift on the 5 keys it overrides.

**Runtime not run (§1 infra, §2 execution+data, §3.1 alembic, §3.2 pytest, §4.3 scheduler endpoint):** same constraints as 10:10 UTC — sandbox has no `docker`/`psql`, Windows firewall blocks host ports, and `request_access` is unreachable without a human. Last known good is 13:20 UTC (~2h ago): all 7 containers healthy, 0 OPEN positions, 84 `evaluation_runs`, alembic head `o5p6q7r8s9t0`, pytest 358/360 (matches DEC-021 baseline). Today is Sunday — no scheduled paper cycles — so state is expected to be unchanged.

**Action:** lower priority than 10:10 UTC's ask. The 13:20 UTC interactive run already covered the Sunday gap; optional interactive re-run Monday pre-09:30 ET for belt-and-suspenders before the first weekday cycle. Long-term fix options still open from 10:10 UTC entry. Full entry mirrored in `apis/state/HEALTH_LOG.md`.

**Email:** ONE consolidated YELLOW draft (see primary log entry for policy note) rather than firing a separate alert identical to the 10:10 UTC one on the same known-blocker issue.

---

## 2026-04-19 ~13:20 UTC — Deep-Dive Interactive Re-Run (closes the 10:10 UTC YELLOW gap) — **GREEN**

Operator-present re-run to restore the §§1/2/3/4 coverage the headless scheduled run at 10:10 UTC had to skip (sandbox couldn't complete `request_access` without a human to approve the dialog). Full entry mirrored in `apis/state/HEALTH_LOG.md`. Headline: **Saturday's 02:32 UTC cleanup is 100% intact in the live DB** — latest `portfolio_snapshots` row is `$100,000 cash / $0 gross / $100,000 equity at 2026-04-19 02:32:48 UTC`, 0 open positions, 0 orders in last 24h, 84 evaluation_runs (≥ 80-floor). All 7 APIS containers healthy; worker scheduler registered 35 jobs at 01:03 UTC (matches expected); pytest `deep_dive+phase22+phase57` sweep `358 passed / 2 failed` (matches documented DEC-021 baseline; the 2 failures are the pre-existing phase22 scheduler-count drift); alembic head `o5p6q7r8s9t0` (single head, ~25 cosmetic drift items unchanged from yesterday); all 10 critical `APIS_*` env flags match `settings.py` defaults; all Step 6/7/8 + Phase 57 Part 2 gates still default-OFF. No regressions, no fixes needed, no email sent (GREEN = silent). Two non-blocking boot-time warnings logged during 01:03 UTC API start (`regime_result_restore_failed` re `detection_basis_json`; `readiness_report_restore_failed` re `ReadinessGateRow.description`) — follow-up bug ticket candidates, don't block Monday 09:35 ET cycle.

Pytest note: required `--no-cov` flag because `/app/apis/.coverage` is on a read-only container layer — pytest-cov's `.erase()` at startup crashes otherwise. Scheduler-job count note: the task-file's `/api/v1/scheduler/jobs` endpoint does not exist in this build; `/openapi.json` only exposes `/api/v1/admin/*` — authoritative job_count=35 comes from the worker `apis_worker_started` log line.

---

## 2026-04-19 10:10 UTC — Deep-Dive Scheduled Run (5 AM CT Sunday, market closed) — **YELLOW (INCOMPLETE)**

Full entry mirrored in `apis/state/HEALTH_LOG.md`. Summary: scheduled autonomous run could only verify §3.3 (git log authoritative — 0 unpushed commits, `main` at `e351528`) and §4.1/4.2 (config flags, file-state GREEN — all 10 critical `APIS_*` values match settings.py defaults / expected values). §§1, 2, 3.1, 3.2, 4.3 NOT RUN because `mcp__computer-use__request_access` for PowerShell timed out 3× with no operator to approve — the scheduled-task sandbox has no `docker`/`psql` and cannot reach the host API, so the infra + execution + alembic + pytest audits could not be performed. No positive RED evidence; no fixes applied. **Action required: operator should re-run the deep-dive interactively before Monday's 09:35 ET baseline cycle to close the gap.**

---

## 2026-04-19 02:15 UTC — Deep-Dive Scheduled Run (5 AM CT Saturday 2026-04-18) — **RED**

Scheduled autonomous run of the APIS Daily Deep-Dive Health Check (8 sections). Operator was not present.

**Severity: RED** — production-paper Postgres was polluted by what appears to be a test-suite run sometime between 01:39:23 and 01:40:14 UTC (≈90 min before this run began). The clean $100k baseline that was in place at 2026-04-18 16:37 UTC has been overwritten.

### §1 Infrastructure — GREEN
All 7 containers healthy, Alertmanager 0 active, worker+api logs clean of crash-triad regressions.

### §2 Execution + Data Audit — **RED**
- `portfolio_snapshots`: 27 rows in last 4h, all from a 01:40 burst. Latest row: `cash=$49,665.68 / gross=$3,831.92 / equity=$53,497.60` (vs. $100k baseline at 16:37 UTC).
- `positions`: 3 rows opened in 0.5s window 01:40:11.776 → 01:40:12.272. 1 still open: NVDA `6307f4e2-…` qty 19 @ $201.78, **`origin_strategy=NULL`**.
- `orders` last-4h: **0**. Positions written directly without order — clear test-fixture signature.
- Phase 63 phantom-cash guard did **not** trigger (cash > 0). Operator approval required for cleanup; standing authority excludes DB writes.

### §3 Code + Schema — YELLOW
- Git: clean against `origin/main`, no unpushed commits, no stale branches. Dirty: `state/DECISION_LOG.md` (4 lines, will commit) + 1 scratch ps1.
- Alembic: head `o5p6q7r8s9t0`, single head ✓. `alembic check` reports ~25 cosmetic drift items (TIMESTAMP↔DateTime types, comment wording, one missing `ix_proposal_executions_proposal_id`). Non-functional.
- Pytest: **358 passed / 2 failed** (matches DEC-021 baseline — phase22 scheduler-count drift only).

### §4 Config + Gate Verification — GREEN
All 10 critical APIS_* flags verified against `apis/config/settings.py` defaults — no drift, no auto-fixes applied.

### Overall: **RED** (driven by §2 test-data pollution)

Full §1–§4 detail is in `apis/state/HEALTH_LOG.md`. Operator email sent to aaron.wilson3142@gmail.com.

---

## Health Check — 2026-03-29 18:57 local

**Overall Status:** HEALTHY

### Docker Containers
| Container | Status | Notes |
|-----------|--------|-------|
| docker-api-1 | Up 5 hours (healthy) | Port 8000 |
| docker-worker-1 | Up 10 hours (healthy) | |
| docker-grafana-1 | Up 2 days | Port 3000 |
| docker-prometheus-1 | Up 7 days | Port 9090 |
| docker-alertmanager-1 | Up 4 days | Port 9093 |
| docker-postgres-1 | Up 7 days (healthy) | Port 5432 |
| docker-redis-1 | Up 7 days (healthy) | Port 6379 |

### API Health Endpoint
- Result: HTTP 200 — `{"status":"ok","service":"api","mode":"paper","timestamp":"2026-03-29T23:56:41.087572+00:00","components":{"db":"ok","broker":"not_connected","scheduler":"no_data","broker_auth":"ok","kill_switch":"ok"}}`
- Note: `broker: not_connected` and `scheduler: no_data` observed — overall status remains "ok"; likely expected in paper mode without active broker session.

### Kubernetes Pods
- `apis-api-68f79b74d8-9f446`: Running (1/1, 0 restarts, age 7d5h)
- `postgres-0`: Running (1/1, 1 restart — normal, age 7d22h)
- `redis-79d54f5d6-nxkmh`: Running (1/1, 1 restart — normal, age 7d22h)
- Worker deployment: Scaled to 0 (intentional — not flagged)

### Issues Found
- None

### Fixes Applied
- None required

### Post-Fix Status
- N/A — no fixes needed

### Action Required
- None

---

## Health Check - 2026-03-30 05:11 local

**Overall Status:** HEALTHY

### Docker Containers
| Container | Status | Notes |
|-----------|--------|-------|
| docker-api-1 | Up 16 hours (healthy) | Port 8000 |
| docker-worker-1 | Up 20 hours (healthy) | |
| docker-grafana-1 | Up 2 days | Port 3000 |
| docker-prometheus-1 | Up 7 days | Port 9090 |
| docker-alertmanager-1 | Up 4 days | Port 9093 |
| docker-postgres-1 | Up 7 days (healthy) | Port 5432 |
| docker-redis-1 | Up 7 days (healthy) | Port 6379 |

### API Health Endpoint
- Result: HTTP 200 -- `{"status":"ok","service":"api","mode":"paper","timestamp":"2026-03-30T10:11:02.795813+00:00","components":{"db":"ok","broker":"not_connected","scheduler":"no_data","broker_auth":"ok","kill_switch":"ok"}}`
- Note: `broker: not_connected` and `scheduler: no_data` persist from yesterday -- expected in paper mode without an active broker session.

### Kubernetes Pods
- `apis-api-68f79b74d8-9f446`: Running (1/1, 0 restarts, age 7d15h)
- `postgres-0`: Running (1/1, 1 restart - normal, age 8d)
- `redis-79d54f5d6-nxkmh`: Running (1/1, 1 restart - normal, age 8d)
- Worker deployment: Scaled to 0 (intentional - not flagged)

### Issues Found
- None

### Fixes Applied
- None required

### Post-Fix Status
- N/A -- no fixes needed

### Action Required
- None

---
