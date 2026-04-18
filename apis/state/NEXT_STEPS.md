# APIS — Next Steps
Last Updated: 2026-04-18 (ALL 8 STEPS OF DEEP-DIVE PLAN NOW ON MAIN at d3d2bfe)

## COMPLETE — Deep-Dive Execution Plan (2026-04-16 → 2026-04-18)

All 8 steps of the 2026-04-16 Deep-Dive Execution Plan are merged to `main`. Every flag introduced by the plan defaults OFF, so production behaviour is byte-for-byte unchanged until the operator opts in.

### Final git state (2026-04-18 post-merge)
`main` fast-forwarded from e6b2a3a → **d3d2bfe**. Steps 7 + 8 commits:
- 7009538 feat(deep-dive): Step 7 — Shadow Portfolio Scorer (DEC-034) [+23 tests]
- d3d2bfe feat(deep-dive): Step 8 — Thompson Strategy Bandit (Rec 12) [+25 tests]

Combined Step 7+8 delta: 14 files, +2902 / −3. Both Alembic migrations verified reversible against live docker-postgres-1 (`upgrade head → downgrade -1 → upgrade head`).

`feat/deep-dive-plan-steps-7-8` still exists at d3d2bfe. Push remains deferred (no `origin` remote).

## IN PROGRESS — Deep-Dive Execution Plan (2026-04-16) [HISTORICAL]

Autonomous scheduled-task run `apis-execution-plan-step-1` is executing the full 8-step plan back-to-back per operator's authorisation. Per-step workflow: grep → implement → test → migrate → update state files → advance. No pausing between steps except on test failure.

### Git state (2026-04-17 08:23 CT — POST-MERGE)
`main` has been fast-forwarded from 7b0c376 → **e6b2a3a**. All 8 Deep-Dive commits are now on `main`:
- 9f37a47 chore: capture pre-deep-dive uncommitted repo state (67 files, +11026 / -3464)
- f8c6889 feat(deep-dive): Step 1 — un-bury 6 hard-coded constants into settings (+255 tests)
- 2d83cc3 feat(deep-dive): Step 2 — stability invariants + idempotency keys + observation floor 10→50 (+1491)
- e9cd8b5 feat(deep-dive): Step 3 — trade-count lift (lower buy threshold + conditional ranking-min) (+261)
- 614ed1e feat(deep-dive): Step 4 — score-weighted rebalance allocator with floor/cap guardrails (+579)
- 1b4995d feat(deep-dive): Step 5 — ATR-scaled per-family stops + portfolio_fit sizing (+605)
- bbe6855 feat(deep-dive): Step 6 — Proposal Outcome Ledger with per-type measurement windows (DEC-035) (+1705 / -42)
- e6b2a3a docs(deep-dive): update state files after commit phase (state file docs + push-deferral note)

Merge summary: 90 files changed, +15957 / −3505 on the fast-forward. Flag defaults all OFF → behavior-neutral in production. `feat/deep-dive-plan-steps-1-6` still exists at the same commit (can be deleted or kept as checkpoint).

Push to remote is deferred — this repo has no `origin` remote configured. Commits are durable locally.

### Scheduled — Steps 7 + 8 (overnight run 2026-04-17 23:00 CT)
Scheduled task `deep-dive-steps-7-8` fires once at 2026-04-17 23:00 America/Chicago. Plan:
- Branch `feat/deep-dive-plan-steps-7-8` off main at e6b2a3a
- Step 7: `ShadowPortfolioService` + 3 new tables + weekly assessment job + parallel rebalance-weighting shadows (DEC-034)
- Step 8: `StrategyBanditService` + `strategy_bandit_state` table + closed-trade hook + clamps (flag OFF, state still accumulates per plan §8.6)
- Flags default OFF. Alembic smoke-test each migration (up/down/up). 40+ new tests target.
- Fast-forward merge to main, write `_overnight_steps_7_8_report.txt` when done.
- Blocker path → `wip/` branch, no merge, SESSION_HANDOFF_LOG entry.

Task file: `C:\Users\aaron\OneDrive\Documents\Claude\Scheduled\deep-dive-steps-7-8\SKILL.md`

### Step status
- **Step 1** — Un-bury 6 hard-coded constants — **DONE 2026-04-16**. 24 tests added (23 pass, 1 skipped for sandbox Python 3.10 only). Pure refactor; defaults byte-for-byte preserved (DEC-032).
- **Step 2** — Broker-adapter health invariant + action conflict detector + idempotency keys + observation floor 10→50 — **DONE 2026-04-17**. 32 tests added (21 pass + 11 skipped for sandbox Python 3.10). Alembic migration `k1l2m3n4o5p6_add_idempotency_keys` written; operator must run `alembic upgrade head` against prod PG before cycle_id-keyed writes take effect. 2 safety flags default ON per DEC-031.
- **Step 3** — Lower buy threshold 0.65→0.55 (flag `APIS_LOWER_BUY_THRESHOLD_ENABLED`, OFF) + conditional ranking-min 0.30→0.20 for held-with-positive-history (flag `APIS_CONDITIONAL_RANKING_MIN_ENABLED`, OFF) — **DONE 2026-04-17**. 21 tests added, all pass. Cross-step sweep 65 pass + 12 skipped. Both flags default OFF → no behaviour change until operator opts in.
- **Step 4** — New `services/rebalancing_engine/allocator.py` with equal / score / score_invvol modes + floor/cap guardrails. Settings `APIS_REBALANCE_WEIGHTING_METHOD="equal"` + master switch `APIS_SCORE_WEIGHTED_REBALANCE_ENABLED=False` (both required to activate). Worker `rebalancing.py` branches on flags. — **DONE 2026-04-17**. 23 tests added, all pass. Cross-step sweep 88 pass + 12 skipped. Flag default OFF → no behaviour change until operator opts in.
- **Step 5** — ATR stops + `FAMILY_PARAMS` + `Position.origin_strategy` + migration `l2m3n4o5p6q7` + `portfolio_fit_score` into sizing. Settings `APIS_ATR_STOPS_ENABLED` + `APIS_PORTFOLIO_FIT_SIZING_ENABLED` both default OFF. — **DONE 2026-04-17**. 38 tests added, all pass. Cross-step sweep 126 pass + 12 skipped. origin_strategy wiring into paper_trading open-path deferred (crosses idempotency-sensitive code); safe to defer because default family is wider/longer than legacy. Operator must run `alembic upgrade head` before flipping ATR flag.
- **Step 6** — `proposal_outcomes` table + migration `m3n4o5p6q7r8` + daily-assessment worker stub + per-type windows (DEC-035) + generator feedback loop + settings flags. Flag `APIS_PROPOSAL_OUTCOME_LEDGER_ENABLED` default OFF. — **DONE 2026-04-17** (Part A). 19 tests (16 pass + 3 Python-3.10 sandbox skip, following Step 5 precedent). Cross-step sweep 142 pass + 15 skipped. Two overnight-artifact bugs fixed during morning verification: (a) `get_session_factory` → `SessionLocal`, (b) 3 tests skipped for dt.UTC-on-3.10. Worker-job APScheduler wiring + real metric computation deferred to Step 6 **Part B**.
- **Step 7** — `shadow_portfolios`/`shadow_positions`/`shadow_trades` tables + weekly job + parallel rebalance-weighting shadows (DEC-034). Flag `APIS_SHADOW_PORTFOLIO_ENABLED` OFF. — **DONE 2026-04-18** (commit 7009538). 23 tests passing. Alembic migration n4o5p6q7r8s9 reversible.
- **Step 8** — `strategy_bandit_state` table + `StrategyBanditService` + closed-trade hook + clamps. Flag `APIS_STRATEGY_BANDIT_ENABLED` OFF (but bandit state accumulates from closed trades even with flag OFF, per plan §8.6). — **DONE 2026-04-18** (commit d3d2bfe). 25 tests passing. Alembic migration o5p6q7r8s9t0 reversible. `last_sampled_weight` stored as Numeric(18, 16) so cached float64 draws round-trip bit-for-bit between cycles.

