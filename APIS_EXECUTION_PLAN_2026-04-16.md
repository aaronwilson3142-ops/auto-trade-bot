# APIS — Execution Plan for Deep-Dive Review Recommendations

**Author:** Claude (internal, for Aaron)
**Date:** 2026-04-16
**Companion doc:** `APIS_DEEP_DIVE_REVIEW_2026-04-16.md` (analysis + 13 ranked recs)
**Governing DECs:** DEC-031 (self-improvement before OOS/data), DEC-032 (AI tilt frozen), DEC-033 (9 hard risk gates frozen), DEC-034 (shadow portfolios include parallel rebalance weightings), DEC-035 (per-type outcome measurement windows)
**Status:** Plan awaiting operator approval. **No code to be written until operator greenlights.**

---

## Rules of Engagement (apply to every step below)

1. **Feature flags.** Every behavioral change lands behind an `APIS_*_ENABLED` env var that defaults to **OFF**. The flag is added to `config/settings.py` as a `bool` field with `env` binding, and the code path must fall through to pre-flag behavior when the flag is False. Operator flips the flag in PAPER (via Redis-updated settings or service restart — noted per step) after reviewing the PR.
2. **Scope isolation.** No step is allowed to touch more than its own files list. If a step's work reveals a cross-cutting refactor need, that becomes a separate PR before the step proceeds.
3. **Test plan.** Every step has a unit-test batch and (where behavior changes) a paper-bake duration. Acceptance criteria are measurable and must be green before the next step's PR is opened.
4. **Rollback strategy.** Every step has a documented rollback that is either (a) flip the env flag to OFF, or (b) revert the PR. Any step requiring a DB migration includes a reversible `down` path.
5. **State hygiene.** Every landed step updates `apis/state/CHANGELOG.md`, `apis/state/DECISION_LOG.md` (only for user-facing decisions), `apis/state/NEXT_STEPS.md`, and the appropriate memory file.
6. **Frozen items (DEC-033).** The 9 hard risk gates (kill switch, daily/weekly/monthly drawdown limits, concentration caps, `max_single_name_pct`, `max_sector_pct`, `daily_loss_limit`, `max_new_positions_per_day`, RESTRICTED_LIVE guard) are **not** touched by any step in this plan.
7. **AI tilt (DEC-032).** `_AI_THEME_BONUS`, `_AI_RANKING_BONUS`, and `max_thematic_pct=0.75` are operator-level bets and are explicitly **not** self-improvement targets. Step 1 makes them config-driven for reversibility; no other step may propose to modify them.
8. **No auto-promotion from shadow data.** Shadow portfolios (Step 7) and the Proposal Outcome Ledger (Step 6) are **sources of proposals**, never **sources of decisions**. The three-gate promotion path (master switch, observation floor, per-proposal confidence) is unchanged.

---

## Step-by-Step Overview

| Step | Recs | Theme | Cal. time | Risk | Behavior change day-1 |
|------|------|-------|-----------|------|------------------------|
| 1 | Rec 1 | Un-bury 6 constants | ~1 d | None | No |
| 2 | Recs 2, 3, 4, 13 | Stability invariants + observation floor | ~3 d | Low | No (invariant triggers are new logs/alerts) |
| 3 | Recs 8, 9 | Trade-count lift (threshold + conditional filter) | ~2 d | Medium | Yes, via flags |
| 4 | Rec 6 | Score-weighted rebalance | ~1 wk | Medium | Yes, via flag |
| 5 | Rec 7 + Rec 5 | ATR stops + per-family max-age + promote `portfolio_fit_score` | ~1.5 wk | Medium | Yes, via flag |
| 6 | Rec 10 | Proposal Outcome Ledger (meta-learning) | ~2 wk | Low (data-only; no decisions) | No (new dashboard section + logs) |
| 7 | Rec 11 | Shadow-Portfolio Scorer (incl. DEC-034 parallel weightings) | ~3 wk | Low (shadow-only; no live impact) | No |
| 8 | Rec 12 | Thompson-sampling strategy bandit | ~1 wk | Medium | Yes, via flag (runs in RESEARCH shadow 2–4 wk first) |

Total: **~11 calendar weeks** at 2–3 focused hours/day, matching the §10 sequencing of the review doc.

---

## Step 1 — Un-bury Six Hard-Coded Constants (Rec 1)

### 1.1 Scope
Move six decision-relevant magic numbers from code into `config/settings.py` with `env` overrides. No behavior change day-one. Unlocks 9 of the remaining 12 recommendations.

### 1.2 Files touched

| File | Change |
|------|--------|
| `apis/config/settings.py` | Add six new fields with env bindings (see table below). |
| `apis/services/ranking_engine/service.py:294-299` | Replace literal `0.65 / 0.45` with `settings.APIS_BUY_THRESHOLD / settings.APIS_WATCH_THRESHOLD`. |
| `apis/services/ranking_engine/service.py:40-50` | Replace literal `_AI_RANKING_BONUS` map with `settings.APIS_AI_RANKING_BONUS_MAP` (pydantic `Dict[str, float]`). |
| `apis/services/self_improvement/service.py:87` | Replace `0.50` literal with `settings.APIS_SOURCE_WEIGHT_HIT_RATE_FLOOR`. |
| `apis/services/self_improvement/service.py:105` | Replace `-0.02` literal with `settings.APIS_RANKING_THRESHOLD_AVG_LOSS_FLOOR`. |
| `apis/strategies/theme_alignment.py:55-64` | Replace literal `_AI_THEME_BONUS` map with `settings.APIS_AI_THEME_BONUS_MAP`. |
| Phase 65 rebalance-target TTL (whichever file implements the close-suppression) | Replace implicit "indefinite" with `settings.APIS_REBALANCE_TARGET_TTL_SECONDS` (default 3600 = 1 hr). |
| `apis/workers/paper_trading.py` (startup log) | Emit one info log line listing all 6 values at worker startup. |

### 1.3 New settings fields

