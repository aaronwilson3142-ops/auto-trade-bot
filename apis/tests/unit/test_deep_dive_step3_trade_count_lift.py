"""Deep-Dive Plan Step 3 — Trade-Count Lift regression tests.

Covers two behavioral flags, both default OFF:
  Rec 9 — ``lower_buy_threshold_enabled`` lowers the "buy" action
          threshold in ``RankingEngineService._recommend_action``
          from 0.65 to ``lower_buy_threshold_value`` (default 0.55).
  Rec 8 — ``conditional_ranking_min_enabled`` relaxes
          ``ranking_min_composite_score`` for tickers that are
          currently held AND have >=1 prior closed trade graded A/B,
          via ``_apply_ranking_min_filter`` in ``apps.worker.jobs.paper_trading``.

Flag-OFF cases must be bit-for-bit equivalent to pre-Step-3 behavior.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

import pytest

from services.ranking_engine.service import RankingEngineService
from apps.worker.jobs.paper_trading import _apply_ranking_min_filter


# ── Shared stubs ─────────────────────────────────────────────────────────────


class _Settings:
    """Lightweight settings stub — attribute access only."""

    def __init__(
        self,
        *,
        buy_threshold: float = 0.65,
        watch_threshold: float = 0.45,
        lower_buy_threshold_enabled: bool = False,
        lower_buy_threshold_value: float = 0.55,
        ranking_min_composite_score: float = 0.30,
        conditional_ranking_min_enabled: bool = False,
        ranking_min_held_positive: float = 0.20,
    ) -> None:
        self.buy_threshold = buy_threshold
        self.watch_threshold = watch_threshold
        self.lower_buy_threshold_enabled = lower_buy_threshold_enabled
        self.lower_buy_threshold_value = lower_buy_threshold_value
        self.ranking_min_composite_score = ranking_min_composite_score
        self.conditional_ranking_min_enabled = conditional_ranking_min_enabled
        self.ranking_min_held_positive = ranking_min_held_positive


@dataclass
class _Ranking:
    ticker: str
    composite_score: float


@dataclass
class _PortfolioState:
    positions: dict[str, Any] = field(default_factory=dict)


@dataclass
class _AppState:
    portfolio_state: Any = None
    trade_grades: list[Any] = field(default_factory=list)


@dataclass
class _Grade:
    ticker: str
    grade: str


# ── Rec 9 — _recommend_action with lower-buy flag ────────────────────────────


class TestLowerBuyThresholdFlagOff:
    """Flag OFF → legacy 0.65 / 0.45 cut-points preserved."""

    def test_below_0_45_is_avoid(self):
        s = _Settings()
        assert RankingEngineService._recommend_action(0.40, None, s) == "avoid"

    def test_between_watch_and_buy_is_watch(self):
        s = _Settings()
        assert RankingEngineService._recommend_action(0.54, None, s) == "watch"
        assert RankingEngineService._recommend_action(0.56, None, s) == "watch"
        assert RankingEngineService._recommend_action(0.64, None, s) == "watch"

    def test_at_or_above_0_65_is_buy(self):
        s = _Settings()
        assert RankingEngineService._recommend_action(0.65, None, s) == "buy"
        assert RankingEngineService._recommend_action(0.70, None, s) == "buy"


class TestLowerBuyThresholdFlagOn:
    """Flag ON → effective buy threshold drops to 0.55."""

    def test_below_0_55_is_watch(self):
        s = _Settings(lower_buy_threshold_enabled=True)
        assert RankingEngineService._recommend_action(0.54, None, s) == "watch"

    def test_at_or_above_0_55_is_buy(self):
        s = _Settings(lower_buy_threshold_enabled=True)
        assert RankingEngineService._recommend_action(0.55, None, s) == "buy"
        assert RankingEngineService._recommend_action(0.56, None, s) == "buy"
        assert RankingEngineService._recommend_action(0.66, None, s) == "buy"

    def test_watch_threshold_unchanged(self):
        """watch_threshold (0.45) is not affected by the lower-buy flag."""
        s = _Settings(lower_buy_threshold_enabled=True)
        assert RankingEngineService._recommend_action(0.40, None, s) == "avoid"
        assert RankingEngineService._recommend_action(0.45, None, s) == "watch"

    def test_custom_lower_value_honored(self):
        s = _Settings(lower_buy_threshold_enabled=True,
                      lower_buy_threshold_value=0.60)
        assert RankingEngineService._recommend_action(0.56, None, s) == "watch"
        assert RankingEngineService._recommend_action(0.60, None, s) == "buy"


# ── Rec 8 — _apply_ranking_min_filter conditional relaxation ─────────────────


class TestConditionalRankingMinFlagOff:
    """Flag OFF → strict 0.30 floor for every ticker."""

    def test_below_floor_filtered_out(self):
        s = _Settings()
        st = _AppState()
        rankings = [_Ranking("MSFT", 0.25)]
        assert _apply_ranking_min_filter(rankings, st, s) == []

    def test_at_or_above_floor_kept(self):
        s = _Settings()
        st = _AppState()
        rankings = [_Ranking("MSFT", 0.30), _Ranking("AAPL", 0.50)]
        out = _apply_ranking_min_filter(rankings, st, s)
        assert [r.ticker for r in out] == ["MSFT", "AAPL"]

    def test_held_status_does_not_matter_when_flag_off(self):
        """Even with held + A-grade history, 0.25 must fail when flag is off."""
        s = _Settings()
        st = _AppState(
            portfolio_state=_PortfolioState(positions={"MSFT": object()}),
            trade_grades=[_Grade("MSFT", "A")],
        )
        rankings = [_Ranking("MSFT", 0.25)]
        assert _apply_ranking_min_filter(rankings, st, s) == []


class TestConditionalRankingMinFlagOn:
    """Flag ON → held+A/B tickers use ``ranking_min_held_positive`` (0.20)."""

    def _cfg_on(self, **overrides) -> _Settings:
        return _Settings(conditional_ranking_min_enabled=True, **overrides)

    def test_held_with_a_grade_history_allowed_at_0_25(self):
        s = self._cfg_on()
        st = _AppState(
            portfolio_state=_PortfolioState(positions={"MSFT": object()}),
            trade_grades=[_Grade("MSFT", "A")],
        )
        out = _apply_ranking_min_filter([_Ranking("MSFT", 0.25)], st, s)
        assert [r.ticker for r in out] == ["MSFT"]

    def test_held_with_b_grade_history_allowed_at_0_21(self):
        s = self._cfg_on()
        st = _AppState(
            portfolio_state=_PortfolioState(positions={"NVDA": object()}),
            trade_grades=[_Grade("NVDA", "B")],
        )
        out = _apply_ranking_min_filter([_Ranking("NVDA", 0.21)], st, s)
        assert [r.ticker for r in out] == ["NVDA"]

    def test_held_with_no_positive_history_rejected_at_0_25(self):
        """Held but never had an A/B closed trade → strict floor still applies."""
        s = self._cfg_on()
        st = _AppState(
            portfolio_state=_PortfolioState(positions={"AAPL": object()}),
            trade_grades=[],
        )
        assert _apply_ranking_min_filter([_Ranking("AAPL", 0.25)], st, s) == []

    def test_unheld_ticker_rejected_at_0_25(self):
        """Even with A/B history, unheld tickers fall back to strict 0.30 floor."""
        s = self._cfg_on()
        st = _AppState(
            portfolio_state=_PortfolioState(positions={}),
            trade_grades=[_Grade("TSLA", "A")],
        )
        assert _apply_ranking_min_filter([_Ranking("TSLA", 0.25)], st, s) == []

    def test_held_with_only_d_grade_history_rejected_at_0_25(self):
        """D/F grades don't count as 'positive history'."""
        s = self._cfg_on()
        st = _AppState(
            portfolio_state=_PortfolioState(positions={"META": object()}),
            trade_grades=[_Grade("META", "D"), _Grade("META", "F")],
        )
        assert _apply_ranking_min_filter([_Ranking("META", 0.25)], st, s) == []

    def test_held_with_c_grade_history_rejected_at_0_25(self):
        """C counts as break-even, not positive — stays under strict floor."""
        s = self._cfg_on()
        st = _AppState(
            portfolio_state=_PortfolioState(positions={"GOOG": object()}),
            trade_grades=[_Grade("GOOG", "C")],
        )
        assert _apply_ranking_min_filter([_Ranking("GOOG", 0.25)], st, s) == []

    def test_mixed_history_one_a_grade_sufficient(self):
        """Any A or B grade in history qualifies — even with losses alongside."""
        s = self._cfg_on()
        st = _AppState(
            portfolio_state=_PortfolioState(positions={"AMZN": object()}),
            trade_grades=[_Grade("AMZN", "F"), _Grade("AMZN", "A"),
                          _Grade("AMZN", "D")],
        )
        out = _apply_ranking_min_filter([_Ranking("AMZN", 0.22)], st, s)
        assert [r.ticker for r in out] == ["AMZN"]

    def test_strict_floor_still_applies_to_held_below_loose(self):
        """Held + A-grade does NOT bypass ``ranking_min_held_positive``."""
        s = self._cfg_on()
        st = _AppState(
            portfolio_state=_PortfolioState(positions={"MSFT": object()}),
            trade_grades=[_Grade("MSFT", "A")],
        )
        assert _apply_ranking_min_filter([_Ranking("MSFT", 0.19)], st, s) == []

    def test_mixed_ranking_list_only_right_ones_pass(self):
        """Full integration: 4 tickers, 2 qualify via different paths."""
        s = self._cfg_on()
        st = _AppState(
            portfolio_state=_PortfolioState(
                positions={"MSFT": object(), "NVDA": object()},
            ),
            trade_grades=[_Grade("MSFT", "A")],
        )
        rankings = [
            _Ranking("MSFT", 0.22),   # held+A → loose pass
            _Ranking("NVDA", 0.22),   # held, no A/B → fail (strict 0.30)
            _Ranking("AAPL", 0.45),   # unheld, well above strict → pass
            _Ranking("TSLA", 0.15),   # unheld, below everything → fail
        ]
        out = _apply_ranking_min_filter(rankings, st, s)
        assert [r.ticker for r in out] == ["MSFT", "AAPL"]

    def test_none_composite_score_treated_as_zero(self):
        s = self._cfg_on()
        st = _AppState()
        rankings = [_Ranking("MSFT", None)]  # type: ignore[arg-type]
        assert _apply_ranking_min_filter(rankings, st, s) == []

    def test_missing_portfolio_state_treated_as_no_positions(self):
        """Defensive: app_state with portfolio_state=None must not crash."""
        s = self._cfg_on()
        st = _AppState(portfolio_state=None, trade_grades=[_Grade("MSFT", "A")])
        assert _apply_ranking_min_filter([_Ranking("MSFT", 0.25)], st, s) == []
