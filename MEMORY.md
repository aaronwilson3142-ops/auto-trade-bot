# APIS Project Memory — Index

Recreated 2026-08-10 by the local AI deep-dive (the previous MEMORY.md + memory/
topic files referenced by 2026-05 health checks were not found anywhere on the
machine — likely lived in a deleted agent-session directory). Keep this file in
git so memory survives session teardown.

## Canonical state files (read these first)
- `apis/state/HEALTH_LOG.md` — primary health-check log (deep-dive entries)
- `state/HEALTH_LOG.md` — mirror summaries
- `state/AUTO_PROBE_LOG.md` — 3x/day Task Scheduler probe one-liners
- `apis/state/ACTIVE_CONTEXT.md`, `DECISION_LOG.md`, `SESSION_HANDOFF_LOG.md`

## Standing facts (verified 2026-08-10)
- Paper bot, Docker Desktop on Windows; repo `C:\Projects\Auto Trade Bot`.
- 8 containers: docker-{worker,api,postgres,redis,grafana,prometheus,alertmanager}-1 + apis-control-plane.
- Alembic head `q7r8s9t0u1v2`. Smoke baseline = targeted tests only (full tests/unit has ~531 pre-existing failures — never use as signal).
- Cycle schedule (UTC): 13:35, 14:30, 15:30, 16:00?, 17:30, 18:30, 19:30 → 7 snapshots/weekday. Bars for Friday land Monday ~10:00 UTC. Signals 10:30 / rankings 10:45 UTC weekdays.
- Phase 87 guards (post Jul-24 $1.00 phantom-liquidation incident) validated in production: `phase87_action_skipped_no_price`, `phase87_cycle_degraded_stale_data` (fired Aug 3 + Aug 10 — recurring yfinance mid-cycle blackouts where healthy tickers return "possibly delisted"; guard drops all actions, self-recovers).
- Monitoring: Task Scheduler probes APIS-Health-Probe-0505/1005/1405 → `state/AUTO_PROBE_LOG.md` + git push; cloud watchdog `apis-probe-watchdog` notifies Aaron on probe RED or >26h silence; local AI deep-dive daily 5 PM CT (this task).
- Known-dead tickers set is_active=false (SEE/CTRA/BK 2026-08-08); yfinance 404s/possibly-delisted for PXD/WRK/IPG/HES/MRO/MMC/JNPR/K/PKI/DFS/CTLT/ANSS etc. are watchlist noise.
- Machine outages are the root recurring risk (5 outages; last Aug 12 ~04:33→19:10 UTC — asleep through all probes + 6/7 cycles). Stack restarts: Sun 2026-08-09 03:21 UTC (harmless), Wed 2026-08-12 ~19:10 UTC (post-outage).

## DB schema gotchas (save yourself the errors)
- `positions` has NO ticker column — join `securities s ON s.id=p.security_id`, use `s.ticker` (NOT s.symbol).
- `portfolio_snapshots`: `cash_balance`, `equity_value`, `drawdown_pct`, `snapshot_timestamp`.
- `daily_market_bars`: date column is `trade_date` (not bar_date).
- Signal/ranking tables: `signal_runs`, `ranking_runs`, `evaluation_runs` (use max(created_at)).
- 16 closed April-2026 positions have NULL origin_strategy — historical, pre-existing; the 0-NULL invariant applies to OPEN rows.
- `positions.status` values are LOWERCASE ('open'/'closed') — `WHERE status='OPEN'` silently returns 0 rows.

## Tooling gotchas
- Desktop Commander + `docker exec -i psql` session DIES on any SQL error — probe column names via information_schema first; one bad statement costs the session.
- PowerShell `docker logs --since 24h X 2>&1 | Out-File` can yield 0 bytes for the api container; use `--tail N` instead.
- `health_probe.ps1` logs components JSON on non-ok /health since 2026-08-11 (deep-dive applied the Aug-10 rec); entries before that record only `health:<status>`.
- Gmail MCP in scheduled sessions exposes create_draft only (no send) — YELLOW/RED notifications = draft + rely on cloud watchdog for push.

