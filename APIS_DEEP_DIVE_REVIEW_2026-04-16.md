# APIS — Deep-Dive Review & Recommendations

**Reviewer:** Claude (internal, for Aaron)
**Date:** 2026-04-16 (same day Phase 66 AI-bias tilt landed)
**Scope:** Architecture understanding, soundness/stability/efficiency improvements, decision-making upgrades, self-improvement engine expansion (meta-learning + shadow portfolios), trade-count expansion — all without adding rules that choke off good options.
**Out of scope (per operator direction 2026-04-16):** walk-forward / OOS harness and survivorship-free data acquisition. Those remain #1 and #2 P&L levers per the Apr-14 independent review and should still be revisited after the work in this document is landed.
**Operator bets preserved as-is:** the Phase 66 AI-heavy tilt (regime weights, theme multipliers, ranking bonus, `max_thematic_pct` 0.75) is treated as an operator-level thesis, not a bug.

---

## 1. Executive Summary

APIS is fundamentally one of the best-governed retail trading systems I've seen. The risk engine is a real gatekeeper, the self-improvement loop is gated the right way, and the execution layer survived a class of bugs (Phases 60–65) that kills most retail bots. What it lacks is not more rules — it lacks **memory and curiosity**. It doesn't remember whether its past proposals actually paid off, it doesn't keep rejected ideas alive to see if they would have worked, and it treats its strategy mix as a static constant rather than a portfolio of bets to be re-weighted. Those three gaps, addressed together, would let the system self-improve meaningfully without any new hard rules — and would arguably increase decision quality more than further parameter tuning would.

The top twelve concrete recommendations, ordered by impact-per-effort and grouped:

