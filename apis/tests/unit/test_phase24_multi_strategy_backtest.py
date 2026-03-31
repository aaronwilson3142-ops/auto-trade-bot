"""Phase 24 unit tests — multi-strategy backtest, operator push endpoints,
and metrics expansion.

Covers:
  - BacktestEngine multi-strategy integration   (TestBacktestMultiStrategy)
  - BacktestEngine enrichment_service wiring    (TestBacktestEnrichmentService)
  - POST /intelligence/events                   (TestPushPolicyEvent)
  - POST /intelligence/news                     (TestPushNewsItem)
  - Metrics expansion (macro_regime, signals,   (TestMetricsExpansion)
    news_insights gauges)
  - operator_api_key in settings                (TestOperatorApiKeySettings)

Run: pytest tests/unit/test_phase24_multi_strategy_backtest.py -v
"""
from __future__ import annotations

import asyncio
import datetime as dt
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient


# ===========================================================================
# Event-loop fixture (required by ib_insync which uses eventkit at import time)
# ===========================================================================

@pytest.fixture(autouse=True)
def _ensure_event_loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield
    loop.close()
    asyncio.set_event_loop(None)


# ===========================================================================
# Shared helpers
# ===========================================================================

def _make_bar_record(
    ticker: str = "AAPL",
    trade_date: dt.date | None = None,
    close: Decimal = Decimal("150"),
    volume: int = 5_000_000,
):
    from services.data_ingestion.models import BarRecord
    d = trade_date or dt.date(2023, 1, 3)
    return BarRecord(
        ticker=ticker,
        trade_date=d,
        open=close,
        high=close + Decimal("1"),
        low=close - Decimal("1"),
        close=close,
        adjusted_close=close,
        volume=volume,
        source_key="yfinance",
    )


def _make_mock_adapter(tickers: list[str], n_bars: int = 80) -> MagicMock:
    from services.data_ingestion.models import BarRecord
    mock = MagicMock()
    all_bars: dict = {}
    for ticker in tickers:
        bars = []
        base_date = dt.date(2022, 10, 1)
        price = Decimal("100")
        for i in range(n_bars):
            d = base_date + dt.timedelta(days=i)
            if d.weekday() >= 5:
                continue
            price += Decimal(str(i % 3 - 1)) * Decimal("0.5")
            bars.append(BarRecord(
                ticker=ticker, trade_date=d,
                open=price, high=price + Decimal("1"),
                low=price - Decimal("1"), close=price,
                adjusted_close=price, volume=5_000_000,
                source_key="yfinance",
            ))
        all_bars[ticker] = bars
    mock.fetch_bulk.return_value = all_bars
    return mock


def _make_policy_signal(bias: float = 0.3):
    from services.macro_policy_engine.models import (
        PolicyEvent, PolicyEventType, PolicySignal,
    )
    evt = PolicyEvent(
        event_id="test_evt",
        headline="Fed holds rates steady",
        event_type=PolicyEventType.INTEREST_RATE,
        published_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2),
    )
    return PolicySignal(
        event=evt,
        affected_sectors=["technology"],
        affected_themes=["ai_infrastructure"],
        directional_bias=bias,
        confidence=0.7,
        implication_summary="Neutral to positive for equities",
        generated_at=dt.datetime.now(dt.timezone.utc),
    )


def _make_news_insight(ticker: str = "NVDA", score: float = 0.5):
    from services.news_intelligence.models import (
        CredibilityTier, NewsInsight, NewsItem, SentimentLabel,
    )
    item = NewsItem(
        source_id="news_001",
        headline="NVDA beats earnings expectations",
        published_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1),
        credibility_tier=CredibilityTier.SECONDARY_VERIFIED,
        tickers_mentioned=[ticker],
    )
    return NewsInsight(
        news_item=item,
        sentiment=SentimentLabel.POSITIVE,
        sentiment_score=score,
        credibility_weight=0.8,
        affected_tickers=[ticker],
        affected_themes=["ai_infrastructure"],
        market_implication="Positive for GPU demand",
        contains_rumor=False,
        processed_at=dt.datetime.now(dt.timezone.utc),
    )


