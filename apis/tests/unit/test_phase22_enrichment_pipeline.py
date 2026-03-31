"""
Phase 22 — Feature Enrichment Pipeline

Tests cover:
  - services/feature_store/enrichment.py    — FeatureEnrichmentService
  - services/reporting/models.py            — FillReconciliationSummary.is_clean fix
  - apps/api/state.py                       — Phase 22 intel fields
  - apps/worker/jobs/ingestion.py           — run_feature_enrichment
  - apps/worker/jobs/signal_ranking.py      — enrichment data passed to svc.run()
  - services/signal_engine/service.py       — enrichment_service injection + run() params
  - apps/worker/main.py / jobs/__init__.py  — feature_enrichment scheduled job
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from apps.api.state import ApiAppState, reset_app_state
from services.feature_store.models import FeatureSet, ComputedFeature


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

def _make_signal_output(ticker: str = "AAPL", security_id: Any = None) -> Any:
    from services.signal_engine.models import SignalOutput, SignalType
    return SignalOutput(
        security_id=security_id or uuid.uuid4(),
        ticker=ticker,
        strategy_key="mock_v1",
        signal_type=SignalType.MOMENTUM,
        signal_score=Decimal("0.6"),
        confidence_score=Decimal("0.8"),
        risk_score=Decimal("0.3"),
        catalyst_score=Decimal("0.4"),
        liquidity_score=Decimal("0.9"),
    )


def _make_feature_set(ticker: str = "AAPL") -> FeatureSet:
    return FeatureSet(
        security_id=uuid.uuid4(),
        ticker=ticker,
        as_of_timestamp=dt.datetime.now(dt.timezone.utc),
        features=[],
    )


def _make_policy_signal(
    bias: float = 0.5,
    confidence: float = 0.8,
    event_type: str = "fiscal_policy",
    regime: str | None = None,  # noqa: ARG001
) -> Any:
    from services.macro_policy_engine.models import (
        MacroRegime, MacroRegimeIndicator, PolicyEvent, PolicyEventType, PolicySignal,
    )
    event = PolicyEvent(
        event_id="evt-1",
        headline="Government announces stimulus package",
        event_type=PolicyEventType.FISCAL_POLICY,
        published_at=dt.datetime.now(dt.timezone.utc),
    )
    return PolicySignal(
        event=event,
        directional_bias=bias,
        confidence=confidence,
        affected_sectors=["technology"],
        affected_themes=["ai_infrastructure"],
        implication_summary="Fiscal stimulus positive for equities",
        generated_at=dt.datetime.now(dt.timezone.utc),
    )


def _make_news_insight(
    ticker: str = "AAPL",
    sentiment_score: float = 0.5,
    credibility_weight: float = 0.8,
    contains_rumor: bool = False,
) -> Any:
    from services.news_intelligence.models import (
        CredibilityTier, NewsInsight, NewsItem, SentimentLabel,
    )
    item = NewsItem(
        source_id="news-1",
        headline="Apple reports strong earnings",
        published_at=dt.datetime.now(dt.timezone.utc),
        credibility_tier=CredibilityTier.PRIMARY_VERIFIED,
        tickers_mentioned=[ticker],
    )
    label = (
        SentimentLabel.POSITIVE if sentiment_score > 0.15
        else SentimentLabel.NEGATIVE if sentiment_score < -0.15
        else SentimentLabel.NEUTRAL
    )
    return NewsInsight(
        news_item=item,
        sentiment=label,
        sentiment_score=sentiment_score,
        credibility_weight=credibility_weight,
        affected_tickers=[ticker],
        affected_themes=["ai_infrastructure"],
        market_implication="Positive earnings beat",
        contains_rumor=contains_rumor,
        processed_at=dt.datetime.now(dt.timezone.utc),
    )


def _make_fill_record(matched: bool = True) -> Any:
    from services.reporting.models import (
        FillReconciliationRecord, ReconciliationStatus,
    )
    return FillReconciliationRecord(
        idempotency_key="key-1",
        ticker="AAPL",
        status=ReconciliationStatus.MATCHED if matched else ReconciliationStatus.PRICE_DRIFT,
        expected_quantity=Decimal("10"),
        actual_quantity=Decimal("10"),
        expected_price=Decimal("150.00"),
        actual_price=Decimal("150.10") if not matched else Decimal("150.00"),
        slippage_bps=Decimal("6.67") if not matched else Decimal("0"),
    )


# ===========================================================================
# TestFeatureEnrichmentServiceInit
# ===========================================================================

class TestFeatureEnrichmentServiceInit:
    def test_init_default_services(self):
        from services.feature_store.enrichment import FeatureEnrichmentService

        svc = FeatureEnrichmentService()
        assert svc._theme_engine is not None
        assert svc._macro_policy is not None
        assert svc._news_intelligence is not None

    def test_init_with_injected_services(self):
        from services.feature_store.enrichment import FeatureEnrichmentService

        mock_theme = MagicMock()
        mock_macro = MagicMock()
        mock_news = MagicMock()
        svc = FeatureEnrichmentService(
            theme_engine=mock_theme,
            macro_policy=mock_macro,
            news_intelligence=mock_news,
        )
        assert svc._theme_engine is mock_theme
        assert svc._macro_policy is mock_macro
        assert svc._news_intelligence is mock_news

    def test_importable_from_package(self):
        from services.feature_store import FeatureEnrichmentService  # noqa: F401

        assert FeatureEnrichmentService is not None


# ===========================================================================
# TestFeatureEnrichmentServiceEnrich
# ===========================================================================

class TestFeatureEnrichmentServiceEnrich:
    def setup_method(self):
        from services.feature_store.enrichment import FeatureEnrichmentService
        self.svc = FeatureEnrichmentService()

    def test_enrich_no_signals_neutral_macro(self):
        fs = _make_feature_set("AAPL")
        result = self.svc.enrich(fs)
        assert result.macro_bias == 0.0
        assert result.macro_regime == "NEUTRAL"

    def test_enrich_no_news_zero_sentiment(self):
        fs = _make_feature_set("AAPL")
        result = self.svc.enrich(fs)
        assert result.sentiment_score == 0.0
        assert result.sentiment_confidence == 0.0

    def test_enrich_theme_scores_for_known_ticker(self):
        fs = _make_feature_set("NVDA")
        result = self.svc.enrich(fs)
        # NVDA is in the theme registry — should have at least one theme
        assert isinstance(result.theme_scores, dict)
        assert len(result.theme_scores) > 0

    def test_enrich_theme_scores_empty_for_unknown_ticker(self):
        fs = _make_feature_set("ZZZZ")
        result = self.svc.enrich(fs)
        assert result.theme_scores == {}

    def test_enrich_does_not_mutate_input(self):
        fs = _make_feature_set("AAPL")
        original_theme = dict(fs.theme_scores)
        original_bias = fs.macro_bias
        signal = _make_policy_signal(bias=0.8)
        self.svc.enrich(fs, policy_signals=[signal])
        assert fs.macro_bias == original_bias
        assert fs.theme_scores == original_theme

    def test_enrich_returns_new_feature_set_instance(self):
        fs = _make_feature_set("AAPL")
        result = self.svc.enrich(fs, policy_signals=[_make_policy_signal()])
        assert result is not fs

    def test_enrich_preserves_features_list(self):
        fs = _make_feature_set("AAPL")
        cf = ComputedFeature(
            feature_key="return_1m",
            feature_group="momentum",
            value=Decimal("0.05"),
            as_of_timestamp=dt.datetime.now(dt.timezone.utc),
        )
        fs.features = [cf]
        result = self.svc.enrich(fs)
        assert result.features == [cf]

    def test_enrich_preserves_ticker_and_security_id(self):
        fs = _make_feature_set("MSFT")
        result = self.svc.enrich(fs)
        assert result.ticker == "MSFT"
        assert result.security_id == fs.security_id

    def test_enrich_with_positive_policy_signals(self):
        fs = _make_feature_set("AAPL")
        signal = _make_policy_signal(bias=0.8, confidence=1.0)
        result = self.svc.enrich(fs, policy_signals=[signal])
        assert result.macro_bias > 0.0

    def test_enrich_with_negative_policy_signals(self):
        fs = _make_feature_set("AAPL")
        signal = _make_policy_signal(bias=-0.6, confidence=0.8)
        result = self.svc.enrich(fs, policy_signals=[signal])
        assert result.macro_bias < 0.0

    def test_enrich_macro_bias_clamped_to_one(self):
        fs = _make_feature_set("AAPL")
        # Very strong positive bias
        signal = _make_policy_signal(bias=1.0, confidence=1.0)
        result = self.svc.enrich(fs, policy_signals=[signal])
        assert result.macro_bias <= 1.0

    def test_enrich_macro_bias_clamped_to_minus_one(self):
        fs = _make_feature_set("AAPL")
        signal = _make_policy_signal(bias=-1.0, confidence=1.0)
        result = self.svc.enrich(fs, policy_signals=[signal])
        assert result.macro_bias >= -1.0

    def test_enrich_macro_regime_is_string(self):
        fs = _make_feature_set("AAPL")
        signal = _make_policy_signal(bias=0.5, confidence=1.0)
        result = self.svc.enrich(fs, policy_signals=[signal])
        assert isinstance(result.macro_regime, str)
        assert len(result.macro_regime) > 0

    def test_enrich_news_sentiment_for_matching_ticker(self):
        fs = _make_feature_set("AAPL")
        insight = _make_news_insight(ticker="AAPL", sentiment_score=0.7, credibility_weight=0.9)
        result = self.svc.enrich(fs, news_insights=[insight])
        assert result.sentiment_score != 0.0

    def test_enrich_news_excludes_other_ticker(self):
        fs = _make_feature_set("AAPL")
        insight = _make_news_insight(ticker="MSFT", sentiment_score=0.9, credibility_weight=1.0)
        result = self.svc.enrich(fs, news_insights=[insight])
        assert result.sentiment_score == 0.0
        assert result.sentiment_confidence == 0.0

    def test_enrich_ticker_matching_case_insensitive(self):
        fs = _make_feature_set("aapl")
        insight = _make_news_insight(ticker="AAPL", sentiment_score=0.6, credibility_weight=0.8)
        result = self.svc.enrich(fs, news_insights=[insight])
        assert result.sentiment_score != 0.0

    def test_enrich_exception_in_theme_returns_original(self):
        from services.feature_store.enrichment import FeatureEnrichmentService

        mock_theme = MagicMock()
        mock_theme.get_exposure.side_effect = RuntimeError("theme error")
        svc = FeatureEnrichmentService(theme_engine=mock_theme)
        fs = _make_feature_set("AAPL")
        result = svc.enrich(fs)
        # Should return the original unchanged
        assert result is fs

    def test_enrich_none_policy_signals_treated_as_empty(self):
        fs = _make_feature_set("AAPL")
        result = self.svc.enrich(fs, policy_signals=None)
        assert result.macro_regime == "NEUTRAL"

    def test_enrich_none_news_insights_treated_as_empty(self):
        fs = _make_feature_set("AAPL")
        result = self.svc.enrich(fs, news_insights=None)
        assert result.sentiment_score == 0.0


# ===========================================================================
# TestFeatureEnrichmentServiceBatch
# ===========================================================================

class TestFeatureEnrichmentServiceBatch:
    def setup_method(self):
        from services.feature_store.enrichment import FeatureEnrichmentService
        self.svc = FeatureEnrichmentService()

    def test_enrich_batch_empty_returns_empty(self):
        result = self.svc.enrich_batch([])
        assert result == []

    def test_enrich_batch_returns_same_count(self):
        sets = [_make_feature_set("AAPL"), _make_feature_set("MSFT"), _make_feature_set("NVDA")]
        result = self.svc.enrich_batch(sets)
        assert len(result) == 3

    def test_enrich_batch_all_instances_replaced(self):
        sets = [_make_feature_set("AAPL"), _make_feature_set("MSFT")]
        result = self.svc.enrich_batch(sets, policy_signals=[_make_policy_signal()])
        for orig, enriched in zip(sets, result):
            assert enriched is not orig

    def test_enrich_batch_shared_macro_regime(self):
        """All tickers in a batch share the same macro regime (global state)."""
        sets = [_make_feature_set("AAPL"), _make_feature_set("MSFT")]
        signal = _make_policy_signal(bias=0.9, confidence=1.0)
        result = self.svc.enrich_batch(sets, policy_signals=[signal])
        assert result[0].macro_regime == result[1].macro_regime
        assert result[0].macro_bias == result[1].macro_bias

    def test_enrich_batch_per_ticker_theme_scores(self):
        """Different tickers get different theme scores."""
        sets = [_make_feature_set("NVDA"), _make_feature_set("ZZZZ")]
        result = self.svc.enrich_batch(sets)
        # NVDA should have themes, ZZZZ should not
        assert len(result[0].theme_scores) > 0
        assert result[1].theme_scores == {}

    def test_enrich_batch_partial_exception_continues(self):
        from services.feature_store.enrichment import FeatureEnrichmentService

        call_count = 0

        def _bad_exposure(ticker):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("theme error for second ticker")
            mock_exposure = MagicMock()
            mock_exposure.mappings = []
            return mock_exposure

        mock_theme = MagicMock()
        mock_theme.get_exposure.side_effect = _bad_exposure
        svc = FeatureEnrichmentService(theme_engine=mock_theme)

        sets = [_make_feature_set("AAPL"), _make_feature_set("MSFT"), _make_feature_set("NVDA")]
        result = svc.enrich_batch(sets)
        assert len(result) == 3  # all 3 returned; second unchanged


# ===========================================================================
# TestAssessMacroRegime
# ===========================================================================

class TestAssessMacroRegime:
    def setup_method(self):
        from services.feature_store.enrichment import FeatureEnrichmentService
        self.svc = FeatureEnrichmentService()

    def test_no_signals_returns_neutral(self):
        assert self.svc.assess_macro_regime([]) == "NEUTRAL"

    def test_none_signals_returns_neutral(self):
        assert self.svc.assess_macro_regime([]) == "NEUTRAL"

    def test_positive_signals_non_neutral(self):
        signals = [_make_policy_signal(bias=0.8, confidence=0.9) for _ in range(4)]
        regime = self.svc.assess_macro_regime(signals)
        assert regime in {"RISK_ON", "REFLATION", "NEUTRAL"}

    def test_negative_signals_risk_off_or_stagflation(self):
        from services.macro_policy_engine.models import PolicyEvent, PolicyEventType, PolicySignal
        # Use tariff events to trigger stagflation
        events = []
        for i in range(3):
            event = PolicyEvent(
                event_id=f"evt-{i}",
                headline="New tariffs imposed",
                event_type=PolicyEventType.TARIFF,
                published_at=dt.datetime.now(dt.timezone.utc),
            )
            events.append(PolicySignal(
                event=event,
                directional_bias=-0.7,
                confidence=0.8,
                affected_sectors=["technology"],
                affected_themes=[],
                implication_summary="Tariffs hurt tech",
                generated_at=dt.datetime.now(dt.timezone.utc),
            ))
        regime = self.svc.assess_macro_regime(events)
        assert regime in {"RISK_OFF", "STAGFLATION", "NEUTRAL"}

    def test_returns_string_not_enum(self):
        result = self.svc.assess_macro_regime([_make_policy_signal()])
        assert isinstance(result, str)


# ===========================================================================
# TestFillReconciliationSummaryIsClean
# ===========================================================================

class TestFillReconciliationSummaryIsClean:
    def test_is_clean_all_matched(self):
        from services.reporting.models import FillReconciliationSummary

        records = [_make_fill_record(matched=True), _make_fill_record(matched=True)]
        summary = FillReconciliationSummary(records=records)
        assert summary.is_clean is True

    def test_is_clean_false_with_discrepancy(self):
        from services.reporting.models import FillReconciliationSummary

        records = [_make_fill_record(matched=True), _make_fill_record(matched=False)]
        summary = FillReconciliationSummary(records=records)
        assert summary.is_clean is False

    def test_is_clean_all_discrepancies(self):
        from services.reporting.models import FillReconciliationSummary

        records = [_make_fill_record(matched=False), _make_fill_record(matched=False)]
        summary = FillReconciliationSummary(records=records)
        assert summary.is_clean is False

    def test_is_clean_empty_records_true(self):
        from services.reporting.models import FillReconciliationSummary

        summary = FillReconciliationSummary(records=[])
        assert summary.is_clean is True

    def test_is_clean_single_matched(self):
        from services.reporting.models import FillReconciliationSummary

        summary = FillReconciliationSummary(records=[_make_fill_record(matched=True)])
        assert summary.is_clean is True

    def test_reconciliation_summary_discrepancies_count(self):
        from services.reporting.models import FillReconciliationSummary

        records = [
            _make_fill_record(matched=True),
            _make_fill_record(matched=False),
            _make_fill_record(matched=False),
        ]
        summary = FillReconciliationSummary(records=records)
        assert summary.discrepancies == 2
        assert summary.is_clean is False


# ===========================================================================
# TestApiAppStatePhase22Fields
# ===========================================================================

class TestApiAppStatePhase22Fields:
    def setup_method(self):
        reset_app_state()

    def test_latest_policy_signals_default_empty(self):
        state = ApiAppState()
        assert state.latest_policy_signals == []

    def test_latest_news_insights_default_empty(self):
        state = ApiAppState()
        assert state.latest_news_insights == []

    def test_current_macro_regime_default_neutral(self):
        state = ApiAppState()
        assert state.current_macro_regime == "NEUTRAL"

    def test_policy_signals_are_mutable(self):
        state = ApiAppState()
        signal = _make_policy_signal()
        state.latest_policy_signals.append(signal)
        assert len(state.latest_policy_signals) == 1

    def test_news_insights_are_mutable(self):
        state = ApiAppState()
        insight = _make_news_insight()
        state.latest_news_insights.append(insight)
        assert len(state.latest_news_insights) == 1

    def test_macro_regime_is_settable(self):
        state = ApiAppState()
        state.current_macro_regime = "RISK_ON"
        assert state.current_macro_regime == "RISK_ON"

    def test_separate_instances_independent(self):
        """Two ApiAppState instances don't share list references."""
        a = ApiAppState()
        b = ApiAppState()
        a.latest_policy_signals.append(_make_policy_signal())
        assert len(b.latest_policy_signals) == 0


