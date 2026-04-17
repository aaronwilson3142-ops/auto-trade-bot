# APIS — Independent Strategic + Code Review

**Reviewer:** Claude (independent audit)
**Date:** 2026-04-14
**Scope requested:** Strategic + code audit, benchmarked against retail algo platforms, pro quant practice, and social/YouTube creators. Focus goals: readiness for live capital and increasing trade frequency without giving up edge.

---

## 1. Bottom Line Up Front

APIS is, from a **governance and architecture** standpoint, in the top 5–10% of retail-built trading systems I can compare it to. The markdown discipline, staged rollout gates, risk-engine-as-hard-gatekeeper, and three-gate self-improvement guard are things most retail projects (and frankly a lot of small hedge funds) do not have.

From a **quantitative / trading-science** standpoint, the system is still at roughly the level of "a well-engineered wrapper around unproven edge." The things that actually decide whether a strategy makes money in live markets — out-of-sample validation, realistic cost/slippage modeling, survivorship-free data, regime awareness, and honest statistical significance for parameter changes — are either missing, simplified, or present only in scaffold form.

**If you flip to real money today**, the architecture will protect you from blowing up; it will not protect you from slowly bleeding 2–4% a year to transaction-cost realism, overfitting, and a too-small universe. The readiness bar you should hold yourself to is higher than the one encoded in the current mode-transition runbook.

**If you want more trades**, the rules worth loosening are *different* from the ones the system currently treats as conservative. More detail in §5 and §6.

---

## 2. What APIS Does Well (Keep These)

- **Hard-gatekeeper risk engine.** Nine independent hard blocks (kill switch, position count, single-name/sector/thematic caps, daily/weekly/monthly DD, new-open-per-day, VaR, stress) with no code path that bypasses them. Most retail bots have *one* stop-loss rule. This is pro-grade.
- **Staged rollout protocol** (RESEARCH → PAPER → HUMAN_APPROVED → RESTRICTED_LIVE) with a code-level guard on live promotion. Kevin Davey's "incubation period" — 6–12 months of live-paper before real capital — is literally the idea here, and you've encoded it.
- **Self-improvement gating.** Three gates (master switch OFF by default, observation floor, per-proposal confidence) is exactly the right pattern. It's a template most "auto-tuning" retail bots skip entirely and then blow up.
- **Idempotent orders + fill reconciliation.** This is unglamorous and the reason the Phase 60–62 fixes mattered. You've survived a class of bugs that wrecks real money systems.
- **Audit trail discipline.** Every signal, rank, action, risk event, proposal, promotion is logged. This is what makes diagnosing bad days actually possible.
- **Second-order beneficiary theme logic.** Most retail momentum bots stop at "buy NVDA because AI." Routing signal through suppliers/power/cooling/networking is genuinely differentiated and more defensible.

---

## 3. The Ten Issues That Most Affect Real-Money Performance

Ordered roughly by expected P&L impact, not by engineering difficulty.

### 3.1 No walk-forward / out-of-sample validation (P&L impact: very high)

The backtest engine fetches all history up front and runs a single pass. Every parameter you have — signal weights, thresholds, stop losses, position age, Kelly fraction, rebalance thresholds — has been (implicitly or explicitly) selected against the *same* data you measure performance on. Academic and practitioner consensus: ~95% of backtested strategies fail live, and most of that failure is overfit parameters.

**Fix:** Implement anchored walk-forward (train on 2018–2022, test 2023; train 2018–2023, test 2024; etc.). Any parameter change — including self-improvement proposals — should have to survive walk-forward before being promoted, not just "last 5 days looked good."

### 3.2 Survivorship bias in yfinance universe (P&L impact: high)