@dataclass
class _FakeAppState:
    latest_policy_signals: list[Any] = field(default_factory=list)
    latest_news_insights: list[Any] = field(default_factory=list)
    current_macro_regime: str = "NEUTRAL"
    latest_rankings: list[Any] = field(default_factory=list)
    paper_loop_active: bool = False
    paper_cycle_results: list[Any] = field(default_factory=list)
    improvement_proposals: list[Any] = field(default_factory=list)
    evaluation_history: list[Any] = field(default_factory=list)
    kill_switch_active: bool = False
    broker_auth_expired: bool = False
    portfolio_state: Any = None


# ===========================================================================
# 1. BacktestEngine — multi-strategy integration
# ===========================================================================

class TestBacktestMultiStrategy:
    """Verify the BacktestEngine uses all 4 strategies by default."""

    def test_default_strategies_count_is_four(self):
        from services.backtest.engine import BacktestEngine
        engine = BacktestEngine(adapter=MagicMock())
        assert len(engine._strategies) == 4

    def test_default_strategies_include_momentum(self):
        from services.backtest.engine import BacktestEngine
        from services.signal_engine.strategies.momentum import MomentumStrategy
        engine = BacktestEngine(adapter=MagicMock())
        types = [type(s) for s in engine._strategies]
        assert MomentumStrategy in types

    def test_default_strategies_include_theme_alignment(self):
        from services.backtest.engine import BacktestEngine
        from services.signal_engine.strategies.theme_alignment import ThemeAlignmentStrategy
        engine = BacktestEngine(adapter=MagicMock())
        types = [type(s) for s in engine._strategies]
        assert ThemeAlignmentStrategy in types

    def test_default_strategies_include_macro_tailwind(self):
        from services.backtest.engine import BacktestEngine
        from services.signal_engine.strategies.macro_tailwind import MacroTailwindStrategy
        engine = BacktestEngine(adapter=MagicMock())
        types = [type(s) for s in engine._strategies]
        assert MacroTailwindStrategy in types

    def test_default_strategies_include_sentiment(self):
        from services.backtest.engine import BacktestEngine
        from services.signal_engine.strategies.sentiment import SentimentStrategy
        engine = BacktestEngine(adapter=MagicMock())
        types = [type(s) for s in engine._strategies]
        assert SentimentStrategy in types

    def test_custom_strategies_override_default(self):
        from services.backtest.engine import BacktestEngine
        from services.signal_engine.strategies.momentum import MomentumStrategy
        custom = [MomentumStrategy()]
        engine = BacktestEngine(adapter=MagicMock(), strategies=custom)
        assert engine._strategies is custom
        assert len(engine._strategies) == 1

    def test_run_returns_backtest_result(self):
        from services.backtest.config import BacktestConfig
        from services.backtest.engine import BacktestEngine
        from services.backtest.models import BacktestResult
        mock_adapter = _make_mock_adapter(["AAPL", "MSFT"], n_bars=80)
        engine = BacktestEngine(adapter=mock_adapter)
        result = engine.run(BacktestConfig(
            start_date=dt.date(2022, 11, 1),
            end_date=dt.date(2022, 12, 31),
            tickers=["AAPL", "MSFT"],
            initial_cash=Decimal("50_000"),
        ))
        assert isinstance(result, BacktestResult)
        assert result.days_simulated > 0

    def test_run_with_single_strategy_completes(self):
        from services.backtest.config import BacktestConfig
        from services.backtest.engine import BacktestEngine
        from services.signal_engine.strategies.momentum import MomentumStrategy
        mock_adapter = _make_mock_adapter(["NVDA"], n_bars=80)
        engine = BacktestEngine(adapter=mock_adapter, strategies=[MomentumStrategy()])
        result = engine.run(BacktestConfig(
            start_date=dt.date(2022, 11, 1),
            end_date=dt.date(2022, 12, 15),
            tickers=["NVDA"],
            initial_cash=Decimal("100_000"),
        ))
        assert result.days_simulated > 0

    def test_run_multi_strategy_generates_more_signals(self):
        """4 strategies × N tickers = more signals than 1 strategy × N tickers."""
        from services.backtest.config import BacktestConfig
        from services.backtest.engine import BacktestEngine
        from services.signal_engine.strategies.momentum import MomentumStrategy

        tickers = ["AAPL", "MSFT"]
        mock_adapter = _make_mock_adapter(tickers, n_bars=80)

        single_engine = BacktestEngine(
            adapter=mock_adapter, strategies=[MomentumStrategy()]
        )
        multi_engine = BacktestEngine(adapter=mock_adapter)

        cfg = BacktestConfig(
            start_date=dt.date(2022, 11, 1),
            end_date=dt.date(2022, 12, 31),
            tickers=tickers,
            initial_cash=Decimal("50_000"),
        )
        single_result = single_engine.run(cfg)
        multi_result = multi_engine.run(cfg)

        # Multi-strategy should produce ≥ signals than single-strategy
        total_single = sum(d.signals_generated for d in single_result.day_results)
        total_multi = sum(d.signals_generated for d in multi_result.day_results)
        assert total_multi >= total_single

    def test_run_accepts_policy_signals_kwarg(self):
        from services.backtest.config import BacktestConfig
        from services.backtest.engine import BacktestEngine
        mock_adapter = _make_mock_adapter(["AAPL"], n_bars=80)
        engine = BacktestEngine(adapter=mock_adapter)
        # Should not raise with policy_signals provided
        result = engine.run(
            BacktestConfig(
                start_date=dt.date(2022, 11, 1),
                end_date=dt.date(2022, 12, 15),
                tickers=["AAPL"],
                initial_cash=Decimal("100_000"),
            ),
            policy_signals=[_make_policy_signal()],
        )
        assert result.days_simulated > 0

    def test_run_accepts_news_insights_kwarg(self):
        from services.backtest.config import BacktestConfig
        from services.backtest.engine import BacktestEngine
        mock_adapter = _make_mock_adapter(["NVDA"], n_bars=80)
        engine = BacktestEngine(adapter=mock_adapter)
        result = engine.run(
            BacktestConfig(
                start_date=dt.date(2022, 11, 1),
                end_date=dt.date(2022, 12, 15),
                tickers=["NVDA"],
                initial_cash=Decimal("100_000"),
            ),
            news_insights=[_make_news_insight("NVDA")],
        )
        assert result.days_simulated > 0

    def test_cash_never_goes_negative_multi_strategy(self):
        from services.backtest.config import BacktestConfig
        from services.backtest.engine import BacktestEngine
        mock_adapter = _make_mock_adapter(["AAPL", "MSFT", "NVDA"], n_bars=80)
        engine = BacktestEngine(adapter=mock_adapter)
        result = engine.run(BacktestConfig(
            start_date=dt.date(2022, 11, 1),
            end_date=dt.date(2022, 12, 31),
            tickers=["AAPL", "MSFT", "NVDA"],
            initial_cash=Decimal("30_000"),
        ))
        for dr in result.day_results:
            assert dr.cash >= Decimal("0"), f"Cash went negative on {dr.date}"


