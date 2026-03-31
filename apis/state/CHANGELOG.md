# APIS — Changelog
Format: [YYYY-MM-DD] | file/module | description

---

## [2026-03-21] Session 56 — Phase 56 COMPLETE (Readiness Report History) — SYSTEM BUILD COMPLETE

### New Files Created
- `infra/db/models/readiness.py` — `ReadinessSnapshot` ORM model
- `infra/db/versions/j0k1l2m3n4o5_add_readiness_snapshots.py` — Alembic migration
- `tests/unit/test_phase56_readiness_history.py` — 60 tests

### Modified Files
- `infra/db/models/__init__.py` — export `ReadinessSnapshot`
- `services/readiness/service.py` — `persist_snapshot(report, session_factory)` static method
- `apps/worker/jobs/readiness.py` — `session_factory` param + persist call
- `apps/worker/main.py` — `_job_readiness_report_update` passes `session_factory`
- `apps/api/schemas/readiness.py` — `ReadinessSnapshotSchema`, `ReadinessHistoryResponse`
- `apps/api/routes/readiness.py` — `GET /system/readiness-report/history`
- `apps/dashboard/router.py` — `_render_readiness_history_table()` + section title updated

### Stats
- 60 new tests → **3626 total passing** (100 skipped)
- Scheduled jobs: **30 total** (no new job)
- **ALL PLANNED PHASES (1–56) COMPLETE**

---

## [2026-03-21] Session 55 — Phase 55 COMPLETE (Fill Quality Alpha-Decay Attribution)

### New Files Created
- `services/fill_quality/models.py` — Added `alpha_captured_pct`, `slippage_as_pct_of_move` to `FillQualityRecord`; new `AlphaDecaySummary` dataclass
- `apps/worker/jobs/fill_quality_attribution.py` — `run_fill_quality_attribution` job (enriches records via DB subsequent price lookup; graceful degradation; fire-and-forget)
- `tests/unit/test_phase55_fill_quality_attribution.py` — 44 tests

### Modified Files
- `services/fill_quality/service.py` — `compute_alpha_decay()` + `compute_attribution_summary()`
- `apps/api/schemas/fill_quality.py` — `AlphaDecaySummarySchema`, `FillAttributionResponse`; alpha fields on record schema
- `apps/api/routes/fill_quality.py` — `GET /portfolio/fill-quality/attribution` (inserted before `/{ticker}`)
- `apps/api/state.py` — 2 new fields: `fill_quality_attribution_summary`, `fill_quality_attribution_updated_at`
- `apps/worker/jobs/__init__.py` — export `run_fill_quality_attribution`
- `apps/worker/main.py` — `fill_quality_attribution` job at 18:32 ET (30 total jobs)
- `apps/dashboard/router.py` — alpha addendum in fill quality section
- 17 prior test files updated (job count 29→30)

### Stats
- 44 new tests → **3566 total passing** (100 skipped)
- Scheduled jobs: **30 total**

---

## [2026-03-21] Session 54 — Phase 54 COMPLETE (Factor Tilt Alerts)

### New Files Created
- `services/factor_alerts/__init__.py` — package init
- `services/factor_alerts/service.py` — `FactorTiltEvent` dataclass + `FactorTiltAlertService` (stateless): two triggers (factor-name change, weight-shift >= 0.15); `build_alert_payload()`
- `apps/api/schemas/factor_alerts.py` — `FactorTiltEventSchema`, `FactorTiltHistoryResponse`
- `apps/api/routes/factor_alerts.py` — `factor_tilt_router`: GET /portfolio/factor-tilt-history (200 + empty list on no data; limit param 1–500 default 50; newest-first)
- `tests/unit/test_phase54_factor_tilt_alerts.py` — 42 tests

### Modified Files
- `apps/api/state.py` — 2 new fields: `last_dominant_factor: Optional[str]`, `factor_tilt_events: list[Any]`
- `apps/worker/jobs/paper_trading.py` — Phase 54 block after Phase 50 factor exposure: detect tilt, append event, fire webhook alert, update `last_dominant_factor`
- `apps/api/routes/__init__.py` — export `factor_tilt_router`
- `apps/api/main.py` — mount `factor_tilt_router` under /api/v1
- `apps/dashboard/router.py` — `_render_factor_tilt_section` with event table + badge; wired after `_render_factor_section`

### Gate Result
**3522/3522 passing, 100 skipped (PyYAML + E2E — expected)**
No new scheduled job (stays 29 total). No new ORM/migration. No new strategies (5 total unchanged). 1 new REST endpoint (GET /portfolio/factor-tilt-history). 1 new dashboard section.

## [2026-03-21] Session 53 — Phase 53 COMPLETE (Automated Live-Mode Readiness Report)

### New Files Created
- `services/readiness/__init__.py` — package init
- `services/readiness/models.py` — `ReadinessGateRow` + `ReadinessReport` dataclasses
- `services/readiness/service.py` — `ReadinessReportService` (stateless): delegates to `LiveModeGateService`, converts gate rows to uppercase status, builds recommendation string; graceful degradation on gate-service errors
- `apps/worker/jobs/readiness.py` — `run_readiness_report_update` job (18:45 ET, after fill_quality_update)
- `apps/api/schemas/readiness.py` — `ReadinessGateRowSchema`, `ReadinessReportResponse`
- `apps/api/routes/readiness.py` — `readiness_router`: GET /system/readiness-report (503 when no data)
- `tests/unit/test_phase53_readiness_report.py` — 56 tests

### Modified Files
- `apps/api/state.py` — 2 new fields: `latest_readiness_report: Optional[Any]`, `readiness_report_computed_at: Optional[dt.datetime]`
- `apps/worker/jobs/__init__.py` — export `run_readiness_report_update`
- `apps/worker/main.py` — `_job_readiness_report_update` wrapper + `readiness_report_update` job at 18:45 ET (29 total)
- `apps/api/routes/__init__.py` — export `readiness_router`
- `apps/api/main.py` — mount `readiness_router` under /api/v1
- `apps/dashboard/router.py` — `_render_readiness_section` with color-coded gate table + wired into main page
- 16 test files — job count assertions updated 28 → 29; `readiness_report_update` added to ID sets in `test_phase22_enrichment_pipeline.py` and `test_worker_jobs.py`

### Gate Result
**3480/3480 passing, 100 skipped (PyYAML + E2E — expected)**
1 new scheduled job (readiness_report_update at 18:45 ET; 29 total). No new ORM/migration. No new strategies (5 total unchanged). 1 new REST endpoint. 1 new dashboard section. overall_status: PASS/WARN/FAIL/NO_GATE.

## [2026-03-21] Session 52 — Phase 52 COMPLETE (Order Fill Quality Tracking)

### New Files Created
- `services/fill_quality/__init__.py` — package init
- `services/fill_quality/models.py` — `FillQualityRecord` (per-fill slippage dataclass), `FillQualitySummary` (aggregate stats dataclass)
- `services/fill_quality/service.py` — `FillQualityService` (stateless): `compute_slippage`, `build_record`, `compute_fill_summary`, `filter_by_ticker`, `filter_by_direction`
- `apps/worker/jobs/fill_quality.py` — `run_fill_quality_update` job (computes fill summary from app_state records, writes to app_state)
- `apps/api/schemas/fill_quality.py` — `FillQualityRecordSchema`, `FillQualitySummarySchema`, `FillQualityResponse`, `FillQualityTickerResponse`
- `apps/api/routes/fill_quality.py` — `fill_quality_router`: GET /portfolio/fill-quality + GET /portfolio/fill-quality/{ticker}
- `tests/unit/test_phase52_fill_quality.py` — 49 tests

### Modified Files
- `apps/api/state.py` — 3 new fields: `fill_quality_records: list[Any]`, `fill_quality_summary: Optional[Any]`, `fill_quality_updated_at: Optional[dt.datetime]`
- `apps/worker/jobs/paper_trading.py` — Phase 52 fill capture block: after execution results, appends one `FillQualityRecord` per FILLED order (fire-and-forget, graceful degradation)
- `apps/worker/jobs/__init__.py` — export `run_fill_quality_update`
- `apps/worker/main.py` — `_job_fill_quality_update` wrapper + `fill_quality_update` job at 18:30 ET
- `apps/api/routes/__init__.py` — export `fill_quality_router`
- `apps/api/main.py` — mount `fill_quality_router` under /api/v1
- `apps/dashboard/router.py` — `_render_fill_quality_section` + wired into main dashboard page
- `tests/unit/test_phase22_enrichment_pipeline.py`, `test_phase18_priority18.py`, `test_phase23_intelligence_api.py`, `test_phase29_fundamentals.py`, `test_phase35_auto_execution.py`, `test_phase36_phase36.py`, `test_phase37_weight_optimizer.py`, `test_phase38_regime_detection.py`, `test_phase43_var.py`, `test_phase44_stress_test.py`, `test_phase45_earnings_calendar.py`, `test_phase46_signal_quality.py`, `test_phase48_dynamic_universe.py`, `test_phase49_rebalancing.py`, `test_worker_jobs.py` — job count assertions updated from 27 → 28

### Gate Result
**3424/3424 passing, 100 skipped (PyYAML + E2E — expected)**
1 new scheduled job (fill_quality_update at 18:30 ET; 28 total). No new ORM/migration. No new strategies (5 total unchanged). 2 new REST endpoints. 1 new dashboard section. Slippage convention: BUY slippage_usd = (fill − expected) × qty; SELL slippage_usd = (expected − fill) × qty; positive = worse fill.

---

## [2026-03-21] Session 51 — Phase 51 COMPLETE (Live Mode Promotion Gate Enhancement)

### Modified Files
- `services/live_mode_gate/service.py` — 3 new private gate methods + import `math`:
  - `_compute_sharpe_from_history(evaluation_history)` — annualised Sharpe from `daily_return_pct` values; type-checks for int/float/Decimal only; returns (sharpe, obs_count)
  - `_check_sharpe_gate(result, app_state, min_sharpe)` — WARN if < 10 observations; PASS/FAIL vs threshold; wired into both checklists (0.5 for PAPER→HA, 1.0 for HA→RL)
  - `_check_drawdown_state_gate(result, app_state)` — NORMAL=PASS, CAUTION=WARN, RECOVERY=FAIL; wired into both checklists
  - `_check_signal_quality_gate(result, app_state, min_win_rate)` — WARN if no SignalQualityReport or no strategy results; PASS/FAIL vs avg win_rate (0.40 for PAPER→HA, 0.45 for HA→RL)
  - New module-level constants: `_PAPER_TO_HA_MIN_SHARPE=0.5`, `_HA_TO_RL_MIN_SHARPE=1.0`, `_MIN_SHARPE_OBSERVATIONS=10`, `_PAPER_TO_HA_MIN_WIN_RATE=0.40`, `_HA_TO_RL_MIN_WIN_RATE=0.45`

### New Files Created
- `tests/unit/test_phase51_live_mode_gate.py` — 57 tests (9 classes):
  TestSharpeComputation, TestSharpeGatePaperToHA, TestSharpeGateHAToRL,
  TestDrawdownGatePaperToHA, TestDrawdownGateHAToRL,
  TestSignalQualityGatePaperToHA, TestSignalQualityGateHAToRL,
  TestFullGateIntegration, TestNewGatesDoNotBreakExisting

### Gate Result
**3375/3375 passing, 100 skipped (PyYAML + E2E — expected)**
No new ORM, no new migration, no new REST endpoints, no new scheduled jobs (27 total), no new strategies (5 total).

---

## [2026-03-21] Session 50 — Phase 50 COMPLETE (Factor Exposure Monitoring)

### New Files Created
- `services/risk_engine/factor_exposure.py` — `FactorExposureService` (stateless; 5 factors MOMENTUM/VALUE/GROWTH/QUALITY/LOW_VOL; `compute_factor_scores`, `compute_portfolio_factor_exposure`; `FactorExposureResult` + `TickerFactorScores` dataclasses)
- `apps/api/schemas/factor.py` — 4 schemas (TickerFactorScoresSchema, FactorExposureResponse, FactorTopBottomEntry, FactorDetailResponse)
- `apps/api/routes/factor.py` — `factor_router` (GET /portfolio/factor-exposure, GET /portfolio/factor-exposure/{factor})
- `tests/unit/test_phase50_factor_exposure.py` — 75 tests (13 classes)

