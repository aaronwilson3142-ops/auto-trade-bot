# Monday Baseline Paper-Cycle Watch Runbook

## Overview

After the 2026-04-17 paper-cycle crash-triad cleanup (`63fa33e`), the
2026-04-18 phantom broker reset, and the Step 5 `origin_strategy` finisher
(`d08875d`), the next paper cycle is the first one to run end-to-end on the
fixed code path. The hard rule from `apis/state/NEXT_STEPS.md` is:

> Do **not** flip any Deep-Dive behavioural flag before the Monday baseline
> cycle runs.

This runbook is the operator checklist for the Monday 2026-04-20 09:35 ET
cycle (and any future "first cycle after maintenance" baseline). It pairs
with `apis/scripts/monday_cycle_watch.py`, which encodes the four watch-list
criteria as exit-code-driven assertions.

---

## §1 — The Four Watch-List Criteria

Direct from `NEXT_STEPS.md`:

1. **No `_fire_ks()` or `broker_adapter_missing_with_live_positions` errors**
   in the worker log for the cycle window. Either pattern reappearing means
   regression vs `63fa33e` (crash-triad fixes) — bisect immediately.

2. **Trades open against a clean ~$100k cash baseline.** The phantom ledger
   from the 2026-04-17 crash-triad cycles left cash at ≈ -$80,274.62; the
   2026-04-18 cleanup reset it to $100k. The cycle should not restore phantom
   cash.

3. **New `positions` rows carry non-NULL `origin_strategy`.** The Step 5
   wiring (`d08875d`) populates this from the highest-scoring contributing
   signal. Any NULL value in a row opened on/after the cycle date is a
   regression.

4. **A new `portfolio_snapshots` row is written by the cycle itself** — not
   just the manual cleanup row from 2026-04-18. This is the cleanest single
   signal that the cycle reached the persistence stage.

---

## §2 — Run the Watcher

```bash
cd apis
python scripts/monday_cycle_watch.py                    # default: today
python scripts/monday_cycle_watch.py --date 2026-04-20  # pin a date
```

Exit code:

- `0` → all four checks ok, **or** ok-with-skipped-doc-log (see §3).
- `1` → at least one check failed; do not flip flags. Pipe the script's
  stdout into `apis/state/HEALTH_LOG.md` for handoff.
- `2` → bad CLI arg.

The script is read-only by design. It will not write to the DB or restart
any container.

---

## §3 — Triage by Failure Mode

### `worker_logs_clean: [fail]`

The worker container is hitting one of the patched 2026-04-18 bugs.

```bash
docker logs docker-worker-1 --since 2026-04-20T13:00:00 \
  | grep -E "_fire_ks|broker_adapter_missing"
```

If `_fire_ks() takes 0 positional arguments`: the `apps/worker/jobs/paper_trading.py`
signature has been silently regressed. `git log -p apps/worker/jobs/paper_trading.py`
to find the offending change.

If `broker_adapter_missing_with_live_positions`: the lazy-init block before
the Step 2 health-invariant check is broken. The fix at `63fa33e` placed it
*before* the invariant; verify it has not been moved.

### `clean_100k_start: [fail]`

Either equity has drifted >$5k from $100k on the very first cycle (suspect a
bad first-cycle execution path) or cash is negative again (phantom-ledger
regression — the Phase 64 position-persistence fix has been undone).

```sql
SELECT * FROM portfolio_snapshots ORDER BY snapshot_date DESC LIMIT 5;
SELECT count(*), status FROM positions GROUP BY status;
```

### `positions_origin_strategy: [fail]`

The Step 5 finisher (`d08875d`) is no longer wired in `apps/worker/jobs/paper_trading.py`.

```bash
git log -p --follow apis/apps/worker/jobs/paper_trading.py | grep -A5 origin_strategy
```

Confirm the `derive_origin_strategy` import + `_persist_positions` call still
pass the family map.

### `portfolio_snapshot_written: [fail]`

The cycle did not reach the persistence stage. Look up the cycle status in
`evaluation_runs`:

```sql
SELECT id, status, started_at, ended_at, error_message
FROM evaluation_runs ORDER BY id DESC LIMIT 5;
```

If `status='failed'`, the `error_message` will point at the next bug to fix.

### `worker_logs_clean: [skip]`

`docker` is not on PATH. Run the manual grep from §3.1 above on the host
that owns the docker socket.

### `positions_origin_strategy: [skip]`

No new positions opened on the cycle date. This is **not** a hard fail — the
ranking engine may have produced no actionable trades — but it is a soft
signal worth investigating before flipping behavioural flags. Check
`evaluation_runs.status` and the worker log for `signals: 0` or
`paper_trading_cycle_skipped_no_rankings`.

---

## §4 — On Green

If exit code is 0 with all four checks `[ok]`:

1. Append the script output to `apis/state/HEALTH_LOG.md` under the cycle
   date.
2. The hard "no flag flips" rule from `NEXT_STEPS.md` is satisfied. Operator
   may now begin flipping Step 6 / Step 8 flags one at a time, with
   post-flip monitoring per the Deep-Dive execution plan.
3. Record the green baseline in `DECISION_LOG.md` so future drift bisects
   have a known-good anchor commit.

---

## Related

- Memory — `project_paper_cycle_crashtriad_2026-04-18.md`
- Memory — `project_phantom_broker_positions.md`
- Memory — `project_deep_dive_step5_origin_strategy_finisher.md`
- Commit — `63fa33e fix(crash-triad): persist 2026-04-18 morning drift fixes`
- Commit — `d08875d feat(deep-dive): wire Step 5 origin_strategy into paper_trading open-path`
- Code — `apis/scripts/monday_cycle_watch.py`