class TestBacktestEnrichmentService:
    """Verify enrichment_service is wired into _simulate_day."""

    def test_enrichment_service_none_by_default(self):
        from services.backtest.engine import BacktestEngine
        engine = BacktestEngine(adapter=MagicMock())
        assert engine._enrichment_service is None

    def test_enrichment_service_injected(self):
        from services.backtest.engine import BacktestEngine
        from services.feature_store.enrichment import FeatureEnrichmentService
        mock_svc = MagicMock(spec=FeatureEnrichmentService)
        engine = BacktestEngine(adapter=MagicMock(), enrichment_service=mock_svc)
        assert engine._enrichment_service is mock_svc

    def test_enrichment_called_when_injected(self):
        """When an enrichment_service is provided, enrich() is called per ticker per day."""
        from services.backtest.config import BacktestConfig
        from services.backtest.engine import BacktestEngine
        from services.feature_store.enrichment import FeatureEnrichmentService
        from services.feature_store.models import FeatureSet

        mock_adapter = _make_mock_adapter(["AAPL"], n_bars=80)

        mock_svc = MagicMock(spec=FeatureEnrichmentService)
        # Must return a valid FeatureSet; we use side_effect to pass through input
        mock_svc.enrich.side_effect = lambda fs, **kw: fs

        engine = BacktestEngine(adapter=mock_adapter, enrichment_service=mock_svc)
        engine.run(BacktestConfig(
            start_date=dt.date(2022, 11, 1),
            end_date=dt.date(2022, 11, 15),
            tickers=["AAPL"],
            initial_cash=Decimal("100_000"),
        ))

        assert mock_svc.enrich.call_count > 0

    def test_enrichment_exception_does_not_crash_engine(self):
        """Enrichment errors are swallowed; simulation still completes."""
        from services.backtest.config import BacktestConfig
        from services.backtest.engine import BacktestEngine
        from services.feature_store.enrichment import FeatureEnrichmentService

        mock_adapter = _make_mock_adapter(["AAPL"], n_bars=80)
        mock_svc = MagicMock(spec=FeatureEnrichmentService)
        mock_svc.enrich.side_effect = RuntimeError("simulated enrichment failure")

        engine = BacktestEngine(adapter=mock_adapter, enrichment_service=mock_svc)
        result = engine.run(BacktestConfig(
            start_date=dt.date(2022, 11, 1),
            end_date=dt.date(2022, 11, 15),
            tickers=["AAPL"],
            initial_cash=Decimal("100_000"),
        ))
        # Should complete despite enrichment errors
        assert result.days_simulated > 0

    def test_policy_signals_forwarded_to_enrichment(self):
        """Policy signals passed to run() are forwarded to enrich() calls."""
        from services.backtest.config import BacktestConfig
        from services.backtest.engine import BacktestEngine
        from services.feature_store.enrichment import FeatureEnrichmentService

        mock_adapter = _make_mock_adapter(["AAPL"], n_bars=80)
        mock_svc = MagicMock(spec=FeatureEnrichmentService)
        mock_svc.enrich.side_effect = lambda fs, **kw: fs

        signals = [_make_policy_signal(0.5)]
        engine = BacktestEngine(adapter=mock_adapter, enrichment_service=mock_svc)
        engine.run(
            BacktestConfig(
                start_date=dt.date(2022, 11, 1),
                end_date=dt.date(2022, 11, 10),
                tickers=["AAPL"],
                initial_cash=Decimal("100_000"),
            ),
            policy_signals=signals,
        )

        # All enrich() calls should have received our signals list
        for call in mock_svc.enrich.call_args_list:
            assert call.kwargs.get("policy_signals") is signals


