"""
Gate B — ranking_engine tests.

Validates RankingEngineService using synthetic SignalOutput objects — no DB,
network, or ORM required.

Gate B criteria verified here:
  - ranking pipeline runs end-to-end
  - outputs are explainable (thesis_summary populated on every RankedResult)
  - sources are tagged by reliability (source_reliability_tier on RankedResult)
  - rumors are separated from verified facts (contains_rumor propagated correctly)
"""
from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest

from services.ranking_engine.models import RankedResult, RankingConfig
from services.ranking_engine.service import RankingEngineService
from services.signal_engine.models import HorizonClassification, SignalOutput, SignalType


def _make_signal(
    ticker: str = "AAPL",
    signal_score: float = 0.70,
    confidence: float = 0.80,
    risk: float = 0.30,
    liquidity: float = 0.90,
    contains_rumor: bool = False,
    reliability: str = "secondary_verified",
) -> SignalOutput:
    return SignalOutput(
        security_id=uuid.uuid4(),
        ticker=ticker,
        strategy_key="momentum_v1",
        signal_type=SignalType.MOMENTUM.value,
        signal_score=Decimal(str(signal_score)),
        confidence_score=Decimal(str(confidence)),
        risk_score=Decimal(str(risk)),
        catalyst_score=None,
        liquidity_score=Decimal(str(liquidity)),
        horizon_classification=HorizonClassification.POSITIONAL.value,
        explanation_dict={
            "rationale": f"{ticker} shows strong upward momentum.",
            "driver_features": {"return_1m": 0.10},
            "signal_type": "momentum",
            "contains_rumor": contains_rumor,
            "source_reliability": reliability,
        },
        source_reliability_tier=reliability,
        contains_rumor=contains_rumor,
        as_of=dt.datetime.utcnow(),
    )


class TestRankingEngineService:
    """End-to-end ranking pipeline tests (in-memory, no DB)."""

    def test_rank_signals_returns_ranked_results(self) -> None:
        """Gate B: ranking pipeline runs."""
        service = RankingEngineService()
        signals = [_make_signal("AAPL"), _make_signal("MSFT"), _make_signal("NVDA")]
        results = service.rank_signals(signals)
        assert len(results) >= 1
        assert all(isinstance(r, RankedResult) for r in results)

    def test_rank_positions_are_sequential_from_one(self) -> None:
        service = RankingEngineService()
        signals = [_make_signal(t) for t in ["AAPL", "MSFT", "NVDA", "GOOGL"]]
        results = service.rank_signals(signals)
        positions = [r.rank_position for r in results]
        assert positions == list(range(1, len(results) + 1))

    def test_higher_score_ranks_first(self) -> None:
        """Securities with higher composite scores appear first."""
        service = RankingEngineService()
        strong = _make_signal("NVDA", signal_score=0.90, confidence=0.95, risk=0.10)
        weak = _make_signal("AAPL", signal_score=0.40, confidence=0.50, risk=0.60)
        results = service.rank_signals([weak, strong])
        assert results[0].ticker == "NVDA"
        assert results[1].ticker == "AAPL"

    def test_thesis_summary_populated_for_all_results(self) -> None:
        """Gate B: every ranking output must have an explainable thesis."""
        service = RankingEngineService()
        signals = [_make_signal(t) for t in ["AAPL", "MSFT"]]
        results = service.rank_signals(signals)
        for r in results:
            assert r.thesis_summary, f"{r.ticker} has empty thesis_summary"
            assert len(r.thesis_summary) > 10

    def test_disconfirming_factors_populated(self) -> None:
        """Gate B: every ranking output must include disconfirming factors."""
        service = RankingEngineService()
        results = service.rank_signals([_make_signal("AAPL")])
        for r in results:
            assert r.disconfirming_factors, f"{r.ticker} has empty disconfirming_factors"

    def test_source_reliability_tier_tagged(self) -> None:
        """Gate B: source reliability tier must be tagged on every result."""
        service = RankingEngineService()
        results = service.rank_signals([_make_signal("MSFT")])
        for r in results:
            assert r.source_reliability_tier, f"{r.ticker} has no source_reliability_tier"

    def test_rumor_signal_propagates_to_result(self) -> None:
        """Gate B: results derived from rumour signals must be flagged."""
        service = RankingEngineService()
        rumor_signal = _make_signal("MEME", contains_rumor=True, reliability="unverified")
        results = service.rank_signals([rumor_signal])
        assert len(results) == 1
        assert results[0].contains_rumor is True
        assert results[0].source_reliability_tier == "unverified"

    def test_clean_signal_not_flagged_as_rumor(self) -> None:
        """Gate B: verified OHLCV signals must NOT be flagged as rumours."""
        service = RankingEngineService()
        results = service.rank_signals([_make_signal("AAPL", contains_rumor=False)])
        assert results[0].contains_rumor is False

    def test_max_results_respected(self) -> None:
        """RankingEngineService caps results at max_results parameter."""
        service = RankingEngineService()
        signals = [_make_signal(f"TK{i}") for i in range(20)]
        # Each signal has a unique security_id so all are distinct securities
        results = service.rank_signals(signals, max_results=5)
        assert len(results) <= 5

    def test_composite_score_populated(self) -> None:
        service = RankingEngineService()
        results = service.rank_signals([_make_signal("AAPL")])
        assert results[0].composite_score is not None

    def test_portfolio_fit_score_populated(self) -> None:
        service = RankingEngineService()
        results = service.rank_signals([_make_signal("AMZN")])
        assert results[0].portfolio_fit_score is not None

    def test_sizing_hint_within_range(self) -> None:
        """Sizing hint should be in [0, max_single_name_pct]."""
        service = RankingEngineService()
        results = service.rank_signals([_make_signal("AAPL")])
        r = results[0]
        if r.sizing_hint_pct is not None:
            assert Decimal("0") <= r.sizing_hint_pct <= Decimal("0.20")

    def test_recommended_action_is_valid(self) -> None:
        service = RankingEngineService()
        signals = [
            _make_signal("STRONG", signal_score=0.90),
            _make_signal("NEUTRAL", signal_score=0.50),
            _make_signal("WEAK", signal_score=0.20, risk=0.80),
        ]
        results = service.rank_signals(signals)
        valid_actions = {"buy", "watch", "avoid"}
        for r in results:
            assert r.recommended_action in valid_actions

    def test_target_horizon_is_set(self) -> None:
        service = RankingEngineService()
        results = service.rank_signals([_make_signal("AAPL")])
        assert results[0].target_horizon

    def test_contributing_signals_present(self) -> None:
        """Each result should carry the raw signal breakdown for audit."""
        service = RankingEngineService()
        results = service.rank_signals([_make_signal("AAPL")])
        assert isinstance(results[0].contributing_signals, list)
        assert len(results[0].contributing_signals) >= 1

    def test_empty_signal_list_returns_empty(self) -> None:
        service = RankingEngineService()
        assert service.rank_signals([]) == []

    def test_ranking_config_used(self) -> None:
        """Custom weights change output scores relative to default config."""
        default_service = RankingEngineService()
        # Very risk-averse config — high risk penalty
        risk_averse = RankingEngineService(
            config=RankingConfig(
                signal_weight=0.30,
                confidence_weight=0.10,
                liquidity_weight=0.10,
                risk_penalty_weight=0.50,
            )
        )
        sig = _make_signal("RISKY", signal_score=0.80, risk=0.90)
        default_result = default_service.rank_signals([sig])[0]
        averse_result = risk_averse.rank_signals([sig])[0]
        # Risk-averse config should penalise more heavily
        assert averse_result.composite_score <= default_result.composite_score


