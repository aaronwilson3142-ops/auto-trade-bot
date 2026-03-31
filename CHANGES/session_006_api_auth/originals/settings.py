"""
APIS application settings loaded from environment variables via pydantic-settings.

All config must flow through this module. No scattered os.getenv() calls in service code.
"""
from __future__ import annotations

from enum import Enum
from functools import lru_cache
from typing import Annotated

from pydantic import Field, PostgresDsn, RedisDsn, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # ── Application ────────────────────────────────────────────────────────────
    env: Environment = Environment.DEVELOPMENT
    debug: bool = False
    log_level: str = "INFO"
    operating_mode: OperatingMode = OperatingMode.RESEARCH

    # ── Database ───────────────────────────────────────────────────────────────
    db_url: Annotated[str, Field(min_length=5)] = (
        "postgresql+psycopg://user:password@localhost:5432/apis"
    )
    # SQLAlchemy connection pool — tunable via env vars for production load
    db_pool_size: int = Field(default=5, ge=1, le=100)
    db_max_overflow: int = Field(default=10, ge=0, le=100)
    db_pool_recycle: int = Field(default=1800, ge=60)   # seconds; rotates stale connections
    db_pool_timeout: int = Field(default=30, ge=1)       # seconds; wait for a free slot

    # ── Cache ──────────────────────────────────────────────────────────────────
    redis_url: str = "redis://localhost:6379/0"

    # ── API Server ─────────────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = Field(default=8000, ge=1, le=65535)

    # ── Risk Controls ──────────────────────────────────────────────────────────
    # These are configurable floors. The risk_engine may enforce tighter hard limits.
    max_positions: int = Field(default=10, ge=1, le=50)
    max_new_positions_per_day: int = Field(default=3, ge=1, le=10)
    daily_loss_limit_pct: float = Field(default=0.02, gt=0.0, le=0.10)
    weekly_drawdown_limit_pct: float = Field(default=0.05, gt=0.0, le=0.20)
    monthly_drawdown_limit_pct: float = Field(default=0.10, gt=0.0, le=0.50)
    max_single_name_pct: float = Field(default=0.20, gt=0.0, le=1.0)
    max_sector_pct: float = Field(default=0.40, gt=0.0, le=1.0)
    max_thematic_pct: float = Field(default=0.50, gt=0.0, le=1.0)

    # ── Exit Strategy Thresholds ───────────────────────────────────────────────
    stop_loss_pct: float = Field(default=0.07, gt=0.0, le=0.50)        # 7% unrealized loss → force close
    max_position_age_days: int = Field(default=20, ge=1, le=365)        # days held before thesis expires
    exit_score_threshold: float = Field(default=0.40, ge=0.0, le=1.0)  # composite score below → thesis invalidated

    # ── Trailing Stop + Take-Profit Exits (Phase 42) ───────────────────────────
    # Trailing stop: fires when current_price < peak_price * (1 - trailing_stop_pct).
    # Only activates after the position has gained trailing_stop_activation_pct or more.
    # Set to 0.0 to disable trailing stops entirely.
    trailing_stop_pct: float = Field(default=0.05, ge=0.0, le=0.50)
    # Minimum gain (fraction) before the trailing stop becomes active.
    # Prevents triggering on normal early-position noise.
    trailing_stop_activation_pct: float = Field(default=0.03, ge=0.0, le=0.20)
    # Take-profit: fires when unrealized_pnl_pct >= take_profit_pct.
    # Set to 0.0 to disable take-profit exits entirely.
    take_profit_pct: float = Field(default=0.20, ge=0.0, le=2.0)

    # ── Correlation-Aware Position Sizing (Phase 39) ───────────────────────────
    # Pairwise Pearson correlation above which size penalty onset applies (0.5).
    # Sizing decays linearly from 1.0 at the onset to correlation_size_floor at 1.0.
    max_pairwise_correlation: float = Field(default=0.75, gt=0.0, le=1.0)
    # Lookback window (calendar days of bars) for return-series correlation.
    correlation_lookback_days: int = Field(default=60, ge=10, le=252)
    # Minimum size multiplier applied to highly correlated new positions.
    correlation_size_floor: float = Field(default=0.25, gt=0.0, le=1.0)

    # ── Portfolio VaR Gate (Phase 43) ─────────────────────────────────────
    # 1-day 95% historical-simulation VaR limit as a fraction of equity.
    # When the portfolio VaR exceeds this threshold, new OPEN actions are
    # blocked by the paper cycle VaR gate until VaR falls back below the limit.
    # Default 3% — a conservative but not overly restrictive threshold for a
    # diversified US equity paper portfolio.  Set to 0.0 to disable the gate.
    max_portfolio_var_pct: float = Field(default=0.03, ge=0.0, le=1.0)

    # ── Stress Test Gate (Phase 44) ────────────────────────────────────────
    # Worst-case scenario loss threshold (fraction of equity).
    # When the largest stressed loss across all built-in scenarios exceeds
    # this threshold, new OPEN actions are blocked until conditions improve.
    # Default 25% — blocks new positions when any scenario implies a loss
    # of more than a quarter of portfolio equity.  Set to 0.0 to disable.
    max_stress_loss_pct: float = Field(default=0.25, ge=0.0, le=1.0)

    # ── Earnings Calendar Gate (Phase 45) ─────────────────────────────────
    # Number of calendar days before an earnings announcement within which
    # new OPEN actions for that ticker are blocked by the earnings proximity
    # gate.  Default 2 days — protects against overnight earnings gaps
    # (announced after close on day 0, gap at open on day 1).
    # Set to 0 to disable the gate entirely.
    max_earnings_proximity_days: int = Field(default=2, ge=0, le=30)

    # ── Phase 47 — Drawdown Recovery Mode ─────────────────────────────────
    drawdown_caution_pct: float = Field(default=0.05, description="Drawdown pct to enter CAUTION state")
    drawdown_recovery_pct: float = Field(default=0.10, description="Drawdown pct to enter RECOVERY state")
    recovery_mode_size_multiplier: float = Field(default=0.50, description="Position size multiplier in RECOVERY mode")
    recovery_mode_block_new_positions: bool = Field(default=False, description="If True, block all new OPENs in RECOVERY mode")

    # ── Phase 48 — Dynamic Universe Management ────────────────────────────
    # Minimum average signal quality score (0.0–1.0) below which a ticker is
    # automatically removed from the active universe.
    # Default 0.0 = quality-based auto-removal is disabled; only operator
    # overrides affect the universe.  Set to e.g. 0.40 to enable quality pruning.
    min_universe_signal_quality_score: float = Field(default=0.0, ge=0.0, le=1.0)

    # ── Phase 49 — Portfolio Rebalancing Engine ────────────────────────
    # Master switch.  Set False to disable all rebalancing logic.
    enable_rebalancing: bool = Field(default=True)
    # Minimum signed drift (fraction of equity) before a TRIM or OPEN action fires.
    # Default 5% — avoids churning positions slightly off target.
    rebalance_threshold_pct: float = Field(default=0.05, ge=0.0, le=1.0)
    # Minimum absolute USD trade size for rebalance actions.
    # Default $500 — avoids tiny, costly orders.
    rebalance_min_trade_usd: float = Field(default=500.0, ge=0.0)

    # ── Liquidity Filter (Phase 41) ────────────────────────────────────────────
    # Minimum 20-day average daily dollar volume required to enter a position.
    # Tickers below this threshold are dropped by LiquidityService at the paper
    # cycle filter step.  Default $1M — excludes micro-cap illiquid names.
    min_liquidity_dollar_volume: float = Field(default=1_000_000.0, gt=0.0)
    # Maximum position notional as a fraction of 20-day average daily dollar
    # volume.  Prevents market-impact risk on entry and limits exit-liquidity
    # exposure.  Default 10% of ADV — conservative but not restrictive for
    # large-cap names with >$100 M ADV.
    max_position_as_pct_of_adv: float = Field(default=0.10, gt=0.0, le=1.0)

    # ── Feature Flags ──────────────────────────────────────────────────────────
    kill_switch: bool = False

    # ── Admin / Ops ────────────────────────────────────────────────────────────
    # Pre-shared bearer token that AWS Secrets Manager rotation Lambda must send
    # to POST /api/v1/admin/invalidate-secrets.  Empty string = endpoint disabled.
    admin_rotation_token: str = ""

    # Pre-shared bearer token for operator-push intelligence endpoints
    # (POST /api/v1/intelligence/events and /intelligence/news).
    # External data feeds must include Authorization: Bearer <token>.
    # Empty string = endpoints disabled (returns 503).
    operator_api_key: str = ""

    # ── Operator Webhook Alerts ────────────────────────────────────────────────
    # Full HTTPS URL of the operator's webhook receiver.
    # Empty string = webhook delivery disabled (no-op, no error).
    webhook_url: str = ""

    # Optional HMAC-SHA256 signing secret.  When set, every POST includes an
    # X-APIS-Signature: sha256=<hex> header for receiver-side verification.
    webhook_secret: str = ""

    # Per-event-type enable/disable flags.  All default True so that a newly
    # configured webhook_url receives all event types out of the box.
    alert_on_kill_switch: bool = True
    alert_on_paper_cycle_error: bool = True
    alert_on_broker_auth_expiry: bool = True
    alert_on_daily_evaluation: bool = True

    # ── Broker (Alpaca) ────────────────────────────────────────────────────────
    # Not prefixed with APIS_ — use raw env vars for broker secrets
    model_config = SettingsConfigDict(
        env_prefix="APIS_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @field_validator("max_positions")
    @classmethod
    def max_positions_must_not_exceed_spec_limit(cls, v: int) -> int:
        """MVP spec hard cap is 10 positions."""
        if v > 10:
            raise ValueError(
                "MVP spec: max_positions cannot exceed 10. "
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