# ===========================================================================
# 2. POST /intelligence/events — operator push
# ===========================================================================

def _make_app_with_state(state_obj):
    """Build a TestClient with the given app_state injected via override."""
    from apps.api.main import app
    from apps.api.deps import get_app_state, get_settings
    from config.settings import get_settings as real_get_settings

    app.dependency_overrides[get_app_state] = lambda: state_obj
    return TestClient(app)


def _make_settings_with_key(key: str = "test_operator_secret"):
    from config.settings import Settings
    s = Settings()
    object.__setattr__(s, "operator_api_key", key)
    return s


class TestPushPolicyEvent:
    """POST /api/v1/intelligence/events"""

    def _client(self, operator_key: str = "secret123"):
        from apps.api.main import app
        from apps.api.deps import get_app_state, get_settings
        state = _FakeAppState()

        def _override_state():
            return state

        def _override_settings():
            return _make_settings_with_key(operator_key)

        app.dependency_overrides[get_app_state] = _override_state
        app.dependency_overrides[get_settings] = _override_settings
        client = TestClient(app)
        return client, state

    def teardown_method(self):
        from apps.api.main import app
        app.dependency_overrides.clear()

    def _valid_body(self):
        return {
            "event_id": "evt_001",
            "headline": "Fed holds rates at 5.25%",
            "event_type": "interest_rate",
            "source": "Reuters",
            "affected_sectors": ["financials"],
            "affected_themes": ["rates"],
            "directional_bias": 0.3,
            "confidence": 0.8,
            "implication_summary": "Rates held; positive for growth equities",
        }

    def test_returns_201_with_valid_auth(self):
        client, _ = self._client("secret123")
        resp = client.post(
            "/api/v1/intelligence/events",
            json=self._valid_body(),
            headers={"Authorization": "Bearer secret123"},
        )
        assert resp.status_code == 201

    def test_response_status_is_accepted(self):
        client, _ = self._client()
        resp = client.post(
            "/api/v1/intelligence/events",
            json=self._valid_body(),
            headers={"Authorization": "Bearer secret123"},
        )
        assert resp.json()["status"] == "accepted"

    def test_event_appended_to_app_state(self):
        client, state = self._client()
        client.post(
            "/api/v1/intelligence/events",
            json=self._valid_body(),
            headers={"Authorization": "Bearer secret123"},
        )
        assert len(state.latest_policy_signals) == 1

    def test_event_signal_has_correct_bias(self):
        client, state = self._client()
        body = self._valid_body()
        body["directional_bias"] = 0.6
        client.post(
            "/api/v1/intelligence/events",
            json=body,
            headers={"Authorization": "Bearer secret123"},
        )
        assert abs(state.latest_policy_signals[0].directional_bias - 0.6) < 1e-6

    def test_multiple_pushes_accumulate(self):
        client, state = self._client()
        for i in range(3):
            body = self._valid_body()
            body["event_id"] = f"evt_{i:03d}"
            client.post(
                "/api/v1/intelligence/events",
                json=body,
                headers={"Authorization": "Bearer secret123"},
            )
        assert len(state.latest_policy_signals) == 3

    def test_items_in_state_reflects_count(self):
        client, state = self._client()
        # Pre-populate state with one signal
        state.latest_policy_signals = [_make_policy_signal()]
        resp = client.post(
            "/api/v1/intelligence/events",
            json=self._valid_body(),
            headers={"Authorization": "Bearer secret123"},
        )
        assert resp.json()["items_in_state"] == 2

    def test_returns_401_wrong_token(self):
        client, _ = self._client("secret123")
        resp = client.post(
            "/api/v1/intelligence/events",
            json=self._valid_body(),
            headers={"Authorization": "Bearer wrong_token"},
        )
        assert resp.status_code == 401

    def test_returns_401_missing_auth_header(self):
        client, _ = self._client("secret123")
        resp = client.post("/api/v1/intelligence/events", json=self._valid_body())
        assert resp.status_code == 401

    def test_returns_503_when_key_not_configured(self):
        client, _ = self._client(operator_key="")  # empty key → disabled
        resp = client.post(
            "/api/v1/intelligence/events",
            json=self._valid_body(),
            headers={"Authorization": "Bearer anything"},
        )
        assert resp.status_code == 503

    def test_returns_422_for_unknown_event_type(self):
        client, _ = self._client()
        body = self._valid_body()
        body["event_type"] = "totally_unknown_type"
        resp = client.post(
            "/api/v1/intelligence/events",
            json=body,
            headers={"Authorization": "Bearer secret123"},
        )
        assert resp.status_code == 422

    def test_most_recent_event_is_first_in_list(self):
        client, state = self._client()
        for i, bias in enumerate([0.1, 0.5, 0.9]):
            body = self._valid_body()
            body["event_id"] = f"e{i}"
            body["directional_bias"] = bias
            client.post(
                "/api/v1/intelligence/events",
                json=body,
                headers={"Authorization": "Bearer secret123"},
            )
        # Latest push should be at index 0
        assert abs(state.latest_policy_signals[0].directional_bias - 0.9) < 1e-6

    def test_directional_bias_clamped_at_plus_one(self):
        client, state = self._client()
        body = self._valid_body()
        body["directional_bias"] = 5.0  # over max
        client.post(
            "/api/v1/intelligence/events",
            json=body,
            headers={"Authorization": "Bearer secret123"},
        )
        assert state.latest_policy_signals[0].directional_bias <= 1.0

    def test_directional_bias_clamped_at_minus_one(self):
        client, state = self._client()
        body = self._valid_body()
        body["directional_bias"] = -5.0  # below min
        client.post(
            "/api/v1/intelligence/events",
            json=body,
            headers={"Authorization": "Bearer secret123"},
        )
        assert state.latest_policy_signals[0].directional_bias >= -1.0


