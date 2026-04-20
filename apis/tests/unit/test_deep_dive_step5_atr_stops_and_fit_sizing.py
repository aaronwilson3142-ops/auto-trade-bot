"""Deep-Dive Plan Step 5 regression tests.

Covers three coupled changes:
  - Rec 7: ATR-scaled per-family stops & trailing, per-family max-age,
           via ``services.risk_engine.family_params`` + the new branch in
           ``RiskEngineService.evaluate_exits`` behind ``atr_stops_enabled``.
  - Rec 5: Promotion of ``portfolio_fit_score`` into
           ``PortfolioEngineService.compute_sizing`` behind
           ``portfolio_fit_sizing_enabled``.
  - Shared schema: ``Position.origin_strategy`` column + ``PortfolioPosition``
           field + ``derive_origin_strategy`` helper.

Flag defaults are **OFF**, so the legacy paths must remain byte-for-byte
identical when neither switch is flipped.
"""
from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from services.portfolio_engine.models import PortfolioPosition, PortfolioState
from services.portfolio_engine.service import PortfolioEngineService
from services.ranking_engine.models import RankedResult
from services.risk_engine.family_params import (
    FAMILY_PARAMS,
    compute_atr_stop_pct,
    compute_atr_trailing_pct,
    derive_origin_strategy,
    resolve_family,
)
from services.risk_engine.service import RiskEngineService

_EPS = 1e-6
_NOW = dt.datetime.now(dt.UTC)


# ── FAMILY_PARAMS table + resolver ───────────────────────────────────────────


class TestFamilyParamsTable:

    def test_default_family_present(self):
        assert "default" in FAMILY_PARAMS
        assert FAMILY_PARAMS["default"].max_age_days == 20

    def test_expected_families_present(self):
        for k in ("momentum", "theme_alignment", "macro_tailwind",
                  "sentiment", "valuation", "mean_reversion"):
            assert k in FAMILY_PARAMS

    def test_momentum_wider_than_sentiment(self):
        m = FAMILY_PARAMS["momentum"]
        s = FAMILY_PARAMS["sentiment"]
        assert m.stop_atr_mult > s.stop_atr_mult
        assert m.max_age_days > s.max_age_days

    def test_valuation_longest_hold(self):
        v = FAMILY_PARAMS["valuation"]
        assert v.max_age_days == max(fp.max_age_days for fp in FAMILY_PARAMS.values())


class TestResolveFamily:

    def test_none_falls_back_to_default(self):
        assert resolve_family(None) is FAMILY_PARAMS["default"]

    def test_empty_string_falls_back(self):
        assert resolve_family("") is FAMILY_PARAMS["default"]

    def test_exact_key_match(self):
        assert resolve_family("momentum") is FAMILY_PARAMS["momentum"]

    def test_case_insensitive(self):
        assert resolve_family("MOMENTUM") is FAMILY_PARAMS["momentum"]

    def test_strategy_suffix_stripped(self):
        assert resolve_family("MomentumStrategy") is FAMILY_PARAMS["momentum"]

    def test_hyphen_and_space_normalised(self):
        assert resolve_family("theme-alignment") is FAMILY_PARAMS["theme_alignment"]
        assert resolve_family("theme alignment") is FAMILY_PARAMS["theme_alignment"]

    def test_unknown_falls_back_to_default(self):
        assert resolve_family("not_a_family") is FAMILY_PARAMS["default"]


# ── ATR math ─────────────────────────────────────────────────────────────────


class TestATRComputations:

    def test_stop_within_floor_cap(self):
        f = FAMILY_PARAMS["momentum"]
        # 2.5 * 2.0 / 100 = 0.05 — inside [0.04, 0.18]
        assert abs(compute_atr_stop_pct(f, 2.0, 100.0) - 0.05) < _EPS

    def test_stop_hits_floor(self):
        f = FAMILY_PARAMS["momentum"]
        assert abs(compute_atr_stop_pct(f, 0.1, 100.0) - f.stop_floor_pct) < _EPS

    def test_stop_hits_cap(self):
        f = FAMILY_PARAMS["momentum"]
        assert abs(compute_atr_stop_pct(f, 20.0, 100.0) - f.stop_cap_pct) < _EPS

    def test_stop_missing_atr_returns_floor(self):
        f = FAMILY_PARAMS["momentum"]
        assert compute_atr_stop_pct(f, None, 100.0) == f.stop_floor_pct

    def test_stop_zero_price_returns_floor(self):
        f = FAMILY_PARAMS["momentum"]
        assert compute_atr_stop_pct(f, 2.0, 0.0) == f.stop_floor_pct

    def test_trailing_follows_same_rules(self):
        f = FAMILY_PARAMS["momentum"]
        # 1.5 * 2.0 / 100 = 0.03 — inside [0.03, 0.12]; floor binds
        assert abs(compute_atr_trailing_pct(f, 2.0, 100.0) - 0.03) < _EPS
        assert compute_atr_trailing_pct(f, None, 100.0) == f.trailing_floor_pct


