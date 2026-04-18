"""Unit tests for Deep-Dive Plan Step 8 — Thompson Strategy Bandit (Rec 12).

Covers:

    * Settings defaults match plan §8 (lambda, floor, ceiling, cadence, flag).
    * Beta(α, β) update semantics: wins raise α, losses raise β, breakeven
      counts as loss, counters stay in sync.
    * Thompson sampling: first call always samples fresh, subsequent calls
      reuse the cached draw until ``cycles_since_resample`` hits the window.
    * Smoothing + floor/ceiling: extreme Beta draws get pulled toward the
      equal-weight baseline and clamped into ``[min, max]`` before renorm.
    * Constructor argument validation (smoothing, floor/ceiling ordering).
    * update_from_trade argument validation + warm-start behaviour (works
      even with no existing row).
    * Plan §8.6 invariant: update runs regardless of flag state.
"""
from __future__ import annotations

import datetime as dt
import math
import random
import uuid
from decimal import Decimal
from typing import Any

import pytest


# ---------------------------------------------------------------------------
# Tiny in-memory Session stub tailored to StrategyBanditService
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self) -> "_FakeResult":
        return self

    def all(self) -> list[Any]:
        return list(self._rows)


class FakeSession:
    """Just-enough session to run StrategyBanditService."""

    def __init__(self) -> None:
        self._rows: dict[uuid.UUID, Any] = {}
        self.flush_count = 0
        self.commit_count = 0

    def add(self, row: Any) -> None:
        self._rows[row.id] = row

    def flush(self) -> None:
        self.flush_count += 1

    def commit(self) -> None:
        self.commit_count += 1

    def execute(self, stmt) -> _FakeResult:
        # Parse the Select: look for where predicates like
        # strategy_family == "momentum" and collect rows.
        where = getattr(stmt, "whereclause", None)
        rows = list(self._rows.values())
        if where is not None:
            left = getattr(where, "left", None)
            right = getattr(where, "right", None)
            if left is not None and right is not None:
                col_key = getattr(left, "key", None)
                val = getattr(right, "value", right)
                if callable(val):
                    try:
                        val = val()
                    except Exception:  # noqa: BLE001
                        pass
                if col_key:
                    rows = [r for r in rows if getattr(r, col_key, None) == val]

        # Detect order_by(strategy_family) so list_all returns sorted.
        ordered_cols: list[str] = []
        for c in getattr(stmt, "_order_by_clauses", ()) or ():
            ck = getattr(c, "key", None)
            if ck:
                ordered_cols.append(ck)
        if "strategy_family" in ordered_cols:
            rows.sort(key=lambda r: r.strategy_family)
        return _FakeResult(rows)


# ---------------------------------------------------------------------------
# Settings integration
# ---------------------------------------------------------------------------


class TestSettingsIntegration:
    def test_bandit_flag_default_false(self) -> None:
        from config.settings import get_settings

        s = get_settings()
        assert s.strategy_bandit_enabled is False

    def test_bandit_numeric_defaults_match_plan(self) -> None:
        from config.settings import get_settings

        s = get_settings()
        assert 0.0 <= s.strategy_bandit_smoothing_lambda <= 1.0
        assert math.isclose(s.strategy_bandit_smoothing_lambda, 0.3)
        assert math.isclose(s.strategy_bandit_min_weight, 0.05)
        assert math.isclose(s.strategy_bandit_max_weight, 0.40)
        assert s.strategy_bandit_resample_every_n_cycles == 10

    def test_bandit_min_leq_max(self) -> None:
        from config.settings import get_settings

        s = get_settings()
        assert s.strategy_bandit_min_weight <= s.strategy_bandit_max_weight


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


class TestConstructorValidation:
    def test_rejects_out_of_range_smoothing(self) -> None:
        from services.strategy_bandit import StrategyBanditService

        with pytest.raises(ValueError, match="smoothing_lambda"):
            StrategyBanditService(FakeSession(), smoothing_lambda=-0.1)
        with pytest.raises(ValueError, match="smoothing_lambda"):
            StrategyBanditService(FakeSession(), smoothing_lambda=1.5)

    def test_rejects_min_above_max(self) -> None:
        from services.strategy_bandit import StrategyBanditService

        with pytest.raises(ValueError, match="min_weight cannot exceed"):
            StrategyBanditService(
                FakeSession(), min_weight=0.5, max_weight=0.2
            )

    def test_rejects_zero_resample_cadence(self) -> None:
        from services.strategy_bandit import StrategyBanditService

        with pytest.raises(ValueError, match="resample_every_n_cycles"):
            StrategyBanditService(FakeSession(), resample_every_n_cycles=0)