class TestPushNewsItem:
    """POST /api/v1/intelligence/news"""

    def _client(self, operator_key: str = "news_secret"):
        from apps.api.main import app
        from apps.api.deps import get_app_state, get_settings
        state = _FakeAppState()

        app.dependency_overrides[get_app_state] = lambda: state
        app.dependency_overrides[get_settings] = lambda: _make_settings_with_key(operator_key)

        return TestClient(app), state

    def teardown_method(self):
        from apps.api.main import app
        app.dependency_overrides.clear()

    def _valid_body(self):
        return {
            "source_id": "ns_001",
            "headline": "NVDA announces record AI chip orders",
            "body_snippet": "NVIDIA reported a surge in datacenter revenue...",
            "sentiment_score": 0.7,
            "credibility_weight": 0.85,
            "affected_tickers": ["NVDA", "AMD"],
            "affected_themes": ["ai_infrastructure", "semiconductors"],
            "market_implication": "Positive for chip stocks",
            "contains_rumor": False,
        }

    def test_returns_201_with_valid_auth(self):
        client, _ = self._client()
        resp = client.post(
            "/api/v1/intelligence/news",
            json=self._valid_body(),
            headers={"Authorization": "Bearer news_secret"},
        )
        assert resp.status_code == 201

    def test_insight_appended_to_app_state(self):
        client, state = self._client()
        client.post(
            "/api/v1/intelligence/news",
            json=self._valid_body(),
            headers={"Authorization": "Bearer news_secret"},
        )
        assert len(state.latest_news_insights) == 1

    def test_insight_sentiment_score_stored(self):
        client, state = self._client()
        client.post(
            "/api/v1/intelligence/news",
            json=self._valid_body(),
            headers={"Authorization": "Bearer news_secret"},
        )
        assert abs(state.latest_news_insights[0].sentiment_score - 0.7) < 1e-6

    def test_positive_sentiment_label_inferred(self):
        from services.news_intelligence.models import SentimentLabel
        client, state = self._client()
        body = self._valid_body()
        body["sentiment_score"] = 0.5
        client.post(
            "/api/v1/intelligence/news",
            json=body,
            headers={"Authorization": "Bearer news_secret"},
        )
        assert state.latest_news_insights[0].sentiment == SentimentLabel.POSITIVE

    def test_negative_sentiment_label_inferred(self):
        from services.news_intelligence.models import SentimentLabel
        client, state = self._client()
        body = self._valid_body()
        body["sentiment_score"] = -0.5
        client.post(
            "/api/v1/intelligence/news",
            json=body,
            headers={"Authorization": "Bearer news_secret"},
        )
        assert state.latest_news_insights[0].sentiment == SentimentLabel.NEGATIVE

    def test_neutral_sentiment_label_inferred(self):
        from services.news_intelligence.models import SentimentLabel
        client, state = self._client()
        body = self._valid_body()
        body["sentiment_score"] = 0.05
        client.post(
            "/api/v1/intelligence/news",
            json=body,
            headers={"Authorization": "Bearer news_secret"},
        )
        assert state.latest_news_insights[0].sentiment == SentimentLabel.NEUTRAL

    def test_affected_tickers_stored(self):
        client, state = self._client()
        client.post(
            "/api/v1/intelligence/news",
            json=self._valid_body(),
            headers={"Authorization": "Bearer news_secret"},
        )
        assert "NVDA" in state.latest_news_insights[0].affected_tickers
        assert "AMD" in state.latest_news_insights[0].affected_tickers

    def test_contains_rumor_flag_stored(self):
        client, state = self._client()
        body = self._valid_body()
        body["contains_rumor"] = True
        client.post(
            "/api/v1/intelligence/news",
            json=body,
            headers={"Authorization": "Bearer news_secret"},
        )
        assert state.latest_news_insights[0].contains_rumor is True

    def test_returns_401_wrong_token(self):
        client, _ = self._client()
        resp = client.post(
            "/api/v1/intelligence/news",
            json=self._valid_body(),
            headers={"Authorization": "Bearer wrong"},
        )
        assert resp.status_code == 401

    def test_returns_401_missing_header(self):
        client, _ = self._client()
        resp = client.post("/api/v1/intelligence/news", json=self._valid_body())
        assert resp.status_code == 401

    def test_returns_503_when_key_empty(self):
        client, _ = self._client(operator_key="")
        resp = client.post(
            "/api/v1/intelligence/news",
            json=self._valid_body(),
            headers={"Authorization": "Bearer anything"},
        )
        assert resp.status_code == 503

    def test_items_in_state_count(self):
        client, state = self._client()
        state.latest_news_insights = [_make_news_insight()]
        resp = client.post(
            "/api/v1/intelligence/news",
            json=self._valid_body(),
            headers={"Authorization": "Bearer news_secret"},
        )
        assert resp.json()["items_in_state"] == 2

    def test_multiple_pushes_accumulate(self):
        client, state = self._client()
        for i in range(4):
            body = self._valid_body()
            body["source_id"] = f"ns_{i:03d}"
            client.post(
                "/api/v1/intelligence/news",
                json=body,
                headers={"Authorization": "Bearer news_secret"},
            )
        assert len(state.latest_news_insights) == 4

    def test_primary_verified_tier_at_high_weight(self):
        from services.news_intelligence.models import CredibilityTier
        client, state = self._client()
        body = self._valid_body()
        body["credibility_weight"] = 0.9
        client.post(
            "/api/v1/intelligence/news",
            json=body,
            headers={"Authorization": "Bearer news_secret"},
        )
        assert state.latest_news_insights[0].news_item.credibility_tier == CredibilityTier.PRIMARY_VERIFIED

    def test_unverified_tier_at_low_weight(self):
        from services.news_intelligence.models import CredibilityTier
        client, state = self._client()
        body = self._valid_body()
        body["credibility_weight"] = 0.2
        client.post(
            "/api/v1/intelligence/news",
            json=body,
            headers={"Authorization": "Bearer news_secret"},
        )
        assert state.latest_news_insights[0].news_item.credibility_tier == CredibilityTier.UNVERIFIED