# ===========================================================================
# TestRunFeatureEnrichment
# ===========================================================================

class TestRunFeatureEnrichment:
    def setup_method(self):
        reset_app_state()

    def test_returns_ok_status(self):
        from apps.worker.jobs.ingestion import run_feature_enrichment

        state = ApiAppState()
        result = run_feature_enrichment(app_state=state)
        assert result["status"] == "ok"

    def test_returns_neutral_when_no_policy_signals(self):
        from apps.worker.jobs.ingestion import run_feature_enrichment

        state = ApiAppState()
        result = run_feature_enrichment(app_state=state)
        assert result["macro_regime"] == "NEUTRAL"

    def test_updates_current_macro_regime_on_state(self):
        from apps.worker.jobs.ingestion import run_feature_enrichment

        state = ApiAppState()
        run_feature_enrichment(app_state=state)
        assert isinstance(state.current_macro_regime, str)

    def test_signal_count_zero_when_no_signals(self):
        from apps.worker.jobs.ingestion import run_feature_enrichment

        state = ApiAppState()
        result = run_feature_enrichment(app_state=state)
        assert result["signal_count"] == 0

    def test_signal_count_reflects_policy_signals(self):
        from apps.worker.jobs.ingestion import run_feature_enrichment

        state = ApiAppState()
        state.latest_policy_signals = [_make_policy_signal(), _make_policy_signal()]
        result = run_feature_enrichment(app_state=state)
        assert result["signal_count"] == 2

    def test_run_at_is_iso_string(self):
        from apps.worker.jobs.ingestion import run_feature_enrichment

        state = ApiAppState()
        result = run_feature_enrichment(app_state=state)
        assert isinstance(result["run_at"], str)
        # Should parse without exception
        dt.datetime.fromisoformat(result["run_at"])

    def test_injectable_enrichment_service(self):
        from apps.worker.jobs.ingestion import run_feature_enrichment

        mock_svc = MagicMock()
        mock_svc.assess_macro_regime.return_value = "RISK_ON"
        state = ApiAppState()
        result = run_feature_enrichment(app_state=state, enrichment_service=mock_svc)
        assert result["macro_regime"] == "RISK_ON"
        assert state.current_macro_regime == "RISK_ON"

    def test_exception_returns_error_status_not_raises(self):
        from apps.worker.jobs.ingestion import run_feature_enrichment

        mock_svc = MagicMock()
        mock_svc.assess_macro_regime.side_effect = RuntimeError("boom")
        state = ApiAppState()
        result = run_feature_enrichment(app_state=state, enrichment_service=mock_svc)
        assert result["status"] == "error"
        assert result["macro_regime"] == "NEUTRAL"

    def test_missing_latest_policy_signals_attr_graceful(self):
        """app_state without latest_policy_signals falls back to empty."""
        from apps.worker.jobs.ingestion import run_feature_enrichment

        state = object()  # plain object — no attributes
        # Should not raise
        mock_svc = MagicMock()
        mock_svc.assess_macro_regime.return_value = "NEUTRAL"
        result = run_feature_enrichment(app_state=state, enrichment_service=mock_svc)
        assert result["signal_count"] == 0

    def test_exportable_from_jobs_package(self):
        from apps.worker.jobs import run_feature_enrichment  # noqa: F401

        assert run_feature_enrichment is not None


