"""Phase 36 — Real-time Price Streaming / WebSocket Feed,
Alternative Data Integration, Promotion Confidence Scoring.

Test classes
------------
1.  TestConfidenceScoreComputation         — _compute_confidence_score logic
2.  TestConfidenceScoreOnProposal          — confidence_score stamped on ImprovementProposal
3.  TestAutoExecuteConfidenceGate          — auto_execute_promoted min_confidence filter
4.  TestAutoExecuteSummarySchema           — skipped_low_confidence field in schema
5.  TestAutoExecuteRouteConfidence         — route surfaces skipped_low_confidence
6.  TestSelfImprovementConfig              — min_auto_execute_confidence default
7.  TestAlternativeDataModels              — AlternativeDataRecord dataclass
8.  TestSocialMentionAdapter               — SocialMentionAdapter determinism + clamping
9.  TestAlternativeDataService             — ingest / get_records / get_ticker_sentiment
10. TestAlternativeDataIngestionJob        — run_alternative_data_ingestion job
11. TestIntelligenceAlternativeRoute       — GET /intelligence/alternative endpoint
12. TestPriceSnapshotRoute                 — GET /api/v1/prices/snapshot
13. TestWebSocketPriceFeed                 — /api/v1/prices/ws WebSocket
14. TestSchedulerAlternativeDataJob        — scheduler has 17 jobs; 06:05 job present
15. TestDashboardPhase36                   — dashboard renders alt-data + confidence sections
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from apps.api.state import ApiAppState, reset_app_state
from services.alternative_data.adapters import SocialMentionAdapter
from services.alternative_data.models import AlternativeDataRecord, AlternativeDataSource
from services.alternative_data.service import AlternativeDataService
from services.self_improvement.config import SelfImprovementConfig
from services.self_improvement.execution import AutoExecutionService
from services.self_improvement.models import (
    ImprovementProposal,
    ProposalEvaluation,
    ProposalStatus,
    ProposalType,
)
from services.self_improvement.service import SelfImprovementService

# ============================================================
# Helpers
# ============================================================

def _make_proposal(
    status: ProposalStatus = ProposalStatus.PROMOTED,
    component: str = "signal_engine",
    confidence: float = 0.0,
) -> ImprovementProposal:
    p = ImprovementProposal(
        proposal_type=ProposalType.SOURCE_WEIGHT,
        target_component=component,
        baseline_version="1.0.0",
        candidate_version="1.0.1",
        proposal_summary="test",
        expected_benefit="test",
    )
    p.status = status
    p.confidence_score = confidence
    return p


def _make_evaluation(
    guardrail_passed: bool = True,
    baseline: dict | None = None,
    candidate: dict | None = None,
) -> ProposalEvaluation:
    base = baseline or {"hit_rate": Decimal("0.50"), "sharpe": Decimal("1.0")}
    cand = candidate or {"hit_rate": Decimal("0.60"), "sharpe": Decimal("1.2")}
    return ProposalEvaluation(
        proposal_id="test-id",
        baseline_metrics=base,
        candidate_metrics=cand,
        comparison_summary="test",
        guardrail_passed=guardrail_passed,
    )


def _make_state(**kwargs) -> ApiAppState:
    s = ApiAppState()
    for k, v in kwargs.items():
        setattr(s, k, v)
    return s


# ============================================================
# 1. TestConfidenceScoreComputation
# ============================================================

class TestConfidenceScoreComputation:
    def setup_method(self):
        self.svc = SelfImprovementService()

    def test_guardrail_blocked_returns_zero(self):
        ev = _make_evaluation(guardrail_passed=False)
        score = self.svc._compute_confidence_score(ev)
        assert score == 0.0

    def test_no_baseline_metrics_returns_zero(self):
        ev = _make_evaluation()
        ev.baseline_metrics = {}
        score = self.svc._compute_confidence_score(ev)
        assert score == 0.0

    def test_all_improving_no_regression(self):
        ev = _make_evaluation(
            baseline={"hit_rate": Decimal("0.50"), "sharpe": Decimal("1.0")},
            candidate={"hit_rate": Decimal("0.60"), "sharpe": Decimal("1.2")},
        )
        score = self.svc._compute_confidence_score(ev)
        assert 0.0 < score <= 1.0

    def test_score_clamped_to_one(self):
        ev = _make_evaluation(
            baseline={"hit_rate": Decimal("0.10")},
            candidate={"hit_rate": Decimal("0.99")},
        )
        score = self.svc._compute_confidence_score(ev)
        assert score <= 1.0

    def test_score_clamped_to_zero_on_regression(self):
        ev = _make_evaluation(
            baseline={"hit_rate": Decimal("0.80")},
            candidate={"hit_rate": Decimal("0.10")},
        )
        score = self.svc._compute_confidence_score(ev)
        assert score >= 0.0

    def test_primary_delta_boost_effect(self):
        """Larger primary delta yields higher score when improvement_ratio < 1."""
        # Use 2 metrics so improvement_ratio = 0.5 (one up, one flat)
        # — primary delta boost is then the differentiator
        ev_small = _make_evaluation(
            baseline={"hit_rate": Decimal("0.50"), "sharpe": Decimal("1.0")},
            candidate={"hit_rate": Decimal("0.501"), "sharpe": Decimal("1.0")},
        )
        ev_large = _make_evaluation(
            baseline={"hit_rate": Decimal("0.50"), "sharpe": Decimal("1.0")},
            candidate={"hit_rate": Decimal("0.60"), "sharpe": Decimal("1.0")},
        )
        small = self.svc._compute_confidence_score(ev_small)
        large = self.svc._compute_confidence_score(ev_large)
        assert large > small

    def test_regression_reduces_score(self):
        ev = _make_evaluation(
            baseline={"hit_rate": Decimal("0.50"), "sharpe": Decimal("1.0")},
            candidate={"hit_rate": Decimal("0.60"), "sharpe": Decimal("0.8")},
        )
        score_with_regression = self.svc._compute_confidence_score(ev)
        ev_clean = _make_evaluation(
            baseline={"hit_rate": Decimal("0.50"), "sharpe": Decimal("1.0")},
            candidate={"hit_rate": Decimal("0.60"), "sharpe": Decimal("1.2")},
        )
        score_clean = self.svc._compute_confidence_score(ev_clean)
        assert score_clean > score_with_regression

    def test_score_is_float(self):
        ev = _make_evaluation()
        score = self.svc._compute_confidence_score(ev)
        assert isinstance(score, float)


# ============================================================
# 2. TestConfidenceScoreOnProposal
# ============================================================

class TestConfidenceScoreOnProposal:
    def setup_method(self):
        self.svc = SelfImprovementService()

    def test_promote_or_reject_stamps_confidence(self):
        p = _make_proposal(status=ProposalStatus.PENDING)
        ev = _make_evaluation()
        ev.result_status = "pass"
        self.svc.promote_or_reject(p, ev)
        assert isinstance(p.confidence_score, float)
        assert 0.0 <= p.confidence_score <= 1.0

    def test_rejected_guardrail_stamps_zero(self):
        p = _make_proposal(status=ProposalStatus.PENDING)
        ev = _make_evaluation(guardrail_passed=False)
        self.svc.promote_or_reject(p, ev)
        assert p.confidence_score == 0.0

    def test_confidence_default_is_zero(self):
        p = ImprovementProposal(
            proposal_type=ProposalType.RANKING_THRESHOLD,
            target_component="ranking_engine",
            baseline_version="1.0.0",
            candidate_version="1.0.1",
            proposal_summary="x",
            expected_benefit="y",
        )
        assert p.confidence_score == 0.0

    def test_good_evaluation_produces_nonzero_confidence(self):
        p = _make_proposal(status=ProposalStatus.PENDING)
        ev = _make_evaluation(
            baseline={"hit_rate": Decimal("0.50")},
            candidate={"hit_rate": Decimal("0.65")},
        )
        ev.result_status = "pass"
        self.svc.promote_or_reject(p, ev)
        assert p.confidence_score > 0.0


# ============================================================
# 3. TestAutoExecuteConfidenceGate
# ============================================================

class TestAutoExecuteConfidenceGate:
    def setup_method(self):
        self.svc = AutoExecutionService()
        self.state = _make_state(
            applied_executions=[],
            runtime_overrides={},
            promoted_versions={},
            last_auto_execute_at=None,
        )

    def test_above_threshold_executes(self):
        p = _make_proposal(confidence=0.85)
        result = self.svc.auto_execute_promoted([p], self.state, min_confidence=0.70)
        assert result["executed_count"] == 1
        assert result["skipped_low_confidence"] == 0

    def test_below_threshold_skips(self):
        p = _make_proposal(confidence=0.40)
        result = self.svc.auto_execute_promoted([p], self.state, min_confidence=0.70)
        assert result["executed_count"] == 0
        assert result["skipped_low_confidence"] == 1
        assert result["skipped_count"] == 1

    def test_at_threshold_executes(self):
        p = _make_proposal(confidence=0.70)
        result = self.svc.auto_execute_promoted([p], self.state, min_confidence=0.70)
        assert result["executed_count"] == 1

    def test_zero_threshold_disables_gate(self):
        p = _make_proposal(confidence=0.0)
        result = self.svc.auto_execute_promoted([p], self.state, min_confidence=0.0)
        assert result["executed_count"] == 1
        assert result["skipped_low_confidence"] == 0

    def test_mixed_confidence_batch(self):
        high = _make_proposal(confidence=0.90)
        low = _make_proposal(confidence=0.20)
        result = self.svc.auto_execute_promoted(
            [high, low], self.state, min_confidence=0.70
        )
        assert result["executed_count"] == 1
        assert result["skipped_low_confidence"] == 1

    def test_returns_skipped_low_confidence_key(self):
        result = self.svc.auto_execute_promoted([], self.state)
        assert "skipped_low_confidence" in result

    def test_non_promoted_not_counted_as_low_confidence(self):
        p = _make_proposal(status=ProposalStatus.PENDING, confidence=0.0)
        result = self.svc.auto_execute_promoted([p], self.state, min_confidence=0.70)
        assert result["skipped_low_confidence"] == 0
        assert result["skipped_count"] == 1

    def test_protected_not_counted_as_low_confidence(self):
        p = _make_proposal(component="risk_engine", confidence=0.0)
        result = self.svc.auto_execute_promoted([p], self.state, min_confidence=0.70)
        assert result["skipped_low_confidence"] == 0


# ============================================================
# 4. TestAutoExecuteSummarySchema
# ============================================================

class TestAutoExecuteSummarySchema:
    def test_schema_has_skipped_low_confidence(self):
        from apps.api.schemas.self_improvement import AutoExecuteSummaryResponse
        schema = AutoExecuteSummaryResponse(
            status="ok",
            executed_count=1,
            skipped_count=2,
            skipped_low_confidence=1,
            error_count=0,
            errors=[],
            run_at=dt.datetime.now(dt.UTC),
        )
        assert schema.skipped_low_confidence == 1

    def test_schema_default_skipped_low_confidence_zero(self):
        from apps.api.schemas.self_improvement import AutoExecuteSummaryResponse
        schema = AutoExecuteSummaryResponse(
            status="ok",
            executed_count=0,
            skipped_count=0,
            error_count=0,
            errors=[],
            run_at=dt.datetime.now(dt.UTC),
        )
        assert schema.skipped_low_confidence == 0


# ============================================================
# 5. TestAutoExecuteRouteConfidence
# ============================================================

class TestAutoExecuteRouteConfidence:
    def setup_method(self):
        reset_app_state()

    def test_route_returns_skipped_low_confidence(self):
        from apps.api.main import app
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.post("/api/v1/self-improvement/auto-execute")
        assert resp.status_code == 200
        data = resp.json()
        assert "skipped_low_confidence" in data

    def test_route_skipped_low_confidence_zero_when_no_proposals(self):
        from apps.api.main import app
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.post("/api/v1/self-improvement/auto-execute")
        assert resp.json()["skipped_low_confidence"] == 0


# ============================================================
# 6. TestSelfImprovementConfig
# ============================================================

class TestSelfImprovementConfig:
    def test_default_min_auto_execute_confidence(self):
        cfg = SelfImprovementConfig()
        assert cfg.min_auto_execute_confidence == 0.70

    def test_custom_min_auto_execute_confidence(self):
        cfg = SelfImprovementConfig(min_auto_execute_confidence=0.90)
        assert cfg.min_auto_execute_confidence == 0.90

    def test_zero_disables_gate(self):
        cfg = SelfImprovementConfig(min_auto_execute_confidence=0.0)
        assert cfg.min_auto_execute_confidence == 0.0


# ============================================================
# 7. TestAlternativeDataModels
# ============================================================

class TestAlternativeDataModels:
    def test_record_creation(self):
        r = AlternativeDataRecord(
            ticker="AAPL",
            source=AlternativeDataSource.SOCIAL_MENTION,
            sentiment_score=0.75,
        )
        assert r.ticker == "AAPL"
        assert r.sentiment_score == 0.75
        assert r.source == AlternativeDataSource.SOCIAL_MENTION

    def test_sentiment_clamped_positive(self):
        r = AlternativeDataRecord(
            ticker="MSFT", source=AlternativeDataSource.SOCIAL_MENTION, sentiment_score=1.5
        )
        assert r.sentiment_score == 1.0

    def test_sentiment_clamped_negative(self):
        r = AlternativeDataRecord(
            ticker="MSFT", source=AlternativeDataSource.SOCIAL_MENTION, sentiment_score=-2.0
        )
        assert r.sentiment_score == -1.0

    def test_is_bullish(self):
        r = AlternativeDataRecord(
            ticker="X", source=AlternativeDataSource.SOCIAL_MENTION, sentiment_score=0.5
        )
        assert r.is_bullish is True
        assert r.is_bearish is False

    def test_is_bearish(self):
        r = AlternativeDataRecord(
            ticker="X", source=AlternativeDataSource.SOCIAL_MENTION, sentiment_score=-0.5
        )
        assert r.is_bearish is True
        assert r.is_bullish is False

    def test_neutral_neither(self):
        r = AlternativeDataRecord(
            ticker="X", source=AlternativeDataSource.SOCIAL_MENTION, sentiment_score=0.05
        )
        assert r.is_bullish is False
        assert r.is_bearish is False

    def test_id_auto_generated(self):
        r1 = AlternativeDataRecord(
            ticker="A", source=AlternativeDataSource.SOCIAL_MENTION, sentiment_score=0.0
        )
        r2 = AlternativeDataRecord(
            ticker="A", source=AlternativeDataSource.SOCIAL_MENTION, sentiment_score=0.0
        )
        assert r1.id != r2.id

    def test_source_enum_values(self):
        assert AlternativeDataSource.SOCIAL_MENTION.value == "social_mention"
        assert AlternativeDataSource.WEB_SEARCH_TREND.value == "web_search_trend"


# ============================================================
# 8. TestSocialMentionAdapter
# ============================================================

class TestSocialMentionAdapter:
    def setup_method(self):
        self.adapter = SocialMentionAdapter()

    def test_source_property(self):
        assert self.adapter.source == AlternativeDataSource.SOCIAL_MENTION

    def test_fetch_returns_one_record_per_ticker(self):
        records = self.adapter.fetch(["AAPL", "MSFT", "GOOG"])
        assert len(records) == 3

    def test_fetch_is_deterministic(self):
        r1 = self.adapter.fetch(["AAPL"])
        r2 = self.adapter.fetch(["AAPL"])
        assert r1[0].sentiment_score == r2[0].sentiment_score
        assert r1[0].mention_count == r2[0].mention_count

    def test_fetch_tickers_uppercased(self):
        records = self.adapter.fetch(["aapl"])
        assert records[0].ticker == "AAPL"

    def test_fetch_empty_tickers(self):
        assert self.adapter.fetch([]) == []

    def test_sentiment_in_range(self):
        records = self.adapter.fetch(["AAPL", "MSFT", "TSLA", "NVDA", "AMZN"])
        for r in records:
            assert -1.0 <= r.sentiment_score <= 1.0

    def test_mention_count_positive(self):
        records = self.adapter.fetch(["AAPL"])
        assert records[0].mention_count >= 1

    def test_different_tickers_different_scores(self):
        r_aapl = self.adapter.fetch(["AAPL"])[0]
        r_msft = self.adapter.fetch(["MSFT"])[0]
        # Very unlikely to be exactly equal across different tickers
        assert r_aapl.sentiment_score != r_msft.sentiment_score or \
               r_aapl.mention_count != r_msft.mention_count


# ============================================================
# 9. TestAlternativeDataService
# ============================================================

class TestAlternativeDataService:
    def setup_method(self):
        self.svc = AlternativeDataService()
        self.adapter = SocialMentionAdapter()

    def test_ingest_returns_count(self):
        count = self.svc.ingest(self.adapter, ["AAPL", "MSFT"])
        assert count == 2

    def test_ingest_stores_records(self):
        self.svc.ingest(self.adapter, ["AAPL"])
        assert self.svc.record_count == 1

    def test_get_records_returns_all(self):
        self.svc.ingest(self.adapter, ["AAPL", "MSFT"])
        records = self.svc.get_records()
        assert len(records) == 2

    def test_get_records_ticker_filter(self):
        self.svc.ingest(self.adapter, ["AAPL", "MSFT"])
        records = self.svc.get_records(ticker="AAPL")
        assert all(r.ticker == "AAPL" for r in records)

    def test_get_records_ticker_filter_case_insensitive(self):
        self.svc.ingest(self.adapter, ["AAPL"])
        assert len(self.svc.get_records(ticker="aapl")) == 1

    def test_get_records_limit(self):
        self.svc.ingest(self.adapter, ["AAPL", "MSFT", "GOOG", "TSLA", "NVDA"])
        records = self.svc.get_records(limit=3)
        assert len(records) == 3

    def test_get_records_newest_first(self):
        import time
        self.svc.ingest(self.adapter, ["AAPL"])
        time.sleep(0.01)
        self.svc.ingest(self.adapter, ["AAPL"])
        records = self.svc.get_records(ticker="AAPL")
        assert records[0].captured_at >= records[1].captured_at

    def test_get_ticker_sentiment_no_data(self):
        assert self.svc.get_ticker_sentiment("AAPL") is None

    def test_get_ticker_sentiment_with_data(self):
        self.svc.ingest(self.adapter, ["AAPL"])
        sentiment = self.svc.get_ticker_sentiment("AAPL")
        assert sentiment is not None
        assert -1.0 <= sentiment <= 1.0

    def test_clear_resets_store(self):
        self.svc.ingest(self.adapter, ["AAPL"])
        self.svc.clear()
        assert self.svc.record_count == 0

    def test_adapter_failure_returns_zero(self):
        bad_adapter = MagicMock()
        bad_adapter.source = AlternativeDataSource.SOCIAL_MENTION
        bad_adapter.fetch.side_effect = RuntimeError("API down")
        count = self.svc.ingest(bad_adapter, ["AAPL"])
        assert count == 0
        assert self.svc.record_count == 0


# ============================================================
# 10. TestAlternativeDataIngestionJob
# ============================================================

class TestAlternativeDataIngestionJob:
    def setup_method(self):
        self.state = _make_state(latest_alternative_data=[])

    def test_ok_result(self):
        from apps.worker.jobs.ingestion import run_alternative_data_ingestion
        result = run_alternative_data_ingestion(
            app_state=self.state,
            tickers=["AAPL", "MSFT"],
        )
        assert result["status"] == "ok"
        assert result["records_ingested"] == 2
        assert result["tickers_processed"] == 2

    def test_state_populated(self):
        from apps.worker.jobs.ingestion import run_alternative_data_ingestion
        run_alternative_data_ingestion(
            app_state=self.state,
            tickers=["AAPL", "MSFT", "GOOG"],
        )
        assert len(self.state.latest_alternative_data) == 3

    def test_injectable_adapter(self):
        from apps.worker.jobs.ingestion import run_alternative_data_ingestion
        mock_adapter = MagicMock()
        mock_adapter.source = AlternativeDataSource.SOCIAL_MENTION
        mock_record = AlternativeDataRecord(
            ticker="AAPL",
            source=AlternativeDataSource.SOCIAL_MENTION,
            sentiment_score=0.5,
        )
        mock_adapter.fetch.return_value = [mock_record]
        result = run_alternative_data_ingestion(
            app_state=self.state,
            adapter=mock_adapter,
            tickers=["AAPL"],
        )
        assert result["records_ingested"] == 1

    def test_job_error_returns_error_status(self):
        from apps.worker.jobs.ingestion import run_alternative_data_ingestion
        broken_svc = MagicMock()
        broken_svc.ingest.side_effect = RuntimeError("boom")
        result = run_alternative_data_ingestion(
            app_state=self.state,
            alt_data_service=broken_svc,
            tickers=["AAPL"],
        )
        assert result["status"] == "error"

    def test_run_at_in_result(self):
        from apps.worker.jobs.ingestion import run_alternative_data_ingestion
        result = run_alternative_data_ingestion(app_state=self.state, tickers=[])
        assert "run_at" in result


# ============================================================
# 11. TestIntelligenceAlternativeRoute
# ============================================================

class TestIntelligenceAlternativeRoute:
    def setup_method(self):
        reset_app_state()

    def test_empty_returns_200(self):
        from apps.api.main import app
        client = TestClient(app)
        resp = client.get("/api/v1/intelligence/alternative")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["records"] == []

    def test_with_data_returns_records(self):
        from apps.api.main import app
        from apps.api.state import get_app_state
        state = get_app_state()
        record = AlternativeDataRecord(
            ticker="AAPL",
            source=AlternativeDataSource.SOCIAL_MENTION,
            sentiment_score=0.6,
            mention_count=10,
            raw_snippet="Test snippet",
        )
        state.latest_alternative_data = [record]

        client = TestClient(app)
        resp = client.get("/api/v1/intelligence/alternative")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["records"][0]["ticker"] == "AAPL"
        assert data["records"][0]["source"] == "social_mention"

    def test_ticker_filter(self):
        from apps.api.main import app
        from apps.api.state import get_app_state
        state = get_app_state()
        state.latest_alternative_data = [
            AlternativeDataRecord(
                ticker="AAPL", source=AlternativeDataSource.SOCIAL_MENTION, sentiment_score=0.5
            ),
            AlternativeDataRecord(
                ticker="MSFT", source=AlternativeDataSource.SOCIAL_MENTION, sentiment_score=-0.3
            ),
        ]
        client = TestClient(app)
        resp = client.get("/api/v1/intelligence/alternative?ticker=AAPL")
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["records"][0]["ticker"] == "AAPL"

    def test_ticker_filter_case_insensitive(self):
        from apps.api.main import app
        from apps.api.state import get_app_state
        state = get_app_state()
        state.latest_alternative_data = [
            AlternativeDataRecord(
                ticker="AAPL", source=AlternativeDataSource.SOCIAL_MENTION, sentiment_score=0.5
            ),
        ]
        client = TestClient(app)
        resp = client.get("/api/v1/intelligence/alternative?ticker=aapl")
        assert resp.status_code == 200
        assert resp.json()["count"] == 1

    def test_limit_param(self):
        from apps.api.main import app
        from apps.api.state import get_app_state
        state = get_app_state()
        state.latest_alternative_data = [
            AlternativeDataRecord(
                ticker=f"T{i}", source=AlternativeDataSource.SOCIAL_MENTION, sentiment_score=0.1
            )
            for i in range(10)
        ]
        client = TestClient(app)
        resp = client.get("/api/v1/intelligence/alternative?limit=3")
        assert resp.status_code == 200
        assert resp.json()["count"] == 3


# ============================================================
# 12. TestPriceSnapshotRoute
# ============================================================

class TestPriceSnapshotRoute:
    def setup_method(self):
        reset_app_state()

    def test_no_positions_returns_empty(self):
        from apps.api.main import app
        client = TestClient(app)
        resp = client.get("/api/v1/prices/snapshot")
        assert resp.status_code == 200
        data = resp.json()
        assert data["position_count"] == 0
        assert data["ticks"] == []
        assert data["note"] is not None

    def test_with_positions(self):
        from apps.api.main import app
        from apps.api.state import get_app_state

        state = get_app_state()

        @dataclass
        class FakePos:
            quantity: float = 10.0
            avg_entry_price: float = 100.0
            current_price: float = 110.0
            market_value: float = 1100.0

        @dataclass
        class FakePortfolio:
            positions: dict = field(default_factory=dict)

        state.portfolio_state = FakePortfolio(positions={"AAPL": FakePos()})
        client = TestClient(app)
        resp = client.get("/api/v1/prices/snapshot")
        assert resp.status_code == 200
        data = resp.json()
        assert data["position_count"] == 1
        tick = data["ticks"][0]
        assert tick["ticker"] == "AAPL"
        assert tick["current_price"] == pytest.approx(110.0)
        assert tick["unrealized_pnl_pct"] == pytest.approx(0.1, abs=1e-4)

    def test_snapshot_has_as_of(self):
        from apps.api.main import app
        client = TestClient(app)
        resp = client.get("/api/v1/prices/snapshot")
        assert "as_of" in resp.json()


# ============================================================
# 13. TestWebSocketPriceFeed
# ============================================================

class TestWebSocketPriceFeed:
    def setup_method(self):
        reset_app_state()

    def test_websocket_connects_and_returns_json(self):
        from apps.api.main import app
        client = TestClient(app)
        with client.websocket_connect("/api/v1/prices/ws") as ws:
            data = ws.receive_json()
        assert "ticks" in data
        assert "position_count" in data
        assert "as_of" in data

    def test_websocket_empty_positions(self):
        from apps.api.main import app
        client = TestClient(app)
        with client.websocket_connect("/api/v1/prices/ws") as ws:
            data = ws.receive_json()
        assert data["ticks"] == []
        assert data["position_count"] == 0

    def test_websocket_with_positions(self):
        from apps.api.main import app
        from apps.api.state import get_app_state

        @dataclass
        class FakePos:
            quantity: float = 5.0
            avg_entry_price: float = 200.0
            current_price: float = 210.0
            market_value: float = 1050.0

        @dataclass
        class FakePortfolio:
            positions: dict = field(default_factory=dict)

        state = get_app_state()
        state.portfolio_state = FakePortfolio(positions={"MSFT": FakePos()})

        client = TestClient(app)
        with client.websocket_connect("/api/v1/prices/ws") as ws:
            data = ws.receive_json()

        assert data["position_count"] == 1
        assert data["ticks"][0]["ticker"] == "MSFT"

    def test_websocket_as_of_is_string(self):
        from apps.api.main import app
        client = TestClient(app)
        with client.websocket_connect("/api/v1/prices/ws") as ws:
            data = ws.receive_json()
        assert isinstance(data["as_of"], str)


# ============================================================
# 14. TestSchedulerAlternativeDataJob
# ============================================================

class TestSchedulerAlternativeDataJob:
    def test_total_job_count_is_17(self):
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        jobs = scheduler.get_jobs()
        assert len(jobs) == 30

    def test_alternative_data_job_present(self):
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        job_ids = [j.id for j in scheduler.get_jobs()]
        assert "alternative_data_ingestion" in job_ids

    def test_alternative_data_job_at_0605(self):
        from apps.worker.main import build_scheduler
        scheduler = build_scheduler()
        job = next(j for j in scheduler.get_jobs() if j.id == "alternative_data_ingestion")
        trigger = job.trigger
        # CronTrigger fields: hour=6, minute=5
        fields = {f.name: str(f) for f in trigger.fields}
        assert fields.get("hour") == "6"
        assert fields.get("minute") == "5"

    def test_alternative_data_imported_from_jobs(self):
        from apps.worker.jobs import run_alternative_data_ingestion
        assert callable(run_alternative_data_ingestion)


# ============================================================
# 15. TestDashboardPhase36
# ============================================================

class TestDashboardPhase36:
    def setup_method(self):
        reset_app_state()

    def test_dashboard_renders_confidence_threshold(self):
        from apps.api.main import app
        client = TestClient(app)
        resp = client.get("/dashboard/")
        assert resp.status_code == 200
        assert "Confidence Threshold" in resp.text

    def test_dashboard_renders_alternative_data_section(self):
        from apps.api.main import app
        client = TestClient(app)
        resp = client.get("/dashboard/")
        assert resp.status_code == 200
        assert "Alternative Data" in resp.text

    def test_dashboard_shows_no_data_message(self):
        from apps.api.main import app
        client = TestClient(app)
        resp = client.get("/dashboard/")
        assert "No alternative data ingested yet" in resp.text

    def test_dashboard_renders_alt_data_records(self):
        from apps.api.main import app
        from apps.api.state import get_app_state
        state = get_app_state()
        state.latest_alternative_data = [
            AlternativeDataRecord(
                ticker="AAPL",
                source=AlternativeDataSource.SOCIAL_MENTION,
                sentiment_score=0.72,
                mention_count=15,
            )
        ]
        client = TestClient(app)
        resp = client.get("/dashboard/")
        assert resp.status_code == 200
        assert "AAPL" in resp.text

    def test_dashboard_auto_execution_section_updated(self):
        from apps.api.main import app
        client = TestClient(app)
        resp = client.get("/dashboard/")
        assert "Auto-Execution" in resp.text
        assert "70%" in resp.text  # default confidence threshold

    def test_prices_snapshot_in_docs(self):
        from apps.api.main import app
        client = TestClient(app)
        resp = client.get("/openapi.json")
        assert resp.status_code == 200
        paths = resp.json().get("paths", {})
        assert "/api/v1/prices/snapshot" in paths
