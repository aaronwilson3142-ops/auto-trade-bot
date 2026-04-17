"""
RankingEngineService — merges signal outputs, computes composite scores,
and produces a ranked list of investment opportunities.

Responsibilities (per 07_API_AND_SERVICE_BOUNDARIES_SPEC §3.9):
  - Accept a list of SignalOutput objects (or load from DB by signal_run_id)
  - Compute composite portfolio-level scores
  - Enforce portfolio-fit pre-scoring (respect Settings.max_positions, max_single_name_pct)
  - Persist RankingRun + RankedOpportunity ORM rows
  - Return a list of RankedResult with full explanations

Gate B compliance:
  - Every RankedResult.thesis_summary is populated (explainable)
  - disconfirming_factors field captures the bear case
  - source_reliability_tier is tagged on every output
  - contains_rumor flag separates verified vs rumour-sourced signals

Does NOT own: order generation, portfolio state mutations, or risk engine decisions.
"""
from __future__ import annotations

import datetime as dt
import logging
import uuid
from decimal import Decimal, InvalidOperation

import sqlalchemy as sa
from sqlalchemy.orm import Session

from config.settings import get_settings
from infra.db.models import RankedOpportunity, RankingRun, Security, SecuritySignal
from services.ranking_engine.models import RankedResult, RankingConfig
from services.signal_engine.models import SignalOutput

logger = logging.getLogger(__name__)

_QUANTIZE = Decimal("0.000001")


def _d(x: float | None) -> Decimal | None:
    if x is None:
        return None
    try:
        return Decimal(str(round(x, 6))).quantize(_QUANTIZE)
    except InvalidOperation:
        return None


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


