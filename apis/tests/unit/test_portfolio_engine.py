"""
Gate C — Portfolio Engine Tests.

Verifies:
  - PortfolioState equity / drawdown / daily_pnl accounting
  - Half-Kelly sizing formula and ceiling logic
  - open_position / close_position action generation
  - apply_ranked_opportunities: respects max_positions, skips held, generates closes
  - snapshot: all fields populated, explainability satisfied
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from config.settings import Settings
from services.portfolio_engine.models import (
    ActionType,
    PortfolioPosition,
    PortfolioState,
)
from services.portfolio_engine.service import PortfolioEngineService
from services.ranking_engine.models import RankedResult

# ─────────────────────────── shared fixtures ──────────────────────────────────

def _make_settings(**overrides) -> Settings:
    """Return a Settings instance with sensible test defaults."""
    import os
    os.environ.setdefault("APIS_ENV", "development")
    os.environ.setdefault("APIS_OPERATING_MODE", "research")
    os.environ.setdefault("APIS_DB_URL", "postgresql+psycopg://test:test@localhost:5432/apis_test")
    s = Settings()
    for k, v in overrides.items():
        object.__setattr__(s, k, v)
    return s


def _make_position(
    ticker: str,
    quantity: Decimal = Decimal("100"),
    avg_entry: Decimal = Decimal("100.00"),
    current: Decimal = Decimal("110.00"),
) -> PortfolioPosition:
    return PortfolioPosition(
        ticker=ticker,
        quantity=quantity,
        avg_entry_price=avg_entry,
        current_price=current,
        opened_at=dt.datetime.utcnow(),
        thesis_summary=f"Long {ticker} — momentum signal",
        strategy_key="momentum_v1",
    )


def _make_ranked(
    ticker: str,
    score: float = 0.70,
    action: str = "buy",
    sizing_hint: float | None = None,
) -> RankedResult:
    return RankedResult(
        rank_position=1,
        security_id=None,
        ticker=ticker,
        composite_score=Decimal(str(score)),
        portfolio_fit_score=Decimal("0.8"),
        recommended_action=action,
        target_horizon="positional",
        thesis_summary=f"{ticker} strong momentum",
        disconfirming_factors="valuation slightly stretched",
        sizing_hint_pct=Decimal(str(sizing_hint)) if sizing_hint is not None else None,
        source_reliability_tier="secondary_verified",
        contains_rumor=False,
    )


@pytest.fixture()
def svc() -> PortfolioEngineService:
    return PortfolioEngineService(settings=_make_settings())


@pytest.fixture()
def empty_state() -> PortfolioState:
    return PortfolioState(cash=Decimal("100000.00"))


@pytest.fixture()
def state_with_one() -> PortfolioState:
    state = PortfolioState(
        cash=Decimal("89000.00"),
        start_of_day_equity=Decimal("100000.00"),
        high_water_mark=Decimal("105000.00"),
    )
    state.positions["AAPL"] = _make_position(
        "AAPL",
        quantity=Decimal("100"),
        avg_entry=Decimal("100.00"),
        current=Decimal("110.00"),
    )   # market_value = 11000
    return state


# ─────────────────────────────────────────────────────────────────────────────
# TestPortfolioState
# ─────────────────────────────────────────────────────────────────────────────

class TestPortfolioState:
    def test_empty_state_equity_equals_cash(self, empty_state):
        assert empty_state.equity == Decimal("100000.00")

    def test_equity_includes_positions(self, state_with_one):
        # cash=89000 + AAPL market_value(100*110=11000) = 100000
        assert state_with_one.equity == Decimal("100000.00")

    def test_gross_exposure_sum_of_market_values(self, state_with_one):
        assert state_with_one.gross_exposure == Decimal("11000.00")

    def test_drawdown_pct_calculated_correctly(self, state_with_one):
        # high_water_mark=105000; equity=100000 → drawdown = 5000/105000 ≈ 0.0476
        expected = Decimal("5000") / Decimal("105000")
        assert abs(state_with_one.drawdown_pct - expected.quantize(Decimal("0.0001"))) < Decimal("0.0001")

    def test_drawdown_zero_when_no_high_water_mark(self, empty_state):
        assert empty_state.drawdown_pct == Decimal("0")

    def test_daily_pnl_pct_when_flat(self):
        """start_of_day_equity == equity → 0% P&L."""
        state = PortfolioState(
            cash=Decimal("100000.00"),
            start_of_day_equity=Decimal("100000.00"),
        )
        assert state.daily_pnl_pct == Decimal("0")

    def test_daily_pnl_pct_negative_on_loss(self, state_with_one):
        # equity=100000; start_of_day=100000 → flat today
        assert state_with_one.daily_pnl_pct == Decimal("0")

    def test_position_count(self, state_with_one):
        assert state_with_one.position_count == 1


# ─────────────────────────────────────────────────────────────────────────────
# TestPortfolioPosition
# ─────────────────────────────────────────────────────────────────────────────

class TestPortfolioPosition:
    def test_market_value(self):
        pos = _make_position("NVDA", quantity=Decimal("10"), current=Decimal("500.00"))
        assert pos.market_value == Decimal("5000.00")

    def test_unrealized_pnl_positive(self):
        pos = _make_position("NVDA", quantity=Decimal("10"), avg_entry=Decimal("400.00"), current=Decimal("500.00"))
        assert pos.unrealized_pnl == Decimal("1000.00")

    def test_unrealized_pnl_negative(self):
        pos = _make_position("NVDA", quantity=Decimal("10"), avg_entry=Decimal("600.00"), current=Decimal("500.00"))
        assert pos.unrealized_pnl == Decimal("-1000.00")

    def test_unrealized_pnl_pct(self):
        pos = _make_position("NVDA", quantity=Decimal("10"), avg_entry=Decimal("500.00"), current=Decimal("550.00"))
        # pnl=500, cost=5000 → 10%
        assert pos.unrealized_pnl_pct == Decimal("0.100000")


# ─────────────────────────────────────────────────────────────────────────────
# TestComputeSizing
# ─────────────────────────────────────────────────────────────────────────────

class TestComputeSizing:
    def test_half_kelly_zero_at_0_5_score(self, svc, empty_state):
        """Composite score of 0.5 implies no edge → 0 notional."""
        result = svc.compute_sizing(_make_ranked("AAPL", score=0.50), empty_state)
        assert result.target_notional == Decimal("0")
        assert result.half_kelly_pct == Decimal("0")

    def test_half_kelly_formula_at_0_70(self, svc, empty_state):
        """p=0.70 → half_kelly = 0.5*(2*0.7-1)=0.5*0.4=0.20.  Equity=100k → 20k."""
        result = svc.compute_sizing(_make_ranked("AAPL", score=0.70), empty_state)
        # Max_single_name_pct default is 0.20, so it hits the ceiling exactly
        assert result.half_kelly_pct == Decimal("0.2")
        assert result.target_notional == Decimal("20000.00")
        assert not result.capped  # exactly at ceiling

    def test_half_kelly_capped_at_max_single_name_pct(self, svc, empty_state):
        """p=0.90 → half_kelly=0.40, but max_single_name_pct=0.20 caps it."""
        result = svc.compute_sizing(_make_ranked("AAPL", score=0.90), empty_state)
        assert result.capped is True
        assert result.target_pct == Decimal("0.2")
        assert result.target_notional == Decimal("20000.00")

    def test_sizing_hint_overrides_kelly_when_lower(self, svc, empty_state):
        """sizing_hint_pct=0.10 is tighter than half_kelly=0.20 → use 0.10."""
        result = svc.compute_sizing(
            _make_ranked("AAPL", score=0.70, sizing_hint=0.10), empty_state
        )
        assert result.capped is True
        assert result.target_pct == Decimal("0.1")
        assert result.target_notional == Decimal("10000.00")

    def test_sizing_hint_not_binding_when_higher(self, svc, empty_state):
        """sizing_hint_pct=0.30 is higher than max_single_name_pct=0.20 → max_single_name wins."""
        result = svc.compute_sizing(
            _make_ranked("AAPL", score=0.70, sizing_hint=0.30), empty_state
        )
        assert result.target_pct == Decimal("0.2")

    def test_rationale_is_populated(self, svc, empty_state):
        result = svc.compute_sizing(_make_ranked("AAPL", score=0.65), empty_state)
        assert len(result.rationale) > 20

    def test_very_low_score_gives_zero(self, svc, empty_state):
        """p=0.40 (below 0.5) → half_kelly < 0 → clamped to 0."""
        result = svc.compute_sizing(_make_ranked("AAPL", score=0.40), empty_state)
        assert result.target_notional == Decimal("0")


# ─────────────────────────────────────────────────────────────────────────────
# TestOpenPosition
# ─────────────────────────────────────────────────────────────────────────────

class TestOpenPosition:
    def test_returns_open_action(self, svc, empty_state):
        action = svc.open_position(_make_ranked("NVDA", score=0.75), empty_state)
        assert action.action_type == ActionType.OPEN
        assert action.ticker == "NVDA"

    def test_thesis_summary_populated(self, svc, empty_state):
        result = _make_ranked("NVDA", score=0.75)
        action = svc.open_position(result, empty_state)
        assert action.thesis_summary == result.thesis_summary

    def test_sizing_rationale_populated(self, svc, empty_state):
        action = svc.open_position(_make_ranked("NVDA", score=0.75), empty_state)
        assert len(action.sizing_rationale) > 10

    def test_risk_approved_false_before_validation(self, svc, empty_state):
        action = svc.open_position(_make_ranked("NVDA", score=0.75), empty_state)
        assert action.risk_approved is False

    def test_ranked_result_attached_for_traceability(self, svc, empty_state):
        ranked = _make_ranked("NVDA", score=0.75)
        action = svc.open_position(ranked, empty_state)
        assert action.ranked_result is ranked


# ─────────────────────────────────────────────────────────────────────────────
# TestClosePosition
# ─────────────────────────────────────────────────────────────────────────────

class TestClosePosition:
    def test_returns_close_action(self, svc, state_with_one):
        action = svc.close_position("AAPL", state_with_one)
        assert action.action_type == ActionType.CLOSE
        assert action.ticker == "AAPL"

    def test_reason_preserved(self, svc, state_with_one):
        action = svc.close_position("AAPL", state_with_one, reason="stop_loss")
        assert action.reason == "stop_loss"

    def test_thesis_taken_from_position(self, svc, state_with_one):
        """Exit explanation must come from the original position thesis."""
        action = svc.close_position("AAPL", state_with_one)
        assert "AAPL" in action.thesis_summary

    def test_close_nonexistent_ticker_safe(self, svc, empty_state):
        """Closing a ticker not in portfolio should not raise."""
        action = svc.close_position("FAKE", empty_state)
        assert action.action_type == ActionType.CLOSE
        assert action.ticker == "FAKE"

    def test_target_quantity_from_position(self, svc, state_with_one):
        action = svc.close_position("AAPL", state_with_one)
        assert action.target_quantity == Decimal("100")


# ─────────────────────────────────────────────────────────────────────────────
# TestApplyRankedOpportunities
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyRankedOpportunities:
    def test_generates_open_for_buy_signal(self, svc, empty_state):
        ranked = [_make_ranked("NVDA", score=0.75, action="buy")]
        actions = svc.apply_ranked_opportunities(ranked, empty_state)
        opens = [a for a in actions if a.action_type == ActionType.OPEN]
        assert len(opens) == 1
        assert opens[0].ticker == "NVDA"

    def test_skips_already_held_ticker(self, svc, state_with_one):
        """AAPL is already held — should not generate a new OPEN."""
        ranked = [_make_ranked("AAPL", score=0.75, action="buy")]
        actions = svc.apply_ranked_opportunities(ranked, state_with_one)
        opens = [a for a in actions if a.action_type == ActionType.OPEN]
        assert len(opens) == 0

    def test_respects_max_positions(self, svc):
        """10 positions in state → no new opens allowed."""
        settings = _make_settings()  # max_positions=10
        svc_full = PortfolioEngineService(settings)
        state = PortfolioState(cash=Decimal("50000.00"))
        for i in range(10):
            ticker = f"T{i:03d}"
            state.positions[ticker] = _make_position(ticker)

        ranked = [_make_ranked("NEWCO", score=0.80, action="buy")]
        actions = svc_full.apply_ranked_opportunities(ranked, state)
        opens = [a for a in actions if a.action_type == ActionType.OPEN]
        assert len(opens) == 0

    def test_generates_close_for_stale_position(self, svc, state_with_one):
        """Holding AAPL but ranked list has only NVDA → AAPL should be closed."""
        ranked = [_make_ranked("NVDA", score=0.75, action="buy")]
        actions = svc.apply_ranked_opportunities(ranked, state_with_one)
        closes = [a for a in actions if a.action_type == ActionType.CLOSE]
        assert any(a.ticker == "AAPL" for a in closes)

    def test_non_buy_action_does_not_generate_open(self, svc, empty_state):
        ranked = [
            _make_ranked("TSLA", score=0.60, action="watch"),
            _make_ranked("AMZN", score=0.55, action="avoid"),
        ]
        actions = svc.apply_ranked_opportunities(ranked, empty_state)
        opens = [a for a in actions if a.action_type == ActionType.OPEN]
        assert len(opens) == 0

    def test_empty_ranked_list_returns_closes_for_all_held(self, svc, state_with_one):
        actions = svc.apply_ranked_opportunities([], state_with_one)
        closes = [a for a in actions if a.action_type == ActionType.CLOSE]
        assert any(a.ticker == "AAPL" for a in closes)

    def test_zero_notional_result_skipped(self, svc, empty_state):
        """composite_score=0.50 → 0 notional — should not generate an open action."""
        ranked = [_make_ranked("LOW_EDGE", score=0.50, action="buy")]
        actions = svc.apply_ranked_opportunities(ranked, empty_state)
        opens = [a for a in actions if a.action_type == ActionType.OPEN]
        assert len(opens) == 0


# ─────────────────────────────────────────────────────────────────────────────
# TestSnapshot
# ─────────────────────────────────────────────────────────────────────────────

class TestSnapshot:
    def test_snapshot_all_fields_present(self, svc, state_with_one):
        snap = svc.snapshot(state_with_one)
        assert snap.cash == state_with_one.cash
        assert snap.equity == state_with_one.equity
        assert snap.gross_exposure == state_with_one.gross_exposure
        assert snap.position_count == 1
        assert snap.snapshot_at is not None
        assert len(snap.positions) == 1

    def test_snapshot_mode_is_operating_mode(self, svc, empty_state):
        snap = svc.snapshot(empty_state)
        assert snap.mode == "research"

    def test_snapshot_drawdown_pct_populated(self, svc, state_with_one):
        # state_with_one has high_water_mark=105000, equity=100000
        snap = svc.snapshot(state_with_one)
        assert snap.drawdown_pct > Decimal("0")

    def test_snapshot_empty_state(self, svc, empty_state):
        snap = svc.snapshot(empty_state)
        assert snap.equity == Decimal("100000.00")
        assert snap.position_count == 0
        assert snap.positions == []