### Modified Files
- `apps/api/state.py` — 2 new fields: `latest_factor_exposure: Optional[Any] = None`, `factor_exposure_computed_at: Optional[dt.datetime] = None`
- `apps/worker/jobs/paper_trading.py` — Phase 50 factor exposure block (after position history persist; queries volatility_20d read-only from DB; builds ticker feature snapshots; writes to app_state)
- `apps/api/routes/__init__.py` — added `factor_router` import + __all__ entry
- `apps/api/main.py` — mounted `factor_router` under /api/v1
- `apps/dashboard/router.py` — `_render_factor_section` (portfolio factor bars + dominant factor badge + per-ticker table)

### Gate Result
**3318/3318 passing, 100 skipped (PyYAML + E2E — expected)**

---

## [2026-03-21] Session 48 — Phase 48 COMPLETE (Dynamic Universe Management)

### New Files Created
- `infra/db/models/universe_override.py` — `UniverseOverride` ORM (ticker, action ADD/REMOVE, reason, operator_id, active, expires_at, TimestampMixin; 3 indexes + check constraint)
- `services/universe_management/__init__.py` — package init
- `services/universe_management/service.py` — `OverrideRecord` DTO + `UniverseTickerStatus` + `UniverseSummary` frozen dataclasses + `UniverseManagementService` (stateless: `get_active_universe`, `compute_universe_summary`, `load_active_overrides`)
- `apps/worker/jobs/universe.py` — `run_universe_refresh` (loads overrides from DB, applies quality pruning, writes active_universe to app_state)
- `apps/api/schemas/universe.py` — 6 schemas (UniverseListResponse, UniverseTickerDetailResponse, UniverseOverrideRequest, UniverseOverrideResponse, UniverseOverrideDeleteResponse, UniverseTickerStatusSchema)
- `apps/api/routes/universe.py` — `universe_router` (GET /universe/tickers, GET /universe/tickers/{ticker}, POST /universe/tickers/{ticker}/override, DELETE /universe/tickers/{ticker}/override)
- `tests/unit/test_phase48_dynamic_universe.py` — 64 tests (16 classes)

### Modified Files
- `config/settings.py` — 1 new field: `min_universe_signal_quality_score: float = 0.0`
- `apps/api/state.py` — 3 new fields: `active_universe: list[str] = []`, `universe_computed_at`, `universe_override_count`
- `apps/worker/jobs/__init__.py` — added `run_universe_refresh` import + __all__ entry
- `apps/worker/main.py` — added `_job_universe_refresh` wrapper; `universe_refresh` CronTrigger at 06:25 ET (26th job)
- `apps/api/routes/__init__.py` — added `universe_router` import + __all__ entry
- `apps/api/main.py` — mounted `universe_router` under /api/v1
- `apps/worker/jobs/signal_ranking.py` — `run_signal_generation` uses `app_state.active_universe` when non-empty; falls back to UNIVERSE_TICKERS
- `apps/dashboard/router.py` — `_render_universe_section` added (active count, net change, removed/added ticker detail tables)
- 13 test files — job count assertions updated 25 → 26; `universe_refresh` added to expected job ID sets

### Gate Result
**3176/3176 passing, 100 skipped (PyYAML + E2E — expected)**

---

## [2026-03-21] Session 47 — Phase 47 COMPLETE (Drawdown Recovery Mode)

### New Files Created
- `services/risk_engine/drawdown_recovery.py` — `DrawdownState` enum (NORMAL/CAUTION/RECOVERY) + `DrawdownStateResult` frozen dataclass + `DrawdownRecoveryService` stateless (evaluate_state, apply_recovery_sizing, is_blocked)
- `apps/api/schemas/drawdown.py` — `DrawdownStateResponse` Pydantic schema
- `tests/unit/test_phase47_drawdown_recovery.py` — 55 tests (8 classes: TestDrawdownStateEvaluation, TestDrawdownRecoverySizing, TestDrawdownIsBlocked, TestDrawdownStateResult, TestDrawdownSettings, TestDrawdownAppState, TestDrawdownAPIEndpoint, TestDrawdownPaperCycleIntegration)

### Modified Files
- `config/settings.py` — 4 new fields: `drawdown_caution_pct=0.05`, `drawdown_recovery_pct=0.10`, `recovery_mode_size_multiplier=0.50`, `recovery_mode_block_new_positions=False`
- `apps/api/state.py` — 2 new fields: `drawdown_state: str = "NORMAL"`, `drawdown_state_changed_at: Optional[datetime]`
- `apps/api/routes/portfolio.py` — Added `GET /portfolio/drawdown-state` endpoint
- `apps/worker/jobs/paper_trading.py` — Phase 47 drawdown block: evaluate state per cycle, apply size multiplier in RECOVERY, block OPENs when block_new_positions=True, fire webhook on state transition
- `apps/dashboard/router.py` — `_render_drawdown_section`: color-coded state badge, drawdown %, HWM, thresholds display

### Gate Result
3112/3112 passing, 100 skipped (PyYAML + E2E — expected). No new job (25 total). No new strategy (5 total).

---

## [2026-03-20] Session 46 — Phase 46 COMPLETE (Signal Quality Tracking + Per-Strategy Attribution)

### New Files Created
- `infra/db/models/signal_quality.py` — `SignalOutcome` ORM (ticker, strategy_name, signal_score, trade_opened_at, trade_closed_at, outcome_return_pct, hold_days, was_profitable; uq_signal_outcome_trade unique constraint; indexes on strategy_name, ticker, trade_opened_at)
- `infra/db/versions/i9j0k1l2m3n4_add_signal_outcomes.py` — migration: creates signal_outcomes table with unique constraint + 3 indexes; down_revision = h8i9j0k1l2m3
- `services/signal_engine/signal_quality.py` — `StrategyQualityResult` + `SignalQualityReport` dataclasses + `SignalQualityService` (stateless: `compute_strategy_quality`, `compute_quality_report`, `build_outcome_dict`; Sharpe estimate (mean/std)×sqrt(252); graceful degradation on empty inputs)
- `apps/worker/jobs/signal_quality.py` — `run_signal_quality_update` (DB path: matches closed trades → SecuritySignal; no-DB path: DEFAULT_STRATEGIES fallback; idempotent re-run via exists-check; 17:20 ET)
- `apps/api/schemas/signal_quality.py` — `StrategyQualitySchema`, `SignalQualityReportResponse`, `StrategyQualityDetailResponse`
- `apps/api/routes/signal_quality.py` — `signal_quality_router` (GET /signals/quality, GET /signals/quality/{strategy_name}; case-insensitive lookup; data_available flag pattern)
- `tests/unit/test_phase46_signal_quality.py` — 61 tests (12 classes)

### Modified Files
- `infra/db/models/__init__.py` — Added `SignalOutcome` import + `__all__` entry
- `apps/api/state.py` — Added `latest_signal_quality`, `signal_quality_computed_at` fields
- `apps/worker/jobs/__init__.py` — Added `run_signal_quality_update` import + `__all__` entry
- `apps/worker/main.py` — Added `_job_signal_quality_update` wrapper; scheduled at 17:20 ET weekdays; updated schedule comment; 25 total jobs
- `apps/api/routes/__init__.py` — Added `signal_quality_router` import + `__all__` entry
- `apps/api/main.py` — Mounted `signal_quality_router` at `/api/v1`; added import
- `apps/dashboard/router.py` — Added `_render_signal_quality_section`: computed_at, total outcomes, per-strategy table (predictions, win rate, avg return, Sharpe estimate, avg hold); warn class for win_rate < 0.40; wired after earnings section
- 13 test files — Job count assertions updated 24 → 25; `signal_quality_update` added to `_EXPECTED_JOB_IDS` sets where present

## [2026-03-20] Session 45 — Phase 45 COMPLETE (Earnings Calendar Integration + Pre-Earnings Risk Management)

### New Files Created
- `services/risk_engine/earnings_calendar.py` — `EarningsEntry` + `EarningsCalendarResult` dataclasses + `EarningsCalendarService` (stateless: `_fetch_next_earnings_date` via yfinance, `build_calendar`, `filter_for_earnings_proximity`); graceful degradation on all fetch failures; OPEN-only gate
- `apps/worker/jobs/earnings_refresh.py` — `run_earnings_refresh` job: fetches next earnings date for all universe tickers, stores EarningsCalendarResult in app_state at 06:23 ET
- `apps/api/schemas/earnings.py` — `EarningsEntrySchema`, `EarningsCalendarResponse`, `EarningsTickerResponse`
- `apps/api/routes/earnings.py` — `earnings_router`: GET /portfolio/earnings-calendar (full calendar + at-risk set) + GET /portfolio/earnings-risk/{ticker} (per-ticker detail)
- `tests/unit/test_phase45_earnings_calendar.py` — 60 tests (11 classes)

### Modified Files
- `config/settings.py` — Added `max_earnings_proximity_days=2` (calendar days before earnings within which OPENs blocked; 0 = disable)
- `apps/api/state.py` — Added `latest_earnings_calendar`, `earnings_computed_at`, `earnings_filtered_count` fields
- `apps/worker/jobs/__init__.py` — Added `run_earnings_refresh` export
- `apps/worker/main.py` — Added `_job_earnings_refresh` wrapper; scheduled at 06:23 ET weekdays; updated schedule comment; 24 total jobs
- `apps/worker/jobs/paper_trading.py` — Added Phase 45 earnings proximity gate (after stress gate): drops OPEN actions for at-risk tickers; updates app_state.earnings_filtered_count
- `apps/api/routes/__init__.py` — Added `earnings_router` import + `__all__` entry
- `apps/api/main.py` — Mounted `earnings_router` at `/api/v1`; added import
- `apps/dashboard/router.py` — Added `_render_earnings_section`: proximity window, last refresh, at-risk tickers with colour, gate-active status, per-ticker table with days_to_earnings; wired after stress section
- 12 test files — Job count assertions updated 23 → 24; `_EXPECTED_JOB_IDS` set extended with `earnings_refresh`

## [2026-03-20] Session 44 — Phase 44 COMPLETE (Portfolio Stress Testing + Scenario Analysis)

### New Files Created
- `services/risk_engine/stress_test.py` — `ScenarioResult` + `StressTestResult` dataclasses + `StressTestService` (stateless: `_get_sector`, `apply_scenario`, `run_all_scenarios`, `filter_for_stress_limit`); `SCENARIO_SHOCKS` dict (4 scenarios × 6 sectors); `SCENARIO_LABELS` dict
- `apps/worker/jobs/stress_test.py` — `run_stress_test` job: computes all 4 scenarios against current portfolio, stores in app_state at 06:21 ET
- `apps/api/schemas/stress.py` — `ScenarioResultSchema`, `StressTestSummaryResponse`, `StressScenarioDetailResponse`
- `apps/api/routes/stress.py` — `stress_router`: GET /portfolio/stress-test (full summary) + GET /portfolio/stress-test/{scenario} (single scenario detail)
- `tests/unit/test_phase44_stress_test.py` — 67 tests (12 classes)

### Modified Files
- `config/settings.py` — Added `max_stress_loss_pct=0.25` (25% worst-case scenario loss gate; set 0.0 to disable)
- `apps/api/state.py` — Added `latest_stress_result`, `stress_computed_at`, `stress_blocked_count` fields
- `apps/worker/jobs/__init__.py` — Added `run_stress_test` export
- `apps/worker/main.py` — Added `_job_stress_test` wrapper; scheduled at 06:21 ET weekdays; updated schedule comment; 23 total jobs
- `apps/worker/jobs/paper_trading.py` — Added Phase 44 stress gate block (after VaR gate): drops all OPEN actions when worst-case scenario loss > limit; updates app_state.stress_blocked_count
- `apps/api/routes/__init__.py` — Added `stress_router` import + `__all__` entry
- `apps/api/main.py` — Mounted `stress_router` at `/api/v1`
- `apps/dashboard/router.py` — Added `_render_stress_section`: computed_at, worst-case scenario name/loss with limit-breach colour, per-scenario table; wired into `_render_page`
- 12 test files — Job count assertions updated 22 → 23; `_EXPECTED_JOB_IDS` set extended with `stress_test`

## [2026-03-20] Session 43 — Phase 43 COMPLETE (Portfolio VaR & CVaR Risk Monitoring)