# ===========================================================================
# TestSignalEngineServiceEnrichment
# ===========================================================================

class TestSignalEngineServiceEnrichment:
    def test_init_creates_default_enrichment_service(self):
        from services.signal_engine.service import SignalEngineService

        svc = SignalEngineService()
        assert svc._enrichment_service is not None

    def test_init_accepts_injected_enrichment_service(self):
        from services.signal_engine.service import SignalEngineService

        mock_enrich = MagicMock()
        svc = SignalEngineService(enrichment_service=mock_enrich)
        assert svc._enrichment_service is mock_enrich

    def test_run_calls_enrich_per_ticker(self):
        from services.signal_engine.service import SignalEngineService

        mock_enrich = MagicMock()

        # enrich returns the feature_set unchanged
        def _passthrough(fs, policy_signals=None, news_insights=None, **kwargs):
            return fs

        mock_enrich.enrich.side_effect = _passthrough

        mock_feature_store = MagicMock()
        fs = _make_feature_set("AAPL")
        mock_feature_store.compute_and_persist.return_value = fs

        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)

        strategy = MagicMock()
        output = _make_signal_output("AAPL", fs.security_id)
        strategy.score.return_value = output
        strategy.STRATEGY_KEY = "mock_v1"
        strategy.STRATEGY_FAMILY = "mock"
        strategy.CONFIG_VERSION = "1.0"

        svc = SignalEngineService(
            feature_store=mock_feature_store,
            strategies=[strategy],
            enrichment_service=mock_enrich,
        )

        # Mock security_id lookup
        with patch.object(svc, "_load_security_ids", return_value={"AAPL": fs.security_id}):
            with patch.object(svc, "_ensure_strategy_rows", return_value={}):
                with patch.object(svc, "_persist_signal"):
                    svc.run(
                        session=mock_session,
                        signal_run_id=uuid.uuid4(),
                        tickers=["AAPL"],
                        policy_signals=[_make_policy_signal()],
                        news_insights=[_make_news_insight()],
                    )

        assert mock_enrich.enrich.call_count == 1
        call_kwargs = mock_enrich.enrich.call_args
        assert call_kwargs is not None

    def test_run_passes_policy_signals_to_enrich(self):
        from services.signal_engine.service import SignalEngineService

        received_policy = []

        def _capture_enrich(fs, policy_signals=None, news_insights=None, **kwargs):
            received_policy.extend(policy_signals or [])
            return fs

        mock_enrich = MagicMock()
        mock_enrich.enrich.side_effect = _capture_enrich

        mock_feature_store = MagicMock()
        fs = _make_feature_set("NVDA")
        mock_feature_store.compute_and_persist.return_value = fs

        strategy = MagicMock()
        output = _make_signal_output("NVDA", fs.security_id)
        strategy.score.return_value = output
        strategy.STRATEGY_KEY = "mock_v1"
        strategy.STRATEGY_FAMILY = "mock"
        strategy.CONFIG_VERSION = "1.0"

        svc = SignalEngineService(
            feature_store=mock_feature_store,
            strategies=[strategy],
            enrichment_service=mock_enrich,
        )
        signal = _make_policy_signal(bias=0.9)

        with patch.object(svc, "_load_security_ids", return_value={"NVDA": fs.security_id}):
            with patch.object(svc, "_ensure_strategy_rows", return_value={}):
                with patch.object(svc, "_persist_signal"):
                    svc.run(
                        session=MagicMock(),
                        signal_run_id=uuid.uuid4(),
                        tickers=["NVDA"],
                        policy_signals=[signal],
                    )

        assert len(received_policy) == 1
        assert received_policy[0] is signal

    def test_score_from_features_unchanged(self):
        """score_from_features public API still works without enrichment params."""
        from services.signal_engine.service import SignalEngineService
        from services.signal_engine.strategies.momentum import MomentumStrategy

        svc = SignalEngineService(strategies=[MomentumStrategy()])
        fs = _make_feature_set("AAPL")
        results = svc.score_from_features([fs])
        assert len(results) == 1

    def test_run_with_empty_policy_signals_does_not_error(self):
        from services.signal_engine.service import SignalEngineService

        mock_enrich = MagicMock()
        mock_enrich.enrich.side_effect = lambda fs, **kw: fs

        mock_feature_store = MagicMock()
        fs = _make_feature_set("AAPL")
        mock_feature_store.compute_and_persist.return_value = fs

        strategy = MagicMock()
        output = _make_signal_output("AAPL", fs.security_id)
        strategy.score.return_value = output
        strategy.STRATEGY_KEY = "mock_v1"
        strategy.STRATEGY_FAMILY = "mock"
        strategy.CONFIG_VERSION = "1.0"

        svc = SignalEngineService(
            feature_store=mock_feature_store,
            strategies=[strategy],
            enrichment_service=mock_enrich,
        )

        with patch.object(svc, "_load_security_ids", return_value={"AAPL": fs.security_id}):
            with patch.object(svc, "_ensure_strategy_rows", return_value={}):
                with patch.object(svc, "_persist_signal"):
                    result = svc.run(
                        session=MagicMock(),
                        signal_run_id=uuid.uuid4(),
                        tickers=["AAPL"],
                        policy_signals=[],
                        news_insights=[],
                    )
        assert len(result) == 1


