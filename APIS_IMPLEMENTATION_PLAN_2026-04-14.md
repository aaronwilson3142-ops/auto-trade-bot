# APIS — Implementation Plan: Top P&L Fixes + Safer Trade-Count Expansion

**Date:** 2026-04-14
**Source:** APIS_INDEPENDENT_REVIEW_2026-04-14.md
**Scope:** 6 work items across two tracks — (A) close the real-money P&L gap, (B) safely increase trade frequency.

---

## 0. Principles and Rules of Engagement

- **Do no harm to live paper.** Every change ships behind a feature flag (`APIS_*_ENABLED` env var) and defaults to OFF. Promote only after green gate.
- **Every change gets a walk-forward check** once Phase A is in place — no exceptions, including this plan's own tuning.
- **Record decisions in `state/DECISION_LOG.md`** as DEC-024..DEC-030.
- **Session-handoff discipline per `03_SESSION_CONTINUITY_AND_EXECUTION_PROTOCOL.md`.**
- **Reset paper bake clock to 0 on each landed phase** — per §6 of the review, you need ≥60 days on the *final* code before live consideration.
- **Treat the review doc as a scorecard.** Each phase lists the review-section it closes.

---

## 1. Phased Sequencing

Dependencies matter. Order is not negotiable:

```
Phase A → Phase B → Phase C → Phase D → Phase E → Phase F
(data)    (OOS)     (safe     (score    (stops    (mean
                    expand)    size)    widen)    rev)
```

- Phase A must land first because walk-forward (B) requires survivorship-free data.
- Universe expansion (C) must precede score-weighted sizing (D), because equal-weighting is fine on 10 names but score-weighting is meaningful only when the feasible set is large.
- Stop widening (E) is a parameter change best validated against the walk-forward harness from (B).
- Mean-reversion (F) is strictly additive and should not be merged before (B) exists to measure it.

Estimated wall-clock: **8–12 weeks** with part-time work, **4–6 weeks** full-time.

---

## Phase A — Survivorship-Free Data (Review §3.2)

**Goal:** Stop letting yfinance silently drop delisted names and corrupt every backtest.

### Deliverables
1. New adapter: `apis/services/data_ingestion/adapters/pointintime_adapter.py`
2. Data-source toggle in `config/settings.py`: `APIS_DATA_SOURCE={yfinance|pointintime}`
3. Schema additions in `apis/services/data_ingestion/models.py`:
   - `securities.first_listed_date`
   - `securities.delisting_date`
   - `securities.delisting_reason` (acquisition|bankruptcy|merger|other)
   - `securities.delisting_price`
4. Migration: `alembic/versions/XXXX_delisting_fields.py`
5. Backtest engine patch (`apis/services/backtest/engine.py`): on any trade date after `delisting_date`, force-close position at `delisting_price`, record realized loss, prevent new opens.
6. Seed script: `apis/scripts/seed_delisting_data.py` — load delisting records from chosen data source.

### Data source options (pick in Decision-Log)
- **Norgate Data Platinum** (~$65/mo) — cleanest for US equities, trivial Python API. *Recommended.*
- **CRSP** via WRDS — gold standard, typically academic/institutional pricing.
- **OpenBB / Financial Modeling Prep** — cheaper, quality varies.
- **Self-curated** (scrape Wikipedia S&P 500 changes + SEC Form 25 filings) — free, labor-heavy, not recommended.

### Acceptance criteria
- [ ] Run a backtest from 2020-01-01 to 2025-12-31 with and without delisting adjustment. Difference in annualized return ≥ 50 bps — proves the fix is doing something.
- [ ] No code path in backtest engine references yfinance directly when `APIS_DATA_SOURCE=pointintime`.
- [ ] Unit tests: delisting mid-hold forces close; delisting before open blocks new open.

### Effort
1.5–2 weeks (most of the time is data plumbing, not modeling).

### Risks
- Paid data subscription required — get Aaron's approval before commit.
- Historical data vendor API shapes differ from yfinance — keep the adapter interface identical.

---

