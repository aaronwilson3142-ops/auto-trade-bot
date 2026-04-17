"""Score-weighted rebalance allocator — Deep-Dive Plan Step 4 (Rec 6).

Three allocation modes, selectable via ``settings.rebalance_weighting_method``:

- ``equal``          — 1/N across the top-N ranked tickers (legacy behaviour).
- ``score``          — weights proportional to each ticker's composite score.
- ``score_invvol``   — weights proportional to composite_score / volatility_20d
                       (risk-parity adjacent). Falls back to ``score`` for any
                       ticker missing volatility data.

Every non-``equal`` path honours two guardrails so that lower-ranked tickers
can't collapse to zero and so that a single high-score ticker can't eat the
whole portfolio:

- ``rebalance_min_weight_floor_fraction`` — every kept ticker gets at least
  this fraction of the equal-weight allocation before any normalisation.
- ``rebalance_max_single_weight`` — post-normalisation cap on a single ticker,
  with the overflow redistributed proportionally to the remaining tickers.

The master kill-switch ``score_weighted_rebalance_enabled`` gates the whole
module: when False, ``compute_weights`` returns the equal-weight allocation
regardless of the method string. This belt-and-suspenders design lets the
operator kill the behaviour with a single env flag even if the method string
was changed elsewhere.

No DB writes — pure function style. Inputs/outputs match the shape of
``RebalancingService.compute_target_weights`` so the worker job can swap
one for the other without changing the downstream drift computation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping


# ── Tunable defaults (used when no settings object is supplied) ───────────────


_DEFAULT_MIN_FLOOR_FRAC: float = 0.10
_DEFAULT_MAX_SINGLE: float = 0.20
_EPS: float = 1e-9


# ── Result dataclass ─────────────────────────────────────────────────────────


@dataclass
class AllocationResult:
    """Output of :func:`compute_weights` — target weights + diagnostics."""

    weights: dict[str, float]
    method_used: str
    tickers_considered: int
    floor_applied_count: int = 0
    cap_applied_count: int = 0
    fell_back_to_equal: bool = False
    reason: str = ""
    per_ticker_raw: dict[str, float] = field(default_factory=dict)


# ── Pure-function API ─────────────────────────────────────────────────────────


def compute_weights(
    ranked_tickers: list[str],
    n_positions: int,
    *,
    method: str = "equal",
    enabled: bool = False,
    scores: Mapping[str, float] | None = None,
    volatilities: Mapping[str, float] | None = None,
    min_floor_fraction: float = _DEFAULT_MIN_FLOOR_FRAC,
    max_single_weight: float = _DEFAULT_MAX_SINGLE,
) -> AllocationResult:
    """Compute target weights for the top-N ranked tickers.

    Args:
        ranked_tickers: ordered list (best first) of tickers from ranking engine.
        n_positions: max number of positions (typically ``settings.max_positions``).
        method: one of ``equal`` / ``score`` / ``score_invvol``.
        enabled: master OFF switch. When False, behaves as if method=``equal``.
        scores: ticker → composite_score (0.0–1.0). Required for non-``equal``.
        volatilities: ticker → annualised volatility_20d (0.0–∞). Required for
            ``score_invvol``; tickers missing from the dict fall back to their
            score-only weight.
        min_floor_fraction: every kept ticker gets at least
            ``min_floor_fraction * equal_weight`` before normalisation (0–1).
        max_single_weight: post-normalisation cap per ticker (0–1).

    Returns:
        AllocationResult with per-ticker weights summing to ~1.0 and diagnostics.
        Empty ``weights`` dict when ``ranked_tickers`` is empty or ``n_positions``
        is non-positive.
    """
    if not ranked_tickers or n_positions < 1:
        return AllocationResult(
            weights={}, method_used="equal", tickers_considered=0,
            reason="empty_input",
        )

    top = ranked_tickers[:n_positions]
    n = len(top)
    equal_w = 1.0 / n

    # Master kill-switch: any "off" state collapses to equal weighting.
    if not enabled or method == "equal":
        return AllocationResult(
            weights={t: equal_w for t in top},
            method_used="equal",
            tickers_considered=n,
            reason="kill_switch_off" if (not enabled and method != "equal") else "",
        )

    if method not in ("score", "score_invvol"):
        return AllocationResult(
            weights={t: equal_w for t in top},
            method_used="equal",
            tickers_considered=n,
            fell_back_to_equal=True,
            reason=f"unknown_method:{method}",
        )

    scores = scores or {}
    volatilities = volatilities or {}

    # Compute raw per-ticker weights (before floor/cap/normalisation).
    raw: dict[str, float] = {}
    positive_count = 0
    for t in top:
        s = float(scores.get(t) or 0.0)
        if s <= 0.0:
            raw[t] = _EPS  # non-zero so floor logic engages
            continue
        positive_count += 1
        if method == "score_invvol":
            v = volatilities.get(t)
            if v is None or float(v) <= 0.0:
                raw[t] = s  # fall back to score-only for this ticker
            else:
                raw[t] = s / float(v)
        else:  # "score"
            raw[t] = s

    if positive_count == 0:
        # No positive scores — cannot meaningfully differentiate; use equal.
        return AllocationResult(
            weights={t: equal_w for t in top},
            method_used="equal",
            tickers_considered=n,
            fell_back_to_equal=True,
            reason="all_scores_zero",
            per_ticker_raw=raw,
        )

    total_raw = sum(raw.values())
    # Normalise raw weights to sum to 1.
    normalised = {t: (w / total_raw) for t, w in raw.items()}

    # Apply minimum floor: every ticker gets at least floor_fraction * equal_w.
    # Floor is enforced exactly by reducing over-floor tickers proportionally
    # rather than renormalising uniformly (which would violate the floor).
    min_w = max(0.0, min_floor_fraction) * equal_w
    # Clamp min_w so n*min_w <= 1.0 (cannot floor beyond full budget).
    if min_w * n > 1.0:
        min_w = 1.0 / n  # collapses to equal
    below = {t for t, w in normalised.items() if w < min_w}
    floor_applied = len(below)
    if below and min_w > 0.0:
        budget_remaining = 1.0 - min_w * len(below)
        above = {t: normalised[t] for t in normalised if t not in below}
        above_sum = sum(above.values())
        floored = {}
        for t in normalised:
            if t in below:
                floored[t] = min_w
            else:
                if above_sum > _EPS:
                    floored[t] = budget_remaining * (normalised[t] / above_sum)
                else:
                    # Degenerate: everyone was below. Equal split of budget.
                    floored[t] = budget_remaining / max(1, len(above))
    else:
        floored = dict(normalised)

    # Apply max cap with overflow redistribution.
    cap = max(0.0, min(1.0, max_single_weight))
    capped, cap_applied = _apply_cap_with_redistribution(floored, cap)

    return AllocationResult(
        weights=capped,
        method_used=method,
        tickers_considered=n,
        floor_applied_count=floor_applied,
        cap_applied_count=cap_applied,
        fell_back_to_equal=False,
        per_ticker_raw=raw,
    )


# ── Internal helpers ─────────────────────────────────────────────────────────


def _apply_cap_with_redistribution(
    weights: dict[str, float],
    cap: float,
    max_iterations: int = 10,
) -> tuple[dict[str, float], int]:
    """Cap individual weights at ``cap``, redistributing overflow proportionally.

    Repeats until either no cap fires or ``max_iterations`` reached. The
    fixed-point converges in O(N) iterations in practice; the iteration cap
    just prevents pathological loops on degenerate inputs.
    """
    if cap >= 1.0 or not weights:
        return dict(weights), 0

    current = dict(weights)
    total_cap_events = 0
    for _ in range(max_iterations):
        over = {t: w for t, w in current.items() if w > cap + _EPS}
        if not over:
            break
        total_cap_events += len(over)
        overflow = sum(w - cap for w in over.values())
        # Lock over-cap tickers AT cap; distribute overflow among the rest.
        under = {t: w for t, w in current.items() if w <= cap + _EPS}
        under_sum = sum(under.values())
        if under_sum <= _EPS:
            # Everyone is at cap → scale proportionally (degenerate case).
            break
        new_current: dict[str, float] = {}
        for t in current:
            if t in over:
                new_current[t] = cap
            else:
                share = current[t] / under_sum
                new_current[t] = current[t] + overflow * share
        current = new_current
    return current, total_cap_events


# ── Class wrapper (matches the RebalancingService style) ─────────────────────


class RebalanceAllocator:
    """Class-style entry point mirroring ``RebalancingService.compute_target_weights``.

    The class form is provided for call-site symmetry with the existing
    ``services/risk_engine/rebalancing.py::RebalancingService`` so tests and
    workers can mock it if needed. Stateless — all logic lives in
    :func:`compute_weights`.
    """

    @staticmethod
    def compute_target_weights(
        ranked_tickers: list[str],
        n_positions: int,
        *,
        method: str = "equal",
        enabled: bool = False,
        scores: Mapping[str, float] | None = None,
        volatilities: Mapping[str, float] | None = None,
        min_floor_fraction: float = _DEFAULT_MIN_FLOOR_FRAC,
        max_single_weight: float = _DEFAULT_MAX_SINGLE,
    ) -> dict[str, float]:
        """Convenience wrapper returning just the weights dict."""
        return compute_weights(
            ranked_tickers,
            n_positions,
            method=method,
            enabled=enabled,
            scores=scores,
            volatilities=volatilities,
            min_floor_fraction=min_floor_fraction,
            max_single_weight=max_single_weight,
        ).weights