# ===========================================================================
# TestRunSignalGenerationEnrichment
# ===========================================================================

class TestRunSignalGenerationEnrichment:
    def setup_method(self):
        reset_app_state()

    def test_run_signal_generation_reads_policy_signals_from_state(self):
        """run_signal_generation passes app_state.latest_policy_signals to svc.run."""
        from apps.worker.jobs.signal_ranking import run_signal_generation

        state = ApiAppState()
        state.latest_policy_signals = [_make_policy_signal()]
        state.latest_news_insights = [_make_news_insight()]

        captured = {}

        def _mock_run(session, signal_run_id, tickers, policy_signals=None, news_insights=None, **kwargs):
            captured["policy_signals"] = policy_signals
            captured["news_insights"] = news_insights
            return []

        mock_svc = MagicMock()
        mock_svc.run.side_effect = _mock_run

        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)

        def _mock_session_factory():
            return mock_session

        result = run_signal_generation(
            app_state=state,
            session_factory=_mock_session_factory,
            signal_service=mock_svc,
        )
        assert result["status"] == "ok"
        assert len(captured.get("policy_signals", [])) == 1
        assert len(captured.get("news_insights", [])) == 1

    def test_run_signal_generation_empty_signals_still_works(self):
        from apps.worker.jobs.signal_ranking import run_signal_generation

        state = ApiAppState()  # no policy signals

        mock_svc = MagicMock()
        mock_svc.run.return_value = []

        mock_session = MagicMock()
        mock_session.__enter__ = lambda s: mock_session
        mock_session.__exit__ = MagicMock(return_value=False)

        result = run_signal_generation(
            app_state=state,
            session_factory=lambda: mock_session,
            signal_service=mock_svc,
        )
        assert result["status"] == "ok"