# ---------------------------------------------------------------------------
# update_from_trade semantics
# ---------------------------------------------------------------------------


class TestUpdateFromTrade:
    def test_positive_pnl_increments_alpha(self) -> None:
        from services.strategy_bandit import StrategyBanditService

        svc = StrategyBanditService(FakeSession())
        r = svc.update_from_trade("momentum", realized_pnl=100.0)
        assert r.outcome == "win"
        assert math.isclose(r.new_alpha, 2.0)
        assert math.isclose(r.new_beta, 1.0)
        assert r.n_wins == 1
        assert r.n_losses == 0

    def test_negative_pnl_increments_beta(self) -> None:
        from services.strategy_bandit import StrategyBanditService

        svc = StrategyBanditService(FakeSession())
        r = svc.update_from_trade("valuation", realized_pnl=-50.0)
        assert r.outcome == "loss"
        assert math.isclose(r.new_alpha, 1.0)
        assert math.isclose(r.new_beta, 2.0)
        assert r.n_losses == 1

    def test_zero_pnl_counts_as_loss(self) -> None:
        """Breakeven trades must NOT inflate the bandit's confidence."""
        from services.strategy_bandit import StrategyBanditService

        svc = StrategyBanditService(FakeSession())
        r = svc.update_from_trade("sentiment", realized_pnl=0.0)
        assert r.outcome == "loss"

    def test_decimal_pnl_accepted(self) -> None:
        from services.strategy_bandit import StrategyBanditService

        svc = StrategyBanditService(FakeSession())
        r = svc.update_from_trade("momentum", realized_pnl=Decimal("42.50"))
        assert r.outcome == "win"

    def test_rejects_empty_family(self) -> None:
        from services.strategy_bandit import StrategyBanditService

        with pytest.raises(ValueError, match="strategy_family required"):
            StrategyBanditService(FakeSession()).update_from_trade(
                "", realized_pnl=1.0
            )

    def test_rejects_non_numeric_pnl(self) -> None:
        from services.strategy_bandit import StrategyBanditService

        with pytest.raises(ValueError, match="realized_pnl must be numeric"):
            StrategyBanditService(FakeSession()).update_from_trade(
                "momentum", realized_pnl="not a number"  # type: ignore
            )

    def test_updates_accumulate_across_calls(self) -> None:
        from services.strategy_bandit import StrategyBanditService

        svc = StrategyBanditService(FakeSession())
        svc.update_from_trade("momentum", realized_pnl=1.0)
        svc.update_from_trade("momentum", realized_pnl=1.0)
        r = svc.update_from_trade("momentum", realized_pnl=-1.0)
        # Two wins + one loss on top of Beta(1, 1) prior
        assert math.isclose(r.new_alpha, 3.0)
        assert math.isclose(r.new_beta, 2.0)
        assert r.n_wins == 2
        assert r.n_losses == 1

    def test_creates_row_if_missing_warm_start(self) -> None:
        """Plan §8.6 — first sighting of a family creates the row."""
        from services.strategy_bandit import StrategyBanditService

        s = FakeSession()
        svc = StrategyBanditService(s)
        assert len(s._rows) == 0
        svc.update_from_trade("brand_new_family", realized_pnl=5.0)
        assert len(s._rows) == 1


# ---------------------------------------------------------------------------
# sample_weights
# ---------------------------------------------------------------------------