### New Files Created
- `services/risk_engine/var_service.py` — `VaRResult` dataclass + `VaRService` (stateless: `compute_returns`, `align_return_series`, `compute_portfolio_returns`, `historical_var`, `historical_cvar`, `compute_ticker_standalone_var`, `compute_var_result`, `filter_for_var_limit`)
- `apps/worker/jobs/var_refresh.py` — `run_var_refresh` job: loads bar data from DB for portfolio tickers, computes VaR/CVaR, stores in app_state at 06:19 ET
- `apps/api/schemas/var.py` — `TickerVaRSchema`, `PortfolioVaRResponse`, `TickerVaRDetailResponse`
- `apps/api/routes/var.py` — `var_router`: GET /portfolio/var (full summary) + GET /portfolio/var/{ticker} (standalone contribution)
- `tests/unit/test_phase43_var.py` — 63 tests (14 classes)

### Modified Files
- `config/settings.py` — Added `max_portfolio_var_pct=0.03` (3% 1-day 95% VaR gate; set 0.0 to disable)
- `apps/api/state.py` — Added `latest_var_result`, `var_computed_at`, `var_filtered_count` fields
- `apps/worker/jobs/__init__.py` — Added `run_var_refresh` export
- `apps/worker/main.py` — Added `_job_var_refresh` wrapper; scheduled at 06:19 ET weekdays; updated schedule comment; 22 total jobs
- `apps/worker/jobs/paper_trading.py` — Added Phase 43 VaR gate block (after liquidity filter): drops all OPEN actions when portfolio VaR > limit; updates app_state.var_filtered_count
- `apps/api/routes/__init__.py` — Added `var_router` import + `__all__` entry
- `apps/api/main.py` — Mounted `var_router` at `/api/v1`
- `apps/dashboard/router.py` — Added `_render_var_section`: computed_at, VaR/CVaR metrics with limit-breach colour coding, per-ticker standalone VaR table; wired into `_render_page`
- 10 test files — Job count assertions updated 21 → 22; `_EXPECTED_JOB_IDS` set extended with `var_refresh`

## [2026-03-20] Session 42 — Phase 42 COMPLETE (Trailing Stop + Take-Profit Exits)

### New Files Created
- `apps/api/schemas/exit_levels.py` — `PositionExitLevelSchema`, `ExitLevelsResponse` Pydantic schemas
- `apps/api/routes/exit_levels.py` — `exit_levels_router`: GET /portfolio/exit-levels (per-position stop-loss, trailing stop, take-profit levels)
- `tests/unit/test_phase42_trailing_stop.py` — 48 tests (8 classes: TestSettings42, TestEvaluateExitsTakeProfit, TestEvaluateExitsTrailingStop, TestEvaluateExitsPriority, TestPeakPriceUpdate, TestExitLevelsEndpoint, TestAppState42, TestPaperCycleTrailingStop)

### Modified Files
- `config/settings.py` — Added `trailing_stop_pct=0.05`, `trailing_stop_activation_pct=0.03`, `take_profit_pct=0.20` (all 0.0-disableable)
- `apps/api/state.py` — Added `position_peak_prices: dict[str, float]` (ticker → peak price since entry)
- `services/risk_engine/service.py` — Added module-level `update_position_peak_prices()` helper; extended `evaluate_exits()` with `peak_prices` param and two new triggers: take-profit (priority 2) and trailing stop (priority 3); age expiry → 4, thesis invalidation → 5
- `apps/worker/jobs/paper_trading.py` — Added Phase 42 peak price update block before evaluate_exits; passes peak_prices to evaluate_exits; cleans stale tickers from peak_prices after broker sync
- `apps/api/routes/__init__.py` — Added `exit_levels_router` import + `__all__` entry
- `apps/api/main.py` — Mounted `exit_levels_router` at `/api/v1`
- `apps/dashboard/router.py` — Added `_render_exit_levels_section`: per-position table with stop-loss/trailing/take-profit levels + colour coding; wired into `_render_page`
- `tests/unit/test_phase26_trim_execution.py` — Added `take_profit_pct=0.0` to integration test (backward compat fix)

### Gate Result
2806/2806 passing, 100 skipped (PyYAML + E2E — expected). 21 scheduled jobs total. 5 strategies total.

---

## [2026-03-20] Session 41 — Phase 41 COMPLETE (Liquidity Filter + Dollar Volume Position Cap)

### New Files Created
- `services/risk_engine/liquidity.py` — `LiquidityService`: `is_liquid` (ADV >= min_liquidity_dollar_volume); `adv_capped_notional` (min of notional and max_pct_of_adv × ADV); `filter_for_liquidity` (OPEN-only: drops illiquid, caps survivors via dataclasses.replace; CLOSE/TRIM pass through); `liquidity_summary` (per-ticker status dict sorted by ADV desc)
- `apps/worker/jobs/liquidity.py` — `run_liquidity_refresh`: queries SecurityFeatureValue for latest dollar_volume_20d per ticker; stores in app_state.latest_dollar_volumes; fire-and-forget; graceful degradation on DB failure
- `apps/api/schemas/liquidity.py` — 3 Pydantic schemas: `TickerLiquiditySchema`, `LiquidityScreenResponse`, `TickerLiquidityDetailResponse`
- `apps/api/routes/liquidity.py` — `liquidity_router`: GET /portfolio/liquidity (full screen, sorted by ADV desc), GET /portfolio/liquidity/{ticker} (single-ticker detail, 200 with data_available=False when unknown)
- `tests/unit/test_phase41_liquidity.py` — 61 tests (8 classes: TestLiquidityServiceIsLiquid, TestLiquidityServiceAdvCap, TestLiquidityServiceFilter, TestLiquidityServiceSummary, TestLiquidityRefreshJob, TestLiquidityRefreshJobNoDb, TestLiquidityRouteScreen, TestLiquidityRouteDetail, TestPaperCycleLiquidityIntegration)

### Modified Files
- `config/settings.py` — Added `min_liquidity_dollar_volume: float = 1_000_000.0` and `max_position_as_pct_of_adv: float = 0.10`
- `apps/api/state.py` — Added `latest_dollar_volumes: dict`, `liquidity_computed_at: Optional[datetime]`, `liquidity_filtered_count: int`
- `apps/worker/jobs/__init__.py` — Added `run_liquidity_refresh` import + `__all__` entry
- `apps/worker/main.py` — Added `_job_liquidity_refresh` wrapper; `liquidity_refresh` job at 06:17 ET (21st total); schedule docstring updated
- `apps/worker/jobs/paper_trading.py` — Added Phase 41 liquidity filter block after sector filter; calls `LiquidityService.filter_for_liquidity`; updates `app_state.liquidity_filtered_count`
- `apps/api/routes/__init__.py` — Added `liquidity_router` import + `__all__` entry
- `apps/api/main.py` — Mounted `liquidity_router` at `/api/v1`
- `apps/dashboard/router.py` — Added `_render_liquidity_section`: cache status + bottom-10 ADV table with gate colour indicators; wired into `_render_page`
- 9 test files — job count assertions 20 → 21; job ID sets updated to include `liquidity_refresh`

### Gate Result
2758/2758 passing, 100 skipped (PyYAML + E2E — expected). 21 scheduled jobs total.

---

## [2026-03-20] Session 40 — Phase 40 COMPLETE (Sector Exposure Limits)

### New Files Created
- `services/risk_engine/sector_exposure.py` — `SectorExposureService`: `get_sector` (TICKER_SECTOR look-up, falls back to "other"); `compute_sector_weights` (sector → fraction of equity); `compute_sector_market_values` (sector → Decimal MV); `projected_sector_weight` (forward projection for candidate OPEN); `filter_for_sector_limits` (drops OPENs breaching max_sector_pct; CLOSE/TRIM always pass through)
- `apps/api/schemas/sector.py` — 3 Pydantic schemas: `SectorAllocationSchema`, `SectorExposureResponse`, `SectorDetailResponse`
- `apps/api/routes/sector.py` — `sector_router`: GET /portfolio/sector-exposure (full breakdown), GET /portfolio/sector-exposure/{sector} (single-sector detail)
- `tests/unit/test_phase40_sector_exposure.py` — 60 tests (8 classes)

### Modified Files
- `apps/api/state.py` — Added `sector_weights: dict` (sector → float), `sector_filtered_count: int`
- `apps/worker/jobs/paper_trading.py` — Added Phase 40 sector exposure filter block after correlation adjustment; calls `SectorExposureService.filter_for_sector_limits` on proposed OPEN actions; updates `app_state.sector_weights` and `app_state.sector_filtered_count`
- `apps/api/routes/__init__.py` — Added `sector_router` import + `__all__` entry
- `apps/api/main.py` — Mounted `sector_router` at `/api/v1`
- `apps/dashboard/router.py` — Added `_render_sector_section`: sector allocation table with at-limit colour indicators; wired into `_render_page`

### Gate Result
2697/2697 passing, 100 skipped (PyYAML + E2E — expected). No new scheduled job (sector filter is inline in the paper cycle).

---

## [2026-03-20] Session 39 — Phase 39 COMPLETE (Correlation-Aware Position Sizing)

### New Files Created
- `services/risk_engine/correlation.py` — `CorrelationService`: `compute_correlation_matrix` (Pearson, numpy, MIN_OBSERVATIONS=20); `get_pairwise` (symmetric look-up); `max_pairwise_with_portfolio` (max |corr| of candidate vs all open positions); `correlation_size_factor` (1.0 ≤ 0.50, linear decay to floor at 1.0); `adjust_action_for_correlation` (dataclasses.replace, OPEN-only, returns adjusted action)
- `apps/worker/jobs/correlation.py` — `run_correlation_refresh`: queries DailyMarketBar, computes daily returns, calls CorrelationService, stores matrix in app_state; fire-and-forget; graceful degradation on DB failure
- `apps/api/schemas/correlation.py` — 3 Pydantic schemas: `CorrelationPairSchema`, `CorrelationMatrixResponse`, `TickerCorrelationResponse`
- `apps/api/routes/correlation.py` — `correlation_router`: GET /portfolio/correlation (full matrix), GET /portfolio/correlation/{ticker} (ticker profile + portfolio max-corr)
- `tests/unit/test_phase39_correlation.py` — 60 tests (8 classes)

### Modified Files
- `config/settings.py` — Added `max_pairwise_correlation=0.75`, `correlation_lookback_days=60`, `correlation_size_floor=0.25`
- `apps/api/state.py` — Added `correlation_matrix: dict`, `correlation_tickers: list[str]`, `correlation_computed_at: Optional[datetime]`
- `apps/worker/jobs/__init__.py` — Added `run_correlation_refresh` import + `__all__` entry
- `apps/worker/main.py` — Added `_job_correlation_refresh` wrapper; `correlation_refresh` job at 06:16 ET (20th total); updated schedule docstring
- `apps/api/routes/__init__.py` — Added `correlation_router` import + `__all__` entry
- `apps/api/main.py` — Mounted `correlation_router` at `/api/v1`
- `apps/worker/jobs/paper_trading.py` — Added Phase 39 correlation adjustment block after `apply_ranked_opportunities`; calls `CorrelationService.adjust_action_for_correlation` for every OPEN action before risk validation
- `apps/dashboard/router.py` — Added `_render_correlation_section`: cache status + top-5 portfolio pair correlation table; wired into `_render_page`
- 11 test files — job count assertions 19 → 20; job ID sets updated to include `correlation_refresh`

---

## [2026-03-20] Session 38 — Phase 38 COMPLETE (Market Regime Detection + Regime-Adaptive Weight Profiles)

### New Files Created
- `services/signal_engine/regime_detection.py` — `MarketRegime` enum (4 values); `REGIME_DEFAULT_WEIGHTS` dict (4 regimes × 5 strategies, each summing to 1.0); `RegimeResult` dataclass; `RegimeDetectionService` (detect_from_signals: median + std_dev heuristics; get_regime_weights; set_manual_override; persist_snapshot: fire-and-forget)
- `infra/db/models/regime_detection.py` — `RegimeSnapshot` ORM (table: regime_snapshots; id, regime, confidence, detection_basis_json, is_manual_override, override_reason + TimestampMixin; 2 indexes)
- `infra/db/versions/h8i9j0k1l2m3_add_regime_snapshots.py` — Alembic migration (down_revision: g7h8i9j0k1l2)
- `apps/api/schemas/regime.py` — 5 Pydantic schemas: RegimeCurrentResponse, RegimeOverrideRequest, RegimeOverrideResponse, RegimeSnapshotSchema, RegimeHistoryResponse
- `apps/api/routes/regime.py` — `regime_router`: GET /signals/regime, POST /signals/regime/override, DELETE /signals/regime/override, GET /signals/regime/history
- `tests/unit/test_phase38_regime_detection.py` — 60 tests (16 classes)

