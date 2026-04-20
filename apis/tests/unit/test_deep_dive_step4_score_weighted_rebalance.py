"""Deep-Dive Plan Step 4 — Score-Weighted Rebalance Allocator regression tests.

Covers the three allocation modes in ``services/rebalancing_engine/allocator.py``:
  - equal             (legacy 1/N, default behaviour)
  - score             (weights proportional to composite score)
  - score_invvol      (weights proportional to score / volatility_20d)

Also covers the two guardrails — ``min_floor_fraction`` and
``max_single_weight`` — plus the master-kill switch ``enabled=False``.

Legacy default (method="equal", enabled=False) must remain byte-for-byte
equivalent to the pre-Step-4 ``RebalancingService.compute_target_weights``.
"""
from __future__ import annotations

from services.rebalancing_engine import RebalanceAllocator, compute_weights
from services.risk_engine.rebalancing import RebalancingService

_EPS = 1e-6


# ── Equal mode (legacy path) ─────────────────────────────────────────────────


class TestEqualModeBackwardsCompat:

    def test_equal_default_path_matches_legacy(self):
        tickers = ["A", "B", "C", "D"]
        r = compute_weights(tickers, n_positions=4)
        legacy = RebalancingService.compute_target_weights(tickers, 4)
        assert r.weights == legacy
        assert r.method_used == "equal"

    def test_top_n_truncation(self):
        """When ranked > n_positions, only first N are allocated."""
        r = compute_weights(["A", "B", "C", "D", "E"], n_positions=3)
        assert set(r.weights) == {"A", "B", "C"}
        assert all(abs(w - 1/3) < _EPS for w in r.weights.values())

    def test_empty_input_returns_empty(self):
        r = compute_weights([], n_positions=3)
        assert r.weights == {}

    def test_zero_n_positions_returns_empty(self):
        r = compute_weights(["A", "B"], n_positions=0)
        assert r.weights == {}

    def test_enabled_false_with_score_method_stays_equal(self):
        r = compute_weights(
            ["A", "B", "C"], n_positions=3,
            method="score", enabled=False,
            scores={"A": 0.9, "B": 0.5, "C": 0.1},
        )
        assert r.method_used == "equal"
        assert all(abs(w - 1/3) < _EPS for w in r.weights.values())


# ── Score mode ───────────────────────────────────────────────────────────────


class TestScoreMode:

    def test_score_proportional(self):
        r = compute_weights(
            ["A", "B", "C"], n_positions=3,
            method="score", enabled=True,
            scores={"A": 0.9, "B": 0.5, "C": 0.3},
            min_floor_fraction=0.0, max_single_weight=1.0,
        )
        total = 0.9 + 0.5 + 0.3
        assert abs(r.weights["A"] - 0.9 / total) < _EPS
        assert abs(r.weights["B"] - 0.5 / total) < _EPS
        assert abs(r.weights["C"] - 0.3 / total) < _EPS
        assert r.method_used == "score"

    def test_weights_sum_to_one(self):
        r = compute_weights(
            ["A", "B", "C", "D"], n_positions=4,
            method="score", enabled=True,
            scores={"A": 0.8, "B": 0.6, "C": 0.4, "D": 0.2},
        )
        assert abs(sum(r.weights.values()) - 1.0) < _EPS

    def test_higher_score_gets_higher_weight(self):
        r = compute_weights(
            ["HIGH", "LOW"], n_positions=2,
            method="score", enabled=True,
            scores={"HIGH": 0.9, "LOW": 0.2},
            min_floor_fraction=0.0, max_single_weight=1.0,
        )
        assert r.weights["HIGH"] > r.weights["LOW"]

    def test_all_zero_scores_falls_back_to_equal(self):
        r = compute_weights(
            ["A", "B"], n_positions=2,
            method="score", enabled=True,
            scores={"A": 0.0, "B": 0.0},
        )
        assert r.method_used == "equal"
        assert r.fell_back_to_equal is True

    def test_missing_scores_treated_as_zero(self):
        """Tickers with no score entry get weight 0 (actually EPS) then floor."""
        r = compute_weights(
            ["A", "B"], n_positions=2,
            method="score", enabled=True,
            scores={"A": 0.9},  # B has no score
            min_floor_fraction=0.0, max_single_weight=1.0,
        )
        # A should dominate
        assert r.weights["A"] > 0.9
        assert r.weights["B"] < 0.1