### Operator action items after run completes
- [ ] Review CHANGELOG entries for Steps 1–8.
- [ ] Run paper-bake per step's acceptance criteria before flipping any behavioral flag.
- [ ] Keep DEC-033 9 hard risk gates intact (unchanged by any step).

---

## Phase 59 — State Persistence & Startup Catch-Up (DONE 2026-04-09)

## Phase 59 — State Persistence & Startup Catch-Up (DONE 2026-04-09)

**Trigger:** Dashboard sections blank after every restart — `ApiAppState` only restored 4 of ~60 fields from DB. See DECISION_LOG DEC-020.

- [x] `apps/api/main.py` — `_load_persisted_state()` expanded with 6 new restoration blocks (portfolio_state, closed_trades/trade_grades, active_weight_profile, regime_result/history, readiness_report, promoted_versions)
- [x] `apps/api/main.py` — `_run_startup_catchup()` added to re-run missed morning pipeline jobs on weekday mid-day starts
- [x] `tests/unit/test_phase59_state_persistence.py` — 36 tests across 7 classes, 33 pass / 3 skip (Python <3.11)
- [x] `state/CHANGELOG.md`, `state/DECISION_LOG.md`, `state/ACTIVE_CONTEXT.md`, `state/NEXT_STEPS.md` updated

---

## Phase 58 — Self-Improvement Auto-Execute Safety Gates (DONE 2026-04-08)

**Trigger:** Live-money readiness review on 2026-04-08. Two issues found: (a) `run_auto_execute_proposals` never passed `min_confidence` to the service, so the documented 0.70 confidence gate was dead code; (b) the job had no guard against running with a near-empty signal-quality history, which is exactly the bot's state after only ~5 trading days of real signals. See DECISION_LOG DEC-019.

- [x] `config/settings.py` — 3 new fields: `self_improvement_auto_execute_enabled` (default **False**), `self_improvement_min_auto_execute_confidence` (default 0.70), `self_improvement_min_signal_quality_observations` (default 10)
- [x] `apps/worker/jobs/self_improvement.run_auto_execute_proposals` rewritten with 3 gates (master switch, observation floor, per-proposal confidence pass-through)
- [x] `tests/unit/test_phase35_auto_execution.py` — helpers updated, 5 existing tests modified, 6 new Phase 58 tests added. All 13 worker-job tests pass.

### Follow-ups for the operator (when ready)
- [ ] When the PAPER → HUMAN_APPROVED readiness gate is about to PASS, manually inspect the latest few PROMOTED proposals from `app_state.improvement_proposals` to sanity-check that their `confidence_score` values track something meaningful.
- [ ] Confirm `latest_signal_quality.total_outcomes_recorded >= 10` via `GET /system/readiness-report`.
- [ ] Flip `APIS_SELF_IMPROVEMENT_AUTO_EXECUTE_ENABLED=true` in `apis/.env` and restart the worker container. Do NOT do this before the readiness report is green.
- [ ] After flipping, watch the 18:15 ET `auto_execute_proposals` job result for a week and confirm `skipped_low_confidence` and `executed_count` are both non-trivial — a zero-on-both run means the confidence distribution is bimodal at the edges and the threshold may need retuning.

---

## Phase 57 — Insider / Smart-Money Flow Signal (IN PROGRESS)

**Trigger:** Review of Samin Yasar "Claude Just Changed the Stock Market Forever" tutorial (YouTube `lH5wrfNwL3k`). The tutorial's real contribution is the *data source* (congressional disclosures + 13F + unusual options flow), not its strategies. Options-wheel portion of the tutorial is **explicitly out of scope** per Master Spec §4.2. See `DECISION_LOG.md` DEC-018.

### Part 1 — Scaffold (DONE 2026-04-08)
- [x] `services/signal_engine/strategies/insider_flow.py` — `InsiderFlowStrategy` (stateless, exponential decay half-life=14d, hard cut at 60d, reliability tier capped at `secondary_verified`, `contains_rumor=False` always, horizon=POSITIONAL)
- [x] `services/data_ingestion/adapters/insider_flow_adapter.py` — `InsiderFlowAdapter` ABC + `InsiderFlowEvent` dataclass + `InsiderFlowOverlay` dataclass + `NullInsiderFlowAdapter` default
- [x] `services/feature_store/models.py` — add overlay fields `insider_flow_score`, `insider_flow_confidence`, `insider_flow_age_days`
- [x] `services/signal_engine/models.py` — add `SignalType.INSIDER_FLOW` enum member
- [x] `services/signal_engine/strategies/__init__.py` — register `InsiderFlowStrategy`
- [x] `tests/unit/test_phase57_insider_flow.py` — 24 tests, all passing (scaffold defaults, decay math, aggregation, reliability, rumour-flag invariant)

### Part 2 — Provider Selection & Wiring (IN PROGRESS)
- [x] **Provider ToS review** — evaluated QuiverQuant, Finnhub, SEC EDGAR. **Selected QuiverQuant (primary, congressional) + SEC EDGAR Form 4/13F (supplementary, insider/institutional).** Finnhub rejected (unclear ToS, undocumented fields). Logged as DEC-023 on 2026-04-11.
- [ ] **Concrete adapter** implementing `InsiderFlowAdapter.fetch_events()` with rate-limiting, backoff, and row-level parse-error swallowing
- [ ] **Enrichment wiring** — extend the feature enrichment pipeline (Phase 22) to call `adapter.fetch_events()` + `adapter.aggregate()` per ticker and populate the three `FeatureSet.insider_flow_*` overlay fields
- [ ] **SignalEngineService** — add `InsiderFlowStrategy` to the default strategies list in `SignalEngineService.score_from_features()` (behind a settings flag, default OFF)
- [ ] **Settings flag** — `APIS_ENABLE_INSIDER_FLOW_STRATEGY: bool = False` in `config/settings.py`, default OFF, so even after Part 2 lands the strategy produces zero effect until explicitly enabled

### Part 3 — Validation Gate (MUST PASS BEFORE ENABLING)
- [ ] **Walk-forward backtest** via `BacktestEngine` (Phase 24) across ≥2 years of historical congressional disclosure + price data, with realistic transaction costs, slippage, and the existing risk-engine stack active. Document Sharpe, max drawdown, win rate, and turnover with and without the insider-flow signal blended in.
- [ ] **Sensitivity analysis** — re-run the backtest with the insider-flow strategy weight at 0.00, 0.05, 0.10, 0.15 to find the Pareto-optimal weight under the existing Phase 37 auto-tuner framework.
- [ ] **LiveModeGateService readiness report** must still PASS with the new signal weight in place — including the Phase 51 Sharpe / drawdown-state / signal-quality gates.
- [ ] **Integration test** — extend `tests/integration/` with a fixture-driven enrichment → signal → rank → paper-trade loop exercising the new signal family.
- [ ] **Only then** flip `APIS_ENABLE_INSIDER_FLOW_STRATEGY=True` in a controlled deployment and monitor via the existing dashboard + factor-tilt alert (Phase 54).

### Out of Scope for Phase 57 (explicitly)
- Options strategies of any kind (Master Spec §4.2)
- "Ladder-in on drawdown" averaging-down rules (Master Spec §9)
- Replacing or deprecating any existing signal strategy
- Copy-trading a single politician's portfolio wholesale (the signal is *one input* among many, not a standalone trading bot)