```python
# config/settings.py (additions)
APIS_BUY_THRESHOLD: float = 0.65   # preserved default; Step 3 lowers to 0.55
APIS_WATCH_THRESHOLD: float = 0.45
APIS_SOURCE_WEIGHT_HIT_RATE_FLOOR: float = 0.50
APIS_RANKING_THRESHOLD_AVG_LOSS_FLOOR: float = -0.02
APIS_AI_THEME_BONUS_MAP: Dict[str, float] = {...}  # preserves current literals
APIS_AI_RANKING_BONUS_MAP: Dict[str, float] = {...}  # preserves current literals
APIS_REBALANCE_TARGET_TTL_SECONDS: int = 3600
```

### 1.4 Feature flag
None. This step is pure refactor with identical defaults.

### 1.5 Test plan
- Unit: add `tests/config/test_settings_new_fields.py` asserting defaults match pre-refactor literals byte-for-byte.
- Unit: modify existing ranking-engine tests to parametrize over threshold values (regression guard).
- Unit: env-override test — `APIS_BUY_THRESHOLD=0.55` in monkeypatch → ranking engine threshold = 0.55.
- Integration: run 1 paper cycle, assert zero diff in `ranking_runs` table rows vs. baseline.

### 1.6 Paper bake
0 days (no behavior change). PR mergeable day-of.

### 1.7 Rollback
Git revert. Constants return to literals. No data migration.

### 1.8 Acceptance criteria
- All 6 literals grep-deletable from code (no stragglers).
- Worker startup log shows all 6 values.
- Zero P&L/trade-count diff on a same-seed paper replay.

---

## Step 2 — Stability Invariants + Observation Floor (Recs 2, 3, 4, 13)

### 2.1 Scope
Four independent guardrails. None of them changes trading behavior. All of them make future bugs loud instead of silent.

### 2.2 Rec 2: Broker-adapter health invariant

**Files touched:**
- `apis/workers/paper_trading.py` — add `_assert_broker_adapter_health()` called at the top of `run_paper_trading_cycle`.
- `apis/services/broker_adapter/health.py` (**new**) — `check_broker_adapter_health(app_state, db) -> HealthResult`.

**Logic:**
```
if app_state.broker_adapter is None and Position.count() > 0:
    fire_kill_switch("broker_adapter_reset_with_live_positions")
    raise BrokerAdapterHealthError

delta = adapter.positions_by_ticker vs DB Position rows
if any(abs(d) > 0.01 for d in delta):
    webhook_alert("broker_adapter_position_drift", delta)
    # continue with DB as source of truth
```

**Feature flag:** `APIS_BROKER_HEALTH_INVARIANT_ENABLED` (default **ON** — this is a safety check, not a behavior change).

**Test plan:**
- Unit: synthetic `app_state.broker_adapter=None` + Position rows → kill-switch triggered.
- Unit: drift >0.01 → webhook mocked; cycle proceeds with DB values.
- Unit: healthy state → no log/alert, cycle proceeds normally.

**Rollback:** Set `APIS_BROKER_HEALTH_INVARIANT_ENABLED=false`.

### 2.3 Rec 3: Rebalance/portfolio-action conflict detector

**Files touched:**
- `apis/services/action_orchestrator/invariants.py` (**new**) — `assert_no_action_conflicts(actions: List[Action]) -> None`.
- `apis/workers/paper_trading.py` — call `assert_no_action_conflicts` after action merge, before risk validation.

**Logic:**
- Reject cycle with webhook alert if any ticker appears in actions with both OPEN and CLOSE.
- Reject cycle with webhook alert if any ticker has TRIM and OPEN with conflicting signs.
- Resolution: drop the lower-confidence action, log the drop, continue.

**Feature flag:** `APIS_ACTION_CONFLICT_DETECTOR_ENABLED` (default **ON**).

**Test plan:**
- Unit: construct synthetic `[Action(AAPL, OPEN), Action(AAPL, CLOSE)]` → assertion fires, lower-confidence dropped.
- Unit: no conflicts → passes.
- Integration: Phase 65 regression — replay the original Phase 65 data and confirm invariant fires before the churn would have occurred.

**Rollback:** Set flag to false.

### 2.4 Rec 4: Idempotency keys on fire-and-forget DB writers

**Files touched:**
- `apis/db/models/portfolio_snapshot.py` — add `idempotency_key` column (unique index).
- `apis/db/models/position_history.py` — same.
- `apis/db/models/paper_cycle_count.py` — same.
- `apis/db/models/evaluation_run.py` — same.
- `alembic/versions/xxxxx_add_idempotency_keys.py` (**new migration**).
- Four `_persist_*` functions updated to compute key `f"{cycle_id}:{job_name}"` and use `ON CONFLICT DO NOTHING`.

**Feature flag:** None — schema-level.

**Test plan:**
- Unit: double-call `_persist_paper_cycle_count` with same cycle_id → exactly 1 row.
- Unit: different cycle_ids → 2 rows.
- Migration: alembic up + down executes cleanly on a clean DB.

**Rollback:** alembic down migration drops the unique indexes + columns. Fire-and-forget returns to pre-Step-2 behavior.

### 2.5 Rec 13: Raise self-improvement observation floor 10 → 50

**Files touched:**
- `apis/config/settings.py` — change `APIS_SELF_IMPROVEMENT_OBSERVATION_FLOOR` default `10 → 50`.
- Add a `CHANGELOG.md` entry citing Apr-14 review §3.6 reasoning.

**Feature flag:** None (this is a governance-level tightening; the flag in use is the master switch, which remains OFF).

**Test plan:**
- Unit: self-improvement service fed 49 observations → emits no proposals.
- Unit: fed 50 observations → emits proposals as before.

**Rollback:** Revert the default in settings.

### 2.6 Acceptance criteria for Step 2
- All 4 unit-test batches green.
- 7 consecutive paper cycles with zero invariant violations (confirming no false positives).
- No change in trade count or P&L.

### 2.7 Paper bake
1 week.

---

## Step 3 — Trade-Count Lift (Recs 8, 9)

