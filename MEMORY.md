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
