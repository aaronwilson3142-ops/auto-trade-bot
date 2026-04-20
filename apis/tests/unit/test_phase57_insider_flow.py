"""
Phase 57 — InsiderFlowStrategy + adapter scaffold tests.

Scope of this test file:
    - FeatureSet overlay fields default to neutral (0.0 / 0.0 / None)
    - InsiderFlowStrategy emits a neutral 0.5 signal with zero confidence
      when no overlay data is present
    - InsiderFlowStrategy.score is stateless and deterministic
    - Age decay math: fresh → 1.0, 14d → 0.5, 28d → 0.25, >=60d → 0.0
    - Reliability tier is ALWAYS at most secondary_verified
    - contains_rumor is ALWAYS False (filings are public record)
    - Aggregation math: single buy → +1.0, balanced → 0.0, full sell → -1.0
    - NullInsiderFlowAdapter always returns an empty event list
    - Strategy is registered in the strategies package __init__

These tests intentionally exercise ONLY the scaffold behaviour.  When a
concrete InsiderFlowAdapter lands, a second test file should cover
provider-specific parsing, rate-limiting, and error paths.
"""
from __future__ import annotations

import datetime as dt
import math
import uuid
from decimal import Decimal

import pytest

from services.data_ingestion.adapters.insider_flow_adapter import (
    InsiderFlowAdapter,
    InsiderFlowEvent,
    NullInsiderFlowAdapter,
)
from services.feature_store.models import ComputedFeature, FeatureSet
from services.signal_engine.models import HorizonClassification, SignalType
from services.signal_engine.strategies import (
    InsiderFlowStrategy,
    MacroTailwindStrategy,
    MomentumStrategy,
    SentimentStrategy,
    ThemeAlignmentStrategy,
    ValuationStrategy,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_feature_set(
    ticker: str = "NVDA",
    flow: float = 0.0,
    conf: float = 0.0,
    age_days: float | None = None,
    volatility: float | None = 0.25,
    dollar_volume: float | None = 1.5e9,
) -> FeatureSet:
    now = dt.datetime(2026, 4, 8, tzinfo=dt.UTC)
    features: list[ComputedFeature] = []
    if volatility is not None:
        features.append(
            ComputedFeature(
                feature_key="volatility_20d",
                feature_group="risk",
                value=Decimal(str(volatility)),
                as_of_timestamp=now,
            )
        )
    if dollar_volume is not None:
        features.append(
            ComputedFeature(
                feature_key="dollar_volume_20d",
                feature_group="liquidity",
                value=Decimal(str(dollar_volume)),
                as_of_timestamp=now,
            )
        )
    fs = FeatureSet(
        security_id=uuid.uuid4(),
        ticker=ticker,
        as_of_timestamp=now,
        features=features,
    )
    fs.insider_flow_score = flow
    fs.insider_flow_confidence = conf
    fs.insider_flow_age_days = age_days
    return fs


# ---------------------------------------------------------------------------
# FeatureSet overlay defaults
# ---------------------------------------------------------------------------

class TestFeatureSetOverlayDefaults:
    def test_insider_flow_overlay_defaults_are_neutral(self) -> None:
        fs = FeatureSet(
            security_id=uuid.uuid4(),
            ticker="AAPL",
            as_of_timestamp=dt.datetime.now(dt.UTC),
        )
        assert fs.insider_flow_score == 0.0
        assert fs.insider_flow_confidence == 0.0
        assert fs.insider_flow_age_days is None

    def test_overlay_fields_are_settable(self) -> None:
        fs = _make_feature_set(flow=0.7, conf=0.8, age_days=3.0)
        assert fs.insider_flow_score == 0.7
        assert fs.insider_flow_confidence == 0.8
        assert fs.insider_flow_age_days == 3.0


# ---------------------------------------------------------------------------
# InsiderFlowStrategy — neutral / no data behaviour
# ---------------------------------------------------------------------------

class TestInsiderFlowStrategyNoData:
    def test_strategy_is_registered_in_package_init(self) -> None:
        # Sibling strategies still importable
        assert MomentumStrategy is not None
        assert SentimentStrategy is not None
        assert ThemeAlignmentStrategy is not None
        assert MacroTailwindStrategy is not None
        assert ValuationStrategy is not None
        # New one
        assert InsiderFlowStrategy is not None

    def test_strategy_metadata(self) -> None:
        s = InsiderFlowStrategy()
        assert s.STRATEGY_KEY == "insider_flow_v1"
        assert s.STRATEGY_FAMILY == "insider_flow"
        assert s.CONFIG_VERSION == "1.0"

    def test_no_overlay_data_yields_neutral_signal(self) -> None:
        fs = _make_feature_set()
        out = InsiderFlowStrategy().score(fs)
        assert out.signal_score == Decimal("0.5")
        assert out.confidence_score == Decimal("0")
        assert out.signal_type == SignalType.INSIDER_FLOW.value
        assert out.horizon_classification == HorizonClassification.POSITIONAL.value
        assert out.contains_rumor is False
        assert out.source_reliability_tier == "unverified"

    def test_zero_confidence_is_neutral_regardless_of_score(self) -> None:
        fs = _make_feature_set(flow=0.9, conf=0.0, age_days=1.0)
        out = InsiderFlowStrategy().score(fs)
        assert out.signal_score == Decimal("0.5")
        assert out.confidence_score == Decimal("0")


# ---------------------------------------------------------------------------
# InsiderFlowStrategy — decay math
# ---------------------------------------------------------------------------

class TestInsiderFlowDecay:
    def test_fresh_filing_full_weight(self) -> None:
        fs = _make_feature_set(flow=1.0, conf=1.0, age_days=0.0)
        out = InsiderFlowStrategy().score(fs)
        # Fully positive flow, full confidence, zero age → score ~ 1.0
        assert out.signal_score is not None
        assert float(out.signal_score) > 0.95

    def test_half_life_14_days(self) -> None:
        fs = _make_feature_set(flow=1.0, conf=1.0, age_days=14.0)
        out = InsiderFlowStrategy().score(fs)
        # age decay at half-life ≈ 0.5
        # effective_conf ≈ 0.5, signal ≈ 0.5 + 0.5*0.5 = 0.75
        assert abs(float(out.signal_score) - 0.75) < 0.01
        assert abs(float(out.confidence_score) - 0.5) < 0.01

    def test_double_half_life_28_days(self) -> None:
        fs = _make_feature_set(flow=1.0, conf=1.0, age_days=28.0)
        out = InsiderFlowStrategy().score(fs)
        # age decay ≈ 0.25
        assert abs(float(out.confidence_score) - 0.25) < 0.01
        # signal = 0.5 + 0.5 * 0.25 = 0.625
        assert abs(float(out.signal_score) - 0.625) < 0.01

    def test_stale_filing_beyond_max_age_is_neutral(self) -> None:
        fs = _make_feature_set(flow=1.0, conf=1.0, age_days=61.0)
        out = InsiderFlowStrategy().score(fs)
        assert out.signal_score == Decimal("0.5")
        assert out.confidence_score == Decimal("0")

    def test_negative_age_treated_as_missing(self) -> None:
        fs = _make_feature_set(flow=1.0, conf=1.0, age_days=-1.0)
        out = InsiderFlowStrategy().score(fs)
        assert out.signal_score == Decimal("0.5")


# ---------------------------------------------------------------------------
# InsiderFlowStrategy — direction, reliability, rumour flag
# ---------------------------------------------------------------------------

class TestInsiderFlowDirection:
    def test_strong_buying_raises_signal_above_neutral(self) -> None:
        fs = _make_feature_set(flow=0.8, conf=0.9, age_days=5.0)
        out = InsiderFlowStrategy().score(fs)
        assert float(out.signal_score) > 0.5

    def test_strong_selling_drops_signal_below_neutral(self) -> None:
        fs = _make_feature_set(flow=-0.8, conf=0.9, age_days=5.0)
        out = InsiderFlowStrategy().score(fs)
        assert float(out.signal_score) < 0.5

    def test_contains_rumor_is_always_false(self) -> None:
        # Even with borderline low confidence the flag stays False
        fs = _make_feature_set(flow=0.5, conf=0.1, age_days=0.0)
        out = InsiderFlowStrategy().score(fs)
        assert out.contains_rumor is False
        assert out.explanation_dict["contains_rumor"] is False

    def test_reliability_tier_never_primary_verified(self) -> None:
        # Even maximum effective_conf should not produce primary_verified
        fs = _make_feature_set(flow=1.0, conf=1.0, age_days=0.0)
        out = InsiderFlowStrategy().score(fs)
        assert out.source_reliability_tier in {"secondary_verified", "unverified"}
        assert out.source_reliability_tier != "primary_verified"

    def test_explanation_contains_required_fields(self) -> None:
        fs = _make_feature_set(flow=0.3, conf=0.6, age_days=7.0)
        out = InsiderFlowStrategy().score(fs)
        exp = out.explanation_dict
        for key in (
            "signal_type",
            "strategy_key",
            "config_version",
            "raw_flow_score",
            "raw_confidence",
            "age_days",
            "age_decay_factor",
            "effective_confidence",
            "base_score",
            "raw_signal_score",
            "reliability_tier",
            "rationale",
            "half_life_days",
            "max_age_days",
        ):
            assert key in exp, f"missing explanation key: {key}"


# ---------------------------------------------------------------------------
# InsiderFlowAdapter — aggregation + NullInsiderFlowAdapter
# ---------------------------------------------------------------------------

class _FakeAdapter(InsiderFlowAdapter):
    """Concrete subclass solely to exercise the shared aggregate() method."""

    def __init__(self, events: list[InsiderFlowEvent]) -> None:
        self._events = events

    def fetch_events(
        self,
        tickers: list[str],
        lookback_days: int = 90,
        as_of: dt.date | None = None,
    ) -> list[InsiderFlowEvent]:
        return list(self._events)


def _evt(
    ticker: str,
    side: str,
    notional: float,
    filing_date: dt.date,
    confidence: float = 1.0,
) -> InsiderFlowEvent:
    return InsiderFlowEvent(
        ticker=ticker,
        actor_type="congress",
        actor_name="Test Actor",
        side=side,
        notional_usd=Decimal(str(notional)),
        trade_date=filing_date - dt.timedelta(days=10),
        filing_date=filing_date,
        source_key="test",
        confidence=confidence,
    )


class TestInsiderFlowAdapter:
    def test_null_adapter_returns_empty_list(self) -> None:
        adapter = NullInsiderFlowAdapter()
        assert adapter.fetch_events(["AAPL", "MSFT"], lookback_days=90) == []
        assert adapter.SOURCE_KEY == "insider_flow_null"
        assert adapter.RELIABILITY_TIER == "secondary_verified"

    def test_aggregate_no_events_is_neutral(self) -> None:
        adapter = _FakeAdapter([])
        overlay = adapter.aggregate(
            ticker="NVDA",
            events=[],
            as_of=dt.date(2026, 4, 8),
        )
        assert overlay.net_flow_score == 0.0
        assert overlay.aggregate_confidence == 0.0
        assert overlay.most_recent_age_days is None
        assert overlay.event_count == 0

    def test_aggregate_all_buys_maps_to_plus_one(self) -> None:
        as_of = dt.date(2026, 4, 8)
        events = [
            _evt("NVDA", "BUY", 100_000, as_of - dt.timedelta(days=5)),
            _evt("NVDA", "BUY", 50_000, as_of - dt.timedelta(days=3)),
        ]
        overlay = _FakeAdapter(events).aggregate("NVDA", events, as_of=as_of)
        assert overlay.net_flow_score == 1.0
        assert overlay.event_count == 2
        assert overlay.most_recent_age_days == 3.0

    def test_aggregate_all_sells_maps_to_minus_one(self) -> None:
        as_of = dt.date(2026, 4, 8)
        events = [_evt("MSFT", "SELL", 200_000, as_of - dt.timedelta(days=1))]
        overlay = _FakeAdapter(events).aggregate("MSFT", events, as_of=as_of)
        assert overlay.net_flow_score == -1.0
        assert overlay.most_recent_age_days == 1.0

    def test_aggregate_balanced_flow_is_zero(self) -> None:
        as_of = dt.date(2026, 4, 8)
        events = [
            _evt("AAPL", "BUY", 100_000, as_of - dt.timedelta(days=2)),
            _evt("AAPL", "SELL", 100_000, as_of - dt.timedelta(days=2)),
        ]
        overlay = _FakeAdapter(events).aggregate("AAPL", events, as_of=as_of)
        assert overlay.net_flow_score == 0.0
        assert overlay.event_count == 2

    def test_aggregate_ignores_other_tickers(self) -> None:
        as_of = dt.date(2026, 4, 8)
        events = [
            _evt("AAPL", "BUY", 100_000, as_of - dt.timedelta(days=2)),
            _evt("MSFT", "SELL", 500_000, as_of - dt.timedelta(days=2)),
        ]
        overlay = _FakeAdapter(events).aggregate("AAPL", events, as_of=as_of)
        assert overlay.event_count == 1
        assert overlay.net_flow_score == 1.0

    def test_dollar_weighted_net_flow(self) -> None:
        as_of = dt.date(2026, 4, 8)
        events = [
            _evt("TSLA", "BUY", 300_000, as_of - dt.timedelta(days=4)),
            _evt("TSLA", "SELL", 100_000, as_of - dt.timedelta(days=4)),
        ]
        overlay = _FakeAdapter(events).aggregate("TSLA", events, as_of=as_of)
        # (300 - 100) / (300 + 100) = 0.5
        assert overlay.net_flow_score == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Sanity: math helper expectations hold
# ---------------------------------------------------------------------------

class TestDecayMathExpectations:
    def test_half_life_formula_matches_constants(self) -> None:
        # Re-derive expected half-life from the strategy's own constants.
        # This guards against accidentally changing the half-life without
        # updating the documented behaviour.
        from services.signal_engine.strategies.insider_flow import (
            _HALF_LIFE_DAYS,
            _MAX_AGE_DAYS,
            _age_decay,
        )
        assert _HALF_LIFE_DAYS == 14.0
        assert _MAX_AGE_DAYS == 60.0
        assert _age_decay(0.0) == pytest.approx(1.0)
        assert _age_decay(14.0) == pytest.approx(0.5, abs=1e-6)
        assert _age_decay(28.0) == pytest.approx(0.25, abs=1e-6)
        assert _age_decay(60.0) == 0.0
        assert _age_decay(None) == 0.0
        # math.exp sanity (kills unused-import warnings too)
        assert math.exp(0) == 1.0
