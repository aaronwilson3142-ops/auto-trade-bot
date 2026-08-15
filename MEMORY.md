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

## Open questions / watch items (as of 2026-08-15)
- Weekend baseline (verified Sat 2026-08-15): 0 cycles/orders/signals/rankings expected Sat/Sun; latest snapshot stays Friday 19:30; eval_runs +0; all 3 probes GREEN (no in-market staleness artifact) — do not flag any of this as missed/stale on weekend runs.
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