### 3.1 Scope
Two flag-gated threshold relaxations. Both build on Step 1's new settings fields. Both are individually reversible.

### 3.2 Rec 9: Lower "buy" threshold 0.65 → 0.55

**Files touched:**
- `apis/config/settings.py` — `APIS_BUY_THRESHOLD` default changes **only when the flag below is ON**.
- Add flag `APIS_LOWER_BUY_THRESHOLD_ENABLED: bool = False`.
- `apis/services/ranking_engine/service.py` — branch on flag:
  ```python
  threshold = 0.55 if settings.APIS_LOWER_BUY_THRESHOLD_ENABLED else settings.APIS_BUY_THRESHOLD
  ```
  (Yes, `APIS_BUY_THRESHOLD` is still operator-overridable if the flag is off.)

**Feature flag:** `APIS_LOWER_BUY_THRESHOLD_ENABLED` — default **OFF**.

**Test plan:**
- Unit: flag ON + composite 0.56 → `recommended_action="buy"`.
- Unit: flag OFF + composite 0.56 → `recommended_action="watch"` (existing behavior).
- Integration: 5 paper cycles with flag ON, expect daily "buy" count to rise by 30–70% vs baseline (rough check against historical data — documented, not asserted).

**Paper bake:** 2 weeks before promoting to default-ON.

**Rollback:** Flip flag to false. Zero state migration needed.

### 3.3 Rec 8: Conditional `ranking_min_composite_score` relaxation

**Files touched:**
- `apis/config/settings.py` — add:
  ```python
  APIS_CONDITIONAL_RANKING_MIN_ENABLED: bool = False
  APIS_RANKING_MIN_HELD_POSITIVE: float = 0.20
  # (existing) APIS_RANKING_MIN_COMPOSITE_SCORE: float = 0.30
  ```
- `apis/workers/paper_trading.py:332-347` — extend the filter logic:
  ```python
  min_score = settings.APIS_RANKING_MIN_COMPOSITE_SCORE
  if settings.APIS_CONDITIONAL_RANKING_MIN_ENABLED:
      is_held_with_positive_history = (
          ticker in current_positions and
          closed_trade_service.positive_grade_count(ticker) > 0
      )
      if is_held_with_positive_history:
          min_score = settings.APIS_RANKING_MIN_HELD_POSITIVE
  ```
- `apis/services/closed_trade_service/service.py` — add `positive_grade_count(ticker: str) -> int` (count of A/B grade closed trades for that ticker).

**Feature flag:** `APIS_CONDITIONAL_RANKING_MIN_ENABLED` — default **OFF**.

**Test plan:**
- Unit: ticker not held → filter at 0.30 (existing).
- Unit: ticker held, no prior closed trades → filter at 0.30.
- Unit: ticker held + 1 A-grade closed trade → filter at 0.20.
- Unit: ticker held + 1 D-grade closed trade (no positives) → filter at 0.30.

**Paper bake:** 2 weeks.

**Rollback:** Flip flag to false.

### 3.4 Acceptance criteria for Step 3
- Both flags togglable live without restart (via env on worker restart).
- Paper trade count over 10 days with both flags ON: target 30–100% increase in daily trades.
- Zero hard-risk-gate violations during bake.
- No increase in realized drawdown vs baseline (paired bootstrap, 95% CI).

---

## Step 4 — Score-Weighted Rebalance Allocator (Rec 6)

### 4.1 Scope
Replace 1/N rebalance allocation with composite-score-weighted allocation, respecting `max_single_name_pct`. Three parallel modes: `equal` (legacy), `score`, `score_invvol`.

### 4.2 Files touched

| File | Change |
|------|--------|
| `apis/services/rebalancing_engine/allocator.py` (**new**) | Implements the three weighting methods. |
| `apis/services/rebalancing_engine/service.py` | Switch allocation path based on `settings.APIS_REBALANCE_WEIGHTING_METHOD`. |
| `apis/config/settings.py` | Add `APIS_REBALANCE_WEIGHTING_METHOD: Literal["equal","score","score_invvol"] = "equal"` (default preserves legacy behavior) + `APIS_SCORE_WEIGHTED_REBALANCE_ENABLED: bool = False`. |
| `apis/services/features/volatility.py` (**new helper**, or extend existing) | `rolling_volatility_20d(ticker) -> float` pulled from feature store. |

### 4.3 Algorithm (per review §5.1)
```
scores        = max(composite_scores − min(composite_scores), 0.01)
raw_weights   = scores / sum(scores)
capped        = min(raw_weights, max_single_name_pct)
final_weights = capped / sum(capped)

# If score_invvol mode:
invvol       = 1 / volatility_20d
final_weights = final_weights × invvol / sum(final_weights × invvol)
capped_again  = min(final_weights, max_single_name_pct)
final_weights = capped_again / sum(capped_again)
```

### 4.4 Feature flag
`APIS_SCORE_WEIGHTED_REBALANCE_ENABLED` — default **OFF**. When OFF, allocation method forced to `equal` regardless of `APIS_REBALANCE_WEIGHTING_METHOD` value.

### 4.5 Test plan
- Unit: `equal` mode reproduces 1/N exactly (backwards-compat).
- Unit: `score` mode with uniform scores → equal weights (edge case).
- Unit: `score` mode respects `max_single_name_pct` cap.
- Unit: `score_invvol` mode with volatile name gets smaller weight than matched low-vol name at same score.
- Unit: re-normalization after cap is exact to float precision.
- Integration: 5 paper cycles in each mode → logged allocation divergence vs `equal`.

### 4.6 Paper bake
2 weeks in `score` mode. **Parallel shadow scoring via Step 7's ShadowPortfolioService (DEC-034) runs all three modes simultaneously** and emits weekly assessment.

### 4.7 Rollback
Flip flag to false. Allocation instantly reverts to 1/N.

### 4.8 Acceptance criteria
- Unit tests green.
- 2-week paper bake: realized vol-per-unit-return of `score` mode ≤ 1.1× that of `equal` mode (guard against noise amplification).
- Operator dashboard shows per-mode P&L divergence daily.

