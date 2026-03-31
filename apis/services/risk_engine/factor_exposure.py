"""
Factor Exposure Monitoring — Phase 50.

FactorExposureService maps each portfolio position to five standard investment
style factors, then aggregates exposures to a portfolio-level summary.

Factors
-------
  MOMENTUM  — price return momentum (from composite ranking score)
  VALUE     — cheap relative to earnings (low P/E = high value)
  GROWTH    — earnings / revenue growth trajectory
  QUALITY   — liquidity / market-cap proxy (high ADV = large, quality name)
  LOW_VOL   — low annualised price volatility

Design rules
------------
- Stateless: all methods are pure (no side-effects, no DB access).
- Neutral score: any missing input yields 0.5 for that factor — never blocks.
- All scores are in [0.0, 1.0] where 1.0 = maximum exposure to that factor.
- Portfolio-level weight = market-value-weighted mean of per-ticker scores.
- Uses structlog only — no print() calls.

Spec references
---------------
- Phase 50 — Factor Exposure Monitoring
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field

import structlog

log = structlog.get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

FACTORS: list[str] = ["MOMENTUM", "VALUE", "GROWTH", "QUALITY", "LOW_VOL"]

# VALUE: P/E at or above this ratio maps to score 0.0 (expensive ceiling)
_VALUE_PE_MAX: float = 50.0

# GROWTH: ±100% EPS growth saturates at score 1.0 / 0.0 respectively
_GROWTH_EPS_SCALE: float = 2.0  # multiplier before 0.5 offset

# QUALITY: ADV at or above this dollar volume maps to score 1.0
_QUALITY_ADV_MAX_LOG: float = math.log10(5_000_000_000)  # $5 B ADV ceiling

# LOW_VOL: annualised vol at or above this maps to score 0.0
_LOW_VOL_MAX: float = 0.50  # 50% annualised — consider extremely high vol


# ── Domain models ──────────────────────────────────────────────────────────────

@dataclass
class TickerFactorScores:
    """Per-ticker factor score record."""
    ticker: str
    scores: dict[str, float]  # factor → [0.0, 1.0]
    market_value: float = 0.0

    @property
    def dominant_factor(self) -> str:
        """Factor with the highest score for this ticker."""
        if not self.scores:
            return "UNKNOWN"
        return max(self.scores, key=lambda f: self.scores[f])


@dataclass
class FactorExposureResult:
    """Portfolio-level factor exposure summary.

    ``portfolio_factor_weights`` is the market-value-weighted mean of all
    per-ticker factor scores.  ``ticker_scores`` provides granular detail.
    """
    portfolio_factor_weights: dict[str, float] = field(default_factory=dict)
    ticker_scores: list[TickerFactorScores] = field(default_factory=list)
    dominant_factor: str = "UNKNOWN"
    position_count: int = 0
    total_market_value: float = 0.0
    computed_at: dt.datetime = field(
        default_factory=lambda: dt.datetime.now(dt.UTC)
    )

    def top_tickers_by_factor(self, factor: str, n: int = 5) -> list[TickerFactorScores]:
        """Return up to *n* tickers with the highest score for *factor*."""
        ranked = sorted(
            self.ticker_scores,
            key=lambda t: t.scores.get(factor, 0.5),
            reverse=True,
        )
        return ranked[:n]

    def bottom_tickers_by_factor(self, factor: str, n: int = 5) -> list[TickerFactorScores]:
        """Return up to *n* tickers with the lowest score for *factor*."""
        ranked = sorted(
            self.ticker_scores,
            key=lambda t: t.scores.get(factor, 0.5),
        )
        return ranked[:n]


# ── Service ────────────────────────────────────────────────────────────────────

class FactorExposureService:
    """Map portfolio positions to investment style factor scores.

    All methods are stateless — caller passes all required data explicitly so
    the service remains fully testable without a running database or app state.

    Factor input keys (all optional — missing → 0.5 neutral):
        ``composite_score``   float in [0.0, 1.0]  → MOMENTUM
        ``pe_ratio``          float > 0             → VALUE
        ``eps_growth``        float fraction        → GROWTH (0.15 = +15% YoY)
        ``dollar_volume_20d`` float USD             → QUALITY
        ``volatility_20d``    float fraction        → LOW_VOL (0.25 = 25% annual)
    """

    # ── Per-factor score computation ────────────────────────────────────────

    @staticmethod
    def _score_momentum(composite_score: float | None) -> float:
        """MOMENTUM score from ranking composite score (already [0, 1])."""
        if composite_score is None:
            return 0.5
        return float(max(0.0, min(1.0, composite_score)))

    @staticmethod
    def _score_value(pe_ratio: float | None) -> float:
        """VALUE score — low P/E → high score.

        Score = max(0, 1 - pe_ratio / PE_MAX).
        P/E = 0  → 1.0 (very cheap); P/E >= PE_MAX → 0.0 (expensive).
        """
        if pe_ratio is None or pe_ratio <= 0:
            return 0.5
        return float(max(0.0, 1.0 - pe_ratio / _VALUE_PE_MAX))

    @staticmethod
    def _score_growth(eps_growth: float | None) -> float:
        """GROWTH score — high EPS growth → high score.

        Score = clamp(0.5 + eps_growth * SCALE, 0, 1).
        eps_growth = 0 → 0.5 neutral; +50% → ~1.0; -50% → ~0.0.
        """
        if eps_growth is None:
            return 0.5
        raw = 0.5 + eps_growth * _GROWTH_EPS_SCALE
        return float(max(0.0, min(1.0, raw)))

    @staticmethod
    def _score_quality(dollar_volume_20d: float | None) -> float:
        """QUALITY score — high ADV (large liquid names) → high score.

        Uses log10 scale: $1 M ADV → ~0.52; $5 B ADV → 1.0.
        """
        if dollar_volume_20d is None or dollar_volume_20d <= 0:
            return 0.5
        log_adv = math.log10(max(1.0, dollar_volume_20d))
        return float(max(0.0, min(1.0, log_adv / _QUALITY_ADV_MAX_LOG)))

    @staticmethod
    def _score_low_vol(volatility_20d: float | None) -> float:
        """LOW_VOL score — low annualised vol → high score.

        Score = max(0, 1 - vol / VOL_MAX).
        vol = 0  → 1.0; vol >= 50% → 0.0.
        """
        if volatility_20d is None or volatility_20d < 0:
            return 0.5
        return float(max(0.0, 1.0 - volatility_20d / _LOW_VOL_MAX))

    # ── Public API ──────────────────────────────────────────────────────────

    @classmethod
    def compute_factor_scores(cls, feature_values: dict) -> dict[str, float]:
        """Compute all five factor scores for a single ticker.

        Args:
            feature_values: Dict with any subset of:
                ``composite_score``, ``pe_ratio``, ``eps_growth``,
                ``dollar_volume_20d``, ``volatility_20d``.
                Missing keys default to 0.5 neutral.

        Returns:
            Dict mapping each factor name → score in [0.0, 1.0].
        """
        return {
            "MOMENTUM": cls._score_momentum(feature_values.get("composite_score")),
            "VALUE":    cls._score_value(feature_values.get("pe_ratio")),
            "GROWTH":   cls._score_growth(feature_values.get("eps_growth")),
            "QUALITY":  cls._score_quality(feature_values.get("dollar_volume_20d")),
            "LOW_VOL":  cls._score_low_vol(feature_values.get("volatility_20d")),
        }

    @classmethod
    def compute_portfolio_factor_exposure(
        cls,
        positions: dict,           # {ticker: PortfolioPosition}
        ticker_scores: dict,       # {ticker: {factor: float}}
        equity: float,
    ) -> FactorExposureResult:
        """Aggregate per-ticker factor scores into portfolio-level weights.

        Portfolio factor weight = market-value-weighted mean of per-ticker scores.
        Positions with zero or negative market_value are excluded from weighting.

        Args:
            positions:     Current portfolio positions (market_value attribute used).
            ticker_scores: Per-ticker factor scores dict {ticker: {factor: score}}.
            equity:        Total portfolio equity (for weight normalisation).

        Returns:
            FactorExposureResult with portfolio_factor_weights and ticker_scores.
        """

        ticker_records: list[TickerFactorScores] = []
        total_mv: float = 0.0
        weighted_sums: dict[str, float] = dict.fromkeys(FACTORS, 0.0)

        for ticker, pos in positions.items():
            mv_raw = getattr(pos, "market_value", None)
            if mv_raw is None:
                continue
            mv = float(mv_raw) if not isinstance(mv_raw, float) else mv_raw
            if mv <= 0.0:
                continue

            scores = ticker_scores.get(ticker) or dict.fromkeys(FACTORS, 0.5)
            ticker_records.append(TickerFactorScores(
                ticker=ticker,
                scores=scores,
                market_value=mv,
            ))
            for factor in FACTORS:
                weighted_sums[factor] += scores.get(factor, 0.5) * mv
            total_mv += mv

        # Normalise
        if total_mv > 0.0:
            portfolio_weights = {
                f: round(weighted_sums[f] / total_mv, 4)
                for f in FACTORS
            }
        else:
            portfolio_weights = dict.fromkeys(FACTORS, 0.5)

        dominant = max(portfolio_weights, key=lambda f: portfolio_weights[f]) if portfolio_weights else "UNKNOWN"

        log.info(
            "factor_exposure_computed",
            position_count=len(ticker_records),
            dominant_factor=dominant,
            portfolio_weights=portfolio_weights,
        )

        return FactorExposureResult(
            portfolio_factor_weights=portfolio_weights,
            ticker_scores=ticker_records,
            dominant_factor=dominant,
            position_count=len(ticker_records),
            total_market_value=total_mv,
        )