# ===========================================================================
# 3. Metrics expansion
# ===========================================================================

class TestMetricsExpansion:
    """Verify the three new Prometheus gauges are emitted by /metrics."""

    def _get_metrics(self, macro_regime: str = "RISK_ON",
                     policy_signals_count: int = 3,
                     news_insights_count: int = 5) -> str:
        from apps.api.main import app
        from apps.api.deps import get_app_state, get_settings

        state = _FakeAppState(
            current_macro_regime=macro_regime,
            latest_policy_signals=[MagicMock()] * policy_signals_count,
            latest_news_insights=[MagicMock()] * news_insights_count,
        )

        app.dependency_overrides[get_app_state] = lambda: state
        client = TestClient(app)
        resp = client.get("/metrics")
        app.dependency_overrides.clear()
        return resp.text

    def test_macro_regime_gauge_present(self):
        text = self._get_metrics()
        assert "apis_macro_regime" in text

    def test_macro_regime_gauge_encodes_regime_label(self):
        text = self._get_metrics(macro_regime="RISK_ON")
        assert 'regime="RISK_ON"' in text

    def test_macro_regime_gauge_neutral(self):
        text = self._get_metrics(macro_regime="NEUTRAL")
        assert 'regime="NEUTRAL"' in text

    def test_macro_regime_gauge_risk_off(self):
        text = self._get_metrics(macro_regime="RISK_OFF")
        assert 'regime="RISK_OFF"' in text

    def test_active_signals_count_gauge_present(self):
        text = self._get_metrics()
        assert "apis_active_signals_count" in text

    def test_active_signals_count_correct_value(self):
        text = self._get_metrics(policy_signals_count=7)
        # Find the value line: "apis_active_signals_count 7 <timestamp>"
        lines = text.splitlines()
        value_lines = [l for l in lines if l.startswith("apis_active_signals_count")]
        assert len(value_lines) == 1
        parts = value_lines[0].split()
        assert int(parts[1]) == 7

    def test_active_signals_count_zero_when_empty(self):
        text = self._get_metrics(policy_signals_count=0)
        lines = text.splitlines()
        value_lines = [l for l in lines if l.startswith("apis_active_signals_count")]
        assert int(value_lines[0].split()[1]) == 0

    def test_news_insights_count_gauge_present(self):
        text = self._get_metrics()
        assert "apis_news_insights_count" in text

    def test_news_insights_count_correct_value(self):
        text = self._get_metrics(news_insights_count=11)
        lines = text.splitlines()
        value_lines = [l for l in lines if l.startswith("apis_news_insights_count")]
        assert len(value_lines) == 1
        assert int(value_lines[0].split()[1]) == 11

    def test_news_insights_count_zero_when_empty(self):
        text = self._get_metrics(news_insights_count=0)
        lines = text.splitlines()
        value_lines = [l for l in lines if l.startswith("apis_news_insights_count")]
        assert int(value_lines[0].split()[1]) == 0

    def test_all_three_new_gauges_have_type_declarations(self):
        text = self._get_metrics()
        assert "# TYPE apis_macro_regime gauge" in text
        assert "# TYPE apis_active_signals_count gauge" in text
        assert "# TYPE apis_news_insights_count gauge" in text

    def test_existing_metrics_still_present(self):
        """Regression: original metrics must all still be emitted."""
        text = self._get_metrics()
        assert "apis_operating_mode" in text
        assert "apis_kill_switch_active" in text
        assert "apis_portfolio_positions" in text
        assert "apis_paper_loop_active" in text
        assert "apis_broker_auth_expired" in text


# ===========================================================================
# 4. Settings — operator_api_key field
# ===========================================================================

class TestOperatorApiKeySettings:
    def test_operator_api_key_default_empty(self):
        from config.settings import Settings
        s = Settings()
        assert s.operator_api_key == ""

    def test_operator_api_key_readable(self):
        from config.settings import Settings
        s = Settings()
        assert hasattr(s, "operator_api_key")

    def test_operator_api_key_env_prefix(self):
        """operator_api_key is set via APIS_OPERATOR_API_KEY env var."""
        import os
        with patch.dict(os.environ, {"APIS_OPERATOR_API_KEY": "my_test_key"}):
            from config.settings import Settings
            s = Settings()
            assert s.operator_api_key == "my_test_key"