class RankingEngineService:
    """Ranks securities by composite score from signal outputs.

    Args:
        config: RankingConfig weight vector.  Defaults to RankingConfig().
    """

    def __init__(self, config: RankingConfig | None = None) -> None:
        self._config = config or RankingConfig()

    # ------------------------------------------------------------------
    # Public API (in-memory path — used by tests and signal engine)
    # ------------------------------------------------------------------

    def rank_signals(
        self,
        signals: list[SignalOutput],
        max_results: int | None = None,
        strategy_weights: dict[str, float] | None = None,
    ) -> list[RankedResult]:
        """Compute composite scores and return a sorted list of RankedResult.

        Args:
            signals:          List of SignalOutput from the signal engine.
            max_results:      Cap on returned results.  Defaults to Settings.max_positions.
            strategy_weights: Optional dict of strategy_key → weight.  When
                              provided the weighted-mean signal score replaces
                              the single-best-confidence anchor score.  Falls
                              back to equal weighting within the available
                              strategy set when None.

        Returns:
            List of RankedResult sorted by composite_score descending.
        """
        settings = get_settings()
        cap = max_results or settings.max_positions

        # Group signals by security_id (multiple strategies may emit signals
        # for the same security; aggregate by best composite)
        grouped: dict[object, list[SignalOutput]] = {}
        for sig in signals:
            grouped.setdefault(sig.security_id, []).append(sig)

        candidates: list[RankedResult] = []
        for security_id, sig_list in grouped.items():
            result = self._aggregate(security_id, sig_list, settings, strategy_weights)
            if result is not None:
                candidates.append(result)

        # Sort by composite score descending
        candidates.sort(key=lambda r: r.composite_score or Decimal("0"), reverse=True)

        # Assign rank positions after sorting
        for i, r in enumerate(candidates[:cap], start=1):
            r.rank_position = i

        return candidates[:cap]

    # ------------------------------------------------------------------
    # DB-backed path
    # ------------------------------------------------------------------

    def run(
        self,
        session: Session,
        signal_run_id: uuid.UUID,
        signals: list[SignalOutput] | None = None,
    ) -> tuple[uuid.UUID, list[RankedResult]]:
        """Run the ranking pipeline and persist results.

        Args:
            session:       Active SQLAlchemy session.
            signal_run_id: FK to signal_runs.id.
            signals:       Pre-computed signals.  If None, loaded from DB.

        Returns:
            (ranking_run_id, list[RankedResult])
        """
        if signals is None:
            signals = self._load_signals_from_db(session, signal_run_id)

        ranked = self.rank_signals(signals, strategy_weights=None)

        run = RankingRun(
            signal_run_id=signal_run_id,
            run_timestamp=dt.datetime.utcnow(),
            config_version=self._config.config_version,
            status="completed",
        )
        session.add(run)
        session.flush()

        for result in ranked:
            self._persist_ranked_result(session, run.id, result)

        logger.info(
            "RankingRun id=%s: %d opportunities ranked.", run.id, len(ranked)
        )
        return run.id, ranked

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _aggregate(
        self,
        security_id: object,
        sig_list: list[SignalOutput],
        settings: object,
        strategy_weights: dict[str, float] | None = None,
    ) -> RankedResult | None:
        """Aggregate signals for one security into a single RankedResult.

        When *strategy_weights* is provided the weighted-mean signal score
        and confidence are computed across all contributing strategies.
        Weights are renormalised to the available strategy set so missing
        strategies (e.g. ValuationStrategy when no fundamentals data) do
        not distort the blend.  Falls back to equal weighting if no profile
        is supplied.
        """
        # Safe float extraction
        def _f(d: Decimal | None) -> float:
            return float(d) if d is not None else 0.5

        # Always keep highest-confidence signal as metadata anchor
        anchor = max(
            sig_list,
            key=lambda s: float(s.confidence_score or 0),
        )

        # Compute weighted-mean signal and confidence scores
        if strategy_weights and len(sig_list) > 1:
            # Build per-signal weight using strategy_key lookup; unknown keys
            # receive the minimum available weight (prevents total exclusion).
            min_w = min(strategy_weights.values()) if strategy_weights else 0.0
            raw_weights = [
                strategy_weights.get(s.strategy_key or "", min_w)
                for s in sig_list
            ]
            total_w = sum(raw_weights) or 1.0
            norm_weights = [w / total_w for w in raw_weights]

            signal_score = sum(
                _f(s.signal_score) * w for s, w in zip(sig_list, norm_weights)
            )
            confidence = sum(
                _f(s.confidence_score) * w for s, w in zip(sig_list, norm_weights)
            )
        else:
            # Single signal or no weights: use anchor directly
            signal_score = _f(anchor.signal_score)
            confidence = _f(anchor.confidence_score)
        liquidity = _f(anchor.liquidity_score)
        risk = _f(anchor.risk_score)

        cfg = self._config
        composite = (
            signal_score * cfg.signal_weight
            + confidence * cfg.confidence_weight
            + liquidity * cfg.liquidity_weight
            - risk * cfg.risk_penalty_weight   # risk deducts
        )
        composite = _clamp(composite + cfg.risk_penalty_weight)  # re-centre after penalty

        portfolio_fit = self._compute_portfolio_fit(composite, liquidity, settings)
        action = self._recommend_action(composite, anchor, settings)
        thesis = self._format_thesis(anchor, composite)
        disconf = self._format_disconfirming(anchor)
        sizing = self._compute_sizing(composite, settings)

        # Gate B: any rumor in contributing signals?
        any_rumor = any(s.contains_rumor for s in sig_list)
        # Gate B: source tag — use the least reliable tier present
        reliability = (
            "unverified" if any_rumor
            else anchor.source_reliability_tier
        )

        return RankedResult(
            rank_position=0,            # assigned after sort
            security_id=security_id,
            ticker=anchor.ticker,
            composite_score=_d(composite),
            portfolio_fit_score=_d(portfolio_fit),
            recommended_action=action,
            target_horizon=anchor.horizon_classification,
            thesis_summary=thesis,
            disconfirming_factors=disconf,
            sizing_hint_pct=sizing,
            source_reliability_tier=reliability,
            contains_rumor=any_rumor,
            as_of=anchor.as_of,
            contributing_signals=[
                {
                    "strategy_key": s.strategy_key,
                    "signal_score": float(s.signal_score or 0),
                    "confidence_score": float(s.confidence_score or 0),
                    "explanation": s.explanation_dict,
                }
                for s in sig_list
            ],
        )

    @staticmethod
    def _compute_portfolio_fit(
        composite: float,
        liquidity: float,
        settings: object,
    ) -> float:
        """Score portfolio fit: high-composite + liquid securities score highest."""
        return _clamp(composite * 0.7 + liquidity * 0.3)

    @staticmethod
    def _recommend_action(
        composite: float,
        anchor: SignalOutput,
        settings: object | None = None,
    ) -> str:
        """Map composite score to recommended action.

        Thresholds sourced from settings (Deep-Dive Plan Step 1):
        - ``buy_threshold`` (default 0.65)
        - ``watch_threshold`` (default 0.45)

        Deep-Dive Plan Step 3 Rec 9: when
        ``lower_buy_threshold_enabled`` is ON, the effective buy
        threshold is pulled from ``lower_buy_threshold_value``
        (default 0.55).  Flag is OFF by default so legacy behavior
        is preserved.
        """
        if settings is None:
            settings = get_settings()
        buy_t = float(getattr(settings, "buy_threshold", 0.65))
        if getattr(settings, "lower_buy_threshold_enabled", False):
            buy_t = float(getattr(settings, "lower_buy_threshold_value", 0.55))
        watch_t = float(getattr(settings, "watch_threshold", 0.45))
        if composite >= buy_t:
            return "buy"
        elif composite >= watch_t:
            return "watch"
        else:
            return "avoid"

    @staticmethod
    def _format_thesis(anchor: SignalOutput, composite: float) -> str:
        """Build a human-readable thesis summary from the anchor signal's explanation."""
        base = anchor.explanation_dict.get("rationale", "")
        extra = (
            f" Composite score: {composite:.2f}. "
            f"Source: {anchor.source_reliability_tier}. "
            f"Rumour content: {'yes' if anchor.contains_rumor else 'none'}."
        )
        return (base + extra).strip()

    @staticmethod
    def _format_disconfirming(anchor: SignalOutput) -> str:
        """Generate disconfirming factors from the signal's downside attributes."""
        parts = []
        risk = float(anchor.risk_score or 0)
        if risk > 0.6:
            parts.append(f"Elevated volatility risk ({risk:.0%})")
        liq = float(anchor.liquidity_score or 0.5)
        if liq < 0.4:
            parts.append("Low liquidity — wide bid/ask spreads possible")
        sig = float(anchor.signal_score or 0.5)
        if sig < 0.5:
            parts.append("Below-neutral momentum")
        if not parts:
            parts.append("No significant disconfirming factors identified at this time")
        return "; ".join(parts) + "."

    @staticmethod
    def _compute_sizing(composite: float, settings: object) -> Decimal | None:
        """Suggest a position size as a fraction of portfolio equity."""
        max_pct = float(getattr(settings, "max_single_name_pct", 0.20))
        sizing = composite * max_pct
        return _d(_clamp(sizing, 0.0, max_pct))

    def _persist_ranked_result(
        self,
        session: Session,
        ranking_run_id: uuid.UUID,
        result: RankedResult,
    ) -> None:
        row = RankedOpportunity(
            ranking_run_id=ranking_run_id,
            security_id=result.security_id,
            rank_position=result.rank_position,
            composite_score=result.composite_score,
            portfolio_fit_score=result.portfolio_fit_score,
            recommended_action=result.recommended_action,
            target_horizon=result.target_horizon,
            thesis_summary=result.thesis_summary,
            disconfirming_factors=result.disconfirming_factors,
            sizing_hint_pct=result.sizing_hint_pct,
        )
        session.add(row)

    @staticmethod
    def _load_signals_from_db(
        session: Session,
        signal_run_id: uuid.UUID,
    ) -> list[SignalOutput]:
        """Load SecuritySignal rows and reconstruct SignalOutput objects."""
        from infra.db.models import Strategy

        rows = session.execute(
            sa.select(
                SecuritySignal,
                Security.ticker,
                Strategy.strategy_key,
                Strategy.strategy_family,
            )
            .join(Security, Security.id == SecuritySignal.security_id)
            .join(Strategy, Strategy.id == SecuritySignal.strategy_id)
            .where(SecuritySignal.signal_run_id == signal_run_id)
        ).all()

        outputs = []
        for sig_row, ticker, strat_key, strat_family in rows:
            exp = sig_row.explanation_json or {}
            outputs.append(
                SignalOutput(
                    security_id=sig_row.security_id,
                    ticker=ticker,
                    strategy_key=strat_key,
                    signal_type=strat_family,
                    signal_score=sig_row.signal_score,
                    confidence_score=sig_row.confidence_score,
                    risk_score=sig_row.risk_score,
                    catalyst_score=sig_row.catalyst_score,
                    liquidity_score=sig_row.liquidity_score,
                    horizon_classification=sig_row.horizon_classification or "unknown",
                    explanation_dict=exp,
                    source_reliability_tier=exp.get("source_reliability", "secondary_verified"),
                    contains_rumor=exp.get("contains_rumor", False),
                )
            )
        return outputs