### Modified Files
- `infra/db/models/__init__.py` — Added `RegimeSnapshot` import + `__all__` entry
- `apps/api/routes/__init__.py` — Added `regime_router` import + `__all__` entry
- `apps/api/main.py` — Mounted `regime_router` at `/api/v1`
- `apps/api/state.py` — Added `current_regime_result: Optional[Any]`, `regime_history: list[Any]`
- `apps/worker/jobs/signal_ranking.py` — Added `run_regime_detection` function
- `apps/worker/jobs/__init__.py` — Exported `run_regime_detection`
- `apps/worker/main.py` — Added `_job_regime_detection` wrapper; scheduled `regime_detection` at 06:20 ET (19th job total); updated docstring
- `apps/dashboard/router.py` — Added `_render_regime_section()`; wired into `_render_page()`
- 8 test files — Updated job count assertions 18→19; added `"regime_detection"` to job ID sets

### Gate
- **2502/2502 tests passing** (37 skipped: PyYAML absent — expected), coverage 88.51%

---

## [2026-03-20] Session 37 — Phase 37 COMPLETE (Strategy Weight Auto-Tuning)

### New Files Created
- `infra/db/models/weight_profile.py` — `WeightProfile` ORM (table: weight_profiles; id, profile_name, source, weights_json, sharpe_metrics_json, is_active, optimization_run_id, notes + timestamps; 2 indexes: ix_weight_profile_is_active, ix_weight_profile_created_at)
- `infra/db/versions/g7h8i9j0k1l2_add_weight_profiles.py` — Alembic migration (down_revision: f6a7b8c9d0e1)
- `services/signal_engine/weight_optimizer.py` — `WeightOptimizerService` (optimize_from_backtest: Sharpe-proportional weights; create_manual_profile; get_active_profile; list_profiles; set_active_profile; equal_weights classmethod; fire-and-forget DB persist); `WeightProfileRecord` dataclass
- `apps/api/schemas/weights.py` — 5 Pydantic schemas: WeightProfileSchema, WeightProfileListResponse, OptimizeWeightsResponse, SetActiveWeightResponse, CreateManualWeightRequest
- `apps/api/routes/weights.py` — `weights_router`: POST /optimize, GET /current, GET /history, PUT /active/{profile_id}, POST /manual
- `tests/unit/test_phase37_weight_optimizer.py` — 58 tests (12 classes)

### Files Modified
- `infra/db/models/__init__.py` — Added `WeightProfile` import + `__all__` export
- `apps/api/routes/__init__.py` — Added `weights_router` export
- `apps/api/main.py` — Mounted `weights_router` under `/api/v1`
- `apps/api/state.py` — Added `active_weight_profile: Optional[Any] = None`
- `apps/worker/jobs/signal_ranking.py` — Added `run_weight_optimization` job function
- `apps/worker/jobs/__init__.py` — Added `run_weight_optimization` export
- `apps/worker/main.py` — Added `_job_weight_optimization` wrapper + `weight_optimization` scheduled at 06:52 ET weekdays (18th job total); updated docstring
- `apps/dashboard/router.py` — Added `_render_weight_profile_section()` + wired into `_render_page()`
- `services/ranking_engine/service.py` — `rank_signals()` accepts optional `strategy_weights: dict[str, float]`; `_aggregate()` computes weighted-mean signal score when weights provided; falls back to anchor-best when single signal or no weights
- 7 test files (job count 17→18): test_worker_jobs.py, test_phase18_priority18.py, test_phase22_enrichment_pipeline.py, test_phase23_intelligence_api.py, test_phase29_fundamentals.py, test_phase35_auto_execution.py, test_phase36_phase36.py

---

## [2026-03-20] Session 36 — Phase 36 COMPLETE (Real-time Price Streaming, Alternative Data Integration, Promotion Confidence Scoring)

### New Files Created
- `services/alternative_data/__init__.py` — package marker
- `services/alternative_data/models.py` — `AlternativeDataRecord` dataclass (ticker, source, sentiment_score [-1,1], mention_count, raw_snippet, captured_at, id); `AlternativeDataSource` enum (social_mention, web_search_trend, employee_review, satellite, custom)
- `services/alternative_data/adapters.py` — `BaseAlternativeAdapter` ABC + `SocialMentionAdapter` (deterministic synthetic stub; sentiment = hash-derived, no external API)
- `services/alternative_data/service.py` — `AlternativeDataService` (ingest, get_records, get_ticker_sentiment, clear; in-memory store)
- `apps/api/schemas/prices.py` — `PriceTickSchema`, `PriceSnapshotResponse` Pydantic schemas
- `apps/api/routes/prices.py` — `GET /api/v1/prices/snapshot` (REST price snapshot) + `WebSocket /api/v1/prices/ws` (streams portfolio prices every 2s)
- `tests/unit/test_phase36_phase36.py` — 81 tests (15 classes)

### Files Modified
- `services/self_improvement/models.py` — Added `confidence_score: float = 0.0` field to `ImprovementProposal`
- `services/self_improvement/config.py` — Added `min_auto_execute_confidence: float = 0.70`
- `services/self_improvement/service.py` — Added `_compute_confidence_score(evaluation) -> float`; stamps `proposal.confidence_score` in `promote_or_reject()`
- `services/self_improvement/execution.py` — `auto_execute_promoted()`: new `min_confidence` param; `skipped_low_confidence` counter; returns `skipped_low_confidence` in summary dict
- `apps/api/schemas/self_improvement.py` — Added `skipped_low_confidence: int = 0` to `AutoExecuteSummaryResponse`
- `apps/api/routes/self_improvement.py` — `auto_execute` route: reads `min_auto_execute_confidence` from config, passes to service, surfaces `skipped_low_confidence` in response
- `apps/api/schemas/intelligence.py` — Added `AlternativeDataRecordSchema`, `AlternativeDataResponse`
- `apps/api/routes/intelligence.py` — Added `GET /api/v1/intelligence/alternative` (ticker filter, limit, returns AlternativeDataResponse)
- `apps/api/routes/__init__.py` — Exported `prices_router`
- `apps/api/main.py` — Mounted `prices_router` under `/api/v1`
- `apps/api/state.py` — Added `latest_alternative_data: list[Any]`
- `apps/worker/jobs/ingestion.py` — Added `run_alternative_data_ingestion` (SocialMentionAdapter + AlternativeDataService; writes to app_state; fire-and-forget; never raises)
- `apps/worker/jobs/__init__.py` — Exported `run_alternative_data_ingestion`
- `apps/worker/main.py` — Scheduled `alternative_data_ingestion` at 06:05 ET (17th job total); imported + wrapped in `_job_alternative_data_ingestion`
- `apps/dashboard/router.py` — Updated `_render_auto_execution_section`: shows confidence threshold (70%); added `_render_alternative_data_section` (source breakdown, bullish/bearish/neutral counts, recent 5 records table); both wired into `_render_page`
- `tests/unit/test_phase18_priority18.py` — Job count 16→17; docstring updated
- `tests/unit/test_phase22_enrichment_pipeline.py` — Job count 16→17; expected_job_ids set updated (+alternative_data_ingestion)
- `tests/unit/test_phase23_intelligence_api.py` — Job count 16→17
- `tests/unit/test_phase29_fundamentals.py` — Job count 16→17
- `tests/unit/test_phase35_auto_execution.py` — Job count 16→17; docstring updated
- `tests/unit/test_worker_jobs.py` — Job count 16→17; _EXPECTED_JOB_IDS updated

---

## [2026-03-20] Session 35 — Phase 35 COMPLETE (Self-Improvement Proposal Auto-Execution)

### New Files Created
- `apis/infra/db/models/proposal_execution.py` — `ProposalExecution` ORM (table: proposal_executions; 12 columns: id, proposal_id, proposal_type, target_component, config_delta_json, baseline_params_json, status, executed_at, rolled_back_at, notes, created_at, updated_at; 2 indexes: ix_proposal_exec_proposal_id, ix_proposal_exec_executed_at)
- `apis/infra/db/versions/f6a7b8c9d0e1_add_proposal_executions.py` — Alembic migration (down_revision: e5f6a7b8c9d0)
- `apis/services/self_improvement/execution.py` — `AutoExecutionService`: execute_proposal (apply candidate_params to runtime_overrides + update promoted_versions + fire-and-forget DB persist), rollback_execution (restore baseline_params + mark rolled_back), auto_execute_promoted (batch; skips protected/non-promoted/already-applied); `ExecutionRecord` dataclass
- `apis/apps/api/schemas/self_improvement.py` — 5 Pydantic schemas: ExecutionRecordSchema, ExecutionListResponse, ExecuteProposalResponse, RollbackExecutionResponse, AutoExecuteSummaryResponse
- `apis/apps/api/routes/self_improvement.py` — `self_improvement_router`: POST /api/v1/self-improvement/proposals/{id}/execute (400 on non-promoted/protected, 404 if not found), POST /api/v1/self-improvement/executions/{id}/rollback, GET /api/v1/self-improvement/executions?limit=50, POST /api/v1/self-improvement/auto-execute
- `apis/tests/unit/test_phase35_auto_execution.py` — 68 tests (11 classes: TestProposalExecutionORM, TestProposalExecutionMigration, TestExecutionRecord, TestAutoExecutionServiceExecute, TestAutoExecutionServiceRollback, TestAutoExecutionServiceBatch, TestAutoExecutionDBPersist, TestSelfImprovementSchemas, TestSelfImprovementRoutes, TestAutoExecuteWorkerJob, TestSchedulerNewJob)

### Files Modified
- `apis/infra/db/models/__init__.py` — Added `ProposalExecution` import and `__all__` export
- `apis/apps/api/routes/__init__.py` — Added `self_improvement_router` export
- `apis/apps/api/main.py` — Mounted `self_improvement_router` under `/api/v1`
- `apis/apps/api/state.py` — Added `applied_executions: list[Any]`, `runtime_overrides: dict[str, Any]`, `last_auto_execute_at: Optional[dt.datetime]`
- `apis/apps/worker/jobs/self_improvement.py` — Added `run_auto_execute_proposals` job function
- `apis/apps/worker/jobs/__init__.py` — Added `run_auto_execute_proposals` export
- `apis/apps/worker/main.py` — Added `_job_auto_execute_proposals` wrapper + `auto_execute_proposals` scheduled at 18:15 ET weekdays; updated docstring (16 jobs total)
- `apis/apps/dashboard/router.py` — Added `_render_auto_execution_section()` + wired into `_render_page()` between alert and promoted_versions sections
- 5 test files updated: job count assertions 15 → 16 (test_phase18_priority18, test_phase22_enrichment_pipeline, test_phase23_intelligence_api, test_phase29_fundamentals, test_worker_jobs); exact job ID set in test_phase22 + test_worker_jobs updated to include "auto_execute_proposals"

**Test count: 2371/2371 passing (100 skipped: PyYAML + E2E)**

---

## [2026-03-20] Session 34 — Phase 34 COMPLETE (Strategy Backtesting Comparison API + Dashboard)

### New Files Created
- `apis/infra/db/models/backtest.py` — `BacktestRun` ORM (table: backtest_runs; 17 columns: id, comparison_id, strategy_name, start/end dates, ticker_count, tickers_json, total_return_pct, sharpe_ratio, max_drawdown_pct, win_rate, total_trades, days_simulated, final_portfolio_value, initial_cash, status, run_note + timestamps; index on comparison_id + created_at)
- `apis/infra/db/versions/e5f6a7b8c9d0_add_backtest_runs.py` — Alembic migration (down_revision: d4e5f6a7b8c9)
- `apis/services/backtest/comparison.py` — `BacktestComparisonService`: runs 5 individual strategy backtests + 1 combined (all_strategies) per request; persists each as a `BacktestRun` row; fire-and-forget DB writes; engine_factory injection for testability
- `apis/apps/api/schemas/backtest.py` — 6 Pydantic schemas: `BacktestCompareRequest`, `BacktestRunRecord`, `BacktestComparisonResponse`, `BacktestComparisonSummary`, `BacktestRunListResponse`, `BacktestRunDetailResponse`
- `apis/apps/api/routes/backtest.py` — `backtest_router`: `POST /api/v1/backtest/compare`, `GET /api/v1/backtest/runs`, `GET /api/v1/backtest/runs/{comparison_id}`
- `apis/tests/unit/test_phase34_backtest_comparison.py` — 50 tests (11 classes)