class TestEndToEndPipeline:
    """Simulate the full research → ranking pipeline with synthetic data."""

    def test_full_pipeline_no_db(self) -> None:
        """
        Gate B: ranking pipeline runs end-to-end.

        Chain: synthetic FeatureSet → MomentumStrategy → RankingEngineService
        → RankedResult with thesis, source tag, and no rumour flag.
        """
        import datetime as dt
        from services.feature_store.models import ComputedFeature, FeatureSet
        from services.signal_engine.strategies.momentum import MomentumStrategy
        from services.ranking_engine.service import RankingEngineService

        # Step 1: Build synthetic feature sets for 5 tickers
        tickers = ["AAPL", "MSFT", "NVDA", "GOOGL", "AMZN"]
        feature_sets = []
        for i, ticker in enumerate(tickers):
            sid = uuid.uuid4()
            now = dt.datetime.utcnow()
            r1m = 0.05 + i * 0.03      # increasing returns
            features = [
                ComputedFeature("return_1m", "momentum", Decimal(str(r1m)), now),
                ComputedFeature("return_3m", "momentum", Decimal(str(r1m * 2.5)), now),
                ComputedFeature("return_6m", "momentum", Decimal(str(r1m * 4)), now),
                ComputedFeature("sma_cross_signal", "trend", Decimal("1.0"), now),
                ComputedFeature("volatility_20d", "risk", Decimal("0.25"), now),
                ComputedFeature("dollar_volume_20d", "liquidity", Decimal("5e8"), now),
                ComputedFeature("sma_20", "trend", Decimal("150.0"), now),
                ComputedFeature("sma_50", "trend", Decimal("145.0"), now),
                ComputedFeature("price_vs_sma20", "trend", Decimal("0.02"), now),
                ComputedFeature("price_vs_sma50", "trend", Decimal("0.04"), now),
            ]
            feature_sets.append(FeatureSet(security_id=sid, ticker=ticker, as_of_timestamp=now, features=features))

        # Step 2: Generate signals
        strategy = MomentumStrategy()
        signals = [strategy.score(fs) for fs in feature_sets]

        # Step 3: Rank
        ranker = RankingEngineService()
        results = ranker.rank_signals(signals)

        # Gate B assertions
        assert len(results) >= 1
        assert results[0].rank_position == 1

        for r in results:
            # Gate B: explainable
            assert r.thesis_summary and len(r.thesis_summary) > 10
            assert r.disconfirming_factors
            # Gate B: source tagged
            assert r.source_reliability_tier
            # Gate B: rumour separation
            assert r.contains_rumor is False
            # Gate B: composite score present
            assert r.composite_score is not None

        # Highest-return ticker (AMZN, i=4) should rank first
        assert results[0].ticker == "AMZN"
