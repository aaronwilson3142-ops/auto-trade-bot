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
- Machine outages are the root recurring risk (4 multi-day outages; last Jul 29–30). Stack restarted Sun 2026-08-09 03:21 UTC (weekend, harmless).

## DB schema gotchas (save yourself the errors)
- `positions` has NO ticker column — join `securities s ON s.id=p.security_id`, use `s.ticker` (NOT s.symbol).
- `portfolio_snapshots`: `cash_balance`, `equity_value`, `drawdown_pct`, `snapshot_timestamp`.
- `daily_market_bars`: date column is `trade_date` (not bar_date).
- Signal/ranking tables: `signal_runs`, `ranking_runs`, `evaluation_runs` (use max(created_at)).
- 16 closed April-2026 positions have NULL origin_strategy — historical, pre-existing; the 0-NULL invariant applies to OPEN rows.

## Tooling gotchas
- Desktop Commander + `docker exec -i psql` session DIES on any SQL error — probe column names via information_schema first; one bad statement costs the session.
- PowerShell `docker logs --since 24h X 2>&1 | Out-File` can yield 0 bytes for the api container; use `--tail N` instead.
- `health_probe.ps1` records only `health:<status>`, NOT which component degraded — retro-diagnosis impossible (rec to Aaron 2026-08-10 to log components JSON).
- Gmail MCP in scheduled sessions exposes create_draft only (no send) — YELLOW/RED notifications = draft + rely on cloud watchdog for push.

## Open questions / watch items (as of 2026-08-10)
- Cause of /health "degraded" at 15:05 + 19:05 UTC Aug 10 (unrecorded component; suspect broker ping error or scheduler heartbeat staleness during provider flakiness).
- PLTR/CZR same-day churn + CZR "Insufficient cash" risk-engine sizing bug (Phase 88 candidate).
