"""APIS API application state.

Holds the latest results produced by background worker jobs.
Routes read from this state; worker jobs write to it.
All fields default to empty/None — routes return "no data yet"
responses until the state has been populated.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


@dataclass
class ApiAppState:
    """Mutable in-memory application state shared by all API routes.

    One instance lives for the lifetime of the API process.  Background
    jobs (Phase 9) populate fields here; route handlers read from them.
    """

    # --- Ranking ---------------------------------------------------------
    latest_rankings: list[Any] = field(default_factory=list)   # list[RankedResult]
    ranking_run_id: str | None = None
    ranking_as_of: dt.datetime | None = None

    # --- Portfolio -------------------------------------------------------
    portfolio_state: Any | None = None                       # PortfolioState | None

    # --- Actions / Risk --------------------------------------------------
    proposed_actions: list[Any] = field(default_factory=list)  # list[PortfolioAction]
    blocked_action_count: int = 0
    active_warnings: list[str] = field(default_factory=list)
    execution_engine: Any | None = None      # ExecutionEngineService | None

    # --- Evaluation ------------------------------------------------------
    latest_scorecard: Any | None = None                     # DailyScorecard | None
    evaluation_run_id: str | None = None
    evaluation_history: list[Any] = field(default_factory=list)

    # --- Reports ---------------------------------------------------------
    latest_daily_report: Any | None = None                  # DailyOperationalReport | None
    report_history: list[Any] = field(default_factory=list)

    # --- Self-improvement ------------------------------------------------
    improvement_proposals: list[Any] = field(default_factory=list)   # list[ImprovementProposal]

    # --- Config tracking -------------------------------------------------
    promoted_versions: dict[str, str] = field(default_factory=dict)  # component → label

    # --- Paper trading loop ----------------------------------------------
    broker_adapter: Any | None = None            # BaseBrokerAdapter | None
    paper_loop_active: bool = False
    last_paper_cycle_at: dt.datetime | None = None
    paper_cycle_results: list[Any] = field(default_factory=list)  # list[dict]

    # --- Live mode gate --------------------------------------------------
    live_gate_last_result: Any | None = None     # LiveModeGateResult | None
    live_gate_promotion_pending: bool = False        # advisory recorded, awaiting operator action

    # --- Broker auth expiry ----------------------------------------------
    # Set True by the paper trading job when BrokerAuthenticationError is raised
    # during broker connect.  Surfaced in /health and /metrics so operators
    # are alerted before the market opens without working broker credentials.
    broker_auth_expired: bool = False
    broker_auth_expired_at: dt.datetime | None = None

    # --- Runtime kill switch (Priority 19) --------------------------------
    # Separates the env-var kill_switch (settings.kill_switch) from a
    # runtime-mutable flag that can be toggled via POST /api/v1/admin/kill-switch
    # without restarting the process.  Persisted to the system_state DB table
    # on every change so it survives process restarts.
    #
    # Effective kill switch = kill_switch_active OR settings.kill_switch.
    # If settings.kill_switch (env) is True the runtime flag cannot be
    # deactivated via the API alone — the env var must be cleared first.
    kill_switch_active: bool = False
    kill_switch_activated_at: dt.datetime | None = None
    kill_switch_activated_by: str | None = None   # source IP or "env"

    # --- Paper trading counters (Priority 19) ----------------------------
    # Durable counter incremented on every successful cycle completion and
    # persisted to DB so live-gate cycle-count checks survive restarts.
    paper_cycle_count: int = 0

    # --- Portfolio snapshot tracking (Priority 20) ------------------------
    # Set by _load_persisted_state() at startup from the latest DB snapshot
    # so the API can surface the last known equity baseline even before the
    # first in-process cycle completes.
    last_snapshot_at: dt.datetime | None = None
    last_snapshot_equity: float | None = None

    # --- Intelligence pipeline state (Phase 22) ---------------------------
    # Populated by run_feature_enrichment (06:22 job); consumed by
    # run_signal_generation to enrich FeatureSets before strategy scoring.
    # Empty lists = neutral overlays (safe default when no intel is available).
    latest_policy_signals: list[Any] = field(default_factory=list)
    latest_news_insights: list[Any] = field(default_factory=list)
    current_macro_regime: str = "NEUTRAL"

    # --- Closed trade ledger (Phase 27) ------------------------------------------
    # Populated by paper_trading.py after each CLOSE or TRIM fill.
    # Persists for the lifetime of the process (reset only on restart).
    closed_trades: list[Any] = field(default_factory=list)    # list[ClosedTrade]

    # Tracks the last date on which start-of-day equity was captured so the
    # paper trading cycle only refreshes SOD equity once per trading day.
    last_sod_capture_date: dt.date | None = None

    # --- Trade grading (Phase 28) ------------------------------------------------
    # Populated by paper_trading.py: for each newly recorded ClosedTrade,
    # EvaluationEngineService.grade_closed_trade() is called and the resulting
    # PositionGrade appended here.  Persists for the lifetime of the process.
    trade_grades: list[Any] = field(default_factory=list)    # list[PositionGrade]

    # --- Fundamentals overlay (Phase 29) -----------------------------------------
    # Populated by run_fundamentals_refresh (06:18 ET job).
    # Dict of ticker → FundamentalsData; consumed by FeatureEnrichmentService
    # to apply valuation overlays (P/E, PEG, EPS growth, earnings surprise)
    # before strategy scoring.  Empty dict = no fundamentals data yet (safe default).
    latest_fundamentals: dict = field(default_factory=dict)  # ticker → FundamentalsData

    # --- Signal/ranking run tracking (Phase 30) ----------------------------------
    # Populated by run_signal_generation after each DB-persisted signal run so
    # run_ranking_generation can link RankingRun → SignalRun via FK.
    last_signal_run_id: str | None = None      # UUID string of last SignalRun persisted
    last_ranking_run_id: str | None = None     # UUID string of last RankingRun persisted

    # --- Operator webhook alert service (Phase 31) --------------------------------
    # Initialized at worker / API startup from settings.webhook_url.
    # None = not yet initialized (send_alert calls are no-ops if URL is empty).
    # Jobs read this field directly via getattr(app_state, 'alert_service', None).
    alert_service: Any | None = None           # WebhookAlertService | None

    # --- Alternative data (Phase 36) ---------------------------------------------
    # Populated by run_alternative_data_ingestion (06:05 ET job).
    # List of AlternativeDataRecord objects; newest-first after each ingest batch.
    latest_alternative_data: list[Any] = field(default_factory=list)

    # --- Strategy weight profile (Phase 37) --------------------------------------
    # Populated by run_weight_optimization (06:52 ET job) or POST /signals/weights/optimize.
    # None = no active profile yet; ranking engine falls back to equal weighting.
    active_weight_profile: Any | None = None   # WeightProfileRecord | None

    # --- Market regime detection (Phase 38) --------------------------------------
    # Populated by run_regime_detection (06:20 ET job) or POST /signals/regime/override.
    # None = no detection has run yet; regime routes return SIDEWAYS / 0.0 stub.
    # current_regime_result: most recent RegimeResult (automated or manual override).
    # regime_history: last 30 RegimeResult objects (newest last); persists for process lifetime.
    current_regime_result: Any | None = None   # RegimeResult | None
    regime_history: list[Any] = field(default_factory=list)   # list[RegimeResult]

    # --- Correlation matrix cache (Phase 39) --------------------------------------
    # Populated by run_correlation_refresh (06:16 ET job).
    # correlation_matrix: dict keyed by (ticker_a, ticker_b) → Pearson correlation float.
    # correlation_tickers: ordered list of tickers included in the last computation.
    # correlation_computed_at: UTC datetime of the last successful matrix computation.
    correlation_matrix: dict = field(default_factory=dict)    # {(str, str): float}
    correlation_tickers: list[str] = field(default_factory=list)
    correlation_computed_at: dt.datetime | None = None

    # --- Sector exposure cache (Phase 40) -----------------------------------------
    # Populated during each paper trading cycle after the sector filter step.
    # sector_weights: dict of sector → fraction of portfolio equity [0.0, 1.0].
    # sector_filtered_count: number of OPEN actions dropped by sector limit this cycle.
    sector_weights: dict = field(default_factory=dict)        # {sector: float}
    sector_filtered_count: int = 0

    # --- Liquidity filter cache (Phase 41) ----------------------------------------
    # Populated by run_liquidity_refresh (06:17 ET job).
    # latest_dollar_volumes: dict of ticker → float (dollar_volume_20d).
    # liquidity_computed_at: UTC datetime of the last successful refresh.
    # liquidity_filtered_count: OPEN actions dropped by liquidity gate this cycle.
    latest_dollar_volumes: dict = field(default_factory=dict)  # {ticker: float}
    liquidity_computed_at: dt.datetime | None = None
    liquidity_filtered_count: int = 0

    # --- Portfolio VaR cache (Phase 43) -------------------------------------------
    # Populated by run_var_refresh (06:19 ET job).
    # latest_var_result: most recent VaRResult (None until first run).
    # var_computed_at: UTC datetime of the last successful VaR computation.
    # var_filtered_count: OPEN actions blocked by VaR gate this cycle.
    latest_var_result: Any | None = None        # VaRResult | None
    var_computed_at: dt.datetime | None = None
    var_filtered_count: int = 0

    # --- Stress test cache (Phase 44) ---------------------------------------------
    # Populated by run_stress_test (06:21 ET job).
    # latest_stress_result: most recent StressTestResult (None until first run).
    # stress_computed_at: UTC datetime of the last successful stress computation.
    # stress_blocked_count: OPEN actions blocked by stress gate this cycle.
    latest_stress_result: Any | None = None     # StressTestResult | None
    stress_computed_at: dt.datetime | None = None
    stress_blocked_count: int = 0

    # --- Signal quality tracking (Phase 46) ---------------------------------------
    # Populated by run_signal_quality_update (17:20 ET job).
    # latest_signal_quality: most recent SignalQualityReport (None until first run).
    # signal_quality_computed_at: UTC datetime of the last successful computation.
    latest_signal_quality: Any | None = None   # SignalQualityReport | None
    signal_quality_computed_at: dt.datetime | None = None

    # --- Earnings calendar cache (Phase 45) ---------------------------------------
    # Populated by run_earnings_refresh (06:23 ET job).
    # latest_earnings_calendar: most recent EarningsCalendarResult (None until first run).
    # earnings_computed_at: UTC datetime of the last successful calendar fetch.
    # earnings_filtered_count: OPEN actions blocked by earnings gate this cycle.
    latest_earnings_calendar: Any | None = None  # EarningsCalendarResult | None
    earnings_computed_at: dt.datetime | None = None
    earnings_filtered_count: int = 0

    # --- Drawdown Recovery Mode (Phase 47) ----------------------------------------
    # drawdown_state: current DrawdownState string ("NORMAL", "CAUTION", "RECOVERY").
    # drawdown_state_changed_at: UTC datetime of the last state transition (None = no change yet).
    drawdown_state: str = "NORMAL"
    drawdown_state_changed_at: dt.datetime | None = None

    # --- Portfolio Rebalancing Engine (Phase 49) -----------------------------------
    # Populated by run_rebalance_check (06:26 ET job).
    # rebalance_targets: dict of ticker → target weight fraction (equal-weight over top N).
    # rebalance_computed_at: UTC datetime of the last successful check.
    # rebalance_drift_count: number of tickers with actionable drift this cycle.
    rebalance_targets: dict = field(default_factory=dict)   # {ticker: float}
    rebalance_computed_at: dt.datetime | None = None
    rebalance_drift_count: int = 0

    # --- Dynamic Universe Management (Phase 48) ------------------------------------
    # Populated by run_universe_refresh (06:25 ET job).
    # active_universe: ordered list of tickers in the current active universe.
    #   Defaults to [] (empty) until the first refresh; signal/ranking jobs fall
    #   back to UNIVERSE_TICKERS when this list is empty.
    # universe_computed_at: UTC datetime of the last successful refresh.
    # universe_override_count: number of active operator overrides applied.
    active_universe: list[str] = field(default_factory=list)
    universe_computed_at: dt.datetime | None = None
    universe_override_count: int = 0

    # --- Factor Exposure Monitoring (Phase 50) ------------------------------------
    # Populated by the paper trading cycle after portfolio sync.
    # latest_factor_exposure: most recent FactorExposureResult (None until first cycle).
    # factor_exposure_computed_at: UTC datetime of the last successful computation.
    latest_factor_exposure: Any | None = None   # FactorExposureResult | None
    factor_exposure_computed_at: dt.datetime | None = None

    # --- Trailing stop peak price tracking (Phase 42) ----------------------------
    # Populated by the paper trading cycle each run. Maps ticker → highest price
    # seen since the position was opened. Used by evaluate_exits() to compute
    # the trailing stop level. Resets to {} on process restart (conservative:
    # peak restarts from current price, so no phantom trailing stop triggers).
    position_peak_prices: dict[str, float] = field(default_factory=dict)

    # --- Self-improvement auto-execution (Phase 35) ------------------------------
    # applied_executions: in-memory list of ExecutionRecord objects appended by
    # AutoExecutionService.execute_proposal(); persists for process lifetime.
    # runtime_overrides: dict of candidate_params applied by executions; consumed
    # by downstream services that check for parameter overrides.
    # last_auto_execute_at: timestamp of the most recent auto-execute batch run.
    applied_executions: list[Any] = field(default_factory=list)  # list[ExecutionRecord]
    runtime_overrides: dict[str, Any] = field(default_factory=dict)
    last_auto_execute_at: dt.datetime | None = None

    # --- Order Fill Quality Tracking (Phase 52) -----------------------------------
    # fill_quality_records: in-memory list of FillQualityRecord objects.
    #   One record appended per filled order by the paper trading cycle.
    #   Persists for the lifetime of the process (reset on restart).
    # fill_quality_summary: most recent FillQualitySummary; computed by
    #   run_fill_quality_update at 18:05 ET.
    # fill_quality_updated_at: UTC timestamp of the last successful summary run.
    fill_quality_records: list[Any] = field(default_factory=list)  # list[FillQualityRecord]
    fill_quality_summary: Any | None = None     # FillQualitySummary | None
    fill_quality_updated_at: dt.datetime | None = None

    # --- Live-Mode Readiness Report (Phase 53) ------------------------------------
    # Pre-computed nightly snapshot of all live-gate requirements.
    # latest_readiness_report: most recent ReadinessReport (None until first run).
    # readiness_report_computed_at: UTC timestamp of the last successful generation.
    latest_readiness_report: Any | None = None   # ReadinessReport | None
    readiness_report_computed_at: dt.datetime | None = None

    # --- Factor Tilt Alerts (Phase 54) --------------------------------------------
    # last_dominant_factor: the dominant factor name from the most recent paper cycle
    #   in which factor exposure was computed. None until the first cycle runs.
    # factor_tilt_events: in-memory list of FactorTiltEvent objects (newest last).
    #   Persists for the lifetime of the process (reset on restart).
    last_dominant_factor: str | None = None
    factor_tilt_events: list[Any] = field(default_factory=list)

    # --- Fill Quality Alpha-Decay Attribution (Phase 55) -------------------------
    # Populated by run_fill_quality_attribution (18:32 ET).
    # fill_quality_attribution_summary: most recent AlphaDecaySummary (None until first run).
    # fill_quality_attribution_updated_at: UTC timestamp of last successful attribution run.
    fill_quality_attribution_summary: Any | None = None   # AlphaDecaySummary | None
    fill_quality_attribution_updated_at: dt.datetime | None = None


# Module-level singleton — one per process
_app_state: ApiAppState = ApiAppState()


def get_app_state() -> ApiAppState:
    """FastAPI dependency — returns the shared application state."""
    return _app_state


def reset_app_state() -> None:
    """Replace the singleton with a fresh instance.  Used in tests."""
    global _app_state
    _app_state = ApiAppState()