---

## **ALL PRIOR PLANNED PHASES COMPLETE**

APIS system build through Phase 56 is finished. 3626 → 3650 tests passing (100 skipped; +24 from Phase 57 scaffold). 35 scheduled jobs. 5 signal strategies wired + 1 new family scaffolded (InsiderFlowStrategy, not yet wired into SignalEngineService).

The only remaining work is **operational**:
- **CRITICAL MONITOR (2026-04-01 06:30 ET):** Check worker logs — `signal_generation_job_complete` should show `"signals": >0` for the first time now that the `securities` table is populated. If still 0, investigate `FeatureStoreService.compute_and_persist()` and whether market data bars exist in the DB.
- **CRITICAL MONITOR (2026-04-01 09:35 ET):** First paper trading cycle should NOT return `skipped_no_rankings`. Cycle count should finally start incrementing.
- **Investigate if needed:** If signals are still 0 despite securities being seeded, the next bottleneck is likely market data — `run_market_data_ingestion` at 06:00 ET needs to have populated OHLCV bars in the `daily_bars` table for `FeatureStoreService` to compute features.
- **Investigate Alpaca broker auth** — API keys may need refresh or re-generation (separate from signal generation issue)
- Set up live broker credentials (Interactive Brokers or equivalent)
- Toggle to live mode via `POST /api/v1/live-gate/promote` then set `APIS_OPERATING_MODE=human_approved` and restart
- Monitor via dashboard at `GET /dashboard` — Infrastructure Health panel shows component status
- **Note:** When running `docker compose` from `apis/infra/docker/`, always pass `--env-file "../../.env"` to avoid Grafana password interpolation error

## Phase 56 — COMPLETE

## Phase 55 — COMPLETE
- **Fill Quality Alpha-Decay Attribution** — `compute_alpha_decay()` + `compute_attribution_summary()` in `FillQualityService`. `run_fill_quality_attribution` job at 18:32 ET. `GET /portfolio/fill-quality/attribution`. Dashboard addendum. 2 new app_state fields. 44 tests → 3566 total passing. **30 scheduled jobs total.**

## Phase 54 — COMPLETE
- **Factor Tilt Alerts** — `FactorTiltAlertService` (stateless), `FactorTiltEvent` dataclass. Two triggers: dominant-factor name change, weight-shift >= 0.15 since last event. Wired into paper trading cycle after Phase 50 factor exposure block. Webhook alert via `alert_service`. GET /portfolio/factor-tilt-history (200 + empty list on no data). Dashboard section. 2 new app_state fields: `last_dominant_factor`, `factor_tilt_events`. 42 tests → 3522 total passing. 29 scheduled jobs total.

## Phase 56 — Next (Readiness Report History, ~55 tests)
- `ReadinessSnapshot` ORM + migration.
- Extend `ReadinessReportService` with `persist_snapshot` fire-and-forget DB write.
- GET /system/readiness-report/history (list, limit param).
- Dashboard trend table (last 10 snapshots, color-coded).
- No new job (stays 30 total).
- ~55 tests.

## Immediate Next Actions (Session 1 — Phase 1 Gate A)

### Priority 1: Complete Foundation (This Session)
- [x] Scaffold repo structure and top-level files
- [x] Create all mandatory state files
- [x] Create `config/settings.py` (pydantic-settings)
- [x] Create `config/logging_config.py` (structlog — fixed for LoggerFactory)
- [x] Create `broker_adapters/base/` abstract adapter + models + exceptions
- [x] Create `broker_adapters/paper/` paper broker implementation
- [x] Create `tests/` harness + Gate A tests
- [x] Run Gate A QA verification → **44/44 PASSED**
- [x] Update SESSION_HANDOFF_LOG with Session 1 checkpoint

### Priority 2: Database Layer — COMPLETE ✓
- [x] Write Alembic environment (`apis/alembic.ini`, `infra/db/env.py`, `infra/db/script.py.mako`)
- [x] Write SQLAlchemy ORM models — 28 tables across 9 modules in `infra/db/models/`
- [x] Write DB session/engine utilities (`infra/db/session.py`)
- [x] Generate + apply migration `9ed5639351bb_initial_schema` → `alembic upgrade head` PASSED
- [x] `alembic check` → no drift. Gate A unit tests 44/44 still green.
- [x] Migration applied to both `apis` and `apis_test` databases

### Priority 3: Research Engine (Phase 3) — COMPLETE ✓
- [x] Define stock universe config (`config/universe.py`, 50 tickers, 8 segments)
- [x] Build data_ingestion: YFinanceAdapter (source_key=yfinance, reliability_tier=secondary_verified), DataIngestionService (ingest_universe_bars, persist_bars ON CONFLICT DO NOTHING)
- [x] Build feature_store: BaselineFeaturePipeline (11 features: return_1m/3m/6m, volatility_20d, atr_14, dollar_volume_20d, sma_20/50, sma_cross_signal, price_vs_sma20/50), FeatureStoreService
- [x] Build signal_engine: MomentumStrategy (sub-scores, explanation_dict, rationale, source tag, contains_rumor), SignalEngineService.score_from_features
- [x] Build ranking_engine: RankingEngineService (composite score, thesis_summary, disconfirming_factors, sizing_hint, source_reliability_tier, contains_rumor)
- [x] Run Gate B QA → **108/108 PASSED**

### Priority 4: Portfolio + Risk (Phase 4) — COMPLETE ✓
- [x] `services/portfolio_engine/service.py` — PortfolioEngineService: apply_ranked_opportunities, open_position, close_position, snapshot, compute_sizing (half-Kelly)
- [x] `services/risk_engine/service.py` — RiskEngineService: validate_action (master gatekeeper), check_kill_switch, check_portfolio_limits (max_positions + max_single_name_pct), check_daily_loss_limit, check_drawdown
- [x] `services/execution_engine/service.py` — ExecutionEngineService: execute_action (OPEN→BUY, CLOSE→SELL, kill-switch re-check), execute_approved_actions batch
- [x] Run Gate C QA → **185/185 PASSED**

### Priority 5: Evaluation Engine (Phase 5) — COMPLETE ✓
- [x] `services/evaluation_engine/models.py` — TradeRecord, PositionGrade, BenchmarkComparison, DrawdownMetrics, AttributionRecord, PerformanceAttribution, DailyScorecard
- [x] `services/evaluation_engine/config.py` — EvaluationConfig (grade thresholds A/B/C/D/F, benchmark tickers)
- [x] `services/evaluation_engine/service.py` — EvaluationEngineService: grade_closed_trade, compute_drawdown_metrics, compute_attribution, generate_daily_scorecard
- [x] Run Gate D QA → **228/228 PASSED**

### Priority 6: Self-Improvement Engine (Phase 6) — COMPLETE ✓
- [x] `services/self_improvement/models.py` — ImprovementProposal, ProposalEvaluation, PromotionDecision, PROTECTED_COMPONENTS, ProposalType, ProposalStatus
- [x] `services/self_improvement/config.py` — SelfImprovementConfig (all thresholds configurable)
- [x] `services/self_improvement/service.py` — SelfImprovementService: generate_proposals, evaluate_proposal (guardrail + metric), promote_or_reject (promotion guard)
- [x] Baseline comparison: metric_deltas, improvement_count, regression_count all computed
- [x] Promotion guard: protected components + blocked types always rejected; accepted changes traceable with rollback_reference
- [x] Run Gate E QA → **301/301 PASSED**