# ── derive_origin_strategy helper ────────────────────────────────────────────


class TestDeriveOriginStrategy:

    def test_empty_or_none_returns_none(self):
        assert derive_origin_strategy(None) is None
        assert derive_origin_strategy([]) is None

    def test_highest_product_wins(self):
        sigs = [
            {"strategy_key": "MomentumStrategy", "signal_score": 0.8, "confidence_score": 0.9},
            {"strategy_key": "ValuationStrategy", "signal_score": 0.9, "confidence_score": 0.5},
        ]
        # 0.8*0.9 = 0.72  vs  0.9*0.5 = 0.45
        assert derive_origin_strategy(sigs) == "MomentumStrategy"

    def test_malformed_entries_skipped(self):
        sigs = [
            {"strategy_key": "MomentumStrategy", "signal_score": "bad", "confidence_score": 0.9},
            {"strategy_key": "ValuationStrategy", "signal_score": 0.6, "confidence_score": 0.6},
        ]
        # MomentumStrategy skipped → Valuation wins
        assert derive_origin_strategy(sigs) == "ValuationStrategy"

    def test_missing_key_skipped(self):
        sigs = [
            {"signal_score": 0.9, "confidence_score": 0.9},  # no strategy_key
            {"strategy_key": "ThemeAlignmentStrategy", "signal_score": 0.3, "confidence_score": 0.3},
        ]
        assert derive_origin_strategy(sigs) == "ThemeAlignmentStrategy"


# ── evaluate_exits behaviour (flag OFF → byte-identical legacy) ──────────────


def _make_position(
    ticker: str,
    unrealized_pct: float,
    opened_days_ago: int = 1,
    current_price: float = 100.0,
    origin_strategy: str = "",
) -> PortfolioPosition:
    """Build a PortfolioPosition with a target unrealized_pnl_pct.

    Uses quantity=1, avg_entry=100, current=100*(1+unrealized_pct).
    """
    avg = Decimal("100")
    cur = Decimal(str(avg * Decimal(str(1 + unrealized_pct))))
    return PortfolioPosition(
        ticker=ticker,
        quantity=Decimal("1"),
        avg_entry_price=avg,
        current_price=cur,
        opened_at=dt.datetime.now(dt.UTC) - dt.timedelta(days=opened_days_ago),
        thesis_summary="",
        strategy_key="",
        security_id=None,
        origin_strategy=origin_strategy,
    )


class _NullLog:
    """No-op logger — absorbs structlog-style kwargs calls."""

    def info(self, *args, **kwargs): pass
    def debug(self, *args, **kwargs): pass
    def warning(self, *args, **kwargs): pass
    def error(self, *args, **kwargs): pass


class _StubSettings:
    """Minimal settings stand-in for RiskEngineService."""

    def __init__(self, atr_on: bool = False):
        self.stop_loss_pct = 0.07
        self.max_position_age_days = 20
        self.exit_score_threshold = 0.30
        self.take_profit_pct = 0.0
        self.trailing_stop_pct = 0.05
        self.trailing_stop_activation_pct = 0.05
        self.atr_stops_enabled = atr_on
        # Risk-engine service pulls many more settings; monkeypatch as needed.
        # For evaluate_exits we only need the above.