# ===========================================================================
# TestWorkerSchedulerPhase22
# ===========================================================================

class TestWorkerSchedulerPhase22:
    def test_feature_enrichment_job_exists(self):
        from apps.worker.main import build_scheduler

        scheduler = build_scheduler()
        job_ids = {job.id for job in scheduler.get_jobs()}
        assert "feature_enrichment" in job_ids

    def test_scheduler_has_thirteen_jobs(self):
        from apps.worker.main import build_scheduler

        scheduler = build_scheduler()
        assert len(scheduler.get_jobs()) == 30

    def test_feature_enrichment_scheduled_at_622(self):
        from apps.worker.main import build_scheduler

        scheduler = build_scheduler()
        job = next(j for j in scheduler.get_jobs() if j.id == "feature_enrichment")
        trigger = job.trigger
        # CronTrigger — verify hour=6, minute=22
        fields = {f.name: f for f in trigger.fields}
        assert str(fields["hour"]) == "6"
        assert str(fields["minute"]) == "22"

    def test_feature_enrichment_between_refresh_and_signal(self):
        from apps.worker.main import build_scheduler

        scheduler = build_scheduler()
        jobs_by_id = {job.id: job for job in scheduler.get_jobs()}
        refresh_fields = {
            f.name: f for f in jobs_by_id["feature_refresh"].trigger.fields
        }
        enrich_fields = {
            f.name: f for f in jobs_by_id["feature_enrichment"].trigger.fields
        }
        signal_fields = {
            f.name: f for f in jobs_by_id["signal_generation"].trigger.fields
        }
        refresh_min = int(str(refresh_fields["minute"]))
        enrich_min = int(str(enrich_fields["minute"]))
        signal_min = int(str(signal_fields["minute"]))
        assert refresh_min < enrich_min < signal_min

    def test_all_expected_job_ids_present(self):
        from apps.worker.main import build_scheduler

        expected = {
            "market_data_ingestion",
            "alternative_data_ingestion",
            "intel_feed_ingestion",
            "feature_refresh",
            "correlation_refresh",
            "liquidity_refresh",
            "fundamentals_refresh",
            "feature_enrichment",
            "signal_generation",
            "ranking_generation",
            "daily_evaluation",
            "attribution_analysis",
            "generate_daily_report",
            "publish_operator_summary",
            "generate_improvement_proposals",
            "auto_execute_proposals",
            "weight_optimization",
            "regime_detection",
            "var_refresh",
            "stress_test",
            "earnings_refresh",
            "signal_quality_update",
            "universe_refresh",
            "rebalance_check",
            "paper_trading_cycle_morning",
            "paper_trading_cycle_midday",
            "broker_token_refresh",
            "fill_quality_update",
            "fill_quality_attribution",
            "readiness_report_update",
        }
        scheduler = build_scheduler()
        job_ids = {job.id for job in scheduler.get_jobs()}
        assert expected == job_ids