## Phase B — Walk-Forward / OOS Validation Harness (Review §3.1)

**Goal:** No parameter ever gets promoted again without surviving out-of-sample.

### Deliverables
1. New module: `apis/services/backtest/walkforward.py`
   - `AnchoredWalkForward` class: configurable train/test window splits
   - `ExpandingWindow` variant
   - Metrics: per-fold Sharpe, Sortino, max DD, Calmar, hit rate, turnover, p-value of Sharpe vs zero (bootstrap)
2. CLI entry point: `apis/scripts/run_walkforward.py`
   ```
   python -m apis.scripts.run_walkforward \
     --start 2018-01-01 --end 2025-12-31 \
     --train-years 3 --test-years 1 --step-years 1 \
     --config config/walkforward_defaults.yaml
   ```
3. Integration with self-improvement:
   - `apis/services/self_improvement/service.py` — promotion gate now requires:
     - Candidate beats baseline in aggregate across folds, AND
     - Candidate beats baseline on ≥60% of individual folds, AND
     - Paired bootstrap p < 0.10 on per-fold Sharpe differences
4. New config file: `config/walkforward_defaults.yaml` — canonical folds for reproducibility.
5. Nightly CI job (added to `infra/docker/docker-compose.yml`): run walk-forward against current live config once per week, alert on Sharpe regression.