**Stability & correctness (land first, zero behavior change):**
1. Move six hard-coded thresholds into `config/settings.py` (the 0.65 buy cut, the 0.50 hit-rate rule, the −0.02 avg-loss rule, the AI ranking/theme bonus tables, and the rebalance-target freshness window).
2. Add a broker-adapter health-check on every cycle; fail loudly if `app_state.broker_adapter` got reset without a Position restore.
3. Add a rebalance/portfolio-action conflict-detection invariant test that runs in every cycle (Phase 65 bug was a data-shape mismatch that passed unit tests — this will catch the next one).
4. Idempotency key on `_persist_position_history` and `_persist_paper_cycle_count` (they're fire-and-forget today; a DB blip followed by a retry can double-write).

**Decision-making (raise signal-to-noise without new gates):**
5. Score-weighted rebalance allocator (keeps all gates intact; just replaces 1/N with normalized-composite within the existing per-name cap). This is the Apr-14 review's §3.3 but without needing walk-forward.
6. ATR-scaled stops and max-age, per strategy family. Today a single 7% / 20-day rule whipsaws you out of momentum theses in high-vol names. Framed correctly this *loosens* behavior (wider stops, longer runway for theses to work) rather than tightening it.
7. Promote the existing `portfolio_fit_score` to actually influence sizing. Today it's computed, logged, and not used.

**Self-improvement engine expansion (the main ask):**
8. **Proposal Outcome Ledger** — persist every promoted proposal, tag it with a measurable outcome window, and feed outcome statistics back into the proposal generator. *This is the foundation for meta-learning.*
9. **Shadow-portfolio scorer** — every REJECTED proposal, and every `"watch"`/near-miss ranked opportunity, is run through a virtual-P&L tracker. Rejected ideas earn their way back into consideration instead of being dropped forever.
10. **Thompson-sampling strategy-weight bandit** — replaces the static equal-weight fallback in `RankingEngineService._combine_signals`. Keeps strategies at their configured weights on average, but continuously probes under-weighted strategies with small exploration and shifts weight to winners *within the existing thematic/sector/position caps*.

**Trade-count expansion (that doesn't need OOS validation):**
11. Split the `recommended_action` gate from the sizing decision — currently the 0.65 buy threshold is a hard filter *and* implicitly the only way the rebalancer learns what's tradable. Lowering it 0.65 → 0.55 while keeping sizing score-weighted (Rec 5) produces more trades without lowering conviction on any individual name.
12. Widen the `ranking_min_composite_score` filter (0.30) only to `0.20`, and only *conditionally* — keep 0.30 for fresh new opens, allow 0.20 for adds/rebalances on names you already hold with a positive-grade closed-trade history in that ticker.

The detailed case for each follows.

---

## 2. What APIS Is — My Synthesis

### 2.1 Purpose and shape

APIS is a long-only, equity-only, disciplined portfolio *operating system* — not a trading bot. The distinction matters: the product surface is a daily scorecard, an audit trail, and a readiness report, and the strategy is (correctly) one replaceable component sitting inside that product. That framing is the single most mature decision the project has made. Most retail systems invert this and treat the strategy as the product, which is why most retail systems die when their one edge decays.

The staged rollout protocol (RESEARCH → PAPER → HUMAN_APPROVED → RESTRICTED_LIVE) and the code-level guard that prevents flipping live without the readiness gate are pro-grade. Keep them exactly as they are.

### 2.2 Pipeline as I now understand it

```
(1) Intel feed ingestion ──► policy signals + news insights
(2) Market data + fundamentals refresh ──► OHLCV + P/E, PEG, growth, surprise
(3) Feature store pipeline ──► 11+ baseline features + theme/macro/news overlays + fundamentals overlays
(4) Signal engine (5 strategies wired) ──► per-security, per-strategy SignalOutput[]
         strategies: Momentum · Theme · Macro · Sentiment · Valuation
         (InsiderFlow scaffolded, not wired)
(5) Ranking engine ──► composite score (40% signal + 20% conf + 20% liquidity − 20% risk + AI bonus)
                    ──► recommended_action: composite ≥ 0.65 = "buy", ≥ 0.45 = "watch", else "avoid"
                    ──► portfolio_fit_score (70% composite + 30% liquidity)  ← currently computed, unused
                    ──► sizing_hint_pct
(6) Portfolio engine ──► apply_ranked_opportunities: opens "buy"-tagged tickers, closes holdings not in buy_set
                      ──► compute_sizing: half-Kelly of composite score, min(half_kelly, sizing_hint, max_single_name_pct)
(7) Paper-trading cycle
    ├─ Phase 65 churn guard (suppress not_in_buy_set CLOSEs when rebalance target active)
    ├─ Phase 39 correlation-adjusted sizing
    ├─ Phase 40 sector exposure filter
    ├─ Phase 41 liquidity filter
    ├─ Phase 43 portfolio VaR gate
    ├─ Phase 44 stress-test gate
    ├─ Phase 45 earnings-proximity gate
    ├─ Phase 47 drawdown recovery mode (NORMAL/CAUTION/RECOVERY, size multiplier)
    ├─ Risk engine evaluate_exits: stop-loss → trailing stop → take-profit → age expiry → thesis invalidation
    ├─ Risk engine evaluate_trims: overconcentration TRIM
    ├─ Rebalancing engine: TRIM/OPEN from drift targets
    ├─ validate_action per action (9 hard gates)
    ├─ execute_approved_actions (idempotent orders, fill tracking)
    ├─ record closed trades + grade them (A/B/C/D/F)
    ├─ broker sync, fill reconciliation, position persistence
    └─ Phase 50/54 factor-exposure + factor-tilt alert
(8) Evaluation engine ──► daily scorecard (A/B/C/D/F) + attribution
(9) Self-improvement engine ──► proposals → evaluation → promotion → (auto-execute gated off by default)
```

This is a clean, well-separated architecture. The recommendations below do not change its shape; they either fill gaps (Proposal Outcome Ledger, Shadow Portfolios, Bandit) or tune existing nodes (sizing, stops, thresholds).

### 2.3 The tension I see in the current design

APIS has a **gatekeeper layer** (risk engine — disallows things) and an **optimizer layer** (ranking/sizing — picks best things) but only a very thin **explorer layer** (the self-improvement engine, which today only fires when grades are bad and only proposes four rule-based mutations). That asymmetry is why the system feels "rule-bound." The fix is not to loosen gates; it's to make the explorer layer richer so the system *earns* relaxations from evidence instead of having them hand-coded in.

---

## 3. Strengths to Preserve (Do Not Refactor These)

| Strength | Why it's rare | Keep exactly because |
|---|---|---|
| Hard-gatekeeper risk engine with 9 independent blocks | Most retail bots have one stop | Every path in `validate_action` is protective; changing any of them individually is easy and wrong. Treat this file as frozen unless a specific audit-trail case says otherwise. |
| Staged rollout + code-level live guard | Kevin Davey's "incubation period" incarnated in code | Do not lower the readiness bar. If anything, raise it per §9. |
| Three-gate self-improvement (master switch, observation floor, per-proposal confidence) | Most "auto-tuning" retail bots have none of these | The observation floor is at 10 today (Apr-14 review §3.6 argues for 50). Keep the three-gate *structure* and raise the floor — do not collapse gates. |
| Guardrail list (`PROTECTED_COMPONENTS`) | Prevents self-improvement from silently weakening safety | Already prevents proposals targeting `risk_engine`, `execution_engine`, `broker_adapter`, `capital_allocation`, `live_trading_permissions`. Do not expand auto-proposal scope *into* these. |
| Idempotent orders + fill reconciliation | Most retail bots lose money to duplicate/mis-routed orders | The Phase 60–62 fixes earned this. |
| Continuity discipline (state files + memory files + CHANGELOG + DECISION_LOG) | Unique to this project | Keeps me and future agents productive. Every recommendation below assumes this continues. |
| Half-Kelly sizing (score-aware at entry) | Most retail bots use fixed-dollar or fixed-percent | Full Kelly is psychologically untenable and assumes known edge. Half-Kelly is the right default. |
| Second-order theme logic (AI → power → cooling → networking → storage) | Differentiated vs "buy NVDA because AI" | Phase 66 amplifies this bet; the *mechanism* is sound even if the *size* of the tilt is a separate question. |
| Per-phase `state/CHANGELOG.md` + `DECISION_LOG.md` discipline | Makes debugging diagnostic rather than forensic | This is why Phases 60–65 could be fixed and documented at the speed they were. |

---

## 4. Stability & Efficiency Improvements (No Behavior Change)

These are the lowest-risk, highest-confidence items. They should land first because they make everything else below easier to evaluate.

### 4.1 Un-bury six hard-coded constants

The code has at least six decision-relevant magic numbers that are not in `config/settings.py`. Every one of them is a self-improvement target that the engine can never touch today because it can't see them. Move each to settings with a short `env`-overridable field and log their value at worker startup:

| Constant | Current location | Value | Why it matters |
|---|---|---|---|
| "buy" / "watch" / "avoid" thresholds | `ranking_engine/service.py:294–299` | 0.65 / 0.45 | Phase 65 memory notes the 0.65 cut makes the portfolio engine's ranking-based OPEN path effectively dead while the rebalancer is doing all opens. Making this configurable is prerequisite for Rec 11. |
| Low hit-rate threshold for SOURCE_WEIGHT proposal | `self_improvement/service.py:87` | 0.50 | The proposal generator's trigger. Should be a setting and eventually a function of the outcome ledger (Rec 8). |
| Avg-loss threshold for RANKING_THRESHOLD proposal | `self_improvement/service.py:105` | −0.02 (−2%) | Same argument. |
| `_AI_THEME_BONUS` multipliers | `strategies/theme_alignment.py:55–64` | 1.15–1.35× | Phase 66 operator bet. Config-driven makes it reversible without a code change. |
| `_AI_RANKING_BONUS` additive | `ranking_engine/service.py:40–50` | 0.03–0.08 | Same argument. |
| Rebalance target freshness window | (implicit, Phase 65 fix) | — | Phase 65 suppresses not_in_buy_set CLOSEs based on an active rebalance target; if that target is stale, the churn returns without warning. Define a TTL in settings and log it. |

**Impact:** zero P&L change on day one. Makes six future tunings trivial. Makes the Phase 66 tilt trivially reversible for A/B tests of Rec 9 (shadow portfolios).

**Effort:** ~1 day. Pure refactor.

### 4.2 Broker-adapter health invariant

Phase 65 persisted `app_state.broker_adapter` so positions survive across cycles. Phase 64 persists authoritative `Position` rows as the restore path. These are two independent bugs with two independent fixes, and nothing actively *checks* they agree.

Add at the top of `run_paper_trading_cycle`:
- If `app_state.broker_adapter is None` *and* any `Position` rows exist in DB → **fatal log + kill-switch on** (operator is required to diagnose why the adapter reset mid-flight).
- If broker adapter has positions that disagree with DB Position rows by more than 0.01 shares → **alert via webhook, continue with DB as source of truth**.

**Impact:** catches the next "adapter got reset" bug at the first cycle instead of at the first execution divergence. The Phase 63 phantom-cash incident would have fired this invariant.

**Effort:** ~2 hours. Easy to unit-test with a synthetic state.

### 4.3 Rebalance/portfolio-action conflict detector

The Phase 65 alternating-churn bug was a data-shape mismatch: `apply_ranked_opportunities` produced CLOSEs on tickers that `rebalancing_engine` was simultaneously producing OPENs for. The fix suppresses CLOSEs during active rebalance — correct, but brittle: if the two engines disagree in any *other* combination (e.g., rebalancer TRIM + portfolio OPEN of the same ticker same cycle), the invariant doesn't fire.

Add a post-merge invariant that walks the merged action list and asserts:
- No ticker has both an OPEN and a CLOSE in the same cycle.
- No ticker has a TRIM and an OPEN in the same cycle with conflicting directions.
- If an invariant violation is found, drop the lower-confidence action and fire a webhook alert.

**Impact:** makes the whole execution path self-healing against the next coupling bug.

**Effort:** ~0.5 day including tests.

### 4.4 Idempotency keys on fire-and-forget DB writers

`_persist_portfolio_snapshot`, `_persist_position_history`, `_persist_paper_cycle_count`, `_persist_evaluation_run` are all fire-and-forget. On a DB blip followed by APScheduler retry, any of them can double-write. For `_persist_paper_cycle_count` specifically that's dangerous because the cycle count feeds the readiness-gate math.

Use a natural idempotency key on each write (`(cycle_id, job_name)` is sufficient) and `ON CONFLICT DO NOTHING` on insert.

**Impact:** prevents a class of latent data-quality bugs that would make readiness decisions on wrong numbers.

**Effort:** ~1 day across four writers.

### 4.5 Kill the unused `portfolio_fit_score` computation or wire it up

`ranking_engine/service.py:289` computes `portfolio_fit_score = 0.7 × composite + 0.3 × liquidity` and returns it on the RankedResult. I cannot find any code path that uses it. Either:
- Delete the field and the computation (<10 min), **or**
- Use it as a secondary tiebreaker in sizing: when two candidates have similar composite, prefer the one with higher portfolio-fit. (It'd need a light behavioral test to confirm no regression.)

Right now it's pure technical debt.

**Effort:** 10 min to delete, ~0.5 day to promote to production sizing with tests.

---

## 5. Decision-Making Improvements (Raise Signal-to-Noise, Don't Add Gates)

### 5.1 Score-weighted rebalance allocator

This is the Apr-14 review's §3.3, ported so it doesn't require the walk-forward harness. The claim is narrow and verifiable without OOS: if the ranking score carries *any* information, and you're allocating 1/N across the top-15 anyway, then reallocating the same N slots by normalized score (with the existing per-name cap intact) is either neutral or better. The downside risk is bounded by `max_single_name_pct`.

**Formula** (paraphrasing what the Apr-14 plan Phase D specifies):
```
scores        = max(composite_scores − min(scores), 0.01)     # floor
raw_weights   = scores / sum(scores)
capped        = min(raw_weights, max_single_name_pct)          # respects existing gate
final_weights = capped / sum(capped)                           # re-normalize
```

Optionally mix in inverse-vol: `w' = w × (1/σ) / Σ(w × (1/σ))` for a second, regime-agnostic weighting. Gate this behind `APIS_REBALANCE_WEIGHTING_METHOD={equal|score|score_invvol}`, default `score`, so the old behavior can be restored instantly if paper shows it misbehaving.

**Why this is safe without walk-forward:** the distribution of outcomes on top-15 is already determined by the ranking quality. Re-weighting only *concentrates* where ranking conviction is highest. If your ranking is noisy, score-weighting amplifies that noise — but the `max_single_name_pct` gate still binds, so the blowup case is bounded. Run 10 days in paper with both modes running in shadow (see Rec 9) and keep whichever has lower realized-vol-per-unit-return.

**Effort:** 3–5 days including tests and a paper shadow.

### 5.2 ATR-scaled horizon-aware stops

The 7% stop × 20-day max-age pair is a legacy from the MVP. For S&P-500 momentum names, 20-day realized vol is often in the 5–8% range, so a 7% stop is inside normal daily noise half the time. You're paying turnover cost to get stopped out of positions that would have worked.

The Apr-14 implementation plan locked the formula already (§7.4):
```
stop_distance = max(0.04, min(0.18, 2.5 × ATR_20 / price))
trailing_stop_distance = 1.5 × ATR_20 / price
```

with per-family multipliers (mean-reversion tighter at 1.5× ATR; value wider at 3.5× ATR). This translates into:

| Strategy family | Stop (ATR mult) | Trailing (ATR mult) | Max age (days) |
|---|---|---|---|
| Momentum | 2.5× (clamped 4–18%) | 1.5× | 60 |
| Theme alignment | 2.5× | 1.5× | 60 |
| Macro tailwind | 2.5× | 1.5× | 20 |
| Sentiment | 2.0× | 1.0× | 15 |
| Valuation | 3.5× | 2.0× | 90 |
| Mean reversion (when added) | 1.5× | 1.0× | 7 |

Attach `origin_strategy` to each `Position` row (schema change, one-line migration) so the exit engine knows which regime to apply when a position was opened by multiple strategies, use the *widest* stop / *longest* max age — let the most patient strategy govern.

**Counter-intuitively increases trade count:** wider stops and longer max-age means capital stays deployed, which means fewer forced-close → re-open churn cycles, which means the `max_new_positions_per_day` budget is spent on *different* names rather than re-entering names you were just stopped out of.

**Effort:** ~1 week. Already a locked decision (DEC-028) in the Apr-14 plan — just needs lifting out of the "blocked by OOS harness" bucket.

### 5.3 Promote `portfolio_fit_score` to a sizing factor

If you keep the field (Rec 4.5 path B), wire it into sizing:

```python
# today
final_pct = min(half_kelly, sizing_hint, max_single_name_pct)
# proposed
liquidity_adjusted = half_kelly × portfolio_fit_score   # fit = 0.7*composite + 0.3*liquidity
final_pct = min(liquidity_adjusted, sizing_hint, max_single_name_pct)
```

Effect: illiquid names get smaller positions automatically, which is what the liquidity filter (Phase 41) is trying to achieve on a binary block/allow basis today. This replaces a hard filter with a smooth penalty.

**Effort:** ~0.5 day. Unit-testable.

---

## 6. Self-Improvement Engine Expansion (The Main Ask)

### 6.1 Current state, honest assessment

`SelfImprovementService.generate_proposals` is a **rule-based mutation generator**. It produces at most 4 proposal types (SOURCE_WEIGHT, RANKING_THRESHOLD, HOLDING_PERIOD_RULE, CONFIDENCE_CALIBRATION), it only fires on D/F/C grades, and the proposals themselves are essentially descriptive — they don't carry the actual parameter changes to apply. The engine has no memory of whether its past proposals worked.

That's not a design flaw — it was the right MVP. But the self-improvement story in APIS stops here, and the user explicitly asked for more. Three additions below.

### 6.2 Proposal Outcome Ledger (the meta-learning foundation)

**Claim:** the single highest-ROI self-improvement upgrade is persisting what happened *after* each proposal decision, because that's the data the proposal generator doesn't currently have.

**Mechanism:**
1. Add table `proposal_outcomes`:
   - `proposal_id` (FK to `improvement_proposals`)
   - `decision` (PROMOTED, REJECTED, EXECUTED, REVERTED)
   - `decision_at`
   - `measurement_window_days` (default 30)
   - `baseline_metric_snapshot` (JSON, captured at decision time)
   - `realized_metric_snapshot` (JSON, captured at `decision_at + measurement_window_days`)
   - `outcome_verdict` (`improved`, `unchanged`, `regressed`, `inconclusive`) — computed by a daily job
   - `outcome_confidence` ([0, 1], bootstrap-based once data is thick enough)

2. New worker job `run_proposal_outcome_assessment` at 18:30 ET daily:
   - Find all `PROMOTED` / `REJECTED` proposals aged exactly `measurement_window_days`
   - Re-sample the metrics from `evaluation_runs` + `portfolio_snapshots` + `closed_trades` in the window
   - Compute verdict
   - Write `proposal_outcomes` row
   - Fire a webhook alert if a PROMOTED proposal has verdict `regressed` (the system promoted something that hurt you)

3. **Feed back into the generator.** Extend `generate_proposals` with an optional `outcome_history` argument (a `ProposalOutcomeHistoryService` you inject at construction). When deciding whether to emit a new proposal of type T targeting component C, the generator consults the historical batting-average of (T, C) pairs and:
   - skips the proposal entirely if the historical success rate is < 20% on ≥10 observations
   - emits with reduced `confidence_score` if success rate is 20–40%
   - emits with boosted `confidence_score` if success rate is ≥ 60%

4. **Surface on the dashboard.** The existing `/dashboard` renders `improvement_proposals`; add a sibling section "Proposal Batting Average by Type" that shows the outcome verdicts. Operator can then see, at a glance, whether HOLDING_PERIOD_RULE proposals have ever actually worked for this system — if not, either fix them or retire the rule.

**Why this is meta-learning, not another rule:** it doesn't add hard constraints anywhere. It adds *evidence-weighted* preferences to a currently-uniform generator. Over time, the generator emits fewer proposals of types that have never worked and more of types that have. The operator always sees the batting averages and can prune or add types manually.

**Safeguards (to keep it from collapsing diversity):**
- Every proposal type retains a floor of ≥1 proposal per month regardless of history — keeps the system exploring.
- The outcome verdict is never used to auto-promote anything. It only affects which proposals are *generated*; the three-gate promotion path is unchanged.

**Effort:** ~2 weeks. New table + migration, one new worker job, ~200 lines in the service, ~30 lines of dashboard rendering.

### 6.3 Shadow-Portfolio Scorer (keep rejected options alive)

**Claim:** the system today has no way to know whether a rejected ranked opportunity, or a rejected proposal, or a rejected strategy weighting would have worked. Every rejection is final. This is the "choked off options" concern the user raised.

**Mechanism:**
1. New service `ShadowPortfolioService` with an API matching `PortfolioEngineService` but writing to a separate `shadow_positions` + `shadow_trades` set of DB tables.
2. In `run_paper_trading_cycle`, after risk validation but before execution (file-line-anchored in the explore report — paper_trading.py step 12 → 13):
   - **Track every REJECTED action.** For each `RiskValidationResult.status == "rejected"`, create a virtual entry at current price in the shadow portfolio.
   - **Track every `"watch"` ranked opportunity.** For each opportunity with composite in [0.55, 0.65] (borderline), create a virtual entry.
   - **Track every exit-triggered position that got stopped out.** Virtual-continue holding until the thesis would have resolved naturally (max_age hit or a larger move).
3. Mark-to-market every cycle, record realized P&L on virtual exits.
4. Weekly job `run_shadow_performance_assessment`:
   - Aggregate shadow-P&L by rejection reason (risk_gate_name, watch_threshold_miss, stop_loss_premature, etc.)
   - If a rejection-reason bucket has shadow-P&L significantly higher than live-P&L on matched positions (paired bootstrap, p < 0.1, ≥ 30 observations), emit an `ImprovementProposal` of type RANKING_THRESHOLD, HOLDING_PERIOD_RULE, or a new type `GATE_LOOSEN` suggesting that particular gate should be relaxed.
5. Never auto-promote based on shadow data alone — it's a source of *proposals*, not of *decisions*.

**Second-order benefit:** the shadow data is the exact input the Proposal Outcome Ledger (§6.2) needs. A REJECTED proposal doesn't just sit dead; its "what-if" parameter set can be applied in a shadow portfolio for `measurement_window_days` and graded the same way a PROMOTED proposal would be. If the shadow outperforms the live, the proposal re-enters the generation queue with boosted confidence.

**Safeguards:**
- Shadow portfolios use the *same* risk gates as the live portfolio. They're not "what if we had no limits" — they're "what if these specific rejected actions had happened within all the existing limits."
- Shadow-derived proposals still go through the full three-gate promotion path (master switch, observation floor, confidence threshold).

**Effort:** ~3 weeks. This is the biggest single item in the document. Worth it because it gives the self-improvement engine real, quantitative evidence about which rejections were right and which weren't.

### 6.4 Thompson-sampling strategy-weight bandit

**Claim:** strategy weights in `RankingEngineService._combine_signals` are static. When given, a weights dict is applied; when not, equal weighting is the fallback. This throws away a continuous learning opportunity: different strategies dominate in different regimes, and that distribution is knowable from live data.

**Mechanism:**
1. Introduce `StrategyBanditService`:
   - Per strategy family, maintain `(α, β)` Beta-distribution parameters tracking wins/losses
   - "Win" = a closed trade where the originating strategy's signal was in the top-3 contributing signals, and realized P&L > 0
   - "Loss" = same but realized P&L ≤ 0
2. Every N cycles (configurable, default 10):
   - Sample a weight from `Beta(α_i, β_i)` for each strategy i
   - Normalize samples to sum to 1
   - Apply a smoothing factor: `final_weight_i = λ × bandit_sample_i + (1−λ) × baseline_weight_i`, with `λ` default 0.3 (cautious)
   - Clamp each weight to `[min_weight, max_weight]` (keeps all strategies in the mix; prevents a winning strategy from going to 100%)
3. Pass the dynamic weights into `SignalEngineService.run()` which already accepts a weights dict.

**Why this doesn't violate the "no new rules" principle:** it *removes* a rule (the equal-weight fallback). The static weights remain as the prior. Exploration is built in. The hard clamps (per-strategy min/max weight) replace the implicit all-strategies-equal rule with a softer, data-aware one.

**Safeguards:**
- Per-strategy weight floor of 5% (keeps all strategies contributing).
- Per-strategy weight ceiling of 40% (prevents single-strategy dominance).
- The RESEARCH mode can run for 2–4 weeks before enabling this in PAPER, building the (α, β) priors from paper data without affecting live decisions.
- A kill-switch: `APIS_STRATEGY_BANDIT_ENABLED=false` reverts instantly to baseline weights.

**Effort:** ~1 week. Sits entirely between signal output and ranking composite; well-bounded.

### 6.5 Summary: expanding what the self-improvement engine can do

Today it proposes changes to 4 things, none of which it can evaluate the downstream effect of. After 6.2–6.4:

| Dimension | Today | After |
|---|---|---|
| Proposal types | 4 hard-coded rules | 4 rules + 1 shadow-derived (GATE_LOOSEN) + unchanged floor |
| Proposal trigger | D/F/C grades only | D/F/C grades + shadow vs live divergence + monthly diversity floor |
| Memory of past decisions | None | 30-day outcome verdicts per proposal |
| Counterfactual data | None | Virtual P&L on every REJECT and every "watch" |
| Strategy weight learning | None | Thompson-sampling bandit with prior + clamps |
| Risk of collapsing diversity | N/A | Mitigated by weight floors, monthly proposal floors |
| Risk of auto-promoting noise | Unchanged — still three-gate | Unchanged — still three-gate |

No hard rule is added. No hard rule is removed. The system now has *memory* and *curiosity* inside the same governance envelope.

---

## 7. Trade-Count Expansion (Without Walk-Forward)

The user asked for more trades. The universe expansion to ~498 names has already landed (Phase C of the Apr-14 plan). The two remaining no-OOS-required levers:

### 7.1 Lower the "buy" threshold with score-weighted sizing

Today: composite ≥ 0.65 → "buy" (hard gate). Phase 65 memory notes this is so strict that effectively all OPENs are coming from the rebalancer, not from the ranking engine's recommendation path. The 0.65 cut is dead for most of the day.

Proposed pair (Recs 4.1 and 5.1 together):
- Move the threshold to `APIS_BUY_THRESHOLD` (default 0.55, config-settable).
- Score-weighted sizing naturally penalizes lower-conviction opens (a 0.56 gets a 12% ceiling of its Kelly fraction vs a 0.72 — math below).

**Kelly check at 0.55:** `f* = 0.5 × max(0, 2×0.55 − 1) = 0.05` → 5% position ceiling before hitting `sizing_hint` or `max_single_name_pct`. That's deliberately tiny. The system opens more names, each smaller, and the existing per-name cap / sector cap / thematic cap still bind.

**Net effect:** more trades, smaller per-trade conviction, portfolio still concentrated by composite score via Rec 5.1. No existing gate is loosened.

**Effort:** ~0.5 day (covered by 4.1 and 5.1).

### 7.2 Conditional `ranking_min_composite_score` relaxation

Today: `ranking_min_composite_score = 0.30` is applied globally as a filter at `paper_trading.py:332–347`. Every ranked opportunity below 0.30 is dropped.

Proposed: keep 0.30 as the default for **new names** but allow 0.20 for names you **already hold with a positive-grade closed-trade history in that ticker**. That's not "trust marginal signals"; it's "trust your own past validation on this specific name."

The logic is trivially wired because Phase 27's `ClosedTrade` ledger already exists. Unit-testable. Reversible via a settings flag.

**Effort:** ~0.5 day.

### 7.3 Things NOT to loosen for trade count

The Apr-14 review and I agree:
- Daily / weekly / monthly drawdown limits — untouched. Real-money insurance.
- `max_single_name_pct` (0.20) / `max_sector_pct` (0.40) — untouched. These are what make score-weighting (Rec 5.1) safe.
- Self-improvement master switch default OFF — untouched.
- RESTRICTED_LIVE guard — untouched.
- Kill switch — untouched.

---

## 8. Rules Audit — Which Gates Are Doing Work, Which Aren't

The user's ask was: don't add rules that choke options. Implied: some existing rules are doing that. Here's my audit:

| Gate | Action | Current | Verdict | Recommendation |
|---|---|---|---|---|
| `max_positions` | Hard block | 15 (was 10) | Doing work. | Keep 15. Don't raise again until 90+ days of paper at 15. |
| `max_new_positions_per_day` | Hard block | 5 (was 3) | Doing work. | Keep 5. Rec 7.1 will pressure this; if the cap routinely binds, operator decision to raise. |
| `max_single_name_pct` | Hard block | 0.20 | Doing work. | Keep. Score-weighting (Rec 5.1) needs this to remain binding. |
| `max_sector_pct` | Hard block | 0.40 | Doing work (occasionally binds on tech-heavy days). | Keep. |
| `max_thematic_pct` | Hard block | 0.75 (was 0.50) | **Phase 66 operator decision.** Will bind often given the AI tilt. | Keep at 0.75 as operator bet. But **add a soft warning log** when projected thematic weight exceeds 0.60 so operator sees the concentration building before the hard cap binds. |
| `daily_loss_limit_pct` | Hard block | 0.02 (2%) | Paper — almost never binds. Live — will bind on high-vol days. | Keep 2% for PAPER/live. **Add an "early warning" soft alert at 1.0%** to give operator lead time. |
| `weekly_drawdown_limit_pct` | Hard block | 0.05 (5%) | Doing work. | Keep. |
| `monthly_drawdown_limit_pct` | Hard block | 0.10 (10%) | Doing work. | Keep. |
| 0.65 buy threshold | Hard filter | Hard-coded | **Choking options** (Phase 65 notes it kills ranking-based opens). | Rec 7.1: lower to 0.55, move to settings. |
| `ranking_min_composite_score` | Hard filter | 0.30 | Sometimes choking on held names. | Rec 7.2: conditional 0.20 for held names with positive history. |
| `exit_score_threshold` | Exit trigger | 0.40 | Doing work on thesis invalidation. | Keep. |
| `stop_loss_pct = 0.07` | Exit trigger | 7% fixed | **Choking options.** Whipsaw on high-vol names. | Rec 5.2: ATR-scaled per family. |
| `max_position_age_days = 20` | Exit trigger | 20 days | **Choking options.** Most theses need longer. | Rec 5.2: per-family (60 for momentum/theme). |
| `take_profit_pct = 0.20` | Exit trigger | 20% | Doing work. | Keep, but consider graduating to trailing-only on high-composite names so runners can run. |
| `trailing_stop_pct = 0.05` | Exit trigger | 5% | Doing work. | Rec 5.2: make ATR-scaled too. |
| Phase 41 liquidity filter | Hard filter | Name-level binary | OK. | Rec 5.3 replaces with smooth penalty via `portfolio_fit_score` in sizing. |
| Phase 43 VaR gate | Hard filter | Portfolio-level | Doing work. | Keep. |
| Phase 44 stress-test gate | Hard filter | Portfolio-level | Doing work. | Keep. |
| Phase 45 earnings-proximity gate | Hard filter | Name-level binary | Occasionally choking on legitimate earnings-breakout plays. | Consider making it *size-reducing* rather than block, but not urgent. |
| Phase 47 drawdown recovery sizing | Soft gate | Size multiplier in RECOVERY | Doing work. | Keep. |
| Self-improvement observation floor | Governance | 10 | **Too low (Apr-14 review §3.6).** Statistical noise at this N. | Raise to 50 per review recommendation. No change to the gate *structure*. |

Net: **six things to loosen** (0.65 threshold, 0.30 filter conditional, 7% stop, 20-day age, 5% trailing, 1/N rebalance → score-weight). **Zero hard risk gates to loosen.** **One governance gate to raise** (observation floor 10 → 50).

---

## 9. What I Would Explicitly NOT Do

These came up in my analysis and I considered and rejected each:

- **Don't add more signal strategies right now.** You have 5 momentum-family + 1 scaffolded InsiderFlow. The Apr-14 review rightly flags "no mean reversion" as a diversifier gap, but mean-reversion without the ATR-stops (Rec 5.2) and without walk-forward is a live-money footgun. Defer until Rec 5.2 lands and walk-forward is eventually tackled.
- **Don't lower the `daily_loss_limit`.** It's the insurance policy.
- **Don't auto-raise `max_positions` past 15.** Equal-weight at 15 names is 6.7% per name; that's the right density for a 498-name universe with a 20% single-name cap. Raising this before you have walk-forward evidence is back-solving for activity, not edge.
- **Don't expand auto-proposal scope into PROTECTED_COMPONENTS.** The guardrail list exists for a reason.
- **Don't build a reinforcement-learning "meta-strategy"** that picks strategies directly. The Thompson-sampling bandit (Rec 6.4) is the 20% of that design that captures 80% of the benefit with a fraction of the overfit risk.
- **Don't replace the A/B/C/D/F daily scorecard** with a more sophisticated metric right now. It's coarse by design (spec principle 3.3 explainability). Add a shadow *continuous* score alongside it rather than replacing.
- **Don't wire InsiderFlow without DEC-023's ToS review outcome being acted on.** That's a known gated item.

---

## 10. Ordered Recommendation List (Impact ÷ Effort)

Format: `Impact (1-5) × Effort-in-days = Priority score`. Higher is better.

| # | Recommendation | Impact | Effort (d) | Score | Depends on |
|---|---|---|---|---|---|
| 1 | Un-bury six hard-coded constants into settings (§4.1) | 3 | 1 | 3.0 | — |
| 2 | Broker-adapter health invariant (§4.2) | 4 | 0.25 | 16 | — |
| 3 | Rebalance/portfolio-action conflict detector (§4.3) | 4 | 0.5 | 8 | — |
| 4 | Idempotency keys on fire-and-forget writers (§4.4) | 3 | 1 | 3.0 | — |
| 5 | Kill / wire `portfolio_fit_score` (§4.5) | 2 | 0.1 or 0.5 | 4–20 | — |
| 6 | Score-weighted rebalance allocator (§5.1) | 5 | 4 | 1.25 | 1 |
| 7 | ATR-scaled horizon-aware stops (§5.2) | 5 | 5 | 1.0 | 1 |
| 8 | Conditional `ranking_min_composite_score` relaxation (§7.2) | 3 | 0.5 | 6 | 1 |
| 9 | Lower "buy" threshold + score-weighted sizing synergy (§7.1) | 4 | 0.5 | 8 | 1, 6 |
| 10 | Proposal Outcome Ledger (§6.2) | 5 | 10 | 0.5 | 1 |
| 11 | Shadow-Portfolio Scorer (§6.3) | 5 | 15 | 0.33 | 1, 10 |
| 12 | Thompson-sampling strategy-weight bandit (§6.4) | 4 | 5 | 0.8 | 1 |
| 13 | Raise self-improvement observation floor 10 → 50 (§8) | 3 | 0.25 | 12 | — |

**Suggested sequencing** (assumes 2–3 hours of focused work per calendar day):

**Week 1:** #1, #2, #3, #4, #5, #13 — all low-risk, set the stage, no behavior change.
**Week 2:** #8, #9 — observable paper-trade-count change. Monitor 1 week before proceeding.
**Weeks 3–4:** #6, #7 — the bigger behavioral changes. Paper-bake 2 weeks.
**Weeks 5–6:** #10 (Proposal Outcome Ledger). Gives the self-improvement engine memory.
**Weeks 7–9:** #11 (Shadow Portfolios). The foundation for real meta-learning.
**Weeks 10–11:** #12 (Bandit). Runs in shadow for 2 weeks before influencing live.

Total: ~11 weeks, matching the user's preferred self-improvement + trade count first ordering. Walk-forward harness and survivorship-free data fold in **after** this batch lands, not before — the shadow portfolios will generate much of the evidence the OOS work needs.

---

## 11. Open Questions for Aaron

1. **The Phase 66 AI tilt size:** you chose to raise `max_thematic_pct` 0.50 → 0.75 and stack a theme-bonus + ranking-bonus. I'm preserving that per your directive. One question though: would you want Rec 6.3 (shadow portfolios) to *also* run a "no-AI-tilt" shadow in parallel, so the operator dashboard shows what the same universe looks like without the tilt? That's pure information, no impact on live. It's the cleanest way to know whether the tilt is paying.

2. **Observation floor:** happy to bump 10 → 50 per the Apr-14 review, or want to wait until Rec 6.2 (outcome ledger) gives you better evidence for what the right number is?

3. **Proposal Outcome Ledger measurement window:** 30 days is reasonable for most proposal types but probably too short for CONFIDENCE_CALIBRATION and too long for HOLDING_PERIOD_RULE. Want per-type windows (adds ~1 day to Rec 10) or one global window?

4. **Shadow portfolios — how far do we go?** Three options:
   - (a) Shadow only REJECTED actions + borderline "watch" names. Narrow, cheap, high-signal.
   - (b) Also shadow stopped-out positions continued-past-stop. Medium cost, medium signal.
   - (c) Also shadow alternative rebalance weightings (equal vs score vs score-invvol) running in parallel. Broadest, most expensive, gives A/B evidence for Rec 5.1 naturally.
   My instinct is (c) — same codepath cost and it directly validates Rec 5.1 without waiting for walk-forward. Your call.

5. **"Better decision making without too many rules" — where's the line?** Specifically: does "too many rules" include the existing risk-engine hard gates (kill switch, concentration caps), or only strategy/signal filters? I've assumed risk gates stay frozen. Let me know if any of them feel restrictive in paper.

6. **Do you want me to start implementing?** Per your earlier answer, this is analysis-only. When you're ready to start, I'd suggest beginning with Rec 1 (un-bury constants) since it unblocks the other nine items and has zero behavior-change risk.

---

## 12. TL;DR

APIS has strong bones. The system is *gated well* but *learns slowly*. The biggest unlock is not more rules, not fewer rules — it's **memory** (Proposal Outcome Ledger), **curiosity** (Shadow Portfolios), and **dynamism** (Strategy Bandit) inside the existing governance envelope. Combined with a few stability invariants (broker-adapter health, conflict detector, idempotency keys) and the score-weighted rebalance / ATR-scaled stops / threshold relaxation trio, you get more trades, better decisions, and a self-improvement engine that can actually evaluate itself — all without weakening any safety control.

The walk-forward harness and survivorship-free data work from the Apr-14 review still matters and still deserves to land eventually. The path in this document is deliberately the shorter loop: it makes the system a better *learner* first, which makes every subsequent rigor upgrade (including OOS) more productive when you land it.