## Open questions / watch items (as of 2026-08-16)
- Weekend baseline (verified Sat 2026-08-15 + Sun 2026-08-16, both fully GREEN): 0 cycles/orders/signals/rankings expected Sat/Sun; latest snapshot stays Friday 19:30; eval_runs +0; all 3 probes GREEN (no in-market staleness artifact) — do not flag any of this as missed/stale on weekend runs.
- **RESOLVED 2026-08-13**: /health "degraded" at 15:05/19:05 UTC = `paper_cycle:"stale"` (components JSON finally logged). Benign timing artifact: in-market probes fire ~35 min after the preceding cycle (15:05 vs 14:30, 19:05 vs 18:30) and the staleness threshold is <35 min. Will recur EVERY in-market probe until fixed. Rec to Aaron: widen threshold to ~70 min (app code — deep-dive can do it if authorized) or move probes to :40. Treat 15:05/19:05 YELLOW health:degraded w/ only paper_cycle stale as known-benign.
- **RESOLVED 2026-08-13**: Aug-12 outage fully self-healed — bars Aug 11+12 ingested (~485 each), signals/rankings ran 10:30/10:45, 7/7 cycles, 3/3 probes fired.
- Probe schtasks still do NOT run missed triggers after wake. Rec to Aaron (open since Aug 12): enable "run ASAP after missed start" on all 3; deep-dive not authorized to edit host scheduler.
- Churn watch (evidence now DAILY as of Aug 14): PFE/V/PANW bought Aug 13 → sold Aug 14 (1-day round-trips); CZR/CSCO sold Aug 13 → rebought Aug 14; earlier BAC/V cross-day rebuys + PLTR/CZR same-day churn + CZR "Insufficient cash" sizing bug. Phase 88 candidates (cash-aware sizing, churn dampener) — deep-dive recommends prioritizing.
- Positions 15/15 (cap, not breach); cash $6.1k, drawdown 0.23% (Aug 14 19:30 UTC snapshot).

## Tooling gotchas (cont.)
- Desktop Commander sessions (PowerShell, cmd, python) DIE silently on: `docker logs --since 24h | Select-String`, Select-String over multi-MB files, findstr in cmd, and MULTI-LINE python paste. Reliable pattern: `docker logs --tail N > %TEMP%\file.log`, then `python -i -q` with ONE-LINE commands only.
- Worker log volume ~1k lines/day; --tail 20000 spans ~1 month.
- `stress_gate_applied` warnings in worker logs are normal risk-engine behavior (firing since ≥Jul 13), not an incident.
- PowerShell `>` redirection writes UTF-16: read the temp log in python with encoding='utf-16' (utf-8 gives mojibake doubling apparent line count).
- Worker log lines are JSON with timestamp mid-line — filter with `'2026-MM-DDT' in line`, NOT `line[:40]` (misses ~97% of lines). Warn/err filter: `'"level": "warning"' or '"level": "error"'`.
- No `.env` at repo root — verify config flags via `docker exec docker-worker-1 sh -c "env | grep APIS_"` instead.

## Updates 2026-08-17 (deep-dive)
- yfinance mid-cycle blackouts on healthy tickers: now 3 CONSECUTIVE MONDAYS (Aug 3/10/17).
  Aug-17 flavor fired `phantom_equity_guard_active` + `mark_to_market_stale_price_preserved`
  (mark-to-market guard family, apps.worker.jobs.paper_trading) with NO phase87_* events —
  cycle not degraded, prior-close preserved, self-recovered. Both guard families are normal
  blackout handling. If Mon Aug-24 repeats, recommend provider fallback/retry layer.
- Churn (Phase 88 evidence, 3rd consecutive trading day): AMP/CSCO/CZR bought Aug-14 → sold
  Aug-17; V bought Aug-13 → sold Aug-14 → rebought Aug-17. Rec escalated to #1.
- Weekday-recovery baseline confirmed Mon Aug-17: Friday bars land ~10:00, signals 10:30,
  rankings 10:45, 7/7 cycles, probes 10:05 GREEN + 15:05/19:05 benign-YELLOW.
