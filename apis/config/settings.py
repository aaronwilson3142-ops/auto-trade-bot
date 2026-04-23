"""
APIS application settings loaded from environment variables via pydantic-settings.

All config must flow through this module. No scattered os.getenv() calls in service code.
"""
from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# -- Deep-Dive Plan Step 1 (2026-04-16) -- centralized AI-bias defaults ------
# These defaults preserve the literals previously embedded in
# services/ranking_engine/service.py (_AI_RANKING_BONUS) and
# services/signal_engine/strategies/theme_alignment.py (_AI_THEME_BONUS).
# Promoted to config/settings.py for reversibility (DEC-032 keeps the values
# frozen; moving them to config does not change the operator bet).
_DEFAULT_AI_RANKING_BONUS_MAP: dict[str, float] = {
    "ai_infrastructure":   0.08,
    "ai_applications":     0.07,
    "semiconductors":      0.06,
    "cybersecurity":       0.06,
    "power_infrastructure": 0.06,
    "networking":          0.06,
    "data_centres":        0.05,
    "cloud_software":      0.04,
    "mega_cap_tech":       0.03,
}

_DEFAULT_AI_THEME_BONUS_MAP: dict[str, float] = {
    "ai_infrastructure":   1.35,
    "ai_applications":     1.30,
    "semiconductors":      1.25,
    "cybersecurity":       1.25,
    "power_infrastructure": 1.25,
    "networking":          1.25,
    "data_centres":        1.20,
    "cloud_software":      1.15,
}


class OperatingMode(str, Enum):
    """Valid APIS operating modes in progression order."""

    RESEARCH = "research"
    BACKTEST = "backtest"
    PAPER = "paper"
    HUMAN_APPROVED = "human_approved"
    RESTRICTED_LIVE = "restricted_live"


