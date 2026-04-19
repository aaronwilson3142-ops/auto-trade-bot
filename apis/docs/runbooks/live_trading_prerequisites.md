# APIS Live-Trading Prerequisites Runbook

## Overview

This runbook is the in-tree checklist for transitioning APIS from `paper` mode
to real-money operation (`human_approved` → `restricted_live`). Before Phase 61
(learning acceleration) landed on 2026-04-09, several risk knobs were loosened
to accelerate signal-quality accumulation. Those overrides were reverted on
2026-04-11 (DEC-022). This document captures the state of the rollback and the
remaining gates that must still be green before flipping to live trading.

**Rule of thumb:** every checkbox below must be explicitly verified — not
assumed — on the day of the transition. Memory records are point-in-time
observations; the code and DB are the authoritative state.

---

## §1 — Learning-Acceleration Rollback (DONE 2026-04-11, DEC-022)

All four overrides from the 2026-04-09 learning-acceleration push (DEC-021) have
been reverted. Confirmed against live tree on 2026-04-18:

| Knob | Acceleration value | Reverted value | Current location |
|---|---|---|---|
| Ranking min composite score | `0.15` | `0.30` | `apis/.env` — `APIS_RANKING_MIN_COMPOSITE_SCORE` |
| Paper trading cycles/day | `12` | `7` | `apis/apps/worker/main.py` (09:35, 10:30, 11:30, 12:00, 13:30, 14:30, 15:30 ET) |
| Max new positions/day | `8` | `3` → then `5` on 2026-04-15 | `apis/.env` — `APIS_MAX_NEW_POSITIONS_PER_DAY` |
| Max position age (days) | `5` | `20` | `apis/.env` — `APIS_MAX_POSITION_AGE_DAYS` |

> The `3 → 5` bump on 2026-04-15 is deliberate, not drift — it tracks the
> `max_positions 10 → 15` raise that followed the ticker-universe expansion.
> See memory `project_position_cap_raise_2026-04-15.md` for context.

### Verification snippet

```bash
# Expect 0.30 / 20 / 5 / false
grep -E "APIS_RANKING_MIN_COMPOSITE_SCORE|APIS_MAX_POSITION_AGE_DAYS|APIS_MAX_NEW_POSITIONS_PER_DAY" apis/.env

# Expect 7 cycles scheduled (paper_trading_cycle_morning + 6 intraday)
grep -c "paper_trading_cycle_" apis/apps/worker/main.py

# Expect default=False
grep "self_improvement_auto_execute_enabled" apis/config/settings.py
```

---

## §2 — Remaining Prerequisites Before Live Mode

These gates must all be green on the day of the flip. Check them **in order** —
earlier items guard against investing effort in later verification on a system
that is not yet ready.

### 2.1 — Self-improvement auto-execute stays OFF until gate passes

Current default: `self_improvement_auto_execute_enabled = False`
(`apis/config/settings.py`). Flip this only after:

- [ ] `GET /system/readiness-report` shows PAPER → HUMAN_APPROVED = PASS
- [ ] `latest_signal_quality.total_outcomes_recorded >= 10` per strategy
- [ ] Manual inspection of the last ~5 PROMOTED proposals from
  `app_state.improvement_proposals` confirms their `confidence_score` tracks
  something meaningful (not bimodal noise at the edges).

If all three check out, set `APIS_SELF_IMPROVEMENT_AUTO_EXECUTE_ENABLED=true`
in `apis/.env` and restart the worker. Watch the 18:15 ET
`auto_execute_proposals` job output for a week — `skipped_low_confidence` and
`executed_count` should both be non-trivial. Zero on both ⇒ retune the
threshold.

See memory `project_apis_self_improvement_gate.md` and DEC-019 for the original
design.

### 2.2 — Readiness gate passes all sub-checks

Run `GET /system/readiness-report` and confirm every gate shows `PASS`,
especially:

- [ ] Phase 51 Sharpe ratio gate
- [ ] Drawdown-state gate (no active deterioration)
- [ ] Signal-quality gate (per 2.1)
- [ ] Phase 54 factor-tilt alerts absent for at least 5 consecutive trading days
- [ ] Phase 55 fill-quality attribution within expected alpha-decay envelope

### 2.3 — Weight profile derived from backtest sweep

- [ ] `app_state.active_weight_profile` is a PROMOTED profile from a recent
  backtest sweep (`apis/scripts/run_backtest_sweep.py`) — not the Phase 23
  fallback defaults.
- [ ] Sweep coverage spans at least one full regime transition (trend → chop or
  similar).

### 2.4 — Deep-Dive Step flags evaluated and set deliberately

All 11 flags from the 2026-04-16 Deep-Dive plan default OFF. Before live
trading, for each flag, either:

- Flip ON with documented paper-bake validation, **or**
- Explicitly decide to leave OFF and record the decision in `DECISION_LOG.md`.

Do not let default-OFF be the implicit choice on the day of the flip — that is
how forgotten improvements accumulate.

### 2.5 — Broker credentials

- [ ] Alpaca (or successor broker) API keys rotated within the last 90 days.
- [ ] `ALPACA_BASE_URL` switched from `paper-api.alpaca.markets` to the live
  endpoint.
- [ ] Kill-switch smoke test against the live endpoint in a non-trading window.

### 2.6 — Backup + rollback path

- [ ] `pg_dump` snapshot taken per `db_backup_runbook.md §2` — retain
  indefinitely.
- [ ] Operator knows how to revert to `APIS_OPERATING_MODE=paper` and has
  tested it in a dry run.

### 2.7 — Mode transition itself

Follow `mode_transition_runbook.md` step-by-step. Key invariant: set
`APIS_OPERATING_MODE=human_approved` **first**. Do not skip to
`restricted_live` — the intermediate `human_approved` mode requires manual
approval on each trade and is the only way to catch silent config drift before
real capital is exposed.

---

## §3 — On the Day of the Flip

1. Start of day: run §2.1 → §2.6 verification; abort if any item is not green.
2. Take the pre-flip `pg_dump` snapshot (§2.6).
3. Flip to `human_approved` only (§2.7).
4. Manually approve the first 10 trades to confirm the approval path is wired
   correctly end-to-end.
5. Watch for 5 consecutive market days with the Phase 54 factor-tilt alerts +
   Phase 55 fill-quality attribution both inside their expected envelopes.
6. Only then flip to `restricted_live` — and even at that point, keep
   `max_positions`, `daily_loss_limit_pct`, and `weekly_drawdown_limit_pct` at
   their current paper-mode values for the first full trading week.

---

## Related

- DEC-019 — self-improvement auto-execute safety gates (`apis/state/DECISION_LOG.md`)
- DEC-021 — learning acceleration (reverted)
- DEC-022 — learning acceleration rollback
- Memory — `project_learning_acceleration_rollback.md`
- Memory — `project_apis_self_improvement_gate.md`
- Runbook — `mode_transition_runbook.md`
- Runbook — `db_backup_runbook.md`