### Files Modified
- `apis/infra/db/models/__init__.py` — Added `BacktestRun` import and `__all__` export
- `apis/apps/api/routes/__init__.py` — Added `backtest_router` export
- `apis/apps/api/main.py` — Mounted `backtest_router` under `/api/v1`
- `apis/apps/dashboard/router.py` — Added `GET /dashboard/backtest` sub-page (strategy comparison table); updated nav bar to include Backtest link on all three pages; `_render_backtest_page()` queries DB for latest 5 comparison groups, degrades gracefully when DB unavailable

**Test count: 2303/2303 passing (100 skipped: PyYAML + E2E)**

---

## [2026-03-20] Session 33 — Phase 33 COMPLETE (Operator Dashboard Enhancements)

### New Files Created
- `apis/tests/unit/test_phase33_dashboard.py` — 56 tests (11 classes): TestDashboardImport, TestDashboardHomeBasics, TestDashboardAutoRefresh, TestDashboardNavigation, TestDashboardPaperCycleSection, TestDashboardPortfolioSection, TestDashboardPerformanceSection, TestDashboardRecentTradesSection, TestDashboardTradeGradesSection, TestDashboardIntelSection, TestDashboardSignalRunsSection, TestDashboardAlertServiceSection, TestDashboardExistingSections, TestDashboardPositionsPage

### Files Modified
- `apis/apps/dashboard/router.py` — Added 8 new section renderers (paper cycle, realized performance, recent closed trades, trade grades, intel feed, signal runs, alert service, enhanced portfolio); added `_fmt_usd`/`_fmt_pct` helpers; added `_page_wrap()` with auto-refresh support; added nav bar (Overview/Positions links); added `GET /dashboard/positions` sub-page route; auto-refresh every 60 s on both pages

**Test count: 2253/2253 passing (37 skipped: PyYAML + E2E)**

---

## [2026-03-20] Session 32 — Phase 32 COMPLETE (Position-level P&L History)

### New Files Created
- `apis/infra/db/versions/d4e5f6a7b8c9_add_position_history.py` — Alembic migration adding `position_history` table (down_revision: c2d3e4f5a6b7); includes `ix_pos_hist_ticker_snapshot` composite index
- `apis/tests/unit/test_phase32_position_history.py` — 41 tests (10 classes): TestPositionHistoryORM, TestPositionHistoryMigration, TestPositionHistorySchemas, TestPersistPositionHistory, TestPersistPositionHistoryNoPositions, TestPersistPositionHistoryInPaperCycle, TestPositionHistoryEndpoint, TestPositionHistoryEndpointFallback, TestPositionSnapshotsEndpoint, TestPositionSnapshotsEndpointFallback, TestHelperFunction

### Files Modified
- `apis/infra/db/models/portfolio.py` — Added `PositionHistory` ORM model (table: position_history; 11 columns: id, ticker, snapshot_at, quantity, avg_entry_price, current_price, market_value, cost_basis, unrealized_pnl, unrealized_pnl_pct + timestamps)
- `apis/infra/db/models/__init__.py` — Added `PositionHistory` import and `__all__` export
- `apis/apps/worker/jobs/paper_trading.py` — Added `_persist_position_history(portfolio_state, snapshot_at)` fire-and-forget helper; wired after portfolio snapshot persist when positions non-empty
- `apis/apps/api/schemas/portfolio.py` — Added `PositionHistoryRecord`, `PositionHistoryResponse`, `PositionLatestSnapshotResponse` Pydantic schemas
- `apis/apps/api/routes/portfolio.py` — Added `GET /portfolio/positions/{ticker}/history?limit=30`, `GET /portfolio/position-snapshots`, and `_pos_hist_row_to_record()` helper; imported new schemas

**Test count: 2197/2197 passing (100 skipped: PyYAML + E2E)**

---

## [2026-03-20] Session 31 — Phase 31 COMPLETE (Operator Alert Webhooks)

### New Files Created
- `apis/services/alerting/__init__.py` — Package exports: `AlertEvent`, `AlertEventType`, `AlertSeverity`, `WebhookAlertService`
- `apis/services/alerting/models.py` — `AlertSeverity` enum (info/warning/critical), `AlertEventType` enum (6 event types), `AlertEvent` dataclass (event_type, severity, title, payload, timestamp)
- `apis/services/alerting/service.py` — `WebhookAlertService`: `send_alert()` (never raises), `_build_payload()`, `_sign()` (HMAC-SHA256), `_post_with_retry()` (configurable retries); `make_alert_service()` factory
- `apis/tests/unit/test_phase31_operator_webhooks.py` — 57 tests (18 classes): TestAlertModels, TestWebhookAlertServiceInit, TestWebhookAlertServiceDisabled, TestBuildPayload, TestSignature, TestPostWithRetrySuccess, TestPostWithRetryNon2xx, TestPostWithRetryNetworkError, TestSendAlertSuccess, TestSendAlertNeverRaises, TestSettingsWebhookFields, TestAppStateAlertService, TestKillSwitchAlertWiring, TestBrokerAuthExpiredAlert, TestPaperCycleFatalErrorAlert, TestDailyEvaluationAlert, TestTestWebhookEndpoint, TestMakeAlertServiceFactory

### Files Modified
- `apis/config/settings.py` — Added `webhook_url`, `webhook_secret`, `alert_on_kill_switch`, `alert_on_paper_cycle_error`, `alert_on_broker_auth_expiry`, `alert_on_daily_evaluation` (all with safe defaults)
- `apis/apps/api/state.py` — Added `alert_service: Optional[Any] = None` field to `ApiAppState`
- `apis/apps/api/routes/admin.py` — Added `POST /api/v1/admin/test-webhook` endpoint; wired kill switch activation/deactivation to fire CRITICAL/WARNING webhook alerts
- `apis/apps/worker/jobs/paper_trading.py` — `BrokerAuthenticationError` path fires `broker_auth_expired` CRITICAL alert; outer fatal exception path fires `paper_cycle_error` WARNING alert
- `apis/apps/worker/jobs/evaluation.py` — Successful scorecard fires `daily_evaluation` alert (INFO if return >= -1%, WARNING if worse)
- `apis/apps/worker/main.py` — `_setup_alert_service()` initializes `app_state.alert_service` at worker startup
- `apis/apps/api/main.py` — `_load_persisted_state()` extended to initialize `app_state.alert_service` at API startup
- `apis/.env.example` — Added `APIS_WEBHOOK_URL`, `APIS_WEBHOOK_SECRET`, `APIS_ALERT_ON_*` vars

### Key Design Decisions
- `send_alert` never raises; all failures logged at WARNING, return False — operator alerts are fire-and-forget
- HMAC-SHA256 signing optional: `X-APIS-Signature: sha256=<hex>` header only when `APIS_WEBHOOK_SECRET` set
- Per-event flags default True: new URL receives all alerts without manual configuration
- `alert_service` stored in `ApiAppState` — consistent with existing broker/execution service pattern
- Jobs use `getattr(app_state, 'alert_service', None)` — zero breaking change to existing function signatures
- `POST /admin/test-webhook` returns 503 when webhook URL not configured (not silently 200)

### Test Results
- **Phase 31 tests**: 57/57 PASSED
- **Full suite**: 2156/2156 PASSED (37 skipped: PyYAML absent)

---

## [2026-03-19] Session 30 — Phase 30 COMPLETE (DB-backed Signal/Rank Persistence)

### Files Modified
- `apis/services/signal_engine/service.py` — Added `SignalRun` to import; `run()` now inserts a `SignalRun(id=signal_run_id, status="in_progress")` row + flush before processing signals; sets `status="completed"` + flush at end
- `apis/apps/api/state.py` — Added `last_signal_run_id: Optional[str]` and `last_ranking_run_id: Optional[str]` fields to `ApiAppState` (Phase 30 signal/ranking tracking)
- `apis/apps/worker/jobs/signal_ranking.py` — `run_signal_generation`: writes `app_state.last_signal_run_id` on success; `run_ranking_generation`: gains `session_factory` param; takes DB path (`svc.run()`) when `session_factory` + `last_signal_run_id` both present, otherwise in-memory fallback; always writes `app_state.last_ranking_run_id`
- `apis/apps/api/routes/__init__.py` — Added `signals_router`, `rankings_router` imports and exports
- `apis/apps/api/main.py` — Mounted `signals_router` + `rankings_router` under `/api/v1`

### New Files Created
- `apis/apps/api/schemas/signals.py` — 6 Pydantic schemas: `SignalRunRecord`, `SignalRunHistoryResponse`, `RankedOpportunityRecord`, `RankingRunRecord`, `RankingRunHistoryResponse`, `RankingRunDetailResponse`
- `apis/apps/api/routes/signals_rankings.py` — 4 endpoints: `GET /signals/runs` (list signal runs, graceful degradation), `GET /rankings/runs` (list ranking runs), `GET /rankings/latest` (newest run detail), `GET /rankings/runs/{run_id}` (specific run detail); UUID validation before session check
- `apis/tests/unit/test_phase30_signal_rank_persistence.py` — 36 tests (8 classes): `TestAppStatePhase30Fields`, `TestSignalEngineServiceSignalRun`, `TestRunSignalGenerationState`, `TestRunRankingGenerationDbPath`, `TestSignalRunSchema`, `TestSignalRunsEndpoint`, `TestRankingRunsEndpoint`, `TestRankingsLatestEndpoint`, `TestRankingRunByIdEndpoint`

### Key Design Decisions
- `SignalRun` status transitions: `in_progress` → `completed`; allows detecting interrupted runs
- `run_ranking_generation` DB path is purely additive — no existing tests broken
- List endpoints always return 200 with empty list on DB failure (graceful degradation)
- Detail endpoints return 503 (DB unavailable) or 404 (run not found) as appropriate
- UUID format validation returns 422 before any DB access

### Test Results
- **Phase 30 tests**: 36/36 PASSED
- **Full suite**: 2099/2099 PASSED (37 skipped: PyYAML absent)

---

## [2026-03-20] Session 29 — Phase 29 COMPLETE (Fundamentals Data Layer + ValuationStrategy)

### Files Modified
- `apis/services/feature_store/models.py` — Added 7 fundamentals overlay fields to `FeatureSet`: `pe_ratio`, `forward_pe`, `peg_ratio`, `price_to_sales`, `eps_growth`, `revenue_growth`, `earnings_surprise_pct` (all `Optional[float] = None`)
- `apis/services/feature_store/enrichment.py` — `enrich()` and `enrich_batch()` accept `fundamentals_store: Optional[dict] = None`; added `_apply_fundamentals()` static method using `dataclasses.replace()`
- `apis/services/signal_engine/service.py` — Added `ValuationStrategy()` as 5th default strategy; `run()` accepts and passes through `fundamentals_store`
- `apis/services/signal_engine/strategies/__init__.py` — Added `ValuationStrategy` import and `__all__` export
- `apis/apps/api/state.py` — Added `latest_fundamentals: dict` field (`ticker → FundamentalsData`)
- `apis/apps/worker/jobs/ingestion.py` — Added `run_fundamentals_refresh()` job function
- `apis/apps/worker/jobs/__init__.py` — Exported `run_fundamentals_refresh`
- `apis/apps/worker/main.py` — Added `_job_fundamentals_refresh()` wrapper; scheduled at 06:18 ET weekdays; total jobs now **15**
- `apis/apps/worker/jobs/signal_ranking.py` — `run_signal_generation` passes `fundamentals_store` from `app_state` to `svc.run()`
- `apis/tests/unit/test_worker_jobs.py` — 14→15 job count; added `fundamentals_refresh` to expected job IDs
- `apis/tests/integration/test_research_pipeline_integration.py` — 4→5 signals, 8→10, added `valuation_v1`, 4→5 contributing signals
- `apis/tests/simulation/test_paper_cycle_simulation.py` — 4→5 strategies, added `valuation_v1` assertion
- `apis/tests/unit/test_phase18_priority18.py` — job count 14→15
- `apis/tests/unit/test_phase21_signal_enhancement.py` — strategy count 4→5
- `apis/tests/unit/test_phase22_enrichment_pipeline.py` — `**kwargs` in side_effect helpers, counts 14→15
- `apis/tests/unit/test_phase23_intelligence_api.py` — job count 14→15