### Acceptance criteria
- [ ] Walk-forward on *current* config produces a documented baseline Sharpe + DD per fold. (Spoiler: expect disappointment — that's the point.)
- [ ] Self-improvement promotion rate drops noticeably (a noise filter working).
- [ ] Any parameter change submitted via self-improvement that passes old gates but fails walk-forward is blocked and logged.

### Effort
2–3 weeks. The harness is moderate; the *honest* interpretation of results is the hard part.

### Risks
- Existing parameters may fail walk-forward. That's a feature, not a bug — but it means you may need to retune before live, which delays the readiness clock.
- Compute cost: a full walk-forward is ~N× a single backtest. Cache feature computations.

---

## Phase C — Universe Expansion 62 → 300+ (Review §3.8, §5)

**Goal:** Biggest single "trade more without losing edge" lever. Risk engine's existing concentration caps will absorb the complexity.

### Deliverables
1. Replace `apis/config/universe.py` hardcoded list with a dynamic loader:
   - Source: S&P 500 historical constituents (from Phase A data source)
   - Liquidity floor: 20-day ADV ≥ $20M (configurable via `APIS_MIN_ADV_USD`)
   - Price floor: close ≥ $10 (configurable)
2. `TICKER_SECTOR` and `TICKER_THEME` dicts → generated, not hardcoded. Pull GICS sector from data source; theme mapping keeps current manual overlay for AI/semis/defense/power.
3. New nightly job in `apis/apps/worker/jobs/universe_refresh.py`:
   - Rebuild universe at 04:00 ET
   - Handle additions/deletions gracefully (close positions in removed names)
4. Bump `max_positions` 10 → 15 (via config, not hardcode).
5. Bump `max_new_positions_per_day` 3 → 5.

### Acceptance criteria
- [ ] Feasible universe on any trading day ≥ 300 names.
- [ ] Walk-forward (Phase B) shows Sharpe does not *decrease* with larger universe. (Expected: it improves; if it worsens, rankings are overfit — escalate.)
- [ ] Risk engine still blocks all concentration breaches correctly (add unit test with 500-name universe).
- [ ] Paper bake 2 full trading weeks with zero unhandled exceptions.

### Effort
1 week.

### Risks
- More names = more data fetches. Pre-warm feature store cache.
- InsiderFlow scaffold touches universe shape — leave InsiderFlow disabled during this rollout.

---

## Phase D — Score-Weighted Rebalancing (Review §3.3)

**Goal:** Stop throwing away the ranking information. Concentrate capital where conviction is highest.

### Deliverables
1. Patch `apis/services/risk_engine/rebalancing.py:72–91`:
   - Replace `weight = 1/N` with:
     ```python
     # normalize composite scores to sum to 1, with floor
     scores = np.maximum(composite_scores - min_score, 0.01)
     target_weights = scores / scores.sum()
     # optional: blend with inverse-vol
     if APIS_USE_INVERSE_VOL_OVERLAY:
         iv = 1 / realized_vol_20d
         target_weights = target_weights * iv / (target_weights * iv).sum()
     # cap any single name at max_single_name_pct
     target_weights = np.minimum(target_weights, cfg.max_single_name_pct)
     target_weights /= target_weights.sum()
     ```
2. New settings:
   - `APIS_REBALANCE_WEIGHTING_METHOD={equal|score|score_invvol}` (default: `score`)
   - `APIS_REBALANCE_MIN_WEIGHT` (default 0.02 — prevents near-zero allocations)
3. Keep `equal` as fallback, feature-flagged for A/B comparison.

### Acceptance criteria
- [ ] Walk-forward shows score-weighted ≥ equal-weight on both aggregate Sharpe and ≥50% of folds (otherwise you have a ranking quality issue, not a sizing issue — STOP and investigate).
- [ ] Highest-scored name gets ≥2× the weight of the lowest, on average.
- [ ] Concentration caps still bind and are never breached.

### Effort
3–5 days (plus walk-forward analysis time).

### Risks
- If your ranking is noisy (it may be, per Phase B findings), score-weighting *amplifies* that noise. This is why Phase B comes first.

---

## Phase E — Horizon-Aware Stops & Max Age (Review §3.5, §5)

**Goal:** Stop whipsawing out of good theses. Counter-intuitively increases net trade count because capital stops churning.

### Deliverables
1. Refactor stop-loss logic in `apis/services/risk_engine/service.py` and `apis/services/portfolio_engine/service.py` to be **per-strategy-family**, not global:
   ```yaml
   strategy_horizons:
     momentum:        { stop_loss_pct: 0.12, max_age_days: 60, trailing_stop_pct: 0.08 }
     theme_alignment: { stop_loss_pct: 0.12, max_age_days: 60, trailing_stop_pct: 0.08 }
     macro_tailwind:  { stop_loss_pct: 0.08, max_age_days: 20, trailing_stop_pct: 0.05 }
     sentiment:       { stop_loss_pct: 0.08, max_age_days: 15, trailing_stop_pct: 0.05 }
     value:           { stop_loss_pct: 0.15, max_age_days: 90, trailing_stop_pct: 0.10 }
     mean_reversion:  { stop_loss_pct: 0.04, max_age_days: 7,  trailing_stop_pct: 0.02 }
   ```
2. Track the *originating strategy* on each position (add `positions.origin_strategy` column + migration).
3. When a position is held by multiple strategies (common case), use the *widest* stop and *longest* max age — let the most patient strategy govern the exit.
4. Optional: ATR-based stops (stop = `N × 20-day ATR`, N configurable per family) instead of fixed percent.

### Acceptance criteria
- [ ] Walk-forward shows reduced stop-out rate AND non-decreasing Sharpe.
- [ ] Average holding period on momentum/theme positions increases from ~15 days to ~30–45 days.
- [ ] Trade count does not decrease (the thesis is that capital-turnover *increases* because you stop recycling into the same names).

### Effort
1 week.

### Risks
- If the walk-forward shows Sharpe *drops* with wider stops, that's a red flag that your entries are only short-horizon profitable — escalate.

---

## Phase F — Add Mean-Reversion Strategy (Review §3.9, §5)

**Goal:** Genuinely independent edge, anti-correlated with momentum. 3–10× the trade frequency. Pulls portfolio Sharpe up even if individually modest.

### Deliverables
1. New strategy: `apis/services/signal_engine/strategies/mean_reversion.py`
   - Universe filter: names with positive 6-month total return (*only buy dips in uptrends* — this is the key to avoiding catching falling knives)
   - Entry signal: 5-day RSI < 30 AND close within 1 ATR of 20-day lower Bollinger band AND volume not spiking (avoid news-driven drops)
   - Exit: revert to 20-day mean OR 5-day RSI > 55 OR max_age_days: 7
   - `signal_score` output normalized to [0, 1] like other strategies
2. Register in strategy pipeline at `apis/services/signal_engine/strategies/__init__.py`.
3. Risk budget: 20–30% of total portfolio risk initially. Implement via per-strategy notional cap in `config/settings.py`:
   - `APIS_MEAN_REVERSION_MAX_PORTFOLIO_PCT=0.25`
4. Horizon config from Phase E already in place for mean_reversion family.
5. Feature-flag: `APIS_MEAN_REVERSION_ENABLED=false` by default.

### Acceptance criteria
- [ ] 24-month walk-forward shows mean-rev Sharpe ≥ 0.3 standalone (low bar — it's a diversifier, not a hero).
- [ ] Correlation of mean-rev monthly returns to existing composite ≤ 0.3.
- [ ] Combined portfolio Sharpe > existing Sharpe on ≥ 60% of walk-forward folds.
- [ ] Trade count increases measurably (target: 2–3× current cycle trade count).
- [ ] Paper bake 4 weeks flag-on with no risk-engine breaches.

### Effort
2 weeks.

### Risks
- Mean reversion failed catastrophically in 2020 and 2022 selloffs. The "only in uptrends" filter is essential — don't skip it.
- Short holding period means higher turnover → slippage costs matter more. Make sure Phase A's slippage model is in place before enabling this live.

---

## 2. Explicitly Out of Scope (For Now)

These came up in the review but are **not** in this plan:
- Tiered slippage model (Review §3.4) — important, but deserves its own focused phase after A-F. Tracked separately.
- Regime detection in sizing (Review §3.7) — already scaffolded (Phase 46); wiring it to sizing is a separate initiative.
- Options / crypto expansion.
- Alpaca live wiring — don't even think about it until A-F are landed and paper-baked 60+ days.

---

## 3. Per-Phase Workflow (Apply to A–F)

```
1. Branch: feature/phase-{X}-{name}
2. Write failing tests first (pytest under apis/tests/)
3. Implement behind feature flag, default OFF
4. Land PR with:
   - Code changes
   - Unit tests (≥60% coverage floor per DEC-015)
   - Decision Log entry DEC-NNN
   - Changelog entry
   - Updated ACTIVE_CONTEXT.md
5. Enable in paper via env var
6. Paper bake 2 weeks; monitor daily scorecard
7. Walk-forward check (once Phase B is live)
8. Operator sign-off → keep enabled
9. Reset the 60-day pre-live paper clock
```

---

## 4. Readiness Gate After All Six Phases Land

These are **additive** to the existing runbook gates, not replacements.

- [ ] 60+ days paper on the post-Phase-F code
- [ ] Walk-forward Sharpe ≥ 0.5 across ≥3 non-overlapping regime folds (2020 crash, 2022 bear, 2023–24 rally)
- [ ] Survivorship-corrected backtest Sharpe ≥ 0.5 (not just the yfinance-inflated number)
- [ ] Aggregate paper Sharpe vs SPY ≥ 0.5 with ≥ 40 closed trades
- [ ] Mean-rev / momentum portfolio correlation < 0.3 confirmed live
- [ ] Operator manually reviewed ≥ 100 live-paper trades in HUMAN_APPROVED mode
- [ ] Hard portfolio-level DD circuit breaker added (separate work item — flag it now)

Only after all green: consider `RESTRICTED_LIVE` at ≤10% of intended capital.

---

## 5. Decision Log Entries to Create (Before Coding)

- **DEC-024:** Data source — Norgate vs CRSP vs self-curated. Commit choice and budget before Phase A starts.
- **DEC-025:** Walk-forward config — fold size, step, metric, significance level. Commit before Phase B.
- **DEC-026:** Universe floor — ADV threshold, price threshold, source of truth. Commit before Phase C.
- **DEC-027:** Rebalance weighting method default. Commit before Phase D.
- **DEC-028:** Per-strategy horizon table authoritative location (settings.py vs YAML). Commit before Phase E.
- **DEC-029:** Mean-reversion risk budget + fail-safe conditions. Commit before Phase F.
- **DEC-030:** Re-baseline of paper-bake clock to 0 upon landing Phase F.

---

## 6. What Could Kill This Plan

- **Phase B reveals current edge is marginal or absent.** This is the likeliest ugly surprise. Response: pause expansion (C/D), shore up signal quality before adding more complexity.
- **Data-source budget not approved.** Fall back to self-curated S&P 500 change list — doable but adds ~1 week to Phase A.
- **Paper-bake failures.** Each phase requires 2 clean weeks before the next lands. A single restart incident resets the clock.

---

## 7. Locked Decisions (Resolved 2026-04-14)

Aaron delegated these calls to the reviewer. Rationale captured here; formal Decision Log entries DEC-024..030 to be written at the start of each phase.

### 7.1 Data source → **Norgate Data Platinum (~$65/month)**
- Rationale: self-curated free path burns 1–2 weeks of work and still has quality gaps on corporate actions. A $780/year subscription to fix the #2 P&L issue is the highest-ROI dollar spend on this project. Pays for itself in under a year on avoided backtest overestimation for any live account ≥ $10k.
- Action: purchase subscription at start of Phase A, log as DEC-024.
- Fallback if blocked: Wikipedia constituent history + SEC Form 25 scraper, add 1 week to Phase A.

### 7.2 Target live capital → **$50,000 target, $5,000 (10%) launch**
- Rationale: meaningful size for strategy math, survivable in a ruin scenario. At 15 positions ≈ $3.3k per name, well below 0.5% of ADV for any S&P 500 stock — no liquidity pressure.
- Implication: ADV floor $20M is comfortable; can relax to $10M later if universe needs widening.
- If real target differs materially (±5×), revisit universe/position-size design.

### 7.3 Walk-forward start date → **2015-01-01**
- Rationale: captures 7 distinct regimes (2015–16 commodity crash, 2017 melt-up, 2018 Q4 selloff, 2019 rally, 2020 COVID, 2022 bear, 2023–25 AI rally). Earlier dates dilute with pre-HFT/pre-ETF-flow market structure.
- Fold config: 3-year training, 1-year test, 1-year step → 8 folds covering 2018–2025.

### 7.4 Stops → **ATR-based, 2.5× 20-day ATR, with fixed-% clamps**
- Rationale: ATR normalizes across volatility regimes (AAPL ~20% vol vs mid-cap AI name ~50% vol require different stops). Fixed-% equalizes the wrong thing.
- Formula: `stop_distance = max(0.04, min(0.18, 2.5 * ATR_20 / price))`
- Trailing stops use same ATR multiplier but tighter floor (1.5× ATR).
- Per-strategy multipliers: mean-reversion uses 1.5× ATR (tighter), value uses 3.5× ATR (wider).

### 7.5 Accepting walk-forward may fail current params → **YES, accept it**
- Rationale: the only scientifically honest choice. Refusing would mean shipping in-sample-fit params — the exact failure mode that kills ~95% of retail strategies.
- Plan accommodation: add a **Phase B.5 — Retune** (0–2 weeks) between B and C, contingent on walk-forward findings. If Phase B shows current params pass OOS, B.5 is a no-op and schedule slips nothing. If they fail, retuning cost is baked in rather than discovered late.
- Philosophical commitment: a Sharpe number that drops after retuning is the **true** baseline. The old higher number was an illusion. Treat it that way.

---

## 8. Updated Sequencing With B.5

```
A (data, 1.5–2 wk)
  ↓
B (walk-forward harness, 2–3 wk)
  ↓
B.5 (retune if needed, 0–2 wk) ← NEW
  ↓
C (universe expand, 1 wk)
  ↓
D (score-weighted rebalance, ~1 wk)
  ↓
E (ATR stops + horizons, 1 wk)
  ↓
F (mean reversion, 2 wk)
```

Revised total: **9–13 weeks part-time, 5–7 weeks full-time.**

---

*Ready to start Phase A. First action: purchase Norgate subscription, write DEC-024.*