### Priority 8: FastAPI Routes (Phase 8) — COMPLETE ✓
- [x] `apps/api/state.py` — ApiAppState singleton
- [x] `apps/api/deps.py` — AppStateDep, SettingsDep
- [x] `apps/api/schemas/` — recommendations, portfolio, actions, evaluation, reports, system schemas
- [x] `apps/api/routes/` — recommendations, portfolio, actions, evaluation, reports, config routers
- [x] `apps/api/main.py` — all routers mounted under /api/v1
- [x] Run Gate G QA → **445/445 PASSED**

### Priority 9: Background Worker Jobs (Phase 9) — COMPLETE ✓
- [x] `apps/worker/jobs/ingestion.py` — run_market_data_ingestion, run_feature_refresh
- [x] `apps/worker/jobs/signal_ranking.py` — run_signal_generation, run_ranking_generation
- [x] `apps/worker/jobs/evaluation.py` — run_daily_evaluation, run_attribution_analysis
- [x] `apps/worker/jobs/reporting.py` — generate_daily_report, publish_operator_summary
- [x] `apps/worker/jobs/self_improvement.py` — generate_improvement_proposals
- [x] `apps/worker/main.py` — APScheduler setup wiring all jobs to ApiAppState
- [x] `apps/api/state.py` — improvement_proposals field added
- [x] Run Gate H QA → **494/494 PASSED**

### Priority 10: Remaining Service Stubs / Integrations — COMPLETE ✓
- [x] Wire POST /api/v1/actions/review to ExecutionEngineService
- [x] `services/news_intelligence/` — NLP pipeline stubs and schema
- [x] `services/macro_policy_engine/` — policy signal schema and stub
- [x] `services/theme_engine/` — theme mapping service stub
- [x] `services/rumor_scoring/` — rumor confidence scoring stub
- [x] `broker_adapters/ibkr/` — IBKR adapter architecture-ready scaffold (25 new tests)
- [x] `apps/dashboard/` — read-only HTML operator dashboard at /dashboard/ (15 new tests)
- **Phase 10 COMPLETE — 575/575 tests**

### Priority 11: Concrete Implementations + Backtest (Phase 11) — COMPLETE ✓
- [x] Concrete `MarketDataService` (yfinance-backed), `NewsIntelligenceService` (NLP), `MacroPolicyEngineService`, `ThemeEngineService`, `RumorScoringService`
- [x] `IBKRBrokerAdapter` — full ib_insync implementation
- [x] `BacktestEngine` — day-by-day simulation, Sharpe/drawdown/win-rate
- **Phase 11 COMPLETE — 646/646 tests**

### Priority 12: Live Paper Trading Loop (Phase 12) — COMPLETE ✓
- [x] `apps/worker/jobs/paper_trading.py` — `run_paper_trading_cycle`: ranked→portfolio→risk→execute→evaluate loop
- [x] `apps/api/state.py` — paper loop fields: `paper_loop_active`, `last_paper_cycle_at`, `paper_cycle_count`, `paper_cycle_errors`
- [x] `apps/worker/main.py` — scheduler wired with paper trading cycle (morning + midday), 11 jobs total
- [x] `broker_adapters/schwab/adapter.py` — Schwab OAuth 2.0 scaffold
- [x] `infra/docker/docker-compose.yml` — Full Docker Compose (postgres, redis, api, worker)
- [x] `infra/docker/Dockerfile` — Multi-stage build
- [x] `apps/api/routes/metrics.py` — Prometheus-compatible scrape endpoint at `GET /metrics`
- [x] 76 Phase 12 tests written and passing
- **Phase 12 COMPLETE — 722/722 tests**

