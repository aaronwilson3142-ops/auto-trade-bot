"""FeatureEnrichmentService — populates FeatureSet overlay fields.

Bridges the intelligence services (ThemeEngine, MacroPolicyEngine,
NewsIntelligence) into the signal pipeline.  Called by SignalEngineService
before strategy scoring so the overlay fields (theme_scores, macro_bias,
macro_regime, sentiment_score, sentiment_confidence) reflect current
market intelligence rather than neutral defaults.

Design rules
------------
- Pure in-memory; no ORM/DB dependency.
- None-safe inputs: empty lists produce neutral overlays (safe defaults).
- Returns a NEW FeatureSet via dataclasses.replace() — never mutates input.
- All per-ticker exceptions are caught and logged; failures return input
  unchanged so the pipeline always continues.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any, Optional

from services.feature_store.models import FeatureSet

logger = logging.getLogger(__name__)


class FeatureEnrichmentService:
    """Enriches a FeatureSet with theme, macro, and news sentiment overlays.

    Args:
        theme_engine:       ThemeEngineService instance.  Defaults to a new
                            ThemeEngineService() with default config.
        macro_policy:       MacroPolicyEngineService instance.  Defaults to a
                            new MacroPolicyEngineService() with default config.
        news_intelligence:  NewsIntelligenceService instance (reserved for
                            future direct processing; insights currently
                            passed in pre-processed at call time).
    """

    def __init__(
        self,
        theme_engine: Any = None,
        macro_policy: Any = None,
        news_intelligence: Any = None,
    ) -> None:
        if theme_engine is None:
            from services.theme_engine.service import ThemeEngineService
            theme_engine = ThemeEngineService()
        if macro_policy is None:
            from services.macro_policy_engine.service import MacroPolicyEngineService
            macro_policy = MacroPolicyEngineService()
        if news_intelligence is None:
            from services.news_intelligence.service import NewsIntelligenceService
            news_intelligence = NewsIntelligenceService()
        self._theme_engine = theme_engine
        self._macro_policy = macro_policy
        self._news_intelligence = news_intelligence

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enrich(
        self,
        feature_set: FeatureSet,
        policy_signals: Optional[list] = None,
        news_insights: Optional[list] = None,
        fundamentals_store: Optional[dict] = None,
    ) -> FeatureSet:
        """Return a new FeatureSet with all overlay fields populated.

        Args:
            feature_set:        Baseline feature set to enrich.
            policy_signals:     List of PolicySignal objects from the current
                                cycle.  Empty list → neutral macro overlay.
            news_insights:      List of NewsInsight objects from the current
                                cycle.  Filtered to those mentioning the ticker.
            fundamentals_store: Optional dict of ticker → FundamentalsData
                                (populated by FundamentalsService).  When
                                present, applies fundamentals overlay fields to
                                the returned FeatureSet so ValuationStrategy
                                has data to score against.

        Returns:
            A new FeatureSet with theme_scores, macro_bias, macro_regime,
            sentiment_score, sentiment_confidence, and (when available)
            fundamentals fields populated.
        """
        policy_signals = policy_signals or []
        news_insights = news_insights or []
        try:
            theme_scores = self._compute_theme_scores(feature_set.ticker)
            macro_bias, macro_regime = self._compute_macro_overlay(policy_signals)
            sentiment_score, sentiment_confidence = self._compute_sentiment_overlay(
                feature_set.ticker, news_insights
            )
            enriched = replace(
                feature_set,
                theme_scores=theme_scores,
                macro_bias=macro_bias,
                macro_regime=macro_regime,
                sentiment_score=sentiment_score,
                sentiment_confidence=sentiment_confidence,
            )
            # Apply fundamentals overlay if available for this ticker
            if fundamentals_store:
                fund_data = fundamentals_store.get(feature_set.ticker)
                if fund_data is not None:
                    enriched = self._apply_fundamentals(enriched, fund_data)
            return enriched
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "feature_enrichment_failed ticker=%s error=%s",
                feature_set.ticker,
                exc,
            )
            return feature_set

    def enrich_batch(
        self,
        feature_sets: list[FeatureSet],
        policy_signals: Optional[list] = None,
        news_insights: Optional[list] = None,
        fundamentals_store: Optional[dict] = None,
    ) -> list[FeatureSet]:
        """Enrich a list of FeatureSets.

        The macro overlay (bias + regime) is computed once and shared across
        all tickers in the batch — it is a global market state, not per-ticker.
        Theme scores, sentiment overlays, and fundamentals are computed per-ticker.

        Args:
            fundamentals_store: Optional dict of ticker → FundamentalsData.

        Returns:
            A list of enriched FeatureSets in the same order as the input.
        """
        policy_signals = policy_signals or []
        news_insights = news_insights or []
        # Pre-compute macro overlay once — shared across the batch
        macro_bias, macro_regime = self._compute_macro_overlay(policy_signals)
        enriched: list[FeatureSet] = []
        for fs in feature_sets:
            try:
                theme_scores = self._compute_theme_scores(fs.ticker)
                sentiment_score, sentiment_confidence = self._compute_sentiment_overlay(
                    fs.ticker, news_insights
                )
                enriched_fs = replace(
                    fs,
                    theme_scores=theme_scores,
                    macro_bias=macro_bias,
                    macro_regime=macro_regime,
                    sentiment_score=sentiment_score,
                    sentiment_confidence=sentiment_confidence,
                )
                if fundamentals_store:
                    fund_data = fundamentals_store.get(fs.ticker)
                    if fund_data is not None:
                        enriched_fs = self._apply_fundamentals(enriched_fs, fund_data)
                enriched.append(enriched_fs)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "feature_enrichment_failed ticker=%s error=%s",
                    fs.ticker,
                    exc,
                )
                enriched.append(fs)
        return enriched

    def assess_macro_regime(self, policy_signals: list) -> str:
        """Return the current macro regime string from active policy signals.

        Returns:
            A MacroRegime value string, uppercased.
            e.g. "NEUTRAL", "RISK_ON", "RISK_OFF", "STAGFLATION", "REFLATION".
        """
        _, regime_str = self._compute_macro_overlay(policy_signals)
        return regime_str

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _compute_theme_scores(self, ticker: str) -> dict:
        """Build theme_scores dict from ThemeEngineService registry."""
        exposure = self._theme_engine.get_exposure(ticker)
        return {m.theme: m.thematic_score for m in exposure.mappings}

    def _compute_macro_overlay(self, policy_signals: list) -> tuple[float, str]:
        """Return (macro_bias, macro_regime_string) from policy signals.

        macro_bias is the confidence-weighted average directional bias clamped
        to [-1.0, 1.0].  Uses the same weighting formula as
        MacroPolicyEngineService.assess_regime() for consistency.

        Returns:
            Tuple of (macro_bias: float, macro_regime: str).
        """
        if not policy_signals:
            return 0.0, "NEUTRAL"
        regime_indicator = self._macro_policy.assess_regime(policy_signals)
        # Weighted bias: sum(bias * confidence) / n_signals  (matches assess_regime)
        weighted_bias = sum(
            s.directional_bias * s.confidence for s in policy_signals
        )
        avg_bias = weighted_bias / len(policy_signals)
        macro_bias = round(max(-1.0, min(1.0, avg_bias)), 4)
        macro_regime = regime_indicator.regime.value.upper()
        return macro_bias, macro_regime

    def _compute_sentiment_overlay(
        self, ticker: str, news_insights: list
    ) -> tuple[float, float]:
        """Return (sentiment_score, sentiment_confidence) for a ticker.

        Filters news_insights to those mentioning the ticker (case-insensitive),
        then computes a credibility-weighted average sentiment score.

        Returns:
            Tuple of (sentiment_score: float, sentiment_confidence: float).
            Both are 0.0 when no relevant insights exist.
        """
        ticker_upper = ticker.upper()
        ticker_insights = [
            i for i in news_insights
            if ticker_upper in [t.upper() for t in i.affected_tickers]
        ]
        if not ticker_insights:
            return 0.0, 0.0
        total_weight = sum(i.credibility_weight for i in ticker_insights)
        if total_weight == 0.0:
            return 0.0, 0.0
        weighted_sentiment = sum(
            i.sentiment_score * i.credibility_weight for i in ticker_insights
        )
        sentiment_score = round(
            max(-1.0, min(1.0, weighted_sentiment / total_weight)), 4
        )
        # Confidence = mean credibility weight capped at 1.0
        sentiment_confidence = round(
            min(1.0, total_weight / len(ticker_insights)), 4
        )
        return sentiment_score, sentiment_confidence

    # ------------------------------------------------------------------
    # Fundamentals overlay helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_fundamentals(feature_set: FeatureSet, fund_data: Any) -> FeatureSet:
        """Return a new FeatureSet with fundamentals fields applied from *fund_data*.

        Uses ``dataclasses.replace`` so the input is never mutated.  Fields on
        *fund_data* that are ``None`` are still written (i.e. they overwrite any
        prior value), because we want the fundamentals refresh timestamp to reset
        stale data.
        """
        return replace(
            feature_set,
            pe_ratio=fund_data.pe_ratio,
            forward_pe=fund_data.forward_pe,
            peg_ratio=fund_data.peg_ratio,
            price_to_sales=fund_data.price_to_sales,
            eps_growth=fund_data.eps_growth,
            revenue_growth=fund_data.revenue_growth,
            earnings_surprise_pct=fund_data.earnings_surprise_pct,
        )