---

## Step 5 — ATR Stops + Per-Family Max-Age + Promote `portfolio_fit_score` (Recs 5, 7)

### 5.1 Scope
Three coupled changes in the exit/sizing path. Grouped because the `origin_strategy` schema change is shared.

### 5.2 Rec 7: ATR-scaled stops and per-family max-age

**Files touched:**
- `apis/db/models/position.py` — add `origin_strategy: Optional[str]` column (nullable for backward compat).
- `alembic/versions/xxxxx_add_position_origin_strategy.py` (**new migration**).
- `apis/services/risk_engine/exit_evaluator.py` — implement ATR-scaled per-family exits:
  ```python
  def compute_stop_distance(position, atr_20, price) -> float:
      family = FAMILY_PARAMS[position.origin_strategy or "default"]
      raw = family.stop_atr_mult * atr_20 / price
      return max(family.stop_floor_pct, min(family.stop_cap_pct, raw))
  ```
- `apis/services/risk_engine/config.py` (**new**) — declarative `FAMILY_PARAMS` table mapping strategy → `{stop_atr_mult, stop_floor_pct, stop_cap_pct, trailing_atr_mult, max_age_days}`.
- `apis/services/features/atr.py` (**new or extended**) — `atr_20(ticker) -> float` from feature store.
- `apis/services/portfolio_engine/service.py` — when opening a position, set `origin_strategy = top_contributing_strategy` on the Position row.
- When multiple strategies originated: apply the **widest stop / longest max-age** per review §5.2.

**Family params** (per review §5.2):

| Family | Stop (ATR mult) | Trailing (ATR mult) | Max age (days) | Stop floor/cap |
|---|---|---|---|---|
| Momentum | 2.5× | 1.5× | 60 | 4–18% |
| Theme alignment | 2.5× | 1.5× | 60 | 4–18% |
| Macro tailwind | 2.5× | 1.5× | 20 | 4–18% |
| Sentiment | 2.0× | 1.0× | 15 | 3–15% |
| Valuation | 3.5× | 2.0× | 90 | 5–25% |
| Mean reversion (future) | 1.5× | 1.0× | 7 | 2–10% |
| Default (null origin_strategy) | 2.5× | 1.5× | 20 | 4–15% |

**Feature flag:** `APIS_ATR_STOPS_ENABLED` — default **OFF**. When OFF, the legacy 7%/20-day/5%-trailing triple is used for every position.

**Backward compat:** Positions opened before this step have `origin_strategy = NULL` → they fall through to "Default" family params (wider stop, legacy max-age). **No open position is stopped out earlier than it would have been under legacy rules.**

**Test plan:**
- Unit: each family's compute_stop_distance/trailing/max_age returns correct values.
- Unit: null `origin_strategy` uses Default params.
- Unit: multi-strategy origin picks widest/longest.
- Unit: flag OFF → legacy 7%/20/5% regardless of ATR.
- Integration: 30 days of paper data replayed with flag ON vs OFF → compare stopped-out count and avg hold duration.

**Paper bake:** 3 weeks.

**Rollback:** Flip flag to false. Migration's column stays (NULL-safe); reversible only if needed.

### 5.3 Rec 5: Promote `portfolio_fit_score` into sizing

**Files touched:**
- `apis/services/portfolio_engine/service.py:170-234` — update `compute_sizing`:
  ```python
  if settings.APIS_PORTFOLIO_FIT_SIZING_ENABLED:
      liquidity_adjusted = half_kelly * ranked_result.portfolio_fit_score
      final_pct = min(liquidity_adjusted, sizing_hint, max_single_name_pct)
  else:
      final_pct = min(half_kelly, sizing_hint, max_single_name_pct)  # legacy
  ```

**Feature flag:** `APIS_PORTFOLIO_FIT_SIZING_ENABLED` — default **OFF**.

**Test plan:**
- Unit: flag OFF → sizing matches pre-Step-5 byte-for-byte.
- Unit: flag ON + portfolio_fit=0.9 → sizing reduced by 10% vs flag OFF.
- Unit: flag ON + portfolio_fit=0.3 + half_kelly already above caps → `max_single_name_pct` still binds.

**Paper bake:** 2 weeks, can run concurrent with ATR stops bake since they operate in different code paths.

**Rollback:** Flip flag to false.

### 5.4 Acceptance criteria for Step 5
- Unit tests green for both sub-steps.
- 3-week paper bake with ATR stops ON: avg position hold duration increases (target +30%) without realized drawdown increase.
- `portfolio_fit_score` now has exactly one production consumer (sizing) — previously zero.

---

## Step 6 — Proposal Outcome Ledger (Rec 10)

### 6.1 Scope
Give the self-improvement engine memory. No impact on live trading decisions. New data pipeline + new dashboard section.

### 6.2 Files touched

| File | Change |
|------|--------|
| `apis/db/models/proposal_outcome.py` (**new**) | Table schema (below). |
| `alembic/versions/xxxxx_add_proposal_outcomes.py` (**new migration**) | Creates table with indexes. |
| `apis/services/self_improvement/outcome_ledger.py` (**new**) | `ProposalOutcomeLedgerService` — read/write. |
| `apis/workers/jobs/proposal_outcome_assessment.py` (**new**) | Daily 18:30 ET job. |
| `apis/services/self_improvement/service.py:40-389` | Inject `ProposalOutcomeHistoryService`; consult batting averages in `generate_proposals`. |
| `apis/config/settings.py` | Add `APIS_PROPOSAL_OUTCOME_WINDOWS` dict (per DEC-035) + `APIS_PROPOSAL_OUTCOME_LEDGER_ENABLED`. |
| `apis/api/routes/dashboard.py` | Add `/dashboard/proposal_outcomes` section rendering batting-average table. |

### 6.3 DB schema (new table `proposal_outcomes`)