### Priority 13: Future Enhancements / Phase 13 — COMPLETE ✓
- [x] Grafana dashboard template (infra/monitoring/grafana_dashboard.json)
- [x] Live trading mode gate (services/live_mode_gate/ + GET|POST /api/v1/live-gate/*)
- [x] Production secrets management (config/secrets.py: EnvSecretManager + AWSSecretManager scaffold)
- [x] 88 new Phase 13 tests — **810/810 total tests passing**

### Priority 14: Concrete Implementations + Monitoring + E2E — COMPLETE ✓
- [x] Schwab adapter: full schwab-py 1.5.1 concrete implementation (connect, all CRUD, fills, market hours)
- [x] AWSSecretManager: concrete boto3 implementation (get/get_optional with cache, invalidate_cache, error handling)
- [x] Grafana provisioning YAML (datasources/prometheus.yaml + dashboards/apis.yaml)
- [x] Prometheus alert rules (10 rules across 4 groups: safety, paper_loop, portfolio, pipeline)
- [x] Prometheus server config (prometheus.yml with scrape targets + rule_files)
- [x] E2E tests: tests/e2e/test_alpaca_paper_e2e.py (30 tests, auto-skip when no credentials)
- [x] Phase 14 mock-based unit tests (tests/unit/test_phase14_priority14.py)
- [x] Phase 12+13 tests updated to reflect concrete (not scaffold) implementations
- **Phase 14 COMPLETE — 916/916 tests passing (3 skipped: PyYAML not installed)**

### Priority 15: Production Deployment Readiness — COMPLETE ✓
- [x] Docker Compose: add Prometheus + Grafana services; mount provisioning YAMLs
- [x] Schwab OAuth token refresh: `refresh_auth()` method (disconnect + reconnect via client_from_token_file)
- [x] IBKR + Schwab adapter mock integration tests
- [x] CI/CD pipeline: GitHub Actions workflow `.github/workflows/ci.yml` (unit-tests matrix + docker-build)
- [x] Health checks: `/health` endpoint returns DB/broker/scheduler component liveness dict; 503 on DB down
- [x] .env.example: production env vars template at workspace root
- [x] 80 new Phase 15 tests — **996/996 total tests passing (3 skipped: PyYAML absent)**

### Priority 16: AWS Secrets Rotation + K8s + Runbook + Live E2E — COMPLETE ✓
- [x] AWS Secrets rotation hook: `POST /api/v1/admin/invalidate-secrets` (HMAC Bearer auth, AWSSecretManager.invalidate_cache(), 503 when disabled, skipped_env_backend for dev)
- [x] `APIS_ADMIN_ROTATION_TOKEN` setting added to Settings + .env.example  
- [x] Operating mode transition runbook: `docs/runbooks/mode_transition_runbook.md` (RESEARCH→PAPER, PAPER→HUMAN_APPROVED, HUMAN_APPROVED→RESTRICTED_LIVE; pre-flight checklists, rollback, kill switch, kubectl + docker compose commands)
- [x] Kubernetes manifests: `infra/k8s/` (namespace, configmap, secret template, api-deployment, api-service, worker-deployment, kustomization)
- [x] Live paper-account E2E tests: `tests/e2e/test_schwab_paper_e2e.py` (12 classes, auto-skip without creds) + `tests/e2e/test_ibkr_paper_e2e.py` (auto-skip without port)
- [x] Phase 16 unit tests: `tests/unit/test_phase16_priority16.py` — 125 tests (10 classes)
- **Phase 16 COMPLETE — 1121/1121 tests passing (3 skipped: PyYAML absent)**

### Priority 11: Concrete Implementations — COMPLETE ✓
- [x] Implement real `market_data` service (NormalizedBar, LiquidityMetrics, MarketDataService)
- [x] Implement concrete news_intelligence NLP layer (keyword rule-based: 35+ pos, 40+ neg, 12 themes)
- [x] Implement concrete macro_policy_engine signal layer (rule sets, bias computation, regime assessment)
- [x] Implement concrete theme_engine ticker-to-theme mapping registry (50 tickers, 12 themes)
- [x] Implement concrete rumor_scoring utils (ticker extraction, text normalisation)
- [x] Implement IBKR adapter (full ib_insync concrete implementation)
- [x] Backtest mode harness (BacktestEngine with day-by-day synthetic fills, Sharpe/drawdown)
- [x] 71 new Phase 11 tests — **646/646 total tests passing**

### Priority 17: Broker Auth Expiry Detection + Admin Audit Log + K8s Hardening — COMPLETE ✓
- [x] `ApiAppState` — `broker_auth_expired: bool` + `broker_auth_expired_at: Optional[datetime]` fields
- [x] `apps/worker/jobs/paper_trading.py` — Catch `BrokerAuthenticationError` in broker-connect step → set state flag, early-return status=error_broker_auth; clear flag on successful reconnect
- [x] `apps/api/main.py` — `/health` endpoint: `broker_auth: ok|expired` component; `expired` → overall=degraded (200, not 503)
- [x] `apps/api/routes/metrics.py` — `apis_broker_auth_expired` gauge (1=expired, 0=ok)
- [x] `infra/db/models/audit.py` — `AdminEvent` ORM model (table: admin_events; 9 columns)
- [x] `infra/db/versions/b1c2d3e4f5a6_add_admin_events.py` — Alembic migration (down_revision: 9ed5639351bb)
- [x] `apps/api/routes/admin.py` — fire-and-forget `_log_admin_event()`; `_get_client_ip()`; audit on all outcomes; `GET /api/v1/admin/events` endpoint (bearer auth, paginated, 503 on DB failure); `request: Request` on all handlers; `AdminEventResponse` schema
- [x] `infra/k8s/hpa.yaml` — HPA (min=2, max=10, CPU 70%, Memory 80%, scaleDown 300s stabilization)
- [x] `infra/k8s/network-policy.yaml` — apis-api-netpol + apis-worker-netpol (ingress 8000, egress 443/5432/6379/7497/53, DNS)
- [x] `infra/k8s/kustomization.yaml` — Updated to include hpa.yaml + network-policy.yaml (8 resources total)
- [x] `infra/monitoring/prometheus/rules/apis_alerts.yaml` — `BrokerAuthExpired` critical alert (apis.paper_loop group; now 11 alert rules)
- [x] `tests/unit/test_phase17_priority17.py` — 84 new tests (14 classes)
- **Phase 17 COMPLETE — 1205/1205 tests passing (34 skipped: PyYAML absent)**

### Priority 18: Schwab Token Auto-Refresh + Admin Rate Limiting + DB Pool Config + Alertmanager — COMPLETE ✓
- [x] `config/settings.py` — Added `db_pool_size`, `db_max_overflow`, `db_pool_recycle`, `db_pool_timeout` fields
- [x] `infra/db/session.py` — `_build_engine()` passes all 4 pool settings to `create_engine`
- [x] `apps/api/routes/admin.py` — In-process sliding-window rate limiter (20 req/60 s/IP); HTTP 429 + Retry-After; `_check_rate_limit()` wired to both handlers
- [x] `apps/worker/jobs/broker_refresh.py` — NEW `run_broker_token_refresh()` job (Schwab-only; sets `broker_auth_expired` on auth failure; never raises)
- [x] `apps/worker/jobs/__init__.py` — Exports `run_broker_token_refresh`
- [x] `apps/worker/main.py` — `_job_broker_token_refresh()` scheduled at 05:30 ET weekdays (12 total jobs)
- [x] `infra/monitoring/alertmanager/alertmanager.yml` — NEW full Alertmanager config (PagerDuty critical, Slack warnings, inhibit rules)
- [x] `infra/monitoring/prometheus/prometheus.yml` — Alerting block uncommented; points at alertmanager:9093
- [x] `infra/docker/docker-compose.yml` — `alertmanager` service + `alertmanager_data` volume; prometheus depends_on alertmanager
- [x] `apis/.env.example` — Added `APIS_DB_POOL_*`, `SLACK_WEBHOOK_URL`, `SLACK_CHANNEL_*`, `PAGERDUTY_INTEGRATION_KEY`
- [x] `tests/unit/test_phase18_priority18.py` — NEW: 83 tests (80 passing, 3 skipped — PyYAML)
- [x] `tests/unit/test_worker_jobs.py` — Updated job count assertion 11→12
- [x] `tests/conftest.py` — Autouse `_reset_admin_rate_limiter` fixture
- [x] `tests/unit/test_phase16_priority16.py` — Added `_mock_request()` helper; 12 direct call sites patched
- **Phase 18 COMPLETE — 1285/1285 tests passing (37 skipped: PyYAML absent)**


### Priority 19: Kill Switch + AppState Persistence — COMPLETE ✓
- [x] `infra/db/models/system_state.py` — NEW: `SystemStateEntry` ORM (string PK, `value_text TEXT`, `updated_at TIMESTAMPTZ`); 4 key constants
- [x] `infra/db/versions/c2d3e4f5a6b7_add_system_state.py` — NEW: Alembic migration (down_revision: b1c2d3e4f5a6)
- [x] `infra/db/models/__init__.py` — Added `AdminEvent` + `SystemStateEntry` to exports
- [x] `apps/api/state.py` — 4 new fields: `kill_switch_active`, `kill_switch_activated_at`, `kill_switch_activated_by`, `paper_cycle_count`
- [x] `apps/worker/jobs/paper_trading.py` — Kill switch guard fires FIRST; fixed `paper_cycle_results.append` bug; `paper_cycle_count` increment + `_persist_paper_cycle_count()` fire-and-forget
- [x] `apps/api/routes/admin.py` — `POST /GET /api/v1/admin/kill-switch`; `_persist_kill_switch()`; `AppStateDep` FastAPI DI; 409 when env=True but deactivate attempted
- [x] `apps/api/main.py` — `_load_persisted_state()` at lifespan startup (non-fatal); kill_switch added to `/health`
- [x] `services/live_mode_gate/service.py` — Effective kill switch = env OR runtime; `paper_cycle_count` durable counter with `len(paper_cycle_results)` fallback
- [x] `apps/api/routes/config.py` + `metrics.py` — Effective kill switch used everywhere
- [x] `tests/unit/test_phase19_priority19.py` — NEW: 84 tests (13 classes)
- **Phase 19 COMPLETE — 1369/1369 tests passing (37 skipped: PyYAML absent)**

### Priority 20: Portfolio Snapshot Persistence + Evaluation Persistence + Continuity Service — COMPLETE ✓
- [x] `services/continuity/models.py` — `ContinuitySnapshot` dataclass (11 fields, `to_dict()`/`from_dict()` JSON roundtrip) + `SessionContext` dataclass (10 fields + `summary_lines`)
- [x] `services/continuity/config.py` — `ContinuityConfig(snapshot_dir, snapshot_filename, max_snapshot_age_hours=48)`
- [x] `services/continuity/service.py` — `ContinuityService`: `take_snapshot`, `save_snapshot`, `load_snapshot` (stale-check + corrupt-safe), `get_session_context`
- [x] `services/continuity/__init__.py` — Exports `ContinuityService`
- [x] `apps/worker/jobs/paper_trading.py` — `_persist_portfolio_snapshot()` fire-and-forget after each successful cycle (inserts `PortfolioSnapshot` row: cash, gross/net exposure, equity, drawdown)
- [x] `apps/worker/jobs/evaluation.py` — `_persist_evaluation_run()` fire-and-forget after scorecard (inserts `EvaluationRun` + 8 `EvaluationMetric` rows: equity, daily_return_pct, net_pnl, hit_rate, drawdowns, position/trade counts)
- [x] `apps/api/schemas/portfolio.py` — `PortfolioSnapshotRecord` + `PortfolioSnapshotHistoryResponse`
- [x] `apps/api/schemas/evaluation.py` — `EvaluationRunRecord` + `EvaluationRunHistoryResponse`
- [x] `apps/api/routes/portfolio.py` — `GET /api/v1/portfolio/snapshots?limit=20` (DB-backed, DESC order, fallback empty list on DB error)
- [x] `apps/api/routes/evaluation.py` — `GET /api/v1/evaluation/runs?limit=20` (DB-backed, with metrics dict, fallback empty list on DB error)
- [x] `apps/api/state.py` — `last_snapshot_at: Optional[datetime]` + `last_snapshot_equity: Optional[float]` fields
- [x] `apps/api/main.py` — `_load_persisted_state()` extended: restores latest portfolio snapshot equity baseline from DB at startup (non-fatal)
- [x] `tests/unit/test_phase20_priority20.py` — NEW: 56 tests (15 classes)
- **Phase 20 COMPLETE — 1425/1425 tests passing (37 skipped: PyYAML absent)**

### Priority 24: Multi-Strategy Backtest + Operator Push + Metrics Expansion (Phase 24) — COMPLETE ✓
- [x] `services/backtest/engine.py` — `BacktestEngine` now uses all 4 strategies by default; `strategies` param replaces `strategy`; `enrichment_service` injection; `run()` accepts `policy_signals` + `news_insights`
- [x] `config/settings.py` — NEW field: `operator_api_key: str = ""` (env: `APIS_OPERATOR_API_KEY`)
- [x] `apps/api/schemas/intelligence.py` — 3 new schemas: `PushEventRequest`, `PushNewsItemRequest`, `PushItemResponse`
- [x] `apps/api/routes/intelligence.py` — 2 new authenticated POST endpoints: `POST /intelligence/events` + `POST /intelligence/news`; Bearer token auth
- [x] `apps/api/routes/metrics.py` — 3 new Prometheus gauges: `apis_macro_regime`, `apis_active_signals_count`, `apis_news_insights_count`
- [x] `tests/unit/test_phase24_multi_strategy_backtest.py` — NEW: 60 tests (6 classes)
- **Phase 24 COMPLETE — 1815/1815 tests passing (37 skipped: PyYAML absent)**

### Priority 25: Exit Strategy + Position Lifecycle Management (Phase 25) — COMPLETE ✓
- [x] `config/settings.py` — 3 new exit threshold fields: `stop_loss_pct=0.07`, `max_position_age_days=20`, `exit_score_threshold=0.40`
- [x] `services/portfolio_engine/models.py` — `ActionType.TRIM = "trim"` added (partial size reduction; target_quantity specifies shares)
- [x] `services/risk_engine/service.py` — `evaluate_exits(positions, ranked_scores, reference_dt)`: 3 triggers in priority order: stop-loss → age expiry → thesis invalidation; returns pre-approved CLOSE actions
- [x] `apps/worker/jobs/paper_trading.py` — Exit evaluation wired after `apply_ranked_opportunities`: refreshes position prices, calls `evaluate_exits`, merges CLOSEs (deduplicated by ticker)
- [x] `tests/unit/test_phase25_exit_strategy.py` — NEW: 55 tests (11 classes)
- **Phase 25 COMPLETE — 1870/1870 tests passing (37 skipped: PyYAML absent)**

### Priority 26: TRIM Execution + Overconcentration Trim Trigger (Phase 26) — COMPLETE ✓
- [x] `services/execution_engine/service.py` — `_execute_trim(request)`: validates `target_quantity > 0`, gets broker position, caps sell at actual holding, places partial SELL MARKET order; `ActionType.TRIM` routed in `execute_action()` dispatch
- [x] `services/risk_engine/service.py` — `evaluate_trims(portfolio_state) -> list[PortfolioAction]`: fires when `position.market_value > equity * max_single_name_pct`; `ROUND_DOWN` import added; returns pre-approved TRIM actions with correct share quantity
- [x] `apps/worker/jobs/paper_trading.py` — Overconcentration TRIM evaluation block wired after exit evaluation; uses `already_closing` deduplication (CLOSE supersedes TRIM for same ticker)
- [x] `tests/unit/test_phase25_exit_strategy.py` — Updated 2 tests: TRIM now returns `REJECTED` (not `ERROR`) when no position exists
- [x] `tests/unit/test_phase26_trim_execution.py` — NEW: 46 tests (11 classes)
- **Phase 26 COMPLETE — 1916/1916 tests passing (37 skipped: PyYAML absent)**

### Priority 27: Closed Trade Ledger + Start-of-Day Equity Refresh (Phase 27) — COMPLETE ✓
- [x] `services/portfolio_engine/models.py` — `ClosedTrade` dataclass (ticker, action_type, fill_price, avg_entry_price, quantity, realized_pnl, realized_pnl_pct, reason, opened_at, closed_at, hold_duration_days; `is_winner` property)
- [x] `apps/api/state.py` — `closed_trades: list[Any]` + `last_sod_capture_date: Optional[dt.date]` fields
- [x] `apps/worker/jobs/paper_trading.py` — (A) SOD equity block: captures `start_of_day_equity` + `high_water_mark` on first cycle of each trading day; (B) closed trade recording block after `execute_approved_actions` and BEFORE broker sync
- [x] `apps/api/schemas/portfolio.py` — `ClosedTradeRecord` + `ClosedTradeHistoryResponse` schemas
- [x] `apps/api/routes/portfolio.py` — `GET /api/v1/portfolio/trades` endpoint (filter by ticker, limit; aggregates: total_pnl, win_rate, win/loss counts)
- [x] `services/risk_engine/service.py` — `evaluate_exits` upgraded to `dt.datetime.now(dt.timezone.utc)`; normalizes naive `opened_at` for backward compatibility
- [x] `tests/unit/test_phase27_trade_ledger.py` — NEW: 46 tests (8 classes)
- **Phase 27 COMPLETE — 1962/1962 tests passing (37 skipped: PyYAML absent)**

### Priority 28: Live Performance Summary + Closed Trade Grading + P&L Metrics (Phase 28) — COMPLETE ✓
- [x] `apps/api/state.py` — `trade_grades: list[Any]` field added to `ApiAppState`
- [x] `apps/worker/jobs/paper_trading.py` — Phase 28 grading block: `_pre_record_count` snapshot, grade each newly-closed trade via `EvaluationEngineService.grade_closed_trade()`, append to `app_state.trade_grades`
- [x] `apps/api/schemas/portfolio.py` — `TradeGradeRecord`, `TradeGradeHistoryResponse`, `PerformanceSummaryResponse` schemas
- [x] `apps/api/routes/portfolio.py` — `GET /api/v1/portfolio/performance` (equity, SOD equity, HWM, daily return pct, drawdown from HWM, realized/unrealized P&L, open position count, win rate) + `GET /api/v1/portfolio/grades` (letter grades, grade distribution, ticker filter, limit)
- [x] `apps/api/routes/metrics.py` — 3 new Prometheus gauges: `apis_realized_pnl_usd`, `apis_unrealized_pnl_usd`, `apis_daily_return_pct`
- [x] `tests/unit/test_phase28_performance_summary.py` — NEW: 33 tests (9 classes): TestPerformanceSummarySchema, TestTradeGradeSchemas, TestPerformanceEndpointNoState, TestPerformanceSummaryEquityMetrics, TestPerformanceSummaryRealizedPnl, TestPerformanceSummaryUnrealized, TestTradeGradeEndpoint, TestPaperCycleGradeIntegration, TestPrometheusMetricsPhase28
- **Phase 28 COMPLETE — 1995/1995 tests passing (37 skipped: PyYAML absent)**





## Blockers
- PostgreSQL and Redis must be provisioned before DB layer work
- Alpaca API keys needed before broker integration testing
- Data provider decision pending (yfinance for dev is acceptable)

## Prerequisites for Next Session
1. Read `state/ACTIVE_CONTEXT.md`
2. Read `state/SESSION_HANDOFF_LOG.md` — latest entry
3. Confirm Gate A QA passed
4. Continue with Priority 2 (Database Layer)

### Priority 22: Feature Enrichment Pipeline (Phase 22) — COMPLETE ✓
- [x] `services/feature_store/enrichment.py` — NEW: `FeatureEnrichmentService.enrich()` (theme scores, macro bias/regime, news sentiment overlays); `enrich_batch()` (shared macro computation); `assess_macro_regime()`
- [x] `services/feature_store/__init__.py` — exports `FeatureEnrichmentService`
- [x] `services/reporting/models.py` — BUG FIX: `FillReconciliationSummary.is_clean` property (was `AttributeError`; only existed on `FillReconciliationRecord`)
- [x] `apps/api/state.py` — 3 new fields: `latest_policy_signals`, `latest_news_insights`, `current_macro_regime`
- [x] `apps/worker/jobs/ingestion.py` — `run_feature_enrichment` job: assesses macro regime from policy signals, sets `app_state.current_macro_regime`
- [x] `apps/worker/jobs/signal_ranking.py` — `run_signal_generation` now passes `latest_policy_signals` + `latest_news_insights` from app_state to `svc.run()`
- [x] `services/signal_engine/service.py` — `SignalEngineService.__init__` accepts `enrichment_service`; `run()` accepts `policy_signals` + `news_insights`; enriches each FeatureSet before scoring
- [x] `apps/worker/jobs/__init__.py` — exports `run_feature_enrichment`
- [x] `apps/worker/main.py` — `feature_enrichment` cron at 06:22 ET; 13 total scheduled jobs
- [x] `tests/unit/test_phase22_enrichment_pipeline.py` — NEW: 74 tests (14 classes)
- [x] `tests/unit/test_worker_jobs.py` + `test_phase18_priority18.py` — job count updated to 13
- **Phase 22 COMPLETE — 1684/1684 tests passing (37 skipped: PyYAML absent)**

### Priority 23: Intel Feed Pipeline + Intelligence API (Phase 23) — COMPLETE ✓
- [x] `services/news_intelligence/seed.py` — NEW: `NewsSeedService`; 8 seed templates (AI/tech, rates, energy, semis, pharma, fintech, EV, consumer); `get_daily_items(reference_dt)` → `list[NewsItem]` with timestamps 2h before now
- [x] `services/macro_policy_engine/seed.py` — NEW: `PolicyEventSeedService`; 5 seed templates (rate policy, fiscal, tariffs, geopolitical, regulation); `get_daily_events(reference_dt)` → `list[PolicyEvent]` with timestamps 3h before now
- [x] `apps/worker/jobs/intel.py` — NEW: `run_intel_feed_ingestion(app_state, ...)`: seeds → MacroPolicyEngine.process_batch() → `app_state.latest_policy_signals`; seeds → NewsIntelligence.process_batch() → `app_state.latest_news_insights`; individual sub-pipeline exceptions produce "partial" status, both fail → "error"
- [x] `apps/api/schemas/intelligence.py` — NEW: 7 Pydantic schemas for intelligence endpoints
- [x] `apps/api/routes/intelligence.py` — NEW: 4 read-only endpoints: `GET /intelligence/regime`, `/signals?limit=`, `/insights?ticker=&limit=`, `/themes/{ticker}`
- [x] `apps/api/routes/__init__.py` — exports `intelligence_router`
- [x] `apps/api/main.py` — mounts `intelligence_router` at `/api/v1`
- [x] `apps/worker/jobs/__init__.py` — exports `run_intel_feed_ingestion`
- [x] `apps/worker/main.py` — `intel_feed_ingestion` cron at 06:10 ET; 14 total scheduled jobs
- [x] `tests/unit/test_phase23_intelligence_api.py` — NEW: 71 tests (11 classes)
- [x] `tests/unit/test_phase22_enrichment_pipeline.py` + `test_worker_jobs.py` + `test_phase18_priority18.py` — job count/set updated to 14
- **Phase 23 COMPLETE — 1755/1755 tests passing (37 skipped: PyYAML absent)**

### Priority 29: Fundamentals Data Layer + ValuationStrategy (Phase 29) — COMPLETE ✓
- [x] `services/feature_store/models.py` — 7 new fundamentals overlay fields on `FeatureSet`: `pe_ratio`, `forward_pe`, `peg_ratio`, `price_to_sales`, `eps_growth`, `revenue_growth`, `earnings_surprise_pct` (all `Optional[float] = None`)
- [x] `services/market_data/fundamentals.py` — NEW: `FundamentalsData` dataclass + `FundamentalsService` (yfinance-backed; per-ticker isolated fetch; `_safe_positive_float` / `_safe_float` / `_extract_earnings_surprise`)
- [x] `services/signal_engine/strategies/valuation.py` — NEW: `ValuationStrategy` (`valuation_v1`): 4 sub-scores (forward_pe w=0.30, peg_ratio w=0.25, eps_growth w=0.30, earnings_surprise w=0.15); re-normalized over available sub-scores; `confidence = n_available/4`; neutral fallback (score=0.5, confidence=0.0) when all None
- [x] `services/signal_engine/strategies/__init__.py` — `ValuationStrategy` import + `__all__` export
- [x] `services/feature_store/enrichment.py` — `enrich()`/`enrich_batch()` accept `fundamentals_store: Optional[dict]`; `_apply_fundamentals()` static method using `dataclasses.replace()`
- [x] `services/signal_engine/service.py` — 5th default strategy added; `run()` passes through `fundamentals_store`
- [x] `apps/api/state.py` — `latest_fundamentals: dict` field (ticker → FundamentalsData)
- [x] `apps/worker/jobs/ingestion.py` — `run_fundamentals_refresh()` job
- [x] `apps/worker/jobs/__init__.py` — exports `run_fundamentals_refresh`
- [x] `apps/worker/main.py` — `_job_fundamentals_refresh()` at 06:18 ET weekdays; **15 total jobs**
- [x] `apps/worker/jobs/signal_ranking.py` — passes `fundamentals_store` from app_state to signal engine `run()`
- [x] `tests/unit/test_phase29_fundamentals.py` — NEW: ~45 tests (8 classes); all PASSED
- [x] Updated counts in: `test_worker_jobs.py`, `test_research_pipeline_integration.py`, `test_paper_cycle_simulation.py`, `test_phase18/21/22/23` (job counts 14→15, strategy counts 4→5)
- **Phase 29 COMPLETE — 2063/2063 tests passing (37 skipped: PyYAML absent)**

## NEXT PHASE: Phase 30 (TBD)
- Candidates: real-time price streaming / WebSocket feed, alternative data integration, portfolio rebalancing optimization, or DB-backed signal/rank persistence

### Priority 30: DB-backed Signal/Rank Persistence (Phase 30) — COMPLETE ✓
- [x] `services/signal_engine/service.py` — `run()` now creates a `SignalRun` header row BEFORE adding `SecuritySignal` rows (satisfies FK constraint); marks `status="completed"` at end
- [x] `apps/api/state.py` — `last_signal_run_id: Optional[str]` + `last_ranking_run_id: Optional[str]` fields added
- [x] `apps/worker/jobs/signal_ranking.py` — `run_signal_generation` now writes `app_state.last_signal_run_id = str(signal_run_id)` on success; `run_ranking_generation` gains `session_factory` param and takes DB path (calls `svc.run()` + persists `RankingRun` + `RankedOpportunity` rows) when both `session_factory` and `last_signal_run_id` are available, otherwise falls back to in-memory path; writes `app_state.last_ranking_run_id`
- [x] `apps/api/schemas/signals.py` — NEW: 6 Pydantic schemas: `SignalRunRecord`, `SignalRunHistoryResponse`, `RankedOpportunityRecord`, `RankingRunRecord`, `RankingRunHistoryResponse`, `RankingRunDetailResponse`
- [x] `apps/api/routes/signals_rankings.py` — NEW: `signals_router` (`GET /api/v1/signals/runs`) + `rankings_router` (`GET /api/v1/rankings/runs`, `GET /api/v1/rankings/latest`, `GET /api/v1/rankings/runs/{run_id}`); all fallback gracefully when DB unavailable
- [x] `apps/api/routes/__init__.py` — Added `signals_router` + `rankings_router` exports
- [x] `apps/api/main.py` — Mounted `signals_router` + `rankings_router` under `/api/v1`
- [x] `tests/unit/test_phase30_signal_rank_persistence.py` — NEW: 36 tests (8 classes)
- **Phase 30 COMPLETE — 2099/2099 tests passing (37 skipped: PyYAML absent)**

### Priority 31: Operator Alert Webhooks (Phase 31) — COMPLETE ✓
- [x] `services/alerting/models.py` — `AlertSeverity`, `AlertEventType`, `AlertEvent` dataclass
- [x] `services/alerting/service.py` — `WebhookAlertService` (send_alert, HMAC-SHA256 signing, retry); `make_alert_service()` factory
- [x] `config/settings.py` — 5 new fields: `webhook_url`, `webhook_secret`, `alert_on_kill_switch`, `alert_on_paper_cycle_error`, `alert_on_broker_auth_expiry`, `alert_on_daily_evaluation`
- [x] `apps/api/state.py` — `alert_service: Optional[Any] = None`
- [x] `apps/api/routes/admin.py` — `POST /api/v1/admin/test-webhook`; kill switch toggle fires webhook alert
- [x] `apps/worker/jobs/paper_trading.py` — broker auth expiry + fatal error alerts wired
- [x] `apps/worker/jobs/evaluation.py` — daily scorecard alert wired (INFO / WARNING based on return)
- [x] `apps/worker/main.py` + `apps/api/main.py` — alert service initialized at startup
- [x] `tests/unit/test_phase31_operator_webhooks.py` — NEW: 57 tests (18 classes)
- **Phase 31 COMPLETE — 2156/2156 tests passing (37 skipped: PyYAML absent)**

### Priority 32: Position-level P&L History (Phase 32) — COMPLETE ✓
- [x] `infra/db/models/portfolio.py` — NEW: `PositionHistory` ORM (table: position_history; ticker, snapshot_at, quantity, avg_entry_price, current_price, market_value, cost_basis, unrealized_pnl, unrealized_pnl_pct; index on ticker+snapshot_at)
- [x] `infra/db/models/__init__.py` — `PositionHistory` exported
- [x] `infra/db/versions/d4e5f6a7b8c9_add_position_history.py` — NEW Alembic migration (down_revision: c2d3e4f5a6b7)
- [x] `apps/worker/jobs/paper_trading.py` — `_persist_position_history()` fire-and-forget; wired after broker sync when positions non-empty
- [x] `apps/api/schemas/portfolio.py` — `PositionHistoryRecord`, `PositionHistoryResponse`, `PositionLatestSnapshotResponse`
- [x] `apps/api/routes/portfolio.py` — `GET /portfolio/positions/{ticker}/history?limit=30` + `GET /portfolio/position-snapshots`; `_pos_hist_row_to_record()` helper; both gracefully return empty list on DB failure
- [x] `tests/unit/test_phase32_position_history.py` — NEW: 41 tests (10 classes)
- **Phase 32 COMPLETE — 2197/2197 tests passing (100 skipped: PyYAML + E2E absent)**

### Priority 33: Operator Dashboard Enhancements (Phase 33) — COMPLETE ✓
- [x] `apps/dashboard/router.py` — 8 new section renderers (paper cycle, realized performance, recent closed trades, trade grades, intel feed, signal/ranking run IDs, alert service, enhanced portfolio with SOD equity/HWM/daily return/drawdown)
- [x] `apps/dashboard/router.py` — `_fmt_usd()` / `_fmt_pct()` helpers; `_page_wrap()` with configurable auto-refresh; navigation bar (Overview/Positions) on all pages; auto-refresh every 60 s via meta http-equiv
- [x] `apps/dashboard/router.py` — `GET /dashboard/positions` sub-page: per-position detail table (qty, avg entry, price, market value, unrealized P&L, opened_at)
- [x] `tests/unit/test_phase33_dashboard.py` — NEW: 56 tests (11 classes)
- **Phase 33 COMPLETE — 2253/2253 tests passing (37 skipped: PyYAML + E2E absent)**

### Priority 34: Strategy Backtesting Comparison API + Dashboard (Phase 34) — COMPLETE ✓
- [x] `infra/db/models/backtest.py` — NEW: `BacktestRun` ORM (table: backtest_runs; 17 columns; index on comparison_id + created_at)
- [x] `infra/db/versions/e5f6a7b8c9d0_add_backtest_runs.py` — NEW: Alembic migration (down_revision: d4e5f6a7b8c9)
- [x] `infra/db/models/__init__.py` — `BacktestRun` exported
- [x] `services/backtest/comparison.py` — NEW: `BacktestComparisonService` (5 strategies individually + all_strategies combined; engine_factory injection; fire-and-forget DB writes; never raises)
- [x] `apps/api/schemas/backtest.py` — NEW: 6 Pydantic schemas
- [x] `apps/api/routes/backtest.py` — NEW: `backtest_router` (POST /compare, GET /runs, GET /runs/{comparison_id})
- [x] `apps/api/routes/__init__.py` + `apps/api/main.py` — `backtest_router` mounted under `/api/v1`
- [x] `apps/dashboard/router.py` — `GET /dashboard/backtest` sub-page + nav link on all 3 pages
- [x] `tests/unit/test_phase34_backtest_comparison.py` — NEW: 50 tests (11 classes)
- **Phase 34 COMPLETE — 2303/2303 tests passing (100 skipped: PyYAML + E2E absent)**

### Priority 47: Drawdown Recovery Mode (Phase 47) — COMPLETE ✓
- [x] `services/risk_engine/drawdown_recovery.py` — NEW: `DrawdownState` enum (NORMAL/CAUTION/RECOVERY), `DrawdownStateResult` frozen dataclass, `DrawdownRecoveryService` (stateless: `evaluate_state`, `apply_recovery_sizing`, `is_blocked`)
- [x] `apps/api/schemas/drawdown.py` — NEW: `DrawdownStateResponse` schema
- [x] `config/settings.py` — 4 new fields: `drawdown_caution_pct=0.05`, `drawdown_recovery_pct=0.10`, `recovery_mode_size_multiplier=0.50`, `recovery_mode_block_new_positions=False`
- [x] `apps/api/state.py` — 2 new fields: `drawdown_state: str = "NORMAL"`, `drawdown_state_changed_at: Optional[datetime]`
- [x] `apps/api/routes/portfolio.py` — `GET /portfolio/drawdown-state` endpoint
- [x] `apps/worker/jobs/paper_trading.py` — Phase 47 block: evaluate state per cycle, apply size multiplier, block OPENs in recovery, fire webhook on transition
- [x] `apps/dashboard/router.py` — `_render_drawdown_section`: color-coded state badge, drawdown %, HWM, thresholds
- [x] `tests/unit/test_phase47_