### New Files Created
- `apis/services/market_data/fundamentals.py` — `FundamentalsData` dataclass + `FundamentalsService` (yfinance-backed; per-ticker isolated fetch; `_safe_positive_float`, `_safe_float`, `_extract_earnings_surprise`)
- `apis/services/signal_engine/strategies/valuation.py` — `ValuationStrategy` (`valuation_v1`): 4 sub-scores (forward_pe, peg_ratio, eps_growth, earnings_surprise), re-normalized weights, confidence = n_available/4, neutral fallback (0.5/0.0) when all None
- `apis/tests/unit/test_phase29_fundamentals.py` — 8 test classes, ~45 tests

### Key Design Decisions
- yfinance isolation: each ticker fetch is wrapped in try/except; failures → None fields (never crash batch)
- `dataclasses.replace()` exclusively — no mutation of FeatureSet or FundamentalsData
- Negative P/E → None via `_safe_positive_float`; growth rates may be negative via `_safe_float`
- `confidence = n_available / 4` — explicitly represents data sparsity in the signal
- Neutral score (0.5) returned when no fundamentals data to avoid false bullish/bearish bias
- 06:18 ET pre-market timing ensures fundamentals are loaded before 09:35 signal generation

### Test Results
- **Phase 29 tests**: 45/45 PASSED
- **Full suite**: 2063/2063 PASSED (37 skipped: PyYAML absent)

---

## [2026-03-19] Session 28 — Phase 28 COMPLETE (Live Performance Summary + Closed Trade Grading + P&L Metrics)

### Files Modified
- `apis/apps/api/state.py` — Added `trade_grades: list[Any]` field to `ApiAppState`
- `apis/apps/worker/jobs/paper_trading.py` — Phase 28 grading block: uses `_pre_record_count` to identify newly-added closed trades, converts each to `TradeRecord`, calls `EvaluationEngineService.grade_closed_trade()`, appends `PositionGrade` to `app_state.trade_grades`
- `apis/apps/api/schemas/portfolio.py` — Added `TradeGradeRecord`, `TradeGradeHistoryResponse`, `PerformanceSummaryResponse` Pydantic schemas
- `apis/apps/api/routes/portfolio.py` — Added `GET /api/v1/portfolio/performance` (equity, SOD equity, HWM, daily return pct, drawdown from HWM, realized/unrealized P&L, win rate) + `GET /api/v1/portfolio/grades` (letter grades, grade distribution, ticker filter) routes
- `apis/apps/api/routes/metrics.py` — Added 3 Prometheus gauges: `apis_realized_pnl_usd`, `apis_unrealized_pnl_usd`, `apis_daily_return_pct`

### New Files Created
- `apis/tests/unit/test_phase28_performance_summary.py` — NEW: 33 tests (9 classes): TestPerformanceSummarySchema, TestTradeGradeSchemas, TestPerformanceEndpointNoState, TestPerformanceSummaryEquityMetrics, TestPerformanceSummaryRealizedPnl, TestPerformanceSummaryUnrealized, TestTradeGradeEndpoint, TestPaperCycleGradeIntegration, TestPrometheusMetricsPhase28

### Key Design Decisions
- Grading uses `_pre_record_count` snapshot to detect only trades closed in the CURRENT cycle
- `TradeRecord.strategy_key = ""` (ClosedTrade model does not track originating strategy)
- Naive `opened_at` timestamps normalized to UTC before conversion
- `drawdown_from_hwm_pct` clamped to ≥ 0 (equity above HWM → 0% drawdown, not negative)
- `win_rate = None` when no closed trades (avoid division by zero; distinguishes "no data" from 0%)

### Test Results
- **Phase 28 tests**: 33/33 PASSED
- **Full suite**: 1995/1995 PASSED (37 skipped: PyYAML absent)

---

## [2026-03-19] Session 27 — Phase 27 COMPLETE (Closed Trade Ledger + Start-of-Day Equity Refresh)

### Files Modified
- `apis/services/portfolio_engine/models.py` — Added `ClosedTrade` dataclass (ticker, action_type, fill_price, avg_entry_price, quantity, realized_pnl, realized_pnl_pct, reason, opened_at, closed_at, hold_duration_days; `is_winner` property)
- `apis/apps/api/state.py` — Added `closed_trades: list[Any]` and `last_sod_capture_date: Optional[dt.date]` fields to `ApiAppState`
- `apis/apps/worker/jobs/paper_trading.py` — (A) SOD equity block: first cycle of each trading day captures `start_of_day_equity` and updates `high_water_mark`; (B) Closed trade recording block: after `execute_approved_actions` and before broker sync, captures CLOSE/TRIM fills as `ClosedTrade` records appended to `app_state.closed_trades`
- `apis/apps/api/schemas/portfolio.py` — Added `ClosedTradeRecord` and `ClosedTradeHistoryResponse` response schemas
- `apis/apps/api/routes/portfolio.py` — Added `GET /api/v1/portfolio/trades` endpoint (filter by ticker, limit, aggregates: total_realized_pnl, win_rate, win/loss count)
- `apis/services/risk_engine/service.py` — Upgraded `dt.datetime.utcnow()` → `dt.datetime.now(dt.timezone.utc)`; normalizes naive `opened_at` for backward compatibility in age expiry calculation

### New Files Created
- `apis/tests/unit/test_phase27_trade_ledger.py` — NEW: 46 tests (8 classes): TestClosedTradeModel, TestAppStateNewFields, TestSodEquityRefresh, TestClosedTradeRecordingLogic, TestTradeHistoryEndpoint, TestTradeHistoryFiltering, TestTradeHistoryAggregates, TestPaperCycleWithTradeLedger

### Key Design Decisions
- Closed trades stored in-memory only (no DB FK complexity with securities table at this stage)
- Trade recording happens BEFORE broker sync (broker sync removes closed positions from `portfolio_state.positions`, so P&L must be captured first)
- SOD equity captured once per trading day, date-gated via `last_sod_capture_date`
- CLOSE supersedes TRIM for same ticker (carried from Phase 26 deduplication logic)

### Test Results
- **Phase 27 tests**: 46/46 PASSED
- **Full suite**: 1962/1962 PASSED (37 skipped: PyYAML absent)

---

## [2026-03-19] Session 26 — Phase 26 COMPLETE (TRIM Execution + Overconcentration Trim Trigger)

### Files Modified
- `apis/services/execution_engine/service.py` — `ActionType.TRIM` routed in `execute_action()` dispatch; `_execute_trim(request)` private method: validates `target_quantity > 0`, queries broker position, caps sell at `min(target_qty, position.qty)`, places SELL MARKET order; returns FILLED or REJECTED
- `apis/services/risk_engine/service.py` — Added `from decimal import Decimal, ROUND_DOWN` import (ROUND_DOWN was missing); added `evaluate_trims(portfolio_state) -> list[PortfolioAction]` method after `evaluate_exits`: detects overconcentration (`market_value > equity * max_single_name_pct`), computes shares via `ROUND_DOWN`, returns pre-approved TRIM actions
- `apis/apps/worker/jobs/paper_trading.py` — Overconcentration TRIM evaluation block added after exit evaluation merge; iterates `evaluate_trims()` results, adds TRIM to `proposed_actions` only if ticker not in `already_closing` (CLOSE supersedes TRIM)
- `apis/tests/unit/test_phase25_exit_strategy.py` — Updated 2 tests: TRIM now returns `REJECTED` (not `ERROR`) when no position; error message references ticker not "Unsupported action_type"

### New Files Created
- `apis/tests/unit/test_phase26_trim_execution.py` — NEW: 46 tests (11 classes): TestTrimExecutionFilled, TestTrimExecutionRejected, TestTrimExecutionKillSwitch, TestTrimExecutionBrokerErrors, TestEvaluateTrimsBasic, TestEvaluateTrimsNoTrigger, TestEvaluateTrimsKillSwitch, TestEvaluateTrimsEdgeCases, TestExecutionEngineTrimRouting, TestPaperCycleTrimIntegration

### Test Results
- **Phase 26 tests**: 46/46 PASSED
- **Full suite**: 1916/1916 PASSED (37 skipped: PyYAML absent)

---

## [2026-03-18] Session 14 — Phase 13 COMPLETE (Live Mode Gate + Secrets + Grafana)

### New Files Created
- `apis/services/live_mode_gate/__init__.py` — package init; exports GateRequirement, GateStatus, LiveModeGateResult, LiveModeGateService
- `apis/services/live_mode_gate/models.py` — GateStatus enum, GateRequirement dataclass (passed property), LiveModeGateResult dataclass (all_passed, failed_requirements)
- `apis/services/live_mode_gate/service.py` — LiveModeGateService.check_prerequisites(); gate checks for PAPER→HUMAN_APPROVED (5 cycles, 5 eval, ≤2 errors, portfolio init) and HUMAN_APPROVED→RESTRICTED_LIVE (20 cycles, 10 eval, rankings available, ≤2 errors, portfolio init); advisory message when all pass
- `apis/config/secrets.py` — SecretManager ABC, EnvSecretManager (reads os.environ, raises KeyError on missing/empty), AWSSecretManager scaffold (raises NotImplementedError with boto3 guidance), get_secret_manager() factory
- `apis/apps/api/schemas/live_gate.py` — PromotableMode enum, GateRequirementSchema, LiveGateStatusResponse, LiveGatePromoteRequest, LiveGatePromoteResponse
- `apis/apps/api/routes/live_gate.py` — GET /api/v1/live-gate/status (run gate for current→next mode, cache in state), POST /api/v1/live-gate/promote (advisory workflow: gate check → record if pass)
- `apis/infra/monitoring/grafana_dashboard.json` — Full Grafana dashboard: 11 data panels + 3 row separators; stat/timeseries types; kill switch, paper loop, positions, equity, cash, rankings, cycles, evaluations, proposals; Prometheus data source variable; 30s auto-refresh
- `apis/tests/unit/test_phase13_live_gate.py` — 88 Phase 13 gate tests across 11 test classes

### Files Modified
- `apis/apps/api/state.py` — Added Phase 13 fields: `live_gate_last_result`, `live_gate_promotion_pending`
- `apis/apps/api/routes/__init__.py` — Added `live_gate_router` export
- `apis/apps/api/main.py` — Mounted `live_gate_router` under `/api/v1`

### Test Results
- **Phase 13 tests**: 88/88 PASSED
- **Full suite**: 810/810 PASSED

---

## [2026-03-19] Session 13 — Phase 12 COMPLETE (Live Paper Trading Loop)

### New Files Created
- `apis/apps/worker/jobs/paper_trading.py` — `run_paper_trading_cycle`: full paper trading pipeline job; mode guard (PAPER/HUMAN_APPROVED only); ranked→portfolio→risk→execute→reconcile loop; structured result dict; all exceptions caught
- `apis/broker_adapters/schwab/adapter.py` — `SchwabBrokerAdapter`: Schwab OAuth 2.0 REST API scaffold; all methods raise `NotImplementedError` with implementation guidance; auth guard raises `BrokerAuthenticationError` if `client_id` is empty
- `apis/infra/docker/docker-compose.yml` — Full Docker Compose: postgres (v17), redis (v7-alpine), api (uvicorn 0.0.0.0:8000), worker (APScheduler); healthchecks on postgres/redis; depends_on healthy
- `apis/infra/docker/Dockerfile` — Multi-stage build: `builder` (pip install) → `api` (uvicorn) / `worker` (python apps/worker/main.py) targets
- `apis/infra/docker/init-db.sql` — Creates `apis_test` database alongside primary `apis` DB
- `apis/apps/api/routes/metrics.py` — Prometheus-compatible scrape endpoint `GET /metrics`; hand-crafted plain-text output; exposes: `apis_paper_loop_active`, `apis_paper_cycle_count`, `apis_position_count`, `apis_portfolio_equity`, `apis_kill_switch_active`, `apis_ranking_count`, `apis_evaluation_history_count`, `apis_info`
- `apis/tests/unit/test_phase12_paper_loop.py` — 76 Phase 12 gate tests across 8 test classes