# ── Score-invvol mode ────────────────────────────────────────────────────────


class TestScoreInvVolMode:

    def test_invvol_lower_vol_gets_more_weight(self):
        """Same score but LOW has half the volatility → LOW gets ~2x weight."""
        r = compute_weights(
            ["HIGH_VOL", "LOW_VOL"], n_positions=2,
            method="score_invvol", enabled=True,
            scores={"HIGH_VOL": 0.6, "LOW_VOL": 0.6},
            volatilities={"HIGH_VOL": 0.40, "LOW_VOL": 0.20},
            min_floor_fraction=0.0, max_single_weight=1.0,
        )
        assert r.weights["LOW_VOL"] > r.weights["HIGH_VOL"]
        # LOW gets 2x the raw weight → ~2/3 of total, HIGH → 1/3
        assert abs(r.weights["LOW_VOL"] - 2/3) < 0.01
        assert abs(r.weights["HIGH_VOL"] - 1/3) < 0.01

    def test_invvol_missing_volatility_falls_back_to_score(self):
        """Ticker w/o volatility entry still gets score-only weight, not zero."""
        r = compute_weights(
            ["A", "B"], n_positions=2,
            method="score_invvol", enabled=True,
            scores={"A": 0.6, "B": 0.6},
            volatilities={"A": 0.20},  # B missing
            min_floor_fraction=0.0, max_single_weight=1.0,
        )
        assert r.weights["A"] > 0
        assert r.weights["B"] > 0
        # A uses 0.6/0.20 = 3.0; B uses 0.6 (fallback) → A >> B
        assert r.weights["A"] > r.weights["B"]

    def test_invvol_zero_volatility_falls_back_to_score(self):
        r = compute_weights(
            ["A", "B"], n_positions=2,
            method="score_invvol", enabled=True,
            scores={"A": 0.6, "B": 0.6},
            volatilities={"A": 0.0, "B": 0.20},  # A has zero vol → fallback
            min_floor_fraction=0.0, max_single_weight=1.0,
        )
        # A is treated as score-only (0.6), B is score_invvol (3.0) → B much larger
        assert r.weights["B"] > r.weights["A"]


# ── Guardrails ───────────────────────────────────────────────────────────────


class TestMinFloorFraction:

    def test_floor_lifts_tiny_weights_up(self):
        """Floor=0.5 means each ticker gets at least 0.5 * (1/N) = 0.5/3 ≈ 0.167."""
        r = compute_weights(
            ["A", "B", "C"], n_positions=3,
            method="score", enabled=True,
            scores={"A": 0.95, "B": 0.03, "C": 0.02},
            min_floor_fraction=0.5, max_single_weight=1.0,
        )
        # Without floor, B/C would be near-zero; with floor they get >= 0.5/3
        min_expected = 0.5 / 3
        assert r.weights["B"] >= min_expected - _EPS
        assert r.weights["C"] >= min_expected - _EPS
        assert r.floor_applied_count >= 2

    def test_floor_zero_leaves_distribution_unchanged(self):
        r_no_floor = compute_weights(
            ["A", "B"], n_positions=2, method="score", enabled=True,
            scores={"A": 0.8, "B": 0.2},
            min_floor_fraction=0.0, max_single_weight=1.0,
        )
        r_with_floor = compute_weights(
            ["A", "B"], n_positions=2, method="score", enabled=True,
            scores={"A": 0.8, "B": 0.2},
            min_floor_fraction=0.0, max_single_weight=1.0,
        )
        assert r_no_floor.weights == r_with_floor.weights