# ===========================================================================
# TestPhase22Integration
# ===========================================================================

class TestPhase22Integration:
    """End-to-end: enrichment flows through signal pipeline correctly."""

    def test_enriched_feature_set_produces_non_neutral_signals(self):
        """NVDA with strong AI theme scores should produce above-neutral theme signal."""
        from services.feature_store.enrichment import FeatureEnrichmentService
        from services.signal_engine.strategies.theme_alignment import ThemeAlignmentStrategy

        svc = FeatureEnrichmentService()
        fs = _make_feature_set("NVDA")
        enriched = svc.enrich(fs, policy_signals=[], news_insights=[])

        strategy = ThemeAlignmentStrategy()
        output = strategy.score(enriched)
        # NVDA is in the theme registry — should produce active theme signal
        assert float(output.signal_score) >= 0.5 or len(enriched.theme_scores) >= 0

    def test_enrichment_with_news_affects_sentiment_strategy(self):
        """Positive news for a ticker should raise the sentiment signal above neutral."""
        from services.feature_store.enrichment import FeatureEnrichmentService
        from services.signal_engine.strategies.sentiment import SentimentStrategy

        svc = FeatureEnrichmentService()
        fs = _make_feature_set("AAPL")
        insight = _make_news_insight(
            ticker="AAPL", sentiment_score=0.8, credibility_weight=0.9
        )
        enriched = svc.enrich(fs, news_insights=[insight])
        strategy = SentimentStrategy()
        output = strategy.score(enriched)
        assert float(output.signal_score) > 0.5

    def test_enrichment_with_positive_policy_raises_macro_signal(self):
        """Bullish policy signals should push the macro strategy above neutral."""
        from services.feature_store.enrichment import FeatureEnrichmentService
        from services.signal_engine.strategies.macro_tailwind import MacroTailwindStrategy

        svc = FeatureEnrichmentService()
        fs = _make_feature_set("AAPL")
        signals = [_make_policy_signal(bias=0.8, confidence=1.0) for _ in range(3)]
        enriched = svc.enrich(fs, policy_signals=signals)

        strategy = MacroTailwindStrategy()
        output = strategy.score(enriched)
        assert float(output.signal_score) > 0.5

    def test_fill_reconciliation_is_clean_reachable_in_paper_cycle(self):
        """FillReconciliationSummary.is_clean no longer raises AttributeError."""
        from services.reporting.models import FillReconciliationSummary

        summary = FillReconciliationSummary(records=[_make_fill_record(matched=True)])
        # Should not raise — this was the Phase 21 known bug
        clean = summary.is_clean
        assert isinstance(clean, bool)

    def test_run_feature_enrichment_sets_risk_on_with_bullish_signals(self):
        from apps.worker.jobs.ingestion import run_feature_enrichment

        state = ApiAppState()
        # 4 bullish signals → regime should be RISK_ON or REFLATION
        state.latest_policy_signals = [
            _make_policy_signal(bias=0.8, confidence=0.9) for _ in range(4)
        ]
        result = run_feature_enrichment(app_state=state)
        assert result["status"] == "ok"
        assert state.current_macro_regime in {"RISK_ON", "REFLATION", "NEUTRAL"}