### Files Modified
- `apis/apps/api/state.py` — Added Phase 12 paper loop fields: `paper_loop_active`, `last_paper_cycle_at`, `paper_cycle_count`, `paper_cycle_errors`
- `apis/apps/worker/jobs/__init__.py` — Added `run_paper_trading_cycle` export
- `apis/apps/worker/main.py` — Added `_job_paper_trading_cycle` wrapper + 2 scheduler entries (morning 09:30, midday); scheduler now has 11 jobs
- `apis/broker_adapters/schwab/__init__.py` — Added `SchwabBrokerAdapter` export
- `apis/apps/api/routes/__init__.py` — Added `metrics_router` export
- `apis/apps/api/main.py` — Mounted `metrics_router` (no prefix, accessible at `/metrics`)
- `apis/tests/unit/test_worker_jobs.py` — Updated `_EXPECTED_JOB_IDS` to include `paper_trading_cycle_morning` + `paper_trading_cycle_midday`; renamed `test_scheduler_has_exactly_nine_jobs` → `test_scheduler_has_exactly_eleven_jobs` (count 9→11)

### Test Results
- **Phase 12 tests**: 76/76 PASSED
- **Full suite**: 722/722 PASSED

---

## [2026-03-19] Session 12 — Phase 11 COMPLETE (Concrete Implementations + Backtest)

### Packages Installed
- `ib_insync 0.9.86` — asyncio IBKR TWS/Gateway client used by IBKRBrokerAdapter

### New Files Created
- `apis/services/market_data/models.py` — `NormalizedBar` (dollar_volume property), `LiquidityMetrics` (is_liquid_enough, tier), `MarketSnapshot`
- `apis/services/market_data/config.py` — `MarketDataConfig`: universe, yfinance interval mapping, max history
- `apis/services/market_data/utils.py` — `classify_liquidity_tier`, `compute_liquidity_metrics`
- `apis/services/market_data/service.py` — `MarketDataService`: yfinance-backed bar fetching, snapshot building, no DB dependency
- `apis/services/market_data/__init__.py`, `schemas.py`
- `apis/services/news_intelligence/utils.py` — POSITIVE_WORDS (35+), NEGATIVE_WORDS (40+), THEME_KEYWORDS (12 themes), score_sentiment, extract_tickers_from_text, detect_themes, generate_market_implication
- `apis/services/macro_policy_engine/utils.py` — EVENT_TYPE_SECTORS/THEMES/DEFAULT_BIAS/BASE_CONFIDENCE dicts, compute_directional_bias, generate_implication_summary
- `apis/services/rumor_scoring/utils.py` — extract_tickers_from_rumor (regex), normalize_source_text (strips whitespace, caps 500 chars)
- `apis/services/backtest/__init__.py` — package init
- `apis/services/backtest/models.py` — `DayResult`, `BacktestResult` (net_profit property)
- `apis/services/backtest/config.py` — `BacktestConfig` (validate() checks date ordering + ticker list)
- `apis/services/backtest/engine.py` — `BacktestEngine.run()`: day-by-day simulation, synthetic fills, Sharpe ratio, max drawdown, win rate, trading_days helper
- `apis/tests/unit/test_phase11_implementations.py` — 71 Phase 11 gate tests across 14 test classes

### Files Modified
- `apis/services/news_intelligence/service.py` — replaced stub with concrete NLP pipeline: credibility weight × keyword sentiment × ticker extraction × theme detection; returns `NewsInsight`
- `apis/services/macro_policy_engine/service.py` — replaced stub with concrete `process_event` (non-zero bias/confidence) + `assess_regime` (RISK_ON/RISK_OFF/STAGFLATION/NEUTRAL)
- `apis/services/theme_engine/utils.py` — replaced stub with `TICKER_THEME_REGISTRY`; 50 tickers × 12 themes with `BeneficiaryOrder` + `thematic_score`
- `apis/services/theme_engine/service.py` — replaced stub with registry-backed `get_exposure` (score filtering)
- `apis/broker_adapters/ibkr/adapter.py` — replaced file with concrete ib_insync implementation: connect/disconnect/ping, place_order (4 order types), cancel_order, get/list orders/positions/fills, is_market_open, next_market_open; paper-port guard + idempotency set. **Removed old scaffold (was lines 430-739; contained § SyntaxError on Python 3.14)**
- `apis/tests/unit/test_service_stubs.py` — updated 3 tests no longer valid with concrete impls
- `apis/tests/unit/test_ibkr_adapter.py` — added `_ensure_event_loop` autouse fixture; updated `TestIBKRAdapterMethodStubs` (NotImplementedError → BrokerConnectionError)
- `apis/state/ACTIVE_CONTEXT.md`, `NEXT_STEPS.md`, `SESSION_HANDOFF_LOG.md` — updated

### Key Bug Fixes
- **BacktestEngine `_simulate_day`**: `portfolio_svc.open/close_position()` returns `PortfolioAction` proposals (does NOT mutate state). Fixed with direct `PortfolioPosition` construction and `portfolio_state.positions[ticker] =` assignment.
- **BacktestEngine list comprehension scope**: `b` was used after `for b in bars` comprehension — Python 3 comprehensions have own scope. Fixed with `last_bar = bars[-1]`.
- **BacktestEngine `MomentumStrategy.score()`**: Engine called with wrong kwargs. Actual signature: `score(self, feature_set: FeatureSet)`. Fixed.
- **ib_insync/eventkit event loop**: `eventkit.util` calls `asyncio.get_event_loop()` at import time. Python 3.14 no longer creates implicit event loop. Fixed with `_ensure_event_loop` autouse fixture (`asyncio.new_event_loop()` + `asyncio.set_event_loop()`).

### Gate Results
- **Phase 11 COMPLETE — 646/646 tests** (71 new + 575 prior; no regressions)
  - ✅ market_data, news_intelligence, macro_policy_engine, theme_engine, rumor_scoring: concrete implementations
  - ✅ IBKRBrokerAdapter: full ib_insync implementation replacing scaffold
  - ✅ BacktestEngine: day-by-day simulation complete and correct
  - ✅ All prior gates A–H unaffected

---

## [2026-03-18] Session 11 — Phase 10 Steps 3 & 4 (IBKR Scaffold + Dashboard)

### New Files Created
- `apis/broker_adapters/ibkr/adapter.py` — `IBKRBrokerAdapter` architecture-ready scaffold. Implements full `BaseBrokerAdapter` interface; all operational methods raise `NotImplementedError` with implementation guidance (ib_insync pattern, port constants, translation notes). Constructor safety guard rejects live ports (7496/4001) when `paper=True`.
- `apis/apps/dashboard/router.py` — `dashboard_router` (FastAPI `APIRouter`, prefix `/dashboard`). Single route `GET /dashboard/` returns a self-contained HTML page drawn from `ApiAppState`: system status, portfolio summary, top-5 rankings, scorecard, self-improvement proposals, promoted versions. Zero external template-engine deps (inline HTML).
- `apis/tests/unit/test_ibkr_adapter.py` — 25 tests across 3 classes: `TestIBKRAdapterImportAndIdentity` (4), `TestIBKRAdapterConstruction` (7), `TestIBKRAdapterMethodStubs` (14).
- `apis/tests/unit/test_dashboard.py` — 15 tests across 2 classes: `TestDashboardImport` (3), `TestDashboardHomeRoute` (12).

### Files Modified
- `apis/broker_adapters/ibkr/__init__.py` — replaced one-liner stub with `IBKRBrokerAdapter` export.
- `apis/apps/dashboard/__init__.py` — replaced one-liner stub with `dashboard_router` export.
- `apis/apps/api/main.py` — mounted `dashboard_router` (no prefix, accessible at `/dashboard/`).

### Gate Results
- **Phase 10 COMPLETE — 575/575 tests** (40 new + 535 prior; no regressions)
  - ✅ IBKR scaffold importable, inherits `BaseBrokerAdapter`, live-port safety guard functional
  - ✅ Dashboard route returns 200 HTML, reflects ApiAppState fields correctly
  - ✅ All prior gates A–H unaffected

---

## [2026-03-17] Session 10 — Phase 9 Background Worker Jobs (APScheduler)

### Packages Installed
- `apscheduler 3.11.2` — in-process task scheduler (pytz already present as transitive dep)

### New Files Created
- `apis/apps/worker/jobs/ingestion.py` — `run_market_data_ingestion` (fetch + persist OHLCV bars for universe), `run_feature_refresh` (compute + persist baseline features). Both skip gracefully when `session_factory=None` (returns `status=skipped_no_session`). Exceptions caught; returns structured result dict.
- `apis/apps/worker/jobs/signal_ranking.py` — `run_signal_generation` (DB-backed signal generation via `SignalEngineService.run()`), `run_ranking_generation` (in-memory `RankingEngineService.rank_signals()` + writes `ApiAppState.latest_rankings`, `ranking_run_id`, `ranking_as_of`). Both accept injected services for testing.
- `apis/apps/worker/jobs/evaluation.py` — `run_daily_evaluation` (builds `PortfolioSnapshot` from live `ApiAppState.portfolio_state` or empty fallback → `EvaluationEngineService.generate_daily_scorecard()` → writes `ApiAppState.latest_scorecard` + `evaluation_history`), `run_attribution_analysis` (standalone attribution log job).
- `apis/apps/worker/jobs/reporting.py` — `run_generate_daily_report` (reads portfolio/scorecard/proposals from `ApiAppState` → `ReportingService.generate_daily_report()` → writes `ApiAppState.latest_daily_report` + `report_history`), `run_publish_operator_summary` (structured operator log entry). Helper `_derive_grade` extracts letter grade from scorecard.
- `apis/apps/worker/jobs/self_improvement.py` — `run_generate_improvement_proposals` (reads `ApiAppState.latest_scorecard` + `promoted_versions` → `SelfImprovementService.generate_proposals()` → writes `ApiAppState.improvement_proposals`). Grade derived via `_scorecard_to_grade`; attribution summary via `_build_attribution_summary`.
- `apis/tests/unit/test_worker_jobs.py` — 49 Gate H tests across 8 classes: `TestIngestionJobs` (6), `TestSignalRankingJobs` (8), `TestEvaluationJobs` (10), `TestReportingJobs` (9), `TestSelfImprovementJobs` (8), `TestScheduler` (3), `TestWorkerJobsImports` (1), `TestEndToEndPipeline` (4).

### Files Modified
- `apis/apps/api/state.py` — Added `improvement_proposals: list[Any]` field to `ApiAppState` (background jobs write here; reporting reads here).
- `apis/apps/worker/jobs/__init__.py` — Replaced stub with full exports of all 9 job functions.
- `apis/apps/worker/main.py` — Full APScheduler `BackgroundScheduler` wiring; `build_scheduler()` factory; 9 cron jobs on US/Eastern weekday schedule; graceful SIGTERM/SIGINT shutdown; `_make_session_factory()` helper with fallback.

### Gate Results
- **Gate H: PASSED — 494/494 tests** (49 new Gate H + 445 prior; no regressions)
- Gate H criteria verified per spec §8.1–8.7:
  - ✅ `run_market_data_ingestion` — skips cleanly without DB; returns structured result
  - ✅ `run_feature_refresh` — skips cleanly without DB; returns structured result
  - ✅ `run_signal_generation` — skips cleanly without DB; returns structured result
  - ✅ `run_ranking_generation` — in-memory path; writes `latest_rankings` to `ApiAppState`
  - ✅ `run_daily_evaluation` — zero-portfolio fallback; writes `latest_scorecard` + history
  - ✅ `run_attribution_analysis` — standalone attribution log; returns counts
  - ✅ `run_generate_daily_report` — reads state; writes `latest_daily_report` + history
  - ✅ `run_publish_operator_summary` — structured operator log; safe when state is empty
  - ✅ `run_generate_improvement_proposals` — reads scorecard grade + attribution; writes proposals
  - ✅ `build_scheduler()` — returns configured scheduler with 9 jobs (mon–fri, US/Eastern)
  - ✅ `ApiAppState.improvement_proposals` added; all prior route tests still pass

---

## [2026-03-17] Session 5 — Phase 4 Portfolio + Risk Engine