class TestMaxSingleWeight:

    def test_cap_caps_top_weight(self):
        r = compute_weights(
            ["A", "B", "C"], n_positions=3,
            method="score", enabled=True,
            scores={"A": 0.9, "B": 0.05, "C": 0.05},
            max_single_weight=0.5, min_floor_fraction=0.0,
        )
        assert r.weights["A"] <= 0.5 + _EPS
        assert r.cap_applied_count >= 1
        assert abs(sum(r.weights.values()) - 1.0) < _EPS

    def test_cap_redistributes_overflow_proportionally(self):
        """B and C absorb A's overflow in proportion to their original weights."""
        r = compute_weights(
            ["A", "B", "C"], n_positions=3,
            method="score", enabled=True,
            scores={"A": 0.8, "B": 0.15, "C": 0.05},
            max_single_weight=0.5, min_floor_fraction=0.0,
        )
        # A capped at 0.5; remaining 0.5 distributed between B and C
        # in ratio 0.15 : 0.05 = 3:1 → B gets 0.375, C gets 0.125
        assert abs(r.weights["A"] - 0.5) < _EPS
        total_bc = r.weights["B"] + r.weights["C"]
        assert abs(total_bc - 0.5) < _EPS
        assert r.weights["B"] > r.weights["C"]

    def test_cap_one_leaves_weights_unchanged(self):
        r = compute_weights(
            ["A", "B"], n_positions=2, method="score", enabled=True,
            scores={"A": 0.8, "B": 0.2},
            max_single_weight=1.0, min_floor_fraction=0.0,
        )
        assert r.cap_applied_count == 0


# ── Class-wrapper API parity ─────────────────────────────────────────────────


class TestClassWrapperParity:

    def test_wrapper_returns_same_weights_as_function(self):
        kwargs = dict(
            ranked_tickers=["A", "B", "C"],
            n_positions=3,
            method="score",
            enabled=True,
            scores={"A": 0.9, "B": 0.5, "C": 0.3},
            min_floor_fraction=0.0,
            max_single_weight=1.0,
        )
        fn_result = compute_weights(**kwargs)  # type: ignore[arg-type]
        cls_result = RebalanceAllocator.compute_target_weights(**kwargs)  # type: ignore[arg-type]
        assert fn_result.weights == cls_result


# ── Unknown method fallback ──────────────────────────────────────────────────


class TestUnknownMethod:

    def test_unknown_method_falls_back_to_equal(self):
        r = compute_weights(
            ["A", "B"], n_positions=2,
            method="softmax_temperature_tuned",  # nonsense
            enabled=True,
            scores={"A": 0.9, "B": 0.1},
        )
        assert r.method_used == "equal"
        assert r.fell_back_to_equal is True
        assert r.reason.startswith("unknown_method:")


# ── Integration: settings loader picks up the new fields ─────────────────────


class TestSettingsIntegration:

    def test_settings_defaults(self):
        from config.settings import get_settings
        s = get_settings()
        assert s.rebalance_weighting_method == "equal"
        assert s.score_weighted_rebalance_enabled is False
        assert 0.0 <= s.rebalance_min_weight_floor_fraction <= 1.0
        assert 0.0 <= s.rebalance_max_single_weight <= 1.0

    def test_invalid_method_string_falls_back_via_validator(self):
        """Settings validator normalises garbage strings to 'equal'."""
        from config.settings import Settings
        s = Settings(rebalance_weighting_method="not_a_real_method")
        assert s.rebalance_weighting_method == "equal"

    def test_valid_method_strings_accepted(self):
        from config.settings import Settings
        for m in ("equal", "score", "score_invvol"):
            s = Settings(rebalance_weighting_method=m)
            assert s.rebalance_weighting_method == m