```sql
CREATE TABLE proposal_outcomes (
    id                        SERIAL PRIMARY KEY,
    proposal_id               INTEGER NOT NULL REFERENCES improvement_proposals(id),
    decision                  VARCHAR(20) NOT NULL,          -- PROMOTED | REJECTED | EXECUTED | REVERTED
    decision_at               TIMESTAMPTZ NOT NULL,
    measurement_window_days   INTEGER NOT NULL,              -- per DEC-035
    baseline_metric_snapshot  JSONB NOT NULL,
    realized_metric_snapshot  JSONB,                         -- populated when window closes
    outcome_verdict           VARCHAR(20),                   -- improved | unchanged | regressed | inconclusive
    outcome_confidence        NUMERIC(4,3),                  -- [0,1] bootstrap-based when N is thick
    measured_at               TIMESTAMPTZ,
    UNIQUE(proposal_id, decision),
    INDEX(decision_at),
    INDEX(outcome_verdict)
);
```

### 6.4 Per-type measurement windows (DEC-035)

```python
# config/settings.py
APIS_PROPOSAL_OUTCOME_WINDOWS: Dict[str, int] = {
    "SOURCE_WEIGHT":         45,
    "RANKING_THRESHOLD":     30,
    "HOLDING_PERIOD_RULE":   14,
    "CONFIDENCE_CALIBRATION": 60,
    "PROMPT_TEMPLATE":       30,
    "FEATURE_TRANSFORMATION": 45,
    "SIZING_FORMULA":        30,
    "REGIME_CLASSIFIER":     60,
    # Unknown-type fallback
    "_DEFAULT":              30,
}
```

Window is persisted as `measurement_window_days` on the outcome row, so historical interpretability survives retuning.

### 6.5 Daily job `run_proposal_outcome_assessment` (18:30 ET)

**Pseudocode:**
```
for proposal in improvement_proposals where decision in ("PROMOTED","REJECTED")
                                    and decision_at == today - window:
    baseline = proposal.baseline_metric_snapshot
    realized = compute_metrics_from_evaluation_runs_and_trades(
                   start=proposal.decision_at,
                   end=proposal.decision_at + window)
    verdict  = grade(baseline, realized)
    confidence = bootstrap_confidence(baseline, realized) if n_trades >= 30 else null
    write proposal_outcomes row
    if verdict == "regressed" and proposal.decision == "PROMOTED":
        webhook_alert("promoted_proposal_regressed", proposal_id)
```

### 6.6 Generator feedback loop

```python
# In SelfImprovementService.generate_proposals
history_stats = outcome_history_service.batting_average(
    proposal_type=T, target_component=C, min_observations=10
)
if history_stats.n >= 10:
    if history_stats.success_rate < 0.20:
        skip  # never emit this (T, C) combo again until a diversity-floor month
    elif history_stats.success_rate < 0.40:
        confidence_score *= 0.8
    elif history_stats.success_rate >= 0.60:
        confidence_score *= 1.2
# Diversity floor: each proposal TYPE gets >=1 emission per calendar month
# regardless of success rate (prevents exploration collapse)
```

### 6.7 Feature flag
`APIS_PROPOSAL_OUTCOME_LEDGER_ENABLED` — default **OFF**.

**When OFF:** The table is written (data collection only), but the generator does **not** consult batting averages. This lets us accumulate data for weeks before any behavior is influenced.

**When ON (operator decision after ≥4 weeks of data):** The generator consults batting averages; behavior may change on `generate_proposals` calls.

### 6.8 Test plan
- Unit: `ProposalOutcomeLedgerService.write_decision` round-trips a row.
- Unit: `run_proposal_outcome_assessment` with synthetic data produces expected verdict for each of `improved / unchanged / regressed / inconclusive`.
- Unit: per-type window lookup correctly routes to 45/30/14/60 based on proposal type.
- Unit: unknown proposal type falls through to `_DEFAULT = 30`.
- Unit: flag OFF → generator behavior matches pre-Step-6 byte-for-byte.
- Unit: flag ON + synthetic history with success_rate=0.15 → that proposal type skipped.
- Unit: diversity floor — 31 days since last `HOLDING_PERIOD_RULE` proposal → one is emitted regardless of stats.
- Integration: run 1 job iteration against a seeded DB; assert rows created with correct windows.

### 6.9 Paper bake
4 weeks of **data collection only** (flag OFF) before considering flipping ON.