class TestEvaluateExitsFlagOff:
    """Default behaviour unchanged when ``atr_stops_enabled`` is False."""

    def _svc(self):
        # Build a RiskEngineService with minimal wiring by monkeypatching.
        svc = object.__new__(RiskEngineService)
        svc._settings = _StubSettings(atr_on=False)
        svc._log = _NullLog()
        return svc

    def test_below_legacy_stop_triggers(self):
        svc = self._svc()
        pos = _make_position("AAA", unrealized_pct=-0.08)  # -8% < -7% legacy
        actions = svc.evaluate_exits({"AAA": pos}, reference_dt=_NOW)
        assert len(actions) == 1
        assert "stop_loss" in actions[0].reason

    def test_above_legacy_stop_holds(self):
        svc = self._svc()
        pos = _make_position("AAA", unrealized_pct=-0.05)  # -5% > -7%
        actions = svc.evaluate_exits({"AAA": pos}, reference_dt=_NOW)
        assert actions == []

    def test_legacy_age_expiry(self):
        svc = self._svc()
        pos = _make_position("AAA", unrealized_pct=0.0, opened_days_ago=25)
        actions = svc.evaluate_exits({"AAA": pos}, reference_dt=_NOW)
        assert len(actions) == 1
        assert "age_expiry" in actions[0].reason


class TestEvaluateExitsFlagOn:
    """ATR-aware per-family exits when ``atr_stops_enabled`` is True."""

    def _svc(self):
        svc = object.__new__(RiskEngineService)
        svc._settings = _StubSettings(atr_on=True)
        svc._log = _NullLog()
        return svc

    def test_null_origin_uses_default_family(self):
        """Null origin → default family (floor 0.04, max_age 20).
        -5% pnl with ATR-derived stop 0.04 (from zero ATR → floor) triggers."""
        svc = self._svc()
        pos = _make_position("AAA", unrealized_pct=-0.05, origin_strategy="")
        # Missing ATR → stop = floor_pct = 0.04 → -5% trips it.
        actions = svc.evaluate_exits({"AAA": pos}, reference_dt=_NOW)
        assert len(actions) == 1
        assert "stop_loss" in actions[0].reason

    def test_valuation_family_has_wider_stop(self):
        """Valuation family has stop_floor_pct=0.05, so -4% does NOT trigger."""
        svc = self._svc()
        pos = _make_position("AAA", unrealized_pct=-0.04,
                             origin_strategy="ValuationStrategy")
        actions = svc.evaluate_exits({"AAA": pos}, reference_dt=_NOW)
        assert actions == []

    def test_sentiment_family_stops_earlier_than_momentum(self):
        """Sentiment floor (0.03) < Momentum floor (0.04). At -3.5% sentiment
        trips, momentum doesn't."""
        svc = self._svc()
        pos_sent = _make_position("SENT", unrealized_pct=-0.035,
                                  origin_strategy="SentimentStrategy")
        pos_mom = _make_position("MOM", unrealized_pct=-0.035,
                                 origin_strategy="MomentumStrategy")
        # ATR unavailable → each uses own floor
        out = svc.evaluate_exits({"SENT": pos_sent, "MOM": pos_mom}, reference_dt=_NOW)
        tickers_triggered = {a.ticker for a in out}
        assert "SENT" in tickers_triggered
        assert "MOM" not in tickers_triggered

    def test_atr_scaling_widens_stop(self):
        """High ATR should widen the stop up to the cap."""
        svc = self._svc()
        # Momentum cap = 0.18 -> at -0.17 we must NOT stop out with atr=20
        pos = _make_position("AAA", unrealized_pct=-0.17, current_price=100.0,
                             origin_strategy="MomentumStrategy")
        actions = svc.evaluate_exits({"AAA": pos}, atr_by_ticker={"AAA": 20.0}, reference_dt=_NOW)
        assert actions == []  # stop is 0.18 (cap), -17% doesn't trip it

    def test_per_family_max_age(self):
        """Momentum family max_age = 60 > legacy 20. 25-day-old position holds."""
        svc = self._svc()
        pos = _make_position("AAA", unrealized_pct=0.0, opened_days_ago=25,
                             origin_strategy="MomentumStrategy")
        actions = svc.evaluate_exits({"AAA": pos}, reference_dt=_NOW)
        assert actions == []

    def test_per_family_max_age_trips(self):
        """Sentiment max_age=15, position held 20 days → expires."""
        svc = self._svc()
        pos = _make_position("AAA", unrealized_pct=0.0, opened_days_ago=20,
                             origin_strategy="SentimentStrategy")
        actions = svc.evaluate_exits({"AAA": pos}, reference_dt=_NOW)
        assert len(actions) == 1
        assert "age_expiry" in actions[0].reason


# ── compute_sizing (Rec 5) ───────────────────────────────────────────────────