The universe of 62 names is curated today. yfinance does not preserve delisted names. Every backtest you run over any multi-year window over-states returns by ~50–150 bps/yr because it silently drops the losers. Your InsiderFlowStrategy idea will be especially vulnerable to this (insider buys in names that later blew up won't show up).

**Fix:** Either (a) freeze a point-in-time S&P 500 / Russell 1000 constituent list per date, or (b) accept the bias explicitly and derate your backtest Sharpe by ~0.3 when making live-promotion decisions.

### 3.3 Equal-weight rebalancing throws away your best information (P&L impact: medium-high)

`rebalancing.py` allocates 1/N across the top 10 ranked names regardless of composite score. If your #1 scores 0.85 and your #10 scores 0.32, you're betting identically on both. The Kelly sizing in `portfolio_engine/service.py` is score-aware, but the *rebalance* codepath overrides it with equal weight.

**Fix:** Size by normalized composite score (with a floor to prevent 99% concentration), or use inverse-volatility weighting on top of score-weighting. Simple change; directly increases information ratio.

### 3.4 Slippage is a fixed 5 bps regardless of name or conditions (P&L impact: medium)

Real slippage is a *distribution*, not a number, and it scales with (order size / ADV), intraday volatility, time-of-day, and spread. 5 bps is roughly right for mega-caps midday; it's wildly optimistic for anything under ~$5M ADV or near open/close. Pro quant practice (and what LEAN/QuantConnect does) is to sample from an empirical distribution conditional on name.

**Fix:** Three tiers minimum — mega-cap (≤5 bps), mid-cap (8–12 bps), small-cap (15–30 bps) — with a Bernoulli "no-fill" probability that increases when order > 1% of ADV. Until this is in, paper results are systematically optimistic.

### 3.5 Stop-loss (7%) + max_position_age (20 days) are mutually hostile (P&L impact: medium)

For US-equity swing trading, 7% is inside typical 20-day realized volatility for half your universe. You will get whipsawed out of otherwise-good theses. Combine that with a 20-day hard expiry and most theses never get room to work. The broader literature on momentum — the signal family you lean on most — uses 6–12 month horizons.

**Fix:** Split horizons by strategy family. Momentum and theme positions: 45–90 day max age, 12–15% stop, ATR-scaled. Macro/event: 10–20 day age, 7–8% stop. Mean reversion (if added): 3–7 day age, 3–4% stop. One stop for everything is wrong.

### 3.6 Self-improvement observation floor (10) is statistical noise (P&L impact: medium)

Ten closed trades gives you ~±25% standard error on a win-rate estimate. At that resolution you can't distinguish a genuinely better weight set from random variance. Your Phase 58 gate will happily promote noise until you raise the floor or add a significance test.

**Fix:** Require ≥50 closed outcomes per strategy family, AND require that the candidate beats baseline at p<0.1 on a paired bootstrap of returns, AND require that the improvement is also positive on the held-out walk-forward fold.

### 3.7 Regime is not used anywhere in sizing or gating (P&L impact: medium)

You have the scaffold (Phase 46 regime classifier) but it doesn't appear to actually feed position sizing, strategy weighting, or the kill switch. Mean-reversion strategies dominate ~65–70% of the tape (the chop/range regime); momentum dominates the rest. Running momentum-heavy into a chop regime is the retail-quant classic blowup.

**Fix:** At minimum, cut position size by 50% and disable new opens when VIX > 30 or realized 20-day vol > 90th percentile. Medium-term: make strategy weights regime-conditional.

### 3.8 Universe is far too small for a diversified signal system (P&L impact: medium)

62 names with ~10 max positions means you're always picking from a 16% slice. After sector/theme concentration caps, the feasible set is often <20 names. That makes the rankings quality-insensitive: any day the top-10 filter is mostly forced by the universe, not by edge. QuantConnect and Alpaca-API retail quant setups routinely run 500–3000 name universes.

**Fix:** Expand to S&P 500 or Russell 1000 with a liquidity floor (ADV ≥ $20M). Your risk engine's concentration caps already handle the rest. This is probably the single biggest "trade more while keeping edge" lever you have.

### 3.9 Only momentum-family signals — no mean reversion (P&L impact: medium)

All five wired strategies (momentum, theme, macro, sentiment, value) are broadly *trend/continuation* in flavor. Mean reversion is a well-established independent edge on a 1–5 day horizon and is *anti-correlated* with momentum — adding it improves combined Sharpe even if each individual edge is weaker. This also directly addresses the "more trades" ask: mean reversion naturally generates 3–10× the trade frequency of momentum.

**Fix:** Add a short-horizon mean-reversion strategy (e.g., 5-day RSI + bollinger-band pullback on names with positive 6-month trend — "buy dips in uptrends"). Budget it to 20–30% of portfolio risk initially.

### 3.10 Market-order-only execution with no liquidity pre-check (P&L impact: low-medium)

Every open/close/trim is a market order. In live, that's fine for AAPL and brutal for FTNT at 15:55 ET. Paper broker's 0 commission + fixed slippage hides this entirely.

**Fix:** Use marketable limit orders (bid + N bps on buys, ask − N bps on sells) with a short timeout and fall-through to market. Add a liquidity pre-check that blocks orders > 0.5% of 20-day ADV.

---

## 4. How APIS Compares to Top-Tier Tools

| Capability | APIS today | QuantConnect (LEAN) | Composer | Alpaca + custom |
|---|---|---|---|---|
| Event-driven backtest | Partial | ✅ full tick/bar engine | ✅ (hosted) | Depends on your code |
| Point-in-time / survivorship-free data | ❌ yfinance | ✅ built-in | ✅ | Depends |
| Walk-forward optimization | ❌ | ✅ native | ❌ (no-code) | DIY |
| Realistic slippage model | Fixed 5 bps | ✅ per-name vol model | Simplified | DIY |
| Options / crypto | ❌ | ✅ | ✅ (added 2025) | ✅ |
| Risk engine (multi-gate) | ✅ best-in-class | Partial | Simplified | DIY |
| Staged paper-to-live gating | ✅ best-in-class | Partial | Partial | DIY |
| Self-improvement / auto-tune | ✅ gated | Manual | Genetic-ish | DIY |
| Community / strategy sharing | ❌ | ✅ | ✅ symphonies | — |
| Multi-asset | Equities only | ✅ | ✅ | ✅ |

**Net read:** Your **governance, risk, and ops** are *better* than QuantConnect's defaults and dramatically better than Composer's. Your **data quality, backtest rigor, and execution realism** are behind both. That mismatch is the thing to close before live capital.

Kevin Davey's process (30-year career, multiple World Cup Trading wins) boils down to: process discipline > strategy cleverness, out-of-sample testing is non-negotiable, and 6–12 months of live-paper incubation before real money. APIS is two-thirds of the way there on process but skipping the out-of-sample step.

---

## 5. Loosening Rules to Trade More — Safely

The user ask was: *can we loosen filters to get more trades and still make money?* Yes, but the filters most worth loosening are not the obvious ones.

### Safe to loosen (expected to help)

| Parameter | Current | Proposed | Why it's safe |
|---|---|---|---|
| Universe size | 62 names | 300–500 (S&P 500 w/ ADV≥$20M) | Risk engine caps still bind. More candidates → better top-10. Most impactful single change. |
| `max_positions` | 10 | 15 | Equal-weight 1/N means each name = 10% today; 15 = 6.7% each, naturally safer. |
| `max_new_positions_per_day` | 3 | 5–6 | Only meaningful if universe expands; otherwise you hit ceiling on already-held names. |
| `ranking_min_composite_score` | 0.30 | 0.25 **only after** walk-forward shows OOS edge persists at 0.25 | Do not lower this blind — it's the last line of defense against junk signals. |
| Strategy mix | 5 momentum-family | Add 1 mean-reversion (5–10 day) at 20–30% risk budget | Diversifies edge, raises trade count, anti-correlated with existing signals. |

### Counter-intuitive: loosen by *relaxing* exits, not entries

Most of your "not enough trades" feeling is probably coming from positions being *stopped out* too fast and not being allowed to replace themselves. Widening stops from 7% → 10–12% and extending max age from 20 → 45–60 days (on momentum/theme) will *increase* net trading activity because you keep capital deployed longer and stop-out churn drops.

### Do NOT loosen

- Daily / weekly / monthly drawdown limits. These are your live-money insurance policy.
- Single-name / sector / thematic concentration caps.
- Self-improvement master switch. Keep OFF until §3.6 is fixed.
- RESTRICTED_LIVE guard in `config/settings.py`. Keep the code-level barrier.

---

## 6. Readiness-for-Live-Capital — My Honest Bar

The current runbook says: 20+ cycles, 10+ evaluations, ≥30 days paper, Sharpe ≥0.5 vs SPY, stress-tested. That's *necessary but insufficient*. Here is what I'd require before turning on real capital, in rough order of importance:

1. **Walk-forward Sharpe ≥ 0.5** (not in-sample) on at least 3 non-overlapping OOS folds covering different regimes (2018 boom, 2020 crash, 2022 bear, 2023–24 rally).
2. **Survivorship-free data** for the backtest window or an explicit Sharpe haircut.
3. **Realistic slippage tiered by name**, applied in both backtest and paper.
4. **60–90 days of paper** with post-Phase-60/61/62 code — not 30. Your critical execution fixes are <7 days old. You have essentially zero paper data on the current code.
5. **A hard portfolio-level circuit breaker** that forces flat, not just blocks new opens, on a trailing peak-to-trough DD ≥ 15%.
6. **Slippage calibration job** that compares paper-expected fills vs Alpaca-paper actual fills (once Alpaca paper is wired) and feeds the diff back into the model.
7. **Self-improvement observation floor raised to 50** + statistical significance test.
8. **Mode-transition rehearsal:** do a HUMAN_APPROVED dry run (operator clicks through every trade) for 2 weeks before flipping auto.
9. **Start RESTRICTED_LIVE at ≤10% of intended capital**, with a separate daily DD circuit breaker (1% of *total net worth*, not 1% of the account), and a committed plan to not scale up for 90 days regardless of results.

The runbook bar ≈ 30 days. My bar ≈ 120 days of credible paper + 90 days of restricted live. That's conservative. It's also what Kevin Davey does and it's why he's been solvent for three decades.

---

## 7. If I Were Starting Over — What I'd Change on Day One

1. **Pick a battle-tested backtest engine** (vectorbt, LEAN, or zipline-reloaded) instead of rolling a custom one. Time saved on engine → more time on actual alpha.
2. **Start with a single, simple, well-documented edge** (e.g., 12-1 cross-sectional momentum on S&P 500, monthly rebalance) and get it live and profitable *first*. Add the multi-strategy/theme/AI/insider-flow stack on top of a known-working base, not as the foundation.
3. **Budget more of the project for data than for code.** Point-in-time CRSP or Norgate (~$500–1500/yr) solves survivorship bias permanently. Your current "free via yfinance" savings are dwarfed by the backtest distortion.
4. **Define the edge *before* writing the system.** Right now the system is very impressive but the edge it implements — a composite of 5 correlated trend signals equal-weighted into 10 top picks — is not obviously differentiated. The governance would scale to *any* edge; it's the edge that needs the same attention.
5. **Build the evaluation layer before the strategy layer.** You largely did this (good), but I'd go further: treat the daily scorecard as the product and the strategy as the test subject. Right now the grading (A/B/C/D/F by daily return) is too coarse to distinguish edge from luck.
6. **Ship mean-reversion before sentiment/theme/insider.** Much better signal-to-noise, more trades, easier to measure, anti-correlated with momentum. Thematic/narrative alpha is notoriously hard to measure and easy to fool yourself on.

---

## 8. What "Top Trading Apps and YouTube Creators" Actually Do That Works

Separating the signal from the noise in this space:

**What consistently works (across pros and credible retail):**
- Process discipline, walk-forward, honest OOS testing (Davey, QuantPy, AlgoAdvantage)
- Volatility-targeted sizing (1–2% account risk per trade, adjusted inversely to realized vol)
- Fractional Kelly at 25–50% (full Kelly is psychologically untenable and assumes known edge — which you don't have)
- Combining momentum + mean reversion across timeframes
- Regime awareness (cut risk in high-VIX environments)
- Point-in-time data, realistic costs, not cherry-picking backtest windows

**What sells but does not work:**
- "Proprietary indicators" without published statistical basis
- Short-sample trade-video validation ("here's my last 10 trades")
- Curve-fit backtests on a single market/window
- Any system where the creator's income is from selling the system, not trading it
- "AI" / "ChatGPT picks stocks" without disciplined out-of-sample validation

**APIS is firmly in the first bucket on process** and partly in the first bucket on methodology (Kelly, concentration caps, multi-factor). The gaps are narrow and fixable.

---

## 9. Questions I Still Have for You

1. **What's the actual live Sharpe / hit rate since securities table was seeded (2026-03-31)?** ACTIVE_CONTEXT doesn't show it and it's the number that matters most right now.
2. **Do you have (or can you get) a survivorship-free data source?** This decides whether walk-forward is meaningfully possible or just theater.
3. **What's the target capital and target return?** "Live capital" with $10k, $100k, and $1M imply very different universe, liquidity, and cost models.
4. **Are you committed to long-only US equities forever, or is options/futures/crypto on the roadmap?** Some of the §7 recommendations would change if the scope is widening.
5. **Is this a business (selling to others), a job (replacing income), or a lab (learning)?** That changes my recommendations about how much to harden vs how much to iterate.

---

## 10. TL;DR Summary

- **Architecture & governance:** top 10% of retail systems. Keep it. Don't over-engineer further.
- **Quant rigor:** middle of the pack. Walk-forward, survivorship-free data, and realistic slippage are the unglamorous fixes that separate "paper bot" from "live strategy."
- **To trade more safely:** expand universe (62 → 300+), widen stops (7% → 10–12%), extend position age (20 → 45–60d) on momentum, add a mean-reversion strategy, raise max_positions to 15. Don't lower the composite score threshold or the drawdown limits.
- **Before live capital:** require OOS walk-forward, raise the paper bake to 60–90 days on *current* code, add a hard portfolio-level DD circuit breaker, raise self-improvement observation floor to 50, start at ≤10% of intended capital.
- **Biggest single P&L lever you haven't pulled yet:** expanding the universe. Biggest risk-of-ruin lever you haven't pulled yet: walk-forward + realistic costs.

You've built the rarest thing in retail algo trading: a system disciplined enough to deploy real money without blowing up from bugs or ops failures. Now the edge itself needs the same rigor the infrastructure got.

---

*Sources used in this review (research phase):*
- [Kevin Davey — algorithmic trading process and incubation period](https://kjtradingsystems.com/)
- [QuantConnect vs Composer 2026](https://www.composer.trade/learn/quantconnect-vs-composer-which-is-the-better-platform-to-create-a-stock-trading-bot)
- [Alpaca — algorithmic trading platform](https://alpaca.markets/)
- [Walk-forward optimization fundamentals (QuantInsti)](https://blog.quantinsti.com/walk-forward-optimization-introduction/)
- [Walk-forward in LEAN / QuantConnect](https://www.quantconnect.com/docs/v2/writing-algorithms/optimization/walk-forward-optimization)
- [Quant hedge-fund due diligence 2026 (Resonanz)](https://resonanzcapital.com/insights/quant-hedge-funds-in-2026-a-due-diligence-framework-by-strategy-type)
- [Position sizing & Kelly in practice (Medium / Polec)](https://medium.com/@jpolec_72972/position-sizing-strategies-for-algo-traders-a-comprehensive-guide-c9a8fc2443c8)
- [Mean reversion vs momentum regime share (Tradewink, QuantInsti)](https://www.tradewink.com/learn/mean-reversion-strategy)
- [95% backtest failure rate — retail algo (QuantVPS)](https://www.quantvps.com/blog/guide-to-quantitative-trading-strategies-and-backtesting)