class Environment(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class DataSource(str, Enum):
    """Market-data provider used by the DataIngestionService."""

    YFINANCE = "yfinance"
    POINTINTIME = "pointintime"


class UniverseSource(str, Enum):
    """Source for the base trading universe."""

    STATIC = "static"
    POINTINTIME = "pointintime"


class Settings(BaseSettings):
    """
    Central settings object for APIS.

    Loaded from environment variables with APIS_ prefix.
    May also load from a .env file in the project root.
    """

    model_config = SettingsConfigDict(
        env_prefix="APIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # -- Application ------------------------------------------------------
    env: Environment = Environment.DEVELOPMENT
    debug: bool = False
    log_level: str = "INFO"
    operating_mode: OperatingMode = OperatingMode.RESEARCH

    # -- Database ---------------------------------------------------------
    db_url: Annotated[str, Field(min_length=5)] = (
        "postgresql+psycopg://user:password@localhost:5432/apis"
    )
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    db_pool_recycle: int = Field(default=1800, ge=60)
    db_pool_timeout: int = Field(default=30, ge=1)

    # -- Cache ------------------------------------------------------------
    redis_url: str = "redis://localhost:6379/0"

    # -- API Server -------------------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1, le=65535)
    allowed_cors_origins: list[str] = Field(
        default=[
            "http://localhost:8000",
            "http://127.0.0.1:8000",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ]
    )

    # -- Risk Controls ----------------------------------------------------
    max_positions: int = Field(default=10, ge=1, le=50)
    max_new_positions_per_day: int = Field(default=3, ge=1, le=10)
    daily_loss_limit_pct: float = Field(default=0.02, gt=0.0, le=0.10)
    weekly_drawdown_limit_pct: float = Field(default=0.05, gt=0.0, le=0.20)
    monthly_drawdown_limit_pct: float = Field(default=0.10, gt=0.0, le=0.50)
    max_single_name_pct: float = Field(default=0.20, gt=0.0, le=1.0)
    max_sector_pct: float = Field(default=0.40, gt=0.0, le=1.0)
    # AI-Heavy Bias (2026-04-16)
    max_thematic_pct: float = Field(default=0.75, gt=0.0, le=1.0)

    # -- Exit Strategy Thresholds -----------------------------------------
    stop_loss_pct: float = Field(default=0.07, gt=0.0, le=0.50)
    max_position_age_days: int = Field(default=20, ge=1, le=365)
    exit_score_threshold: float = Field(default=0.40, ge=0.0, le=1.0)

    # -- Trailing Stop + Take-Profit (Phase 42) ---------------------------
    trailing_stop_pct: float = Field(default=0.05, ge=0.0, le=0.50)
    trailing_stop_activation_pct: float = Field(default=0.03, ge=0.0, le=0.20)
    take_profit_pct: float = Field(default=0.20, ge=0.0, le=2.0)

    # -- Correlation-Aware Sizing (Phase 39) ------------------------------
    max_pairwise_correlation: float = Field(default=0.75, gt=0.0, le=1.0)
    correlation_lookback_days: int = Field(default=60, ge=10, le=252)
    correlation_size_floor: float = Field(default=0.25, gt=0.0, le=1.0)

    # -- Portfolio VaR Gate (Phase 43) ------------------------------------
    max_portfolio_var_pct: float = Field(default=0.03, ge=0.0, le=1.0)

    # -- Stress Test Gate (Phase 44) --------------------------------------
    max_stress_loss_pct: float = Field(default=0.25, ge=0.0, le=1.0)

    # -- Earnings Calendar Gate (Phase 45) --------------------------------
    max_earnings_proximity_days: int = Field(default=2, ge=0, le=30)

    # -- Phase 47 Drawdown Recovery Mode ----------------------------------
    drawdown_caution_pct: float = Field(default=0.05)
    drawdown_recovery_pct: float = Field(default=0.10)
    recovery_mode_size_multiplier: float = Field(default=0.50)
    recovery_mode_block_new_positions: bool = Field(default=False)

    # -- Phase 48 Dynamic Universe ----------------------------------------
    min_universe_signal_quality_score: float = Field(default=0.0, ge=0.0, le=1.0)

    # -- Deep-Dive Plan Step 1 (2026-04-16) -- Un-buried Constants --------
    buy_threshold: float = Field(default=0.65, ge=0.0, le=1.0)
    watch_threshold: float = Field(default=0.45, ge=0.0, le=1.0)
    source_weight_hit_rate_floor: float = Field(default=0.50, ge=0.0, le=1.0)
    ranking_threshold_avg_loss_floor: float = Field(
        default=-0.02, ge=-1.0, le=0.0
    )
    ai_ranking_bonus_map: dict[str, float] = Field(
        default_factory=lambda: dict(_DEFAULT_AI_RANKING_BONUS_MAP)
    )
    ai_theme_bonus_map: dict[str, float] = Field(
        default_factory=lambda: dict(_DEFAULT_AI_THEME_BONUS_MAP)
    )
    # Phase 65 regression fix 2026-04-22: rebalance_check runs at 06:26 ET daily;
    # first paper cycle runs at 09:35 ET (3h9m gap). Previous 3600s (1h) TTL
    # expired targets before any paper cycle could use them, bypassing the
    # Phase 65 rebalance-close suppression and causing alternating churn (dupe
    # CLOSED rows every cycle). 43200s (12h) keeps targets fresh for the full
    # trading day (06:26 ET → 18:26 ET) and naturally expires before the next
    # day's 06:26 ET rebalance_check overwrites them.
    rebalance_target_ttl_seconds: int = Field(default=43200, ge=0)

    # -- Deep-Dive Plan Step 2 (2026-04-16) Stability Invariants ---------
    # Two safety-only invariants; default ON.
    # Broker-adapter health invariant (Rec 2)
    broker_health_invariant_enabled: bool = Field(default=True)
    broker_health_position_drift_tolerance: float = Field(
        default=0.01, ge=0.0, le=100.0
    )
    # Action-conflict detector (Rec 3)
    action_conflict_detector_enabled: bool = Field(default=True)

    # -- Deep-Dive Plan Step 3 (2026-04-17) Trade-Count Lift -------------
    # Both flags default OFF — behavior preserved until operator flips.
    # Rec 9: Lower "buy" threshold 0.65 -> 0.55.
    lower_buy_threshold_enabled: bool = Field(default=False)
    lower_buy_threshold_value: float = Field(default=0.55, ge=0.0, le=1.0)
    # Rec 8: Conditional ranking_min_composite_score relaxation for held
    # names with positive closed-trade history.
    conditional_ranking_min_enabled: bool = Field(default=False)
    ranking_min_held_positive: float = Field(default=0.20, ge=0.0, le=1.0)

    # -- Deep-Dive Plan Step 4 (2026-04-17) Score-Weighted Rebalance ------
    # Rec 6. Default "equal" preserves legacy 1/N equal-weight rebalance
    # behaviour byte-for-byte. "score" weights by composite_score; "score_invvol"
    # weights by composite_score / volatility_20d (risk-parity-ish).  Any invalid
    # string falls through to "equal" via the validator.
    rebalance_weighting_method: str = Field(default="equal")
    # Master OFF switch — even when method != "equal", this must be True to
    # actually switch paths.  Belt-and-suspenders so operators can kill it
    # without reading through env files.
    score_weighted_rebalance_enabled: bool = Field(default=False)
    # Floor fraction of equal weight that every allocation must clear; prevents
    # score-weighted or invvol paths from putting near-zero weight on the
    # lowest-ranked ticker.  0.10 means each ticker gets at least 10% of the
    # equal-weight slot (i.e. 1 percentage point when N=10).
    rebalance_min_weight_floor_fraction: float = Field(
        default=0.10, ge=0.0, le=1.0
    )
    # Cap fraction of total equity a single ticker can hold, applied AFTER the
    # method's natural weights.  Matches ``max_single_name_pct`` semantics.
    rebalance_max_single_weight: float = Field(default=0.20, ge=0.0, le=1.0)

    @field_validator("rebalance_weighting_method")
    @classmethod
    def _validate_rebalance_method(cls, v: str) -> str:
        allowed = {"equal", "score", "score_invvol"}
        if v not in allowed:
            return "equal"
        return v

    # -- Deep-Dive Plan Step 6 (2026-04-17) Proposal Outcome Ledger ------
    # Rec 10. When OFF the ledger silently collects decision rows (write-only)
    # but the generator does NOT consult batting averages — behaviour is
    # byte-for-byte legacy.  When ON, ``generate_proposals`` consults the
    # ledger via ``ProposalOutcomeLedgerService.batting_average`` and skips /
    # downweights / upweights by success_rate per plan §6.6.
    proposal_outcome_ledger_enabled: bool = Field(default=False)
    # Diversity floor: minimum observations before the generator will start
    # skipping a (proposal_type, target_component) combo based on success rate.
    proposal_outcome_min_observations: int = Field(default=10, ge=1, le=1000)
    # Emit at least one proposal per TYPE per N days regardless of stats
    # (prevents exploration collapse).  Plan §6.6 calls for 31 days.
    proposal_outcome_diversity_floor_days: int = Field(default=31, ge=1, le=365)

    # -- Deep-Dive Plan Step 5 (2026-04-17) ATR Stops + Portfolio-Fit Sizing
    # Rec 7. Master switch for ATR-scaled per-family exits. When OFF, legacy
    # stop_loss_pct/trailing_stop_pct/max_position_age_days still drive exits
    # byte-for-byte. When ON, each position consults FAMILY_PARAMS (in
    # services/risk_engine/family_params.py) keyed by its origin_strategy;
    # positions opened before this step have origin_strategy=NULL and fall
    # through to the "default" family, which is wider/longer than legacy by
    # design so no open position is stopped-out earlier than it would be now.
    atr_stops_enabled: bool = Field(default=False)
    # Rec 5. Master switch for promoting portfolio_fit_score into position
    # sizing. When OFF, sizing = min(half_kelly, sizing_hint, max_single_name).
    # When ON, half_kelly is multiplied by the result's portfolio_fit_score
    # before the same min() stack; the max_single_name cap still binds.
    portfolio_fit_sizing_enabled: bool = Field(default=False)

    # -- Deep-Dive Plan Step 7 (2026-04-17) Shadow Portfolio Scorer ------
    # Rec 11 + DEC-034. When OFF the shadow tables exist but receive zero
    # writes; the weekly assessment job is also a no-op.  When ON, the
    # paper-trading worker pushes virtual entries into six named shadows
    # (rejected_actions, watch_tier, stopped_out_continued, rebalance_equal,
    # rebalance_score, rebalance_score_invvol) after risk validation but
    # before execution.  Live portfolio behaviour is unaffected either way.
    shadow_portfolio_enabled: bool = Field(default=False)
    # Which alternative rebalance weightings get parallel A/B shadows.  The
    # live allocator still uses ``rebalance_weighting_method``; these only
    # control the set of *shadow* portfolios that are written.
    shadow_rebalance_modes: list[str] = Field(
        default_factory=lambda: ["equal", "score", "score_invvol"]
    )
    # Composite-score band [low, high] for the ``watch_tier`` shadow.
    # Opportunities with composite in this band get virtual entries pushed
    # into ``watch_tier`` even if the live portfolio passes on them.
    shadow_watch_composite_low: float = Field(default=0.55, ge=0.0, le=1.0)
    shadow_watch_composite_high: float = Field(default=0.65, ge=0.0, le=1.0)
    # How many days a virtual-continue (stopped_out_continued) position is
    # held before being force-closed by the weekly job (plan §7.5.2).
    shadow_stopped_out_max_age_days: int = Field(default=30, ge=1, le=365)

    # -- Deep-Dive Plan Step 8 (2026-04-17) Thompson Strategy Bandit -----
    # Rec 12.  Per plan §8.6, ``(alpha, beta)`` priors accumulate from live
    # closed trades *even when the flag is OFF* — only the weight
    # *application* in ranking is gated.  Operator flips the flag to ON
    # only after 2-4 weeks of accumulated state.
    strategy_bandit_enabled: bool = Field(default=False)
    # How strongly the sampled Thompson weights pull away from the equal-
    # weight baseline.  1.0 == pure bandit, 0.0 == pure baseline.
    strategy_bandit_smoothing_lambda: float = Field(default=0.3, ge=0.0, le=1.0)
    # Per-strategy floor/ceiling applied AFTER smoothing (before renormalise)
    # so diversity is preserved even if one strategy dominates.
    strategy_bandit_min_weight: float = Field(default=0.05, ge=0.0, le=1.0)
    strategy_bandit_max_weight: float = Field(default=0.40, ge=0.0, le=1.0)
    # Sample new weights only every N ranking cycles; reuse the cached
    # weights in between.  Prevents per-cycle jitter from Thompson noise.
    strategy_bandit_resample_every_n_cycles: int = Field(
        default=10, ge=1, le=1000
    )

    # -- Ranking Minimum Composite Score ----------------------------------
    ranking_min_composite_score: float = Field(default=0.30, ge=0.0, le=1.0)

    # -- Self-Improvement Auto-Execute Gate (Phase 58) -------------------
    self_improvement_auto_execute_enabled: bool = Field(default=False)
    enable_insider_flow_strategy: bool = Field(default=False)
    # -- Phase 57 Part 2 — Insider-Flow Provider Wiring (2026-04-18, DEC-024) --
    # Provider selection for InsiderFlowAdapter.  Defaults to "null" so the
    # signal stays neutral unless an operator both flips
    # ``enable_insider_flow_strategy`` AND names a real provider here.  This is
    # the promotion gate from the Phase 57 scaffold: the strategy + overlay
    # fields have been live since Phase 57 Part 1; Part 2 only adds optional
    # concrete data sources behind default-OFF flags.
    #   - "null"        → NullInsiderFlowAdapter (no data, neutral score)
    #   - "quiverquant" → QuiverQuantAdapter (requires quiverquant_api_key)
    #   - "sec_edgar"   → SECEdgarFormFourAdapter (requires sec_edgar_user_agent)
    #   - "composite"   → both providers merged (requires both credentials)
    # If the chosen provider's credentials are missing the factory falls back
    # to NullInsiderFlowAdapter and logs a WARNING so the operator notices.
    insider_flow_provider: str = Field(default="null")
    quiverquant_api_key: str = Field(default="")
    # SEC requires a contact email in the User-Agent on all programmatic
    # access per https://www.sec.gov/os/accessing-edgar-data ; format is
    # "<App Name> <contact-email>".  Omitting it means no EDGAR calls.
    sec_edgar_user_agent: str = Field(default="")
    self_improvement_min_auto_execute_confidence: float = Field(
        default=0.70, ge=0.0, le=1.0
    )
    # Default raised 10 -> 50 by Deep-Dive Plan Step 2 Rec 13 (2026-04-16)
    self_improvement_min_signal_quality_observations: int = Field(
        default=50, ge=0, le=10000
    )

    # -- Phase 49 Rebalancing --------------------------------------------
    enable_rebalancing: bool = Field(default=True)
    rebalance_threshold_pct: float = Field(default=0.05, ge=0.0, le=1.0)
    rebalance_min_trade_usd: float = Field(default=500.0, ge=0.0)

    # -- Liquidity Filter (Phase 41) -------------------------------------
    min_liquidity_dollar_volume: float = Field(default=1_000_000.0, gt=0.0)
    max_position_as_pct_of_adv: float = Field(default=0.10, gt=0.0, le=1.0)

    # -- Market Data Provider (Phase A) -----------------------------------
    data_source: DataSource = DataSource.YFINANCE
    universe_source: UniverseSource = UniverseSource.STATIC
    pointintime_index_name: str = "S&P 500"
    pointintime_watchlist_name: str = "S&P 500 Current & Past"

    # -- Feature Flags ----------------------------------------------------
    kill_switch: bool = False

    # -- Admin / Ops ------------------------------------------------------
    operator_token: str = ""
    admin_rotation_token: str = ""
    operator_api_key: str = ""

    # -- Operator Webhook Alerts ------------------------------------------
    webhook_url: str = ""
    webhook_secret: str = ""
    alert_on_kill_switch: bool = True
    alert_on_paper_cycle_error: bool = True
    alert_on_broker_auth_expiry: bool = True
    alert_on_daily_evaluation: bool = True

    @field_validator("max_positions")
    @classmethod
    def max_positions_must_not_exceed_spec_limit(cls, v: int) -> int:
        if v > 15:
            raise ValueError(
                "Spec: max_positions cannot exceed 15. "
                "Update the spec before increasing this limit."
            )
        return v

    @field_validator("operating_mode")
    @classmethod
    def validate_operating_mode(cls, v: OperatingMode) -> OperatingMode:
        """Warn if a dangerous mode is selected outside of explicit intent."""
        if v == OperatingMode.RESTRICTED_LIVE:
            raise ValueError(
                "RESTRICTED_LIVE mode requires explicit spec revision and gate passage. "
                "Cannot be set via environment config alone."
            )
        return v

    @property
    def is_research_mode(self) -> bool:
        return self.operating_mode == OperatingMode.RESEARCH

    @property
    def is_paper_mode(self) -> bool:
        return self.operating_mode == OperatingMode.PAPER

    @property
    def is_live_capable(self) -> bool:
        return self.operating_mode in (
            OperatingMode.HUMAN_APPROVED,
            OperatingMode.RESTRICTED_LIVE,
        )

    @property
    def is_kill_switch_active(self) -> bool:
        return self.kill_switch


class AlpacaSettings(BaseSettings):
    """
    Alpaca broker credentials.

    Loaded from environment without the APIS_ prefix to keep secrets cleanly separate.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    alpaca_api_key: str = ""
    alpaca_api_secret: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"

    @property
    def is_configured(self) -> bool:
        return bool(self.alpaca_api_key and self.alpaca_api_secret)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the singleton Settings instance."""
    return Settings()


@lru_cache(maxsize=1)
def get_alpaca_settings() -> AlpacaSettings:
    """Return the singleton AlpacaSettings instance."""
    return AlpacaSettings()