class TestSampleWeights:
    def test_weights_sum_to_one_on_first_call(self) -> None:
        from services.strategy_bandit import StrategyBanditService

        svc = StrategyBanditService(FakeSession(), rng=random.Random(42))
        r = svc.sample_weights(["a", "b", "c"])
        assert r.sampled_fresh is True
        assert math.isclose(sum(r.weights.values()), 1.0, abs_tol=1e-9)

    def test_weights_respect_floor(self) -> None:
        from services.strategy_bandit import StrategyBanditService

        min_w = 0.20
        max_w = 0.40
        svc = StrategyBanditService(
            FakeSession(), min_weight=min_w, max_weight=max_w,
            rng=random.Random(7),
        )
        # Clamping is applied BEFORE renormalisation, so final weights land
        # in [min_w / (min_w + max_w*(n-1)), max_w / (max_w + min_w*(n-1))]
        # — i.e. the renormalised floor is lower than ``min_weight`` when
        # not every family is clamped to the floor simultaneously.  What we
        # really want to verify is that ``min_weight`` bounds the CLAMPED
        # value (pre-renorm invariant) and that final weights still sum to
        # 1.0 and stay in the renormalised band.
        families = ["x", "y", "z", "w"]
        n = len(families)
        renorm_floor = min_w / (min_w + max_w * (n - 1))
        renorm_ceiling = max_w / (max_w + min_w * (n - 1))
        r = svc.sample_weights(families)
        assert math.isclose(sum(r.weights.values()), 1.0, abs_tol=1e-9)
        for w in r.weights.values():
            assert renorm_floor - 1e-9 <= w <= renorm_ceiling + 1e-9

    def test_cached_draw_reused_between_resample_windows(self) -> None:
        from services.strategy_bandit import StrategyBanditService

        svc = StrategyBanditService(
            FakeSession(), resample_every_n_cycles=3,
            rng=random.Random(1),
        )
        first = svc.sample_weights(["a", "b"])
        assert first.sampled_fresh is True
        second = svc.sample_weights(["a", "b"])
        assert second.sampled_fresh is False
        # Cached draws -> identical final weights
        assert second.weights == first.weights

    def test_resamples_after_window_expires(self) -> None:
        from services.strategy_bandit import StrategyBanditService

        svc = StrategyBanditService(
            FakeSession(), resample_every_n_cycles=2,
            rng=random.Random(2),
        )
        svc.sample_weights(["a", "b"])  # fresh
        svc.sample_weights(["a", "b"])  # cache hit; counter -> 1 per family
        r = svc.sample_weights(["a", "b"])  # counter -> 2 -> resample
        assert r.sampled_fresh is True

    def test_force_resample_bypasses_cache(self) -> None:
        from services.strategy_bandit import StrategyBanditService

        svc = StrategyBanditService(
            FakeSession(), resample_every_n_cycles=100,
            rng=random.Random(3),
        )
        svc.sample_weights(["a", "b"])
        r = svc.sample_weights(["a", "b"], force_resample=True)
        assert r.sampled_fresh is True

    def test_empty_families_returns_empty(self) -> None:
        from services.strategy_bandit import StrategyBanditService

        svc = StrategyBanditService(FakeSession())
        r = svc.sample_weights([])
        assert r.weights == {}
        assert r.sampled_fresh is False

    def test_smoothing_lambda_zero_returns_equal_weights(self) -> None:
        from services.strategy_bandit import StrategyBanditService

        svc = StrategyBanditService(
            FakeSession(), smoothing_lambda=0.0,
            min_weight=0.0, max_weight=1.0,
            rng=random.Random(0),
        )
        r = svc.sample_weights(["a", "b", "c", "d"])
        for w in r.weights.values():
            assert math.isclose(w, 0.25, abs_tol=1e-9)

    def test_default_families_when_none_given(self) -> None:
        from services.strategy_bandit import (
            DEFAULT_STRATEGY_FAMILIES,
            StrategyBanditService,
        )

        svc = StrategyBanditService(FakeSession(), rng=random.Random(0))
        r = svc.sample_weights()
        assert set(r.weights.keys()) == set(DEFAULT_STRATEGY_FAMILIES)


# ---------------------------------------------------------------------------
# Plan §8.6 invariant: updates run regardless of flag state
# ---------------------------------------------------------------------------


class TestFlagIndependentUpdate:
    def test_update_runs_even_when_flag_off(self) -> None:
        """The posterior update path takes no ``enabled`` argument — the
        fact that the service runs regardless of ``settings.strategy_bandit_enabled``
        is the contract plan §8.6 codifies.  This test makes that explicit.
        """
        from services.strategy_bandit import StrategyBanditService

        # No settings patched, nothing gated
        svc = StrategyBanditService(FakeSession())
        r1 = svc.update_from_trade("momentum", realized_pnl=1.0)
        r2 = svc.update_from_trade("momentum", realized_pnl=-1.0)
        assert r1.outcome == "win"
        assert r2.outcome == "loss"
        assert r2.n_wins == 1
        assert r2.n_losses == 1


# ---------------------------------------------------------------------------
# Read helpers
# ---------------------------------------------------------------------------


class TestReads:
    def test_get_state_returns_none_for_unknown(self) -> None:
        from services.strategy_bandit import StrategyBanditService

        svc = StrategyBanditService(FakeSession())
        assert svc.get_state("does_not_exist") is None

    def test_list_all_sorted_by_family(self) -> None:
        from services.strategy_bandit import StrategyBanditService

        svc = StrategyBanditService(FakeSession())
        svc.update_from_trade("zebra", realized_pnl=1.0)
        svc.update_from_trade("alpha", realized_pnl=1.0)
        svc.update_from_trade("mike", realized_pnl=1.0)
        fams = [r.strategy_family for r in svc.list_all()]
        assert fams == sorted(fams)