### New Files Created
- `apis/services/portfolio_engine/models.py` — `PortfolioPosition` (market_value/cost_basis/unrealized_pnl/unrealized_pnl_pct properties), `PortfolioState` (equity/gross_exposure/drawdown_pct/daily_pnl_pct derived properties), `ActionType` enum (OPEN/CLOSE/BLOCKED), `PortfolioAction`, `SizingResult`, `PortfolioSnapshot` (replaces stub)
- `apis/services/portfolio_engine/service.py` — `PortfolioEngineService`: `apply_ranked_opportunities` (opens top buys up to max_positions, closes stale), `open_position`, `close_position` (explainable exits with thesis from position), `snapshot`, `compute_sizing` (half-Kelly: f*=0.5×max(0,2p−1); capped at min(sizing_hint_pct, max_single_name_pct)) (replaces stub)
- `apis/services/risk_engine/models.py` — `RiskSeverity` (HARD_BLOCK/WARNING), `RiskViolation`, `RiskCheckResult` (`is_hard_blocked` property, `adjusted_max_notional`) (replaces stub)
- `apis/services/risk_engine/service.py` — `RiskEngineService`: `validate_action` (master gatekeeper), `check_kill_switch`, `check_portfolio_limits` (max_positions hard_block + max_single_name_pct size warning), `check_daily_loss_limit`, `check_drawdown` (replaces stub)
- `apis/services/execution_engine/models.py` — `ExecutionStatus` (FILLED/REJECTED/BLOCKED/ERROR), `ExecutionRequest`, `ExecutionResult` (replaces stub)
- `apis/services/execution_engine/service.py` — `ExecutionEngineService`: `execute_action` (kill-switch guard, OPEN→BUY market order floor(notional/price) shares, CLOSE→SELL full position via broker, all exceptions → structured results), `execute_approved_actions` batch (replaces stub)
- `apis/tests/unit/test_portfolio_engine.py` — 40 Gate C tests (PortfolioState, PortfolioPosition, sizing, open/close, apply_ranked_opportunities, snapshot)
- `apis/tests/unit/test_risk_engine.py` — 22 Gate C tests (kill_switch, max_positions, max_single_name_pct, daily_loss_limit, drawdown, validate_action master gatekeeper)
- `apis/tests/unit/test_execution_engine.py` — 15 Gate C tests (kill switch blocks, open fills, close fills, rejected on no position, batch execution, partial failure isolation)

### Gate Results
- **Gate C: PASSED — 185/185 tests** (77 new Gate C + 108 Gate B + 44 Gate A; no regressions)
- Gate C criteria verified:
  - ✅ sizing and exposure rules work (half-Kelly formula verified, max_single_name_pct cap verified)
  - ✅ invalid trades are blocked (kill_switch, max_positions, daily_loss_limit, drawdown all generate hard_block violations)
  - ✅ exits are explainable (thesis_summary from original position attached to every CLOSE action)
  - ✅ limits are enforced (validate_action aggregates all violations; action.risk_approved set only on full pass)

---

## [2026-03-18] Session 4 — Phase 3 Research Engine

### New Packages Installed
- `yfinance==1.2.0` — market data adapter
- `pandas==3.0.1` — dataframe operations
- `numpy==2.4.3` — numerical operations (transitive dep)

### New Files Created
- `apis/config/universe.py` — 50-ticker universe config across 8 segments; `get_universe_tickers()` helper; `TICKER_SECTOR` map
- `apis/services/data_ingestion/models.py` — `BarRecord`, `IngestionRequest`, `IngestionResult`, `TickerResult`, `IngestionStatus` (replaces stub)
- `apis/services/data_ingestion/adapters/__init__.py` — adapters sub-package
- `apis/services/data_ingestion/adapters/yfinance_adapter.py` — `YFinanceAdapter` (source_key="yfinance", reliability_tier="secondary_verified"); `fetch_bars`, `fetch_bulk`, `_normalise_df`
- `apis/services/data_ingestion/service.py` — `DataIngestionService` (ingest_universe_bars, ingest_single_ticker, get_or_create_security, persist_bars via pg_insert ON CONFLICT DO NOTHING)
- `apis/services/feature_store/models.py` — `FeatureSet`, `ComputedFeature`, `FEATURE_KEYS`, `FEATURE_GROUP_MAP` (replaces stub)
- `apis/services/feature_store/pipeline.py` — `BaselineFeaturePipeline` (11 features: momentum×3, risk×2, liquidity×1, trend×5; all individually testable)
- `apis/services/feature_store/service.py` — `FeatureStoreService` (ensure_feature_catalog, compute_and_persist, get_features)
- `apis/services/signal_engine/models.py` — `SignalOutput`, `HorizonClassification`, `SignalType` (replaces stub)
- `apis/services/signal_engine/strategies/__init__.py` — strategies sub-package
- `apis/services/signal_engine/strategies/momentum.py` — `MomentumStrategy` (weighted sub-scores, explanation_dict with rationale + driver_features, source_reliability_tier, contains_rumor=False)
- `apis/services/signal_engine/service.py` — `SignalEngineService` (run + score_from_features, _ensure_strategy_rows, _persist_signal)
- `apis/services/ranking_engine/models.py` — `RankedResult`, `RankingConfig` (replaces stub)
- `apis/services/ranking_engine/service.py` — `RankingEngineService` (rank_signals in-memory + run DB path; composite score, thesis_summary, disconfirming_factors, sizing_hint, source_reliability_tier, contains_rumor propagation)
- `apis/tests/unit/test_data_ingestion.py` — 13 Gate B tests (adapter, models, service)
- `apis/tests/unit/test_feature_store.py` — 17 Gate B tests (pipeline + FeatureSet helpers)
- `apis/tests/unit/test_signal_engine.py` — 16 Gate B tests (MomentumStrategy + SignalEngineService)
- `apis/tests/unit/test_ranking_engine.py` — 18 Gate B tests (RankingEngineService + end-to-end pipeline)

### Gate Results
- **Gate B: PASSED — 108/108 tests** (64 new + 44 Gate A retained)
- Gate B criteria verified:
  - ✅ ranking pipeline runs (TestEndToEndPipeline.test_full_pipeline_no_db)
  - ✅ outputs are explainable (thesis_summary + explanation_dict.rationale on every output)
  - ✅ sources are tagged by reliability (source_reliability_tier on BarRecord + SignalOutput + RankedResult)
  - ✅ rumors separated from verified facts (contains_rumor flag propagated through full pipeline)

---



### Top-Level Files Created
- `apis/README.md` — project summary, architecture table, setup instructions, governing doc index
- `apis/pyproject.toml` — project metadata, dependencies, ruff/mypy/pytest config
- `apis/requirements.txt` — flat requirements file
- `apis/.env.example` — non-secret environment variable template
- `apis/.gitignore` — standard Python + data/secrets gitignore

### State Files Created
- `apis/state/ACTIVE_CONTEXT.md` — initial ground truth
- `apis/state/NEXT_STEPS.md` — Phase 1 next actions + future phase plan
- `apis/state/DECISION_LOG.md` — 10 founding architecture decisions (DEC-001 through DEC-010)
- `apis/state/CHANGELOG.md` — this file
- `apis/state/SESSION_HANDOFF_LOG.md` — session checkpoint log initialized

### Config Layer Created
- `apis/config/__init__.py`
- `apis/config/settings.py` — pydantic-settings `Settings` class with all env vars
- `apis/config/logging_config.py` — structlog structured JSON logging setup

### Broker Adapter Layer Created
- `apis/broker_adapters/base/__init__.py`
- `apis/broker_adapters/base/adapter.py` — `BaseBrokerAdapter` abstract base class
- `apis/broker_adapters/base/models.py` — `Order`, `Fill`, `Position`, `AccountState` domain models
- `apis/broker_adapters/base/exceptions.py` — broker exception hierarchy
- `apis/broker_adapters/paper/__init__.py`
- `apis/broker_adapters/paper/adapter.py` — `PaperBrokerAdapter` full implementation

### Strategy, App, and Service Stubs Created
- 6 strategy stubs: `long_term`, `swing`, `event_driven`, `theme_rotation`, `ai_theme`, `policy_trade`
- 16 service stubs: `data_ingestion`, `market_data`, `news_intelligence`, `macro_policy_engine`, `theme_engine`, `rumor_scoring`, `feature_store`, `signal_engine`, `ranking_engine`, `portfolio_engine`, `risk_engine`, `execution_engine`, `evaluation_engine`, `self_improvement`, `reporting`, `continuity`
- 3 app stubs: `apps/api/`, `apps/worker/`, `apps/dashboard/`
- Other directories: `data/`, `research/`, `infra/`, `scripts/`, `models/`

### Test Harness Created
- `apis/tests/__init__.py`
- `apis/tests/conftest.py` — shared fixtures for paper broker and config
- `apis/tests/unit/__init__.py`
- `apis/tests/unit/test_config.py` — config loads correctly, env vars validated
- `apis/tests/unit/test_paper_broker.py` — paper broker: place order, fill order, get state
- `apis/tests/integration/__init__.py`
- `apis/tests/e2e/__init__.py`
- `apis/tests/simulation/__init__.py`
- `apis/tests/fixtures/__init__.py`

### Gate A Status
**PASSED** — 44/44 unit tests passing.
- `TestSettingsLoad` — 9/9 pass
- `TestLoggingConfig` — 3/3 pass (fixed: use `stdlib.LoggerFactory` not `PrintLoggerFactory`)
- `TestLifecycle` — 3/3 pass
- `TestOrderPlacementAndFill` — 6/6 pass
- `TestCashAccounting` — 3/3 pass
- `TestPositions` — 7/7 pass
- `TestSafetyInvariants` — 6/6 pass
- `TestOrderCancellation` — 2/2 pass
- `TestAccountState` — 3/3 pass
- `TestFillRetrieval` — 2/2 pass

### Python environment
- Python 3.14.3 (workspace)
- Virtual env: `apis/.venv/`
- Key packages: pydantic 2.12.5, pydantic-settings 2.13.1, structlog 25.5.0, pytest 9.0.2

---

## [2026-03-17] Session 2 — PostgreSQL Provisioning

### Infrastructure
- PostgreSQL 17.9 installed via EDB installer (winget-cached, UAC-elevated)
- Service `postgresql-x64-17` running, Automatic start
- Databases created: `apis` (UTF8), `apis_test` (UTF8)
- postgres superuser password set to `ApisDev2026!` (trust-mode reset)
- `C:\Program Files\PostgreSQL\17\bin` added to user PATH
- `.env` file created with real connection string

### Python Packages Added to Venv
- sqlalchemy 2.0.48
- alembic 1.18.4
- psycopg 3.3.3 (psycopg[binary])
- redis 7.3.0

---

## [2026-03-17] Session 3 — Phase 2 Database Layer

### Alembic Environment
- `apis/alembic.ini` — Alembic config; `script_location = infra/db`; `prepend_sys_path = .`
- `apis/infra/__init__.py` — Python package init
- `apis/infra/db/__init__.py` — Python package init
- `apis/infra/db/env.py` — migration env; reads DB URL from `get_settings()`; imports Base
- `apis/infra/db/script.py.mako` — standard Alembic migration file template

### ORM Models (infra/db/models/)
- `base.py` — `Base` (DeclarativeBase) + `TimestampMixin` (created_at, updated_at)
- `reference.py` — `Security`, `Theme`, `SecurityTheme`
- `source.py` — `Source`, `SourceEvent`, `SecurityEventLink`
- `market_data.py` — `DailyMarketBar`, `SecurityLiquidityMetric`
- `analytics.py` — `Feature`, `SecurityFeatureValue`
- `signal.py` — `Strategy`, `SignalRun`, `SecuritySignal`, `RankingRun`, `RankedOpportunity`
- `portfolio.py` — `PortfolioSnapshot`, `Position`, `Order`, `Fill`, `RiskEvent`
- `evaluation.py` — `EvaluationRun`, `EvaluationMetric`, `PerformanceAttribution`
- `self_improvement.py` — `ImprovementProposal`, `ImprovementEvaluation`, `PromotedVersion`
- `audit.py` — `DecisionAudit`, `SessionCheckpoint`
- `__init__.py` — re-exports all 28 model classes + Base

### Database Utilities
- `apis/infra/db/session.py` — `engine`, `SessionLocal`, `get_db()` (FastAPI dep), `db_session()` (context mgr)

### Migration
- `apis/infra/db/versions/9ed5639351bb_initial_schema.py` — autogenerated; creates all 28 tables + 15 indexes
- Applied to `apis` (29 rows in pg_tables incl. `alembic_version`)
- Applied to `apis_test` (29 rows)
- `alembic check` → "No new upgrade operations detected"

### Gate Status
- Gate A unit tests: **44/44 PASSED** (no regressions)
- Gate A DB check: **PASSED** (`alembic upgrade head` clean on both databases)