### 6.10 Rollback
Flip flag to false. Data stays (it's only informational). Table can be truncated if operator wants.

### 6.11 Acceptance criteria
- Migration up/down clean.
- Daily job runs for 7 consecutive days without errors.
- Dashboard renders batting-average table with data for ≥1 proposal type.
- Flag-OFF vs pre-Step-6: zero diff in generator behavior on a seeded replay.

---

## Step 7 — Shadow-Portfolio Scorer (Rec 11, DEC-034 scope)

### 7.1 Scope
The biggest single item. Keeps rejected ideas alive in virtual P&L so the system can see whether its rejections are right. Per **DEC-034**, this **also** includes parallel alternative-rebalance-weighting shadows (equal / score / score_invvol) to provide A/B evidence for Step 4 without waiting for walk-forward.

### 7.2 Scope — what gets shadowed

1. **Every REJECTED action** (composite filter miss, risk-gate rejection, etc.).
2. **Every `"watch"`-tier ranked opportunity** with composite in [0.55, 0.65] (borderline names).
3. **Every stopped-out position** — virtual-continue holding until natural thesis resolution (max_age hit or larger move).
4. **(DEC-034)** Parallel alternative-rebalance-weighting portfolios running with `equal`, `score`, `score_invvol` simultaneously on the same live universe.

### 7.3 Files touched

| File | Change |
|------|--------|
| `apis/db/models/shadow_position.py` (**new**) | `shadow_positions` table. |
| `apis/db/models/shadow_trade.py` (**new**) | `shadow_trades` table. |
| `apis/db/models/shadow_portfolio.py` (**new**) | `shadow_portfolios` table (supports multiple named shadows: `rejected_actions`, `watch_tier`, `stopped_out_continued`, `rebalance_equal`, `rebalance_score`, `rebalance_score_invvol`). |
| `alembic/versions/xxxxx_add_shadow_portfolios.py` (**new**) | All three tables + indexes. |
| `apis/services/shadow_portfolio/service.py` (**new**) | `ShadowPortfolioService` API matching `PortfolioEngineService` shape. |
| `apis/workers/paper_trading.py` (step 12→13) | Hooks to push virtual entries into ShadowPortfolioService after risk validation, before execution. |
| `apis/workers/jobs/shadow_performance_assessment.py` (**new**) | Weekly job; emits `GATE_LOOSEN` proposals when rejection-reason buckets underperform. |
| `apis/services/self_improvement/service.py` | Add new proposal type `GATE_LOOSEN` to enum; wire shadow-derived evidence source. |
| `apis/api/routes/dashboard.py` | Add `/dashboard/shadow_portfolios` — per-shadow P&L vs live, by bucket. |
| `apis/config/settings.py` | `APIS_SHADOW_PORTFOLIO_ENABLED: bool = False` + `APIS_SHADOW_REBALANCE_MODES: List[str] = ["equal","score","score_invvol"]`. |

### 7.4 DB schema (shadow_portfolios)

```sql
CREATE TABLE shadow_portfolios (
    id             SERIAL PRIMARY KEY,
    name           VARCHAR(64) UNIQUE NOT NULL,    -- rejected_actions | watch_tier | stopped_out | rebalance_equal | ...
    starting_cash  NUMERIC(14,2) NOT NULL DEFAULT 100000,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE shadow_positions (
    id                  SERIAL PRIMARY KEY,
    shadow_portfolio_id INTEGER REFERENCES shadow_portfolios(id),
    ticker              VARCHAR(16),
    shares              NUMERIC(14,4),
    avg_cost            NUMERIC(14,4),
    opened_at           TIMESTAMPTZ,
    opened_source       VARCHAR(64),   -- which rejection reason / which weighting mode originated this
    UNIQUE(shadow_portfolio_id, ticker)
);

CREATE TABLE shadow_trades (
    id                  SERIAL PRIMARY KEY,
    shadow_portfolio_id INTEGER REFERENCES shadow_portfolios(id),
    ticker              VARCHAR(16),
    action              VARCHAR(10),
    shares              NUMERIC(14,4),
    price               NUMERIC(14,4),
    executed_at         TIMESTAMPTZ,
    realized_pnl        NUMERIC(14,2),
    rejection_reason    VARCHAR(64),   -- null for rebalance-mode shadows
    weighting_mode      VARCHAR(32),   -- null for rejection/watch/stopped-out shadows
    INDEX(shadow_portfolio_id, executed_at)
);
```

### 7.5 Shadow integration points in `run_paper_trading_cycle`

**Per review §6.3 and DEC-034 — three hook points:**

1. **After risk validation, before execution** (paper_trading.py step 12 → 13):
   - For every `RiskValidationResult.status == "rejected"`, push virtual entry into `rejected_actions` shadow at current price.
   - For every opportunity with composite in [0.55, 0.65], push virtual entry into `watch_tier` shadow.

2. **In exit evaluator** — when a position is stopped out:
   - Push virtual-continue entry into `stopped_out_continued` shadow; virtual-close at max_age or at 1.5× original stop distance breach.

3. **In rebalancing engine** — run allocator three times in parallel:
   - `equal` mode → push virtual orders into `rebalance_equal` shadow.
   - `score` mode → push virtual orders into `rebalance_score` shadow.
   - `score_invvol` mode → push virtual orders into `rebalance_score_invvol` shadow.
   - Live portfolio still uses whichever mode `APIS_REBALANCE_WEIGHTING_METHOD` dictates (Step 4's flag).

**All shadows apply the same risk gates as the live portfolio** — they're "what if these rejected actions had happened within all the existing limits," not "what if we had no limits."

### 7.6 Weekly job `run_shadow_performance_assessment` (Sunday 19:00 ET)

**Pseudocode:**
```
for shadow in shadow_portfolios:
    live_pnl_matched, shadow_pnl = align_matched_windows(shadow)
    delta, p_value = paired_bootstrap(live_pnl_matched, shadow_pnl, n_boot=10000)
    if p_value < 0.1 and observations >= 30:
        emit_improvement_proposal(
            type="GATE_LOOSEN" if shadow.name in REJECTION_SHADOWS else "ALLOCATOR_CHANGE",
            target_component=shadow.rejection_reason or shadow.weighting_mode,
            evidence=delta,
            confidence_score=bootstrap_confidence,
        )
```

### 7.7 Feature flag
`APIS_SHADOW_PORTFOLIO_ENABLED` — default **OFF**.

**When OFF:** Shadow tables exist; no writes happen; no weekly job runs.

**When ON (operator decision after Step 6 is stable):** All hooks active.

### 7.8 Test plan
- Unit: `ShadowPortfolioService.place_virtual_order` round-trips position + trade rows.
- Unit: Virtual mark-to-market on a synthetic price move produces expected shadow P&L.
- Unit: Weekly assessment with synthetic data → emits `GATE_LOOSEN` proposal above threshold, skips below.
- Unit: Parallel rebalance shadows — the three modes produce materially different shadow positions (sanity check).
- Integration: Replay Phase 65 rejected-action data → `rejected_actions` shadow shows >0 virtual trades.
- Integration: Flag OFF → shadow tables receive zero writes.

### 7.9 Paper bake
4 weeks of data collection. No live behavior change.

### 7.10 Rollback
Flip flag to false. Shadow data stays but doesn't grow. Tables can be truncated.

### 7.11 Acceptance criteria
- Weekly job runs 4 consecutive Sundays without errors.
- Dashboard renders shadow P&L vs live for each bucket.
- At least one `GATE_LOOSEN` or `ALLOCATOR_CHANGE` proposal emitted (or explicit "no significant divergence" log).
- Zero impact on live paper portfolio P&L / position count vs a pre-Step-7 replay.

---

## Step 8 — Thompson-Sampling Strategy-Weight Bandit (Rec 12)

### 8.1 Scope
Replace the static equal-weight fallback in `RankingEngineService._combine_signals` with a Thompson-sampling bandit. Per-strategy weights are learned from closed-trade outcomes, with floors and ceilings preserving diversity.

### 8.2 Files touched

| File | Change |
|------|--------|
| `apis/services/strategy_bandit/service.py` (**new**) | `StrategyBanditService` — `(α, β)` state per strategy, `sample_weights() -> Dict[str, float]`. |
| `apis/db/models/strategy_bandit_state.py` (**new**) | Persistence of `(α, β)` tuples. |
| `alembic/versions/xxxxx_add_strategy_bandit_state.py` (**new**) | Table. |
| `apis/services/ranking_engine/service.py` | `_combine_signals` accepts weights dict (already does); bandit's weights are the source when flag ON. |
| `apis/services/closed_trade_service/service.py` | Add hook: on closed trade, update bandit `(α, β)` based on origin strategies + P&L sign. |
| `apis/config/settings.py` | Add flag + bandit params. |

### 8.3 Bandit state table

```sql
CREATE TABLE strategy_bandit_state (
    strategy_family  VARCHAR(32) PRIMARY KEY,
    alpha            NUMERIC(10,4) NOT NULL DEFAULT 1.0,
    beta             NUMERIC(10,4) NOT NULL DEFAULT 1.0,
    wins             INTEGER NOT NULL DEFAULT 0,
    losses           INTEGER NOT NULL DEFAULT 0,
    last_updated     TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

### 8.4 Algorithm (per review §6.4)

**State update** on closed trade `t`:
```
for strategy in t.top_3_contributing_strategies:
    if t.realized_pnl > 0: strategy.alpha += 1
    else:                  strategy.beta  += 1
```

**Weight sampling** every N cycles (default 10):
```
samples   = [Beta(α_i, β_i).sample() for i in strategies]
weights   = samples / sum(samples)
smoothed  = λ × weights + (1-λ) × baseline_weights    # λ default 0.3
clamped   = clip(smoothed, per-strategy floor=0.05, ceiling=0.40)
final     = clamped / sum(clamped)
```

### 8.5 Settings
```python
APIS_STRATEGY_BANDIT_ENABLED: bool = False
APIS_STRATEGY_BANDIT_SMOOTHING_LAMBDA: float = 0.3
APIS_STRATEGY_BANDIT_MIN_WEIGHT: float = 0.05
APIS_STRATEGY_BANDIT_MAX_WEIGHT: float = 0.40
APIS_STRATEGY_BANDIT_RESAMPLE_EVERY_N_CYCLES: int = 10
```

### 8.6 RESEARCH-mode shadow first
Per review §6.4 safeguards: the bandit state updates from live closed trades even when flag is OFF. After 2–4 weeks of accumulated state, operator can flip the flag ON in PAPER. This means Step 8's code lands but the flag stays OFF until the `(α, β)` priors have real shape.

### 8.7 Test plan
- Unit: `StrategyBanditService.update_on_closed_trade` correctly increments α/β for contributing strategies.
- Unit: `sample_weights()` returns normalized weights summing to 1.
- Unit: Weight floor and ceiling bind when samples are extreme.
- Unit: Flag OFF → ranking engine uses baseline weights regardless of bandit state.
- Unit: Flag ON + cycle index not divisible by N → reuse last cached weights.
- Integration: Seed 50 synthetic closed trades; observe weights converge toward strategies with higher win rate within clamps.

### 8.8 Paper bake
2 weeks in RESEARCH-mode shadow (flag OFF, state accumulates). Then 2 weeks in PAPER with flag ON.

### 8.9 Rollback
Flip flag to false. Ranking reverts to baseline weights. Bandit state preserved for future re-enable.

### 8.10 Acceptance criteria
- Unit tests green.
- 4-week bake (2 RESEARCH + 2 PAPER): per-strategy weights show non-trivial divergence from baseline (evidence the bandit is learning) without any strategy pinned at its floor or ceiling for >50% of samples.
- No material increase in realized drawdown vs Step-7 baseline.

---

## Cross-Cutting Concerns

### C.1 Observability
Every step adds one line to the existing worker startup log reporting its flag state. Every new webhook alert uses the existing webhook infrastructure (`apis/services/alerting/webhook.py`). No new observability stack is introduced.

### C.2 DB migrations
Steps 2, 5, 6, 7, 8 each add one migration. All must be reversible. Run `alembic upgrade head && alembic downgrade -1 && alembic upgrade head` as a smoke test before each migration PR merges.

### C.3 Configuration audit
At the end of Step 8, `config/settings.py` has grown by ~20 new fields. Add an audit doc `APIS_SETTINGS_CATALOG.md` listing every `APIS_*_ENABLED` flag, its default, its purpose, and which step introduced it.

### C.4 Feature-flag sunset policy
After a step has been ON in PAPER for ≥4 weeks with green acceptance criteria, operator may:
- Leave flag in place (continues to gate rollbacks).
- Or, if code complexity from the flag branch is undesired, retire the flag and delete the legacy branch — **only after** explicit DEC entry documenting the retirement.

### C.5 What this plan **does not** cover (explicit deferrals)
- **Walk-forward / OOS harness** — deferred per DEC-031. Survivorship-free data acquisition (Apr-14 Phase A/B) also deferred. Both to be re-planned after Step 8 lands. The Shadow Portfolio data from Step 7 is expected to substantially inform the OOS work when it resumes.
- **Mean-reversion strategy** — deferred per Apr-14 review; depends on Step 5's ATR stops landing first (review §9).
- **InsiderFlow strategy wiring** — deferred per DEC-023 (ToS review outstanding).
- **Phase 66 AI tilt magnitude** — preserved as operator bet per DEC-032.

### C.6 Optional appendix (if operator approves)
If you want, I can add **Appendix A: OOS / Survivorship-Free Data Follow-On** that takes the Apr-14 plan's Phases A/B and re-sequences them to land after Step 8. That would be a ~2-page addendum. Not included in this plan unless you greenlight it.

---

## Per-Step Approval Checkpoint

Before starting any code on step N, operator confirms:
1. Step N-1 is green on all acceptance criteria.
2. Step N's feature flags and defaults are acceptable.
3. Step N's DB migration (if any) has been reviewed.
4. Step N's paper-bake duration is acceptable.

Any operator-requested changes reopen this document as a revision, not as an ad-hoc change during implementation.

---

## Summary Table — All Feature Flags Introduced

| Flag | Default | Introduced in | Purpose |
|---|---|---|---|
| `APIS_BROKER_HEALTH_INVARIANT_ENABLED` | ON | Step 2 | Phase 63-class safety invariant |
| `APIS_ACTION_CONFLICT_DETECTOR_ENABLED` | ON | Step 2 | Phase 65-class safety invariant |
| `APIS_LOWER_BUY_THRESHOLD_ENABLED` | OFF | Step 3 | 0.65 → 0.55 |
| `APIS_CONDITIONAL_RANKING_MIN_ENABLED` | OFF | Step 3 | 0.30 → 0.20 for held-with-positive-history |
| `APIS_SCORE_WEIGHTED_REBALANCE_ENABLED` | OFF | Step 4 | Score-weighted allocation |
| `APIS_REBALANCE_WEIGHTING_METHOD` | `equal` | Step 4 | Allocation mode literal |
| `APIS_ATR_STOPS_ENABLED` | OFF | Step 5 | Per-family ATR stops + max-age |
| `APIS_PORTFOLIO_FIT_SIZING_ENABLED` | OFF | Step 5 | Promote fit score into sizing |
| `APIS_PROPOSAL_OUTCOME_LEDGER_ENABLED` | OFF | Step 6 | Meta-learning feedback to generator |
| `APIS_SHADOW_PORTFOLIO_ENABLED` | OFF | Step 7 | Virtual P&L for rejections + watch + stopped-out + parallel weightings (DEC-034) |
| `APIS_STRATEGY_BANDIT_ENABLED` | OFF | Step 8 | Thompson-sampling weights |

**Every trading-behavior change is OFF by default.** Safety invariants (broker health, action conflict) are ON by default because they are protective-only.

---

## Appendix A — Post-Step-8 Follow-On: OOS Harness + Survivorship-Free Data

This appendix is a **pointer, not a re-plan**. The authoritative design for Phase A (point-in-time / survivorship-free universe) and Phase B (walk-forward / OOS harness) remains `APIS_IMPLEMENTATION_PLAN_2026-04-14.md`. This section only documents how those two Apr-14 phases re-sequence *after* Step 8 of the current plan and how the artifacts built in Steps 6–7 feed them.

### A.1 Sequencing (post-Step-8, roughly Q3–Q4 2026)

| Step | Source | Est. time | Depends on |
|------|--------|-----------|-----------|
| 9 | Apr-14 Phase A — Survivorship-free universe + point-in-time adjustments | ~3 wk | Step 8 green in PAPER |
| 10 | Apr-14 Phase B — Walk-forward / OOS harness | ~4 wk | Step 9 |
| 11 | Apr-14 Phase F — Mean-reversion strategy family (was blocked on Phase B + Step 5 ATR stops) | ~2 wk | Steps 5, 10 |

The Apr-14 plan's Phases C (universe expansion) and D (score-weighted rebalance) are already absorbed by the current plan (Phase C landed in Phase 66, Phase D is Step 4). Apr-14 Phase E (ATR stops) is Step 5. So the Apr-14 plan reduces to A + B + F for the post-Step-8 work.

### A.2 How Steps 6–7 artifacts feed the OOS work

- **Proposal Outcome Ledger (Step 6)** provides 3–6 months of verdict-tagged proposal history by the time Step 10 begins. That's the ground truth set against which the walk-forward harness can calibrate its grading function — no need to hand-label a training set.
- **Shadow-Portfolio Scorer (Step 7)** is the de-facto OOS sandbox for the current live universe. When Step 10 introduces survivorship-free historical data, the existing shadow infrastructure (`ShadowPortfolioService`, `shadow_positions`, `shadow_trades`) is reusable with a historical price-feed adapter instead of a live one. This cuts Step 10's scope materially: instead of building a separate OOS harness, it's "swap the price feed, extend the bucket taxonomy."
- **Parallel rebalance-weighting shadows (DEC-034)** are the first-pass A/B evidence for `score` vs `score_invvol` vs `equal`. Step 10 upgrades that to walk-forward evidence. If the shadow A/B is already decisive by then, Step 10 can focus on the harder questions (regime classifier validation, stop-param search) rather than re-litigating allocation.

### A.3 Known unknowns to revisit at post-Step-8 replanning

- **Data vendor choice** for survivorship-free pricing — CRSP vs Norgate vs Polygon-plus-manual-adjustments. Apr-14 plan leaned Norgate; price quotes and ToS terms may have shifted by the time we're ready.
- **Walk-forward window sizes** — Apr-14 plan specified 24-month train / 6-month test rolling. Revisit in light of whatever the shadow-portfolio data shows about how quickly strategy edge decays.
- **Live-money readiness gate additions** — the readiness gate (Phase 51) should probably grow an "OOS pass required" clause once Step 10 lands. Defer the exact formulation until Step 10 design.

### A.4 What *is not* in this appendix

- No file-path-level plan, no feature flag names, no test-plan detail. Those land in a fresh execution plan after Step 8 completes, because (a) the codebase will have shifted by then, (b) the Apr-14 plan is the authoritative design and I don't want to create drift, (c) estimating specifics 3 months out is false precision.

### A.5 Status

Deferred until Step 8 (Thompson bandit) is green on all acceptance criteria. At that point, open a new planning doc `APIS_OOS_EXECUTION_PLAN_YYYY-MM-DD.md` that takes this appendix as its scope frame.

---

Awaiting operator approval to begin Step 1.