def _ranked(ticker: str, composite: float, fit: float | None) -> RankedResult:
    return RankedResult(
        rank_position=1,
        security_id=None,
        ticker=ticker,
        composite_score=Decimal(str(composite)),
        portfolio_fit_score=Decimal(str(fit)) if fit is not None else None,
        recommended_action="buy",
        target_horizon="short",
        thesis_summary="",
        disconfirming_factors="",
        sizing_hint_pct=None,
        source_reliability_tier="verified",
        contains_rumor=False,
        as_of=dt.datetime.now(dt.UTC),
    )


def _portfolio(equity: float = 100_000.0) -> PortfolioState:
    return PortfolioState(cash=Decimal(str(equity)))


class _SizingSettings:
    """Minimal settings stub for compute_sizing."""

    def __init__(self, fit_on: bool = False):
        self.max_single_name_pct = 0.20
        self.portfolio_fit_sizing_enabled = fit_on


class TestComputeSizingFlagOff:

    def test_flag_off_byte_for_byte_legacy(self):
        # Two services, same input, one with fit ON + fit=0.5, one OFF.
        # Flag OFF should not dip below legacy Kelly at all.
        svc_off = PortfolioEngineService(_SizingSettings(fit_on=False))
        r = _ranked("AAA", composite=0.80, fit=0.10)  # very bad fit
        out = svc_off.compute_sizing(r, _portfolio())
        # half-Kelly at p=0.8 = 0.5 * (2*0.8 - 1) = 0.30; cap 0.20 binds
        assert float(out.target_pct) == pytest.approx(0.20, abs=_EPS)
        assert out.capped


class TestComputeSizingFlagOn:

    def test_fit_half_reduces_kelly(self):
        """fit=0.5 cuts Kelly from 0.30 to 0.15 (under the 0.20 cap)."""
        svc = PortfolioEngineService(_SizingSettings(fit_on=True))
        r = _ranked("AAA", composite=0.80, fit=0.50)
        out = svc.compute_sizing(r, _portfolio())
        assert float(out.target_pct) == pytest.approx(0.15, abs=_EPS)
        assert not out.capped

    def test_fit_cap_still_binds_when_kelly_big(self):
        """fit=1.0 leaves Kelly at 0.30; cap 0.20 still binds."""
        svc = PortfolioEngineService(_SizingSettings(fit_on=True))
        r = _ranked("AAA", composite=0.80, fit=1.0)
        out = svc.compute_sizing(r, _portfolio())
        assert float(out.target_pct) == pytest.approx(0.20, abs=_EPS)
        assert out.capped

    def test_fit_none_leaves_kelly_alone(self):
        """Missing fit score → no multiplier applied."""
        svc = PortfolioEngineService(_SizingSettings(fit_on=True))
        r = _ranked("AAA", composite=0.70, fit=None)
        out = svc.compute_sizing(r, _portfolio())
        # half-Kelly at p=0.7 = 0.20, ties cap
        assert float(out.target_pct) == pytest.approx(0.20, abs=_EPS)

    def test_fit_zero_produces_zero(self):
        """fit=0 should zero out the position."""
        svc = PortfolioEngineService(_SizingSettings(fit_on=True))
        r = _ranked("AAA", composite=0.80, fit=0.0)
        out = svc.compute_sizing(r, _portfolio())
        assert float(out.target_pct) == pytest.approx(0.0, abs=_EPS)

    def test_rationale_mentions_fit_only_when_on(self):
        svc_on = PortfolioEngineService(_SizingSettings(fit_on=True))
        out = svc_on.compute_sizing(_ranked("AAA", 0.7, 0.5), _portfolio())
        assert "fit_score" in out.rationale

        svc_off = PortfolioEngineService(_SizingSettings(fit_on=False))
        out2 = svc_off.compute_sizing(_ranked("AAA", 0.7, 0.5), _portfolio())
        assert "fit_score" not in out2.rationale


# ── Settings integration ─────────────────────────────────────────────────────


class TestSettingsIntegration:

    def test_defaults_off(self):
        from config.settings import get_settings
        get_settings.cache_clear()  # type: ignore[attr-defined]
        s = get_settings()
        assert s.atr_stops_enabled is False
        assert s.portfolio_fit_sizing_enabled is False

    def test_flags_settable_via_env(self, monkeypatch):
        from config.settings import Settings
        monkeypatch.setenv("APIS_ATR_STOPS_ENABLED", "true")
        monkeypatch.setenv("APIS_PORTFOLIO_FIT_SIZING_ENABLED", "true")
        s = Settings()
        assert s.atr_stops_enabled is True
        assert s.portfolio_fit_sizing_enabled is True