- Snapshot 8/17 19:30: cash $6,561.80, equity $106,803.27, drawdown 0.02% (near-zero after
  Friday's 0.23%).


## Updates 2026-08-18 (deep-dive) — YELLOW
- NEW FAILURE MODE: silent partial bar ingestion. Tue 10:00 UTC job upserted ~120k
  history rows, logged "status=PARTIAL" at INFO with zero errors, but Monday Aug-17
  bars landed for only 2/485 tickers (MNST, HUBB) — yfinance returned data ending
  Fri Aug-14 for the rest. ONLY detectable via SQL: count(*) per trade_date. The
  Monday-blackout pattern (Aug 3/10/17) now also contaminates Tuesday ingestion.
- Verification duty for Wed Aug-19 run: Aug-17 should backfill to ~485 via the daily
  period=1y fetch; if still ~2 rows AND Aug-18 bars also missing → RED.
- Signals/rankings ran on stale (Aug-14) bars today; buys MU/STX/TRV carry that caveat.
- Churn day 4: V 2nd full round-trip (8/13 buy→8/14 sell→8/17 rebuy→8/18 sell);
  VLO 8/17→8/18 flip. Phase 88 remains rec #1.
- Notification gap confirmed: scheduled session had NO email/push tools at all (not
  even create_draft); cloud watchdog blind to bar staleness (probes GREEN). YELLOW
  notifications currently reach Aaron only via HEALTH_LOG + commit message.
- Snapshot 8/18 19:30: cash $7,403.10, equity $106,934.71, drawdown 0.00%.


## Updates 2026-08-19 (deep-dive) — GREEN
- Aug-18 silent-partial-ingestion YELLOW SELF-HEALED as predicted: Wed 10:00 UTC period=1y
  fetch backfilled Aug-17 to 484/485 (only AVB missing) and landed Aug-18 at 485/485.
  Confirms the failure mode is provider-side lag (yfinance serves Monday bars ~2 days late),
  not a pipeline break. Ingestion STILL logs "status=PARTIAL" at INFO with healthy data
  (dead tickers inflate it) — PARTIAL alone is not a signal; SQL count-per-trade_date is
  the only reliable freshness check.
- Churn day 5 — ESCALATION: all 6 of today's orders were same-day sell→rebuy round-trips
  (SNOW 13:35 sell→14:30 rebuy; DELL and STX 14:30 sell→15:30 rebuy; STX had been bought
  8/18). Zero net position change. Churn has progressed from cross-day to 1–2 hour
  intraday round-trips. Phase 88 rec #1, evidence now 5 consecutive trading days.
- Snapshot 8/19 19:30: cash $7,059.45, equity $106,410.16, drawdown 0.49%.
- Watch items for next runs: AVB Aug-17 bar (harmless, should backfill); Mon Aug-24
  yfinance blackout pattern (would be 4th consecutive Monday).


## Updates 2026-08-20 (deep-dive) — GREEN
- Fully nominal day: bars current (Aug-19 485/485 landed on time), 7/7 cycles, clean
  logs, no guard events, smoke 28/28, probes 3/3. No fixes needed.
- Churn day 6, milder flavor: no same-day round-trips; instead 13:35 sell block
  (TRV/STX/TGT) → 14:30 buy block of NEW names (MRK/AMGN/GE). STX totals 4 trades in
  3 days (8/18 buy→8/19 sell→8/19 rebuy→8/20 sell); TRV 2-day hold. Phase 88 still #1.
- Snapshot 8/20 19:30: cash $7,062.70, equity $106,477.95, drawdown 0.43%.
- Watch: AVB Aug-17 bar (still 484/485, harmless); Mon Aug-24 yfinance blackout
  (would be 4th consecutive Monday).



## Updates 2026-08-21 (deep-dive) — GREEN
- Fully nominal day. AVB Aug-17 bar BACKFILLED (485/485) — watch item closed; all bars
  current through Aug-20.
- Churn day 7 — FIRST REALIZED COST: MRNA bought 14:30 @ $156.88 → sold same day 18:30
  @ $140.80 (-10.2%, ≈-$723), drove drawdown 0.43%→1.39%. Also MRK/GE 1-day round-trips
  (bought 8/20, sold 8/21), V 3rd rebuy since 8/13, TGT 8/20 sell→8/21 rebuy. Churn is
  no longer cost-free turnover — Phase 88 rec strengthened.
- Positions 14/15 (first day below cap since Aug 14); cash $12,969.64.
- Schema note: fills quantity column is `fill_quantity` (NOT fill_qty) — a wrong guess
  killed a psql session this run; probe information_schema first (standing gotcha).
- `phase82_daily_evaluation_skipped_other_process` warning seen in worker log — benign
  duplicate-process skip, not an incident.
- Watch for Mon Aug-24: 4th consecutive Monday yfinance blackout would confirm pattern →
  escalate provider-fallback rec.



## Updates 2026-08-22 (deep-dive) — GREEN
- Saturday run, 3rd fully-GREEN weekend day (after Aug 15/16) — weekend baseline holds:
  0 snapshots/fills/signals/rankings, eval_runs +0, snapshot stays Friday 19:30, bars
  through Aug-20 (Friday's bars due Monday), all 3 probes GREEN, worker log 24h window
  had ZERO warnings/errors (fully quiet weekend log is itself normal).
- No fixes needed; no drift; smoke 28/28; git clean.
- Standing watch for Mon Aug-24 run: (a) 4th consecutive Monday yfinance blackout →
  escalate provider-fallback rec; (b) churn evidence day 8 (Phase 88 rec #1);
  (c) Friday Aug-21 bars should land ~10:00 UTC + Tue silent-partial-ingestion risk.



## Updates 2026-08-23 (deep-dive) — GREEN
- Sunday run, 4th fully-GREEN weekend day (Aug 15/16/22/23) — weekend baseline is now
  well-established across both Sat and Sun; nothing new learned, no anomalies, worker
  log 24h window had zero warnings/errors (normal for weekend).
- No fixes needed; no drift; smoke 28/28; git clean; probes 3/3 GREEN, schtasks Ready.
- Snapshot unchanged: Friday 8/21 19:30, cash $12,969.64, equity $105,451.81, dd 1.39%.
- Standing watch for Mon Aug-24 run (unchanged from Aug-22 entry): (a) 4th consecutive
  Monday yfinance blackout → escalate provider-fallback rec; (b) churn evidence day 8
  (Phase 88 rec #1); (c) Friday Aug-21 bars ~10:00 UTC + Tue silent-partial risk.



## Updates 2026-08-24 (deep-dive) — RED
- **FIRST HARD CAP BREACH: 16 open > APIS_MAX_POSITIONS=15.** Mechanism: 13:35 cycle,
  portfolio engine planned opens:1/closes:4; rebalance merge grew opens to 4
  (TMO/DGX/A/MRNA); phase65/65b suppressed exits + converted PSX close→trim; only
  JPM/JNJ closed → 16. risk_validate_action passed every open (violation_count=0) and
  factor_exposure logged position_count:16 — max-position check validates PLANNED
  closes, not post-suppression reality. NEW BUG CLASS: phase65 exit-suppression ×
  cap validation. Rec #1 to Aaron (deep-dive can fix if authorized).
  NEXT-RUN DUTY: verify open_pos ≤15 (cap should block new opens while ≥15); a 17th
  position = escalate hard.
- Monday yfinance blackout now 4 CONSECUTIVE (Aug 3/10/17/24) — pattern CONFIRMED,
  provider-fallback rec escalated to firm. Aug-24 flavor = Aug-17 (mark-to-market
  guard family, no phase87, cycle not degraded, equity frozen 14:30→19:30).
- Trim leftovers create dust positions that still count as open rows: PSX 1 sh,
  TECH 4 sh (TECH sector-trim 99 sh at 14:30, healthcare 46.8% > 40%,
  "closed_trade_recorded" fires even for partial trim — realized_pnl on trimmed lot).
- Churn day 8: MRNA sold 8/21 @140.80 (−10.2%) → rebought 8/24 @133.43 (sell-low-
  rebuy-lower round trip). JPM/JNJ age-expiry closes (age 20d cap works).
- Gmail MCP in THIS scheduled session DID expose send_message (not just create_draft)
  — notification gap note from 8/18 is session-dependent, check tool list each run.
- Snapshot 8/24 19:30: cash $13,501.89, equity $105,537.78 (frozen from 14:30 by
  stale-price preservation), drawdown 1.31%.



## Updates 2026-08-25 (deep-dive) — GREEN
- **Aug-24 cap breach SELF-CORRECTED**: 13:35 cycle closed MRVL (29 sh) + trimmed AMGN
  (15 sh), ZERO opens while ≥15 → cap enforcement blocks new opens correctly once over;
  16→15. The bug is only in breach CREATION (phase65 suppression × validation counting
  planned closes) — still unfixed, rec #1. Verification duty discharged.
- NO Tuesday silent-partial repeat: Mon Aug-24 bars 484/485 despite 4th-Monday blackout.
  Missing ORGN/EQR/EA (EA = open position) — AVB-style benign gap, watch for backfill.
- Churn PAUSED (day 9 quiet): 2 sells only, no buys/round-trips. Evidence stays 8 days.
- Schema gotcha: `side` lives on orders, NOT fills — `f.side` killed a psql session
  (join orders o and use o.side). Env also confirms APIS_MAX_SINGLE_NAME_PCT=0.20,
  APIS_MAX_POSITION_AGE_DAYS=20, daily-loss 0.02, weekly-dd 0.05.
- Cash $27,256.04 (+$13.7k from sells), equity $105,890.04, dd 0.98% (8/25 19:30).
- Watch next runs: ORGN/EQR/EA Aug-24 bar backfill; churn resumption; whether cap
  stays ≤15 on next open-eligible cycle.



## Updates 2026-08-26 (deep-dive) — GREEN
- Fully nominal day; cap stayed 15/15 with normal trading (3 sells 13:35 → 3 buys
  14:30) — second consecutive day of correct cap behavior after the 8/24 breach.
- NEW BASELINE FACT: portfolio equity_value freezes to the cent from the last fill
  (typically 14:30) through 19:30 on quiet days — verified identical on nominal
  Aug-20. Valuation updates on fills/daily bars, not intraday quotes. NOT staleness;
  do not confuse with Monday-blackout stale-price preservation (that logs
  mark_to_market_* events; this logs nothing).
- Churn resumed (evidence day 9) after 1 quiet day: MRNA same-day sell→rebuy
  (13:35 sell 53 sh @149.50, 14:30 rebuy 47 sh @149.37); the 8/24 rebuy @133.43
  realized +12% — first PROFITABLE round-trip in the churn series. A/SNOW closed →
  DASH/MA opened (sell-block→buy-block flavor).
- Bar-gap watch: Aug-24 ORGN+EA backfilled (EQR still missing); Aug-25 missing
  EQR+AVB. EQR now missing 2 consecutive days — if it hits ~4 days without
  backfill (unlike AVB precedent), consider is_active review.
- Tooling: `python -i` REPL was BLOCKED by session policy this run; one-shot
  `python -c "..."` (single line, no `^` chars — cmd mangles regex carets) works
  for log analysis. psql/powershell sessions unaffected.
- Snapshot 8/26 19:30: cash $28,463.16, equity $106,656.02, drawdown 0.26%.
- Watch next runs: EQR/AVB backfill; churn; Mon Aug-31 = 5th-Monday blackout test.



## Updates 2026-08-27 (deep-dive) — RED
- **CAP BREACH #2: 16 open > 15** (3 days after #1). Mechanism reconstructed: 13:35
  correctly BLOCKED KO/WST opens at count 15 (action_blocked_by_risk max_positions)
  and closed TGT → 14. Then 14:30 planned opens:1/closes:1, rebalance merge grew
  opens to 2 (KO/WST, origin_strategy='rebalance' — first non-momentum_v1 opens seen);
  the close was phase65-suppressed; BOTH opens validated individually against count
  14 and passed → 16. **NEW proven gap: no running open-count across same-cycle
  validations**, in addition to the 8/24 suppressed-close counting gap. Enforcement
  works AT the cap but breaks CROSSING it. Fix = URGENT rec #1.
- phase65b suppressing age-expiry exits every cycle: TECH 30d>20d (dust 4 sh, held
  since 7/28) + EA 27d — "rebalance_protected" indefinitely; contributes to stuck
  dust/aged rows.
- EQR bar missing 3rd consecutive day (8/24–26); AVB/EA/ORGN gaps churn daily
  (backfill then vanish again). If EQR hits ~4 days, review is_active.
- Churn day 10 mild: TGT closed after 6-day hold; no round-trips.
- Tooling: PowerShell session DIED on inline `python -c` with escaped quotes —
  run python one-shots via their own start_process (cmd), not inside the psql/PS
  session. Also `git rev-list --count origin/main..main` works fine.
- Gmail MCP this session: send_message available (like 8/24, unlike 8/18).
- Snapshot 8/27 19:30: cash $21,437.55, equity $106,709.46, dd 0.21%.
- Watch Fri 8/28: breach must self-correct to ≤15 (17th = hard escalate); EQR bar;
  churn; then Mon Aug-31 = 5th-Monday blackout test.



## Updates 2026-08-28 (deep-dive, ran 8:35 PM CT on wake) — RED
- **OUTAGE #6 — full trading day lost**: reboot Thu 8/27 11:39 PM CT, then sleep/
  Docker-down until ~8:20 PM CT Fri. 0/7 cycles, 0/3 probes (schtasks skip missed
  triggers — rec open since Aug 12), no Aug-27 bars, no signals/rankings. Cowork
  scheduled tasks DO fire on wake (this run, 3.5h late); host schtasks do NOT.
  NEW REC: Docker Desktop auto-start on login (containers did not come up at reboot).
- **Cap breach #2 UNCORRECTED (16 open)** — mechanically impossible to self-correct
  with zero cycles; 0 fills so no 17th. Expect correction Mon 8/31 13:35 UTC.
  MON-RUN DUTY: verify ≤15 AND 5th-Monday blackout test AND Aug-27/28 bar catch-up
  (may slip to Tue 9/1 given Monday-blackout pattern).
- **Bar-vanish behavior CONFIRMED via max(trade_date)**: EA (OPEN position) max bar
  = 8/10 — its "backfilled 8/24" row no longer exists (daily upsert apparently
  deletes/churns single-name rows). EQR max 8/21, AVB 8/24, ORGN 7/15. Proposed
  invariant: every open position must have a bar ≤2 trading days old.
- Post-restart nominal: clean worker startup (36 jobs, 0 errors), /health ok 7/7,
  smoke 28/28, env nominal, git clean, next market jobs Mon 8/31 (no Friday-night
  catch-up trading — restart-at-night is safe).
- Snapshot unchanged (8/27 19:30): cash $21,437.55, equity $106,709.46, dd 0.21%.
- Tooling: containers "Up 3 minutes" on arrival is itself a finding — always check
  container uptime FIRST; LastBootUpTime ≠ awake (sleep hides behind old boot time;
  compare schtasks Last Run Times to detect sleep windows).



## Updates 2026-08-29 (deep-dive, Sat) — RED (carried)
- Cap breach #2 unchanged (16 open, day 3) — weekend hold, nothing to learn; Mon
  8/31 13:35 UTC is the correction test (8/25 precedent: closes/trims, zero opens).
- Outage #6 recovery CONFIRMED: no re-sleep — containers up 21h straight, 3/3 host
  probes fired (first full probe day since 8/27), all GREEN. Weekend probes show NO
  paper_cycle:stale artifact (in-market-only, as expected).
- 5th consecutive GREEN-baseline weekend day (8/15,16,22,23,29): fully quiet worker
  log (0 warn/err in 616 today-lines), 0 snapshots/fills/signals/rankings, snapshot
  frozen at 8/27 19:30 (cash $21,437.55 / equity $106,709.46 / dd 0.21%).
- EA stale-bar now 19 days (last bar 8/10) — worst case yet for an OPEN position;
  the other 15 opens all have bars ≥8/26. Unchangeable on weekend (no ingestion).
- Nothing fixed (nothing to fix); no drift; smoke 28/28; git clean.
- Mon 8/31 TRIPLE DUTY: (a) cap ≤15 else hard escalate; (b) 5th-Monday yfinance
  blackout test; (c) Aug-27/28 bar catch-up + signals/rankings resumption (Tue 9/1
  slip acceptable).
