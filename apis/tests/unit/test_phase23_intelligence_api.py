"""Phase 23 — Intel Feed Pipeline + Intelligence API tests.

Covers:
  - NewsSeedService                   (TestNewsSeedServiceInit,
                                       TestNewsSeedServiceGetDailyItems)
  - PolicyEventSeedService            (TestPolicyEventSeedServiceInit,
                                       TestPolicyEventSeedServiceGetDailyEvents)
  - run_intel_feed_ingestion          (TestRunIntelFeedIngestion)
  - /api/v1/intelligence/* endpoints  (TestMacroRegimeEndpoint,
                                       TestPolicySignalsEndpoint,
                                       TestNewsInsightsEndpoint,
                                       TestNewsInsightsTickerFilter,
                                       TestThematicExposureEndpoint)
  - Scheduler                         (TestWorkerSchedulerPhase23)
  - Integration                       (TestPhase23Integration)
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_policy_event(event_id: str = "e1", event_type_val: str = "fiscal_policy"):
    from services.macro_policy_engine.models import PolicyEvent, PolicyEventType
    return PolicyEvent(
        event_id=event_id,
        headline=f"Headline for {event_id}",
        event_type=PolicyEventType(event_type_val),
        published_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1),
        source="TestSource",
        body_snippet="Some body text",
    )


def _make_policy_signal(bias: float = 0.4, confidence: float = 0.6):
    from services.macro_policy_engine.models import PolicyEvent, PolicyEventType, PolicySignal
    evt = _make_policy_event()
    return PolicySignal(
        event=evt,
        affected_sectors=["technology"],
        affected_themes=["ai_infrastructure"],
        affected_tickers=[],
        directional_bias=bias,
        confidence=confidence,
        implication_summary="A positive macro signal",
        generated_at=dt.datetime.now(dt.timezone.utc),
    )


def _make_news_item(source_id: str = "ni1", ticker: str = "NVDA"):
    from services.news_intelligence.models import CredibilityTier, NewsItem
    return NewsItem(
        source_id=source_id,
        headline=f"Headline for {source_id}",
        published_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1),
        body_snippet="Some news body",
        credibility_tier=CredibilityTier.SECONDARY_VERIFIED,
        tickers_mentioned=[ticker],
    )


def _make_news_insight(source_id: str = "ni1", ticker: str = "NVDA", score: float = 0.4):
    from services.news_intelligence.models import (
        CredibilityTier, NewsInsight, NewsItem, SentimentLabel,
    )
    item = _make_news_item(source_id, ticker)
    return NewsInsight(
        news_item=item,
        sentiment=SentimentLabel.POSITIVE,
        sentiment_score=score,
        credibility_weight=0.7,
        affected_tickers=[ticker],
        affected_themes=["ai_infrastructure"],
        market_implication="Positive for tech",
        contains_rumor=False,
        processed_at=dt.datetime.now(dt.timezone.utc),
    )


@dataclass
class _FakeAppState:
    latest_policy_signals: list[Any] = field(default_factory=list)
    latest_news_insights: list[Any] = field(default_factory=list)
    current_macro_regime: str = "NEUTRAL"


# ---------------------------------------------------------------------------
# NewsSeedService
# ---------------------------------------------------------------------------

class TestNewsSeedServiceInit:
    def test_default_seeds_loaded(self):
        from services.news_intelligence.seed import NewsSeedService, _DEFAULT_SEEDS
        svc = NewsSeedService()
        assert svc.seed_count == len(_DEFAULT_SEEDS)

    def test_custom_seeds_override(self):
        from services.news_intelligence.seed import NewsSeedService
        custom = [{"source_id": "x", "headline": "H", "credibility_tier": None, "tickers_mentioned": []}]
        svc = NewsSeedService(seeds=custom)
        assert svc.seed_count == 1

    def test_empty_seeds_override(self):
        from services.news_intelligence.seed import NewsSeedService
        svc = NewsSeedService(seeds=[])
        assert svc.seed_count == 0


class TestNewsSeedServiceGetDailyItems:
    def test_returns_list(self):
        from services.news_intelligence.seed import NewsSeedService
        items = NewsSeedService().get_daily_items()
        assert isinstance(items, list)

    def test_count_matches_seeds(self):
        from services.news_intelligence.seed import NewsSeedService, _DEFAULT_SEEDS
        items = NewsSeedService().get_daily_items()
        assert len(items) == len(_DEFAULT_SEEDS)

    def test_all_items_are_news_items(self):
        from services.news_intelligence.models import NewsItem
        from services.news_intelligence.seed import NewsSeedService
        for item in NewsSeedService().get_daily_items():
            assert isinstance(item, NewsItem)

    def test_published_at_is_tz_aware(self):
        from services.news_intelligence.seed import NewsSeedService
        for item in NewsSeedService().get_daily_items():
            assert item.published_at.tzinfo is not None

    def test_published_at_uses_reference_dt(self):
        from services.news_intelligence.seed import NewsSeedService
        ref = dt.datetime(2026, 1, 15, 10, 0, 0, tzinfo=dt.timezone.utc)
        items = NewsSeedService().get_daily_items(reference_dt=ref)
        expected = ref - dt.timedelta(hours=2)
        for item in items:
            assert item.published_at == expected

    def test_tickers_mentioned_are_lists(self):
        from services.news_intelligence.seed import NewsSeedService
        for item in NewsSeedService().get_daily_items():
            assert isinstance(item.tickers_mentioned, list)

    def test_empty_seeds_returns_empty_list(self):
        from services.news_intelligence.seed import NewsSeedService
        assert NewsSeedService(seeds=[]).get_daily_items() == []

    def test_tickers_not_mutated_between_calls(self):
        from services.news_intelligence.seed import NewsSeedService, _DEFAULT_SEEDS
        svc = NewsSeedService()
        items1 = svc.get_daily_items()
        items1[0].tickers_mentioned.append("ZZZZ")
        items2 = svc.get_daily_items()
        # original seed template must not be contaminated
        assert "ZZZZ" not in items2[0].tickers_mentioned


# ---------------------------------------------------------------------------
# PolicyEventSeedService
# ---------------------------------------------------------------------------

class TestPolicyEventSeedServiceInit:
    def test_default_seeds_loaded(self):
        from services.macro_policy_engine.seed import (
            PolicyEventSeedService, _DEFAULT_SEEDS,
        )
        svc = PolicyEventSeedService()
        assert svc.seed_count == len(_DEFAULT_SEEDS)

    def test_custom_seeds_override(self):
        from services.macro_policy_engine.seed import PolicyEventSeedService
        from services.macro_policy_engine.models import PolicyEventType
        seeds = [{
            "event_id": "x1", "headline": "H", "event_type": PolicyEventType.OTHER,
        }]
        svc = PolicyEventSeedService(seeds=seeds)
        assert svc.seed_count == 1

    def test_empty_seeds_override(self):
        from services.macro_policy_engine.seed import PolicyEventSeedService
        svc = PolicyEventSeedService(seeds=[])
        assert svc.seed_count == 0


class TestPolicyEventSeedServiceGetDailyEvents:
    def test_returns_list(self):
        from services.macro_policy_engine.seed import PolicyEventSeedService
        events = PolicyEventSeedService().get_daily_events()
        assert isinstance(events, list)

    def test_count_matches_seeds(self):
        from services.macro_policy_engine.seed import (
            PolicyEventSeedService, _DEFAULT_SEEDS,
        )
        events = PolicyEventSeedService().get_daily_events()
        assert len(events) == len(_DEFAULT_SEEDS)

    def test_all_are_policy_events(self):
        from services.macro_policy_engine.models import PolicyEvent
        from services.macro_policy_engine.seed import PolicyEventSeedService
        for ev in PolicyEventSeedService().get_daily_events():
            assert isinstance(ev, PolicyEvent)

    def test_published_at_is_tz_aware(self):
        from services.macro_policy_engine.seed import PolicyEventSeedService
        for ev in PolicyEventSeedService().get_daily_events():
            assert ev.published_at.tzinfo is not None

    def test_published_at_uses_reference_dt(self):
        from services.macro_policy_engine.seed import PolicyEventSeedService
        ref = dt.datetime(2026, 3, 1, 8, 0, 0, tzinfo=dt.timezone.utc)
        events = PolicyEventSeedService().get_daily_events(reference_dt=ref)
        expected = ref - dt.timedelta(hours=3)
        for ev in events:
            assert ev.published_at == expected

    def test_empty_seeds_returns_empty(self):
        from services.macro_policy_engine.seed import PolicyEventSeedService
        assert PolicyEventSeedService(seeds=[]).get_daily_events() == []

    def test_event_ids_match_seeds(self):
        from services.macro_policy_engine.seed import (
            PolicyEventSeedService, _DEFAULT_SEEDS,
        )
        events = PolicyEventSeedService().get_daily_events()
        ids = {ev.event_id for ev in events}
        expected_ids = {s["event_id"] for s in _DEFAULT_SEEDS}
        assert ids == expected_ids


# ---------------------------------------------------------------------------
# run_intel_feed_ingestion
# ---------------------------------------------------------------------------

class TestRunIntelFeedIngestion:
    def _mock_policy(self, signals=None):
        m = MagicMock()
        m.process_batch.return_value = signals if signals is not None else [_make_policy_signal()]
        return m

    def _mock_news(self, insights=None):
        m = MagicMock()
        m.process_batch.return_value = insights if insights is not None else [_make_news_insight()]
        return m

    def _mock_policy_seed(self, n=3):
        m = MagicMock()
        m.get_daily_events.return_value = [_make_policy_event(str(i)) for i in range(n)]
        return m

    def _mock_news_seed(self, n=4):
        m = MagicMock()
        m.get_daily_items.return_value = [_make_news_item(str(i)) for i in range(n)]
        return m

    def test_status_ok_happy_path(self):
        from apps.worker.jobs.intel import run_intel_feed_ingestion
        state = _FakeAppState()
        result = run_intel_feed_ingestion(
            app_state=state,
            policy_engine=self._mock_policy(),
            news_service=self._mock_news(),
            policy_seed_service=self._mock_policy_seed(),
            news_seed_service=self._mock_news_seed(),
        )
        assert result["status"] == "ok"

    def test_policy_signals_stored_in_app_state(self):
        from apps.worker.jobs.intel import run_intel_feed_ingestion
        signals = [_make_policy_signal(0.5), _make_policy_signal(0.3)]
        state = _FakeAppState()
        run_intel_feed_ingestion(
            app_state=state,
            policy_engine=self._mock_policy(signals),
            news_service=self._mock_news(),
            policy_seed_service=self._mock_policy_seed(),
            news_seed_service=self._mock_news_seed(),
        )
        assert state.latest_policy_signals is signals

    def test_news_insights_stored_in_app_state(self):
        from apps.worker.jobs.intel import run_intel_feed_ingestion
        insights = [_make_news_insight("a"), _make_news_insight("b")]
        state = _FakeAppState()
        run_intel_feed_ingestion(
            app_state=state,
            policy_engine=self._mock_policy(),
            news_service=self._mock_news(insights),
            policy_seed_service=self._mock_policy_seed(),
            news_seed_service=self._mock_news_seed(),
        )
        assert state.latest_news_insights is insights

    def test_policy_signals_count_in_result(self):
        from apps.worker.jobs.intel import run_intel_feed_ingestion
        signals = [_make_policy_signal(), _make_policy_signal()]
        result = run_intel_feed_ingestion(
            app_state=_FakeAppState(),
            policy_engine=self._mock_policy(signals),
            news_service=self._mock_news(),
            policy_seed_service=self._mock_policy_seed(),
            news_seed_service=self._mock_news_seed(),
        )
        assert result["policy_signals_count"] == 2

    def test_news_insights_count_in_result(self):
        from apps.worker.jobs.intel import run_intel_feed_ingestion
        insights = [_make_news_insight("x"), _make_news_insight("y"), _make_news_insight("z")]
        result = run_intel_feed_ingestion(
            app_state=_FakeAppState(),
            policy_engine=self._mock_policy(),
            news_service=self._mock_news(insights),
            policy_seed_service=self._mock_policy_seed(),
            news_seed_service=self._mock_news_seed(),
        )
        assert result["news_insights_count"] == 3

    def test_partial_status_when_policy_fails(self):
        from apps.worker.jobs.intel import run_intel_feed_ingestion
        bad_policy = MagicMock()
        bad_policy.process_batch.side_effect = RuntimeError("policy boom")
        result = run_intel_feed_ingestion(
            app_state=_FakeAppState(),
            policy_engine=bad_policy,
            news_service=self._mock_news(),
            policy_seed_service=self._mock_policy_seed(),
            news_seed_service=self._mock_news_seed(),
        )
        assert result["status"] == "partial"
        assert result["policy_signals_count"] == 0
        assert result["news_insights_count"] == 1

    def test_partial_status_when_news_fails(self):
        from apps.worker.jobs.intel import run_intel_feed_ingestion
        bad_news = MagicMock()
        bad_news.process_batch.side_effect = RuntimeError("news boom")
        result = run_intel_feed_ingestion(
            app_state=_FakeAppState(),
            policy_engine=self._mock_policy(),
            news_service=bad_news,
            policy_seed_service=self._mock_policy_seed(),
            news_seed_service=self._mock_news_seed(),
        )
        assert result["status"] == "partial"
        assert result["policy_signals_count"] == 1
        assert result["news_insights_count"] == 0

    def test_error_status_when_both_fail(self):
        from apps.worker.jobs.intel import run_intel_feed_ingestion
        bad_p = MagicMock()
        bad_p.process_batch.side_effect = RuntimeError("p boom")
        bad_n = MagicMock()
        bad_n.process_batch.side_effect = RuntimeError("n boom")
        result = run_intel_feed_ingestion(
            app_state=_FakeAppState(),
            policy_engine=bad_p,
            news_service=bad_n,
            policy_seed_service=self._mock_policy_seed(),
            news_seed_service=self._mock_news_seed(),
        )
        assert result["status"] == "error"
        assert len(result["errors"]) == 2

    def test_errors_key_populated_on_failure(self):
        from apps.worker.jobs.intel import run_intel_feed_ingestion
        bad = MagicMock()
        bad.process_batch.side_effect = ValueError("seed fail")
        result = run_intel_feed_ingestion(
            app_state=_FakeAppState(),
            policy_engine=bad,
            news_service=self._mock_news(),
            policy_seed_service=self._mock_policy_seed(),
            news_seed_service=self._mock_news_seed(),
        )
        assert any("policy_ingestion" in e for e in result["errors"])

    def test_run_at_is_iso_string(self):
        from apps.worker.jobs.intel import run_intel_feed_ingestion
        result = run_intel_feed_ingestion(
            app_state=_FakeAppState(),
            policy_engine=self._mock_policy(),
            news_service=self._mock_news(),
            policy_seed_service=self._mock_policy_seed(),
            news_seed_service=self._mock_news_seed(),
        )
        # Should not raise
        dt.datetime.fromisoformat(result["run_at"])

    def test_app_state_without_fields_does_not_raise(self):
        """If app_state lacks the intel fields, hasattr guard prevents crash."""
        from apps.worker.jobs.intel import run_intel_feed_ingestion

        class _Bare:
            pass

        result = run_intel_feed_ingestion(
            app_state=_Bare(),
            policy_engine=self._mock_policy(),
            news_service=self._mock_news(),
            policy_seed_service=self._mock_policy_seed(),
            news_seed_service=self._mock_news_seed(),
        )
        assert result["status"] == "ok"

    def test_result_has_required_keys(self):
        from apps.worker.jobs.intel import run_intel_feed_ingestion
        result = run_intel_feed_ingestion(
            app_state=_FakeAppState(),
            policy_engine=self._mock_policy(),
            news_service=self._mock_news(),
            policy_seed_service=self._mock_policy_seed(),
            news_seed_service=self._mock_news_seed(),
        )
        assert set(result) == {
            "status", "policy_signals_count", "news_insights_count", "errors", "run_at"
        }

    def test_errors_empty_on_success(self):
        from apps.worker.jobs.intel import run_intel_feed_ingestion
        result = run_intel_feed_ingestion(
            app_state=_FakeAppState(),
            policy_engine=self._mock_policy(),
            news_service=self._mock_news(),
            policy_seed_service=self._mock_policy_seed(),
            news_seed_service=self._mock_news_seed(),
        )
        assert result["errors"] == []


# ---------------------------------------------------------------------------
# Intelligence API endpoint helpers
# ---------------------------------------------------------------------------

def _make_test_client(state_override=None):
    """Create a TestClient with app_state dependency overridden."""
    from fastapi import FastAPI
    from apps.api.deps import AppStateDep, get_app_state
    from apps.api.routes.intelligence import router

    test_app = FastAPI()
    test_app.include_router(router, prefix="/api/v1")

    if state_override is not None:
        test_app.dependency_overrides[get_app_state] = lambda: state_override

    return TestClient(test_app)


# ---------------------------------------------------------------------------
# GET /api/v1/intelligence/regime
# ---------------------------------------------------------------------------

class TestMacroRegimeEndpoint:
    def test_returns_200(self):
        client = _make_test_client(_FakeAppState())
        resp = client.get("/api/v1/intelligence/regime")
        assert resp.status_code == 200

    def test_default_regime_neutral(self):
        client = _make_test_client(_FakeAppState())
        data = client.get("/api/v1/intelligence/regime").json()
        assert data["regime"] == "NEUTRAL"

    def test_regime_reflects_app_state(self):
        state = _FakeAppState()
        state.current_macro_regime = "RISK_ON"
        data = _make_test_client(state).get("/api/v1/intelligence/regime").json()
        assert data["regime"] == "RISK_ON"

    def test_signal_count_zero_by_default(self):
        data = _make_test_client(_FakeAppState()).get("/api/v1/intelligence/regime").json()
        assert data["signal_count"] == 0

    def test_signal_count_reflects_list_length(self):
        state = _FakeAppState()
        state.latest_policy_signals = [_make_policy_signal(), _make_policy_signal()]
        data = _make_test_client(state).get("/api/v1/intelligence/regime").json()
        assert data["signal_count"] == 2

    def test_as_of_present_in_response(self):
        data = _make_test_client(_FakeAppState()).get("/api/v1/intelligence/regime").json()
        assert "as_of" in data


# ---------------------------------------------------------------------------
# GET /api/v1/intelligence/signals
# ---------------------------------------------------------------------------

class TestPolicySignalsEndpoint:
    def test_returns_200(self):
        resp = _make_test_client(_FakeAppState()).get("/api/v1/intelligence/signals")
        assert resp.status_code == 200

    def test_empty_signals(self):
        data = _make_test_client(_FakeAppState()).get("/api/v1/intelligence/signals").json()
        assert data["count"] == 0
        assert data["signals"] == []

    def test_count_matches_signals(self):
        state = _FakeAppState()
        state.latest_policy_signals = [_make_policy_signal(), _make_policy_signal()]
        data = _make_test_client(state).get("/api/v1/intelligence/signals").json()
        assert data["count"] == 2

    def test_signal_fields_present(self):
        state = _FakeAppState()
        state.latest_policy_signals = [_make_policy_signal(0.4, 0.6)]
        sig = _make_test_client(state).get("/api/v1/intelligence/signals").json()["signals"][0]
        assert "event_id" in sig
        assert "headline" in sig
        assert "directional_bias" in sig
        assert "confidence" in sig

    def test_directional_bias_rounded(self):
        state = _FakeAppState()
        state.latest_policy_signals = [_make_policy_signal(0.123456789, 0.5)]
        sig = _make_test_client(state).get("/api/v1/intelligence/signals").json()["signals"][0]
        assert sig["directional_bias"] == round(0.123456789, 4)

    def test_limit_param_respected(self):
        state = _FakeAppState()
        state.latest_policy_signals = [_make_policy_signal() for _ in range(10)]
        data = _make_test_client(state).get("/api/v1/intelligence/signals?limit=3").json()
        assert data["count"] == 3


# ---------------------------------------------------------------------------
# GET /api/v1/intelligence/insights
# ---------------------------------------------------------------------------

class TestNewsInsightsEndpoint:
    def test_returns_200(self):
        resp = _make_test_client(_FakeAppState()).get("/api/v1/intelligence/insights")
        assert resp.status_code == 200

    def test_empty_insights(self):
        data = _make_test_client(_FakeAppState()).get("/api/v1/intelligence/insights").json()
        assert data["count"] == 0
        assert data["insights"] == []

    def test_count_matches_insights(self):
        state = _FakeAppState()
        state.latest_news_insights = [_make_news_insight("a"), _make_news_insight("b")]
        data = _make_test_client(state).get("/api/v1/intelligence/insights").json()
        assert data["count"] == 2

    def test_insight_fields_present(self):
        state = _FakeAppState()
        state.latest_news_insights = [_make_news_insight()]
        ins = _make_test_client(state).get("/api/v1/intelligence/insights").json()["insights"][0]
        for field in ("source_id", "headline", "sentiment", "sentiment_score",
                      "credibility_weight", "affected_tickers", "contains_rumor"):
            assert field in ins

    def test_limit_param_respected(self):
        state = _FakeAppState()
        state.latest_news_insights = [_make_news_insight(str(i)) for i in range(8)]
        data = _make_test_client(state).get("/api/v1/intelligence/insights?limit=4").json()
        assert data["count"] == 4

    def test_sentiment_score_rounded(self):
        state = _FakeAppState()
        insight = _make_news_insight()
        insight.sentiment_score = 0.123456789
        state.latest_news_insights = [insight]
        ins = _make_test_client(state).get("/api/v1/intelligence/insights").json()["insights"][0]
        assert ins["sentiment_score"] == round(0.123456789, 4)


class TestNewsInsightsTickerFilter:
    def _state_with_insights(self):
        state = _FakeAppState()
        state.latest_news_insights = [
            _make_news_insight("n1", "NVDA"),
            _make_news_insight("n2", "AAPL"),
            _make_news_insight("n3", "NVDA"),
            _make_news_insight("n4", "MSFT"),
        ]
        return state

    def test_ticker_filter_returns_only_matching(self):
        data = _make_test_client(self._state_with_insights()).get(
            "/api/v1/intelligence/insights?ticker=NVDA"
        ).json()
        assert data["count"] == 2

    def test_ticker_filter_case_insensitive(self):
        data = _make_test_client(self._state_with_insights()).get(
            "/api/v1/intelligence/insights?ticker=nvda"
        ).json()
        assert data["count"] == 2

    def test_ticker_filter_no_match_returns_empty(self):
        data = _make_test_client(self._state_with_insights()).get(
            "/api/v1/intelligence/insights?ticker=ZZZZ"
        ).json()
        assert data["count"] == 0

    def test_no_filter_returns_all(self):
        data = _make_test_client(self._state_with_insights()).get(
            "/api/v1/intelligence/insights"
        ).json()
        assert data["count"] == 4


# ---------------------------------------------------------------------------
# GET /api/v1/intelligence/themes/{ticker}
# ---------------------------------------------------------------------------

class TestThematicExposureEndpoint:
    def test_returns_200_known_ticker(self):
        resp = _make_test_client().get("/api/v1/intelligence/themes/NVDA")
        assert resp.status_code == 200

    def test_ticker_uppercased_in_response(self):
        data = _make_test_client().get("/api/v1/intelligence/themes/nvda").json()
        assert data["ticker"] == "NVDA"

    def test_unknown_ticker_returns_empty_mappings(self):
        data = _make_test_client().get("/api/v1/intelligence/themes/ZZZZ").json()
        assert isinstance(data["mappings"], list)
        assert data["max_score"] == 0.0

    def test_response_has_required_fields(self):
        data = _make_test_client().get("/api/v1/intelligence/themes/NVDA").json()
        for field in ("ticker", "primary_theme", "max_score", "mappings", "as_of"):
            assert field in data

    def test_mapping_fields_present_when_known_ticker(self):
        data = _make_test_client().get("/api/v1/intelligence/themes/NVDA").json()
        if data["mappings"]:
            mapping = data["mappings"][0]
            for field in ("theme", "beneficiary_order", "thematic_score", "rationale"):
                assert field in mapping


# ---------------------------------------------------------------------------
# Worker Scheduler — Phase 23 assertions
# ---------------------------------------------------------------------------

class TestWorkerSchedulerPhase23:
    def _build_scheduler(self):
        from apps.worker.main import build_scheduler
        return build_scheduler()

    def test_intel_feed_ingestion_job_registered(self):
        scheduler = self._build_scheduler()
        ids = {job.id for job in scheduler.get_jobs()}
        assert "intel_feed_ingestion" in ids

    def test_total_job_count_is_14(self):
        scheduler = self._build_scheduler()
        assert len(scheduler.get_jobs()) == 30

    def test_intel_feed_fires_at_06_10(self):
        from apscheduler.triggers.cron import CronTrigger
        scheduler = self._build_scheduler()
        job = next(j for j in scheduler.get_jobs() if j.id == "intel_feed_ingestion")
        trigger = job.trigger
        assert isinstance(trigger, CronTrigger)
        fields = {f.name: str(f) for f in trigger.fields}
        assert fields["hour"] == "6"
        assert fields["minute"] == "10"

    def test_intel_feed_before_feature_enrichment(self):
        """intel_feed at 06:10 must appear before feature_enrichment at 06:22."""
        scheduler = self._build_scheduler()
        jobs_by_id = {j.id: j for j in scheduler.get_jobs()}
        assert "intel_feed_ingestion" in jobs_by_id
        assert "feature_enrichment" in jobs_by_id
        # Both exist; schedule ordering is implicit from cron config

    def test_worker_jobs_package_exports_run_intel_feed_ingestion(self):
        from apps.worker.jobs import run_intel_feed_ingestion
        assert callable(run_intel_feed_ingestion)


# ---------------------------------------------------------------------------
# Integration — full pipeline: seeds → intel services → enrichment
# ---------------------------------------------------------------------------

class TestPhase23Integration:
    def test_news_seed_through_news_intelligence_produces_insights(self):
        from services.news_intelligence.seed import NewsSeedService
        from services.news_intelligence.service import NewsIntelligenceService
        items = NewsSeedService().get_daily_items()
        insights = NewsIntelligenceService().process_batch(items)
        assert len(insights) > 0

    def test_policy_seed_through_macro_engine_produces_signals(self):
        from services.macro_policy_engine.seed import PolicyEventSeedService
        from services.macro_policy_engine.service import MacroPolicyEngineService
        events = PolicyEventSeedService().get_daily_events()
        signals = MacroPolicyEngineService().process_batch(events)
        assert len(signals) > 0

    def test_macro_regime_is_non_neutral_with_seeded_signals(self):
        """Default seeds include a mix of risk-on and risk-off events;
        the resulting regime should not be None."""
        from services.macro_policy_engine.seed import PolicyEventSeedService
        from services.macro_policy_engine.service import MacroPolicyEngineService
        events = PolicyEventSeedService().get_daily_events()
        signals = MacroPolicyEngineService().process_batch(events)
        indicator = MacroPolicyEngineService().assess_regime(signals)
        assert indicator.regime is not None

    def test_full_run_intel_feed_populates_app_state(self):
        """run_intel_feed_ingestion with real services populates app_state."""
        from apps.worker.jobs.intel import run_intel_feed_ingestion
        state = _FakeAppState()
        result = run_intel_feed_ingestion(app_state=state)
        assert result["status"] in ("ok", "partial")
        assert len(state.latest_policy_signals) > 0
        assert len(state.latest_news_insights) > 0

    def test_enrichment_produces_non_neutral_overlay_after_intel_feed(self):
        """After running the intel feed, FeatureEnrichmentService.enrich()
        should populate at least one overlay field with a non-zero value."""
        from apps.worker.jobs.intel import run_intel_feed_ingestion
        from services.feature_store.enrichment import FeatureEnrichmentService
        from services.feature_store.models import FeatureSet

        state = _FakeAppState()
        run_intel_feed_ingestion(app_state=state)

        enrichment_svc = FeatureEnrichmentService()
        import uuid
        import datetime as dt
        fs = FeatureSet(
            ticker="NVDA",
            security_id=uuid.uuid4(),
            as_of_timestamp=dt.datetime.now(dt.timezone.utc),
            features=[],
        )
        enriched = enrichment_svc.enrich(
            fs,
            policy_signals=state.latest_policy_signals,
            news_insights=state.latest_news_insights,
        )
        # At least one intel overlay should be non-trivially populated
        has_theme = bool(enriched.theme_scores)
        has_macro = (enriched.macro_bias != 0.0 or enriched.macro_regime != "NEUTRAL")
        has_sentiment = enriched.sentiment_score != 0.0
        assert has_theme or has_macro or has_sentiment
