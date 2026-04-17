"""Per-family ATR-stop and max-age parameters — Deep-Dive Plan Step 5 Rec 7.

Each strategy family gets its own tuple of (stop_atr_mult, stop_floor_pct,
stop_cap_pct, trailing_atr_mult, trailing_floor_pct, trailing_cap_pct,
max_age_days, activation_pct). Exits use the family bound to the position's
``origin_strategy``; anything missing or unknown falls back to ``"default"``.

The ``"default"`` row is intentionally **wider and longer** than the legacy
``stop_loss_pct=0.07``/``trailing_stop_pct=0.05``/``max_position_age_days=20``
triple so that flipping ``atr_stops_enabled=True`` for an existing portfolio
can never stop out a position earlier than the legacy rule would have.

Design note: only the stop/trail multipliers get clamped by the floor/cap
range — the goal is to keep exits intelligible in percentage terms even when
volatility (ATR/price) is temporarily extreme. Without the floor an ultra-low
vol name would get a 1% stop (too tight, noise trips it); without the cap a
post-earnings blow-up would get a 35% stop (too wide, risk ballooning).

See ``services/risk_engine/service.py::evaluate_exits`` for the call-site.
This module is side-effect-free; importing it is safe.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class FamilyParams:
    """ATR-scaled exit/sizing parameters for a single strategy family."""

    stop_atr_mult: float
    stop_floor_pct: float
    stop_cap_pct: float
    trailing_atr_mult: float
    trailing_floor_pct: float
    trailing_cap_pct: float
    max_age_days: int
    activation_pct: float


# Deep-Dive Plan Step 5 Rec 7 — per review §5.2 table.
# Keys are matched against ``Position.origin_strategy`` (case-insensitive).
FAMILY_PARAMS: dict[str, FamilyParams] = {
    # Momentum — ride winners long, wide stop to tolerate trend noise.
    "momentum": FamilyParams(
        stop_atr_mult=2.5, stop_floor_pct=0.04, stop_cap_pct=0.18,
        trailing_atr_mult=1.5, trailing_floor_pct=0.03, trailing_cap_pct=0.12,
        max_age_days=60, activation_pct=0.05,
    ),
    # Theme alignment — thesis is long-running, mirror momentum's patience.
    "theme_alignment": FamilyParams(
        stop_atr_mult=2.5, stop_floor_pct=0.04, stop_cap_pct=0.18,
        trailing_atr_mult=1.5, trailing_floor_pct=0.03, trailing_cap_pct=0.12,
        max_age_days=60, activation_pct=0.05,
    ),
    # Macro tailwind — thesis can invalidate fast, shorter hold than momentum.
    "macro_tailwind": FamilyParams(
        stop_atr_mult=2.5, stop_floor_pct=0.04, stop_cap_pct=0.18,
        trailing_atr_mult=1.5, trailing_floor_pct=0.03, trailing_cap_pct=0.12,
        max_age_days=20, activation_pct=0.05,
    ),
    # Sentiment — news/flow driven, mean-reverts quickly.  Tighter everything.
    "sentiment": FamilyParams(
        stop_atr_mult=2.0, stop_floor_pct=0.03, stop_cap_pct=0.15,
        trailing_atr_mult=1.0, trailing_floor_pct=0.02, trailing_cap_pct=0.10,
        max_age_days=15, activation_pct=0.04,
    ),
    # Valuation — slowest-moving thesis, widest stop, longest hold.
    "valuation": FamilyParams(
        stop_atr_mult=3.5, stop_floor_pct=0.05, stop_cap_pct=0.25,
        trailing_atr_mult=2.0, trailing_floor_pct=0.04, trailing_cap_pct=0.18,
        max_age_days=90, activation_pct=0.06,
    ),
    # Mean reversion — future family (deferred per Apr-14 review §11),
    # listed here for completeness so the lookup table matches the plan.
    "mean_reversion": FamilyParams(
        stop_atr_mult=1.5, stop_floor_pct=0.02, stop_cap_pct=0.10,
        trailing_atr_mult=1.0, trailing_floor_pct=0.02, trailing_cap_pct=0.08,
        max_age_days=7, activation_pct=0.02,
    ),
    # Default — hit for NULL/unknown origin_strategy.  Slightly wider/longer
    # than legacy (7% stop / 20d / 5% trailing) so migrating live portfolios is
    # safe.  The contract: no previously-open position gets stopped out earlier
    # than it would under legacy rules when atr_stops_enabled flips True.
    "default": FamilyParams(
        stop_atr_mult=2.5, stop_floor_pct=0.04, stop_cap_pct=0.15,
        trailing_atr_mult=1.5, trailing_floor_pct=0.03, trailing_cap_pct=0.10,
        max_age_days=20, activation_pct=0.05,
    ),
}


def resolve_family(origin_strategy: str | None) -> FamilyParams:
    """Return the FamilyParams matching ``origin_strategy`` (case-insensitive).

    Strategy keys produced by the ranking engine use a mix of conventions —
    ``"MomentumStrategy"``, ``"momentum"``, ``"theme-alignment"``, etc.  This
    helper normalises: lowercase, strip trailing ``"strategy"`` suffix, swap
    hyphens/spaces for underscores. Unknown keys fall through to the
    ``"default"`` family.
    """
    if not origin_strategy:
        return FAMILY_PARAMS["default"]
    key = str(origin_strategy).strip().lower()
    key = key.replace("-", "_").replace(" ", "_")
    if key.endswith("strategy"):
        key = key[: -len("strategy")].rstrip("_")
    return FAMILY_PARAMS.get(key, FAMILY_PARAMS["default"])


def compute_atr_stop_pct(family: FamilyParams, atr: float, price: float) -> float:
    """Compute the stop distance as a % of entry price for a given family/ATR/price.

    Falls back to the floor when ATR/price data is missing or zero so the
    caller always gets a usable number.
    """
    if atr is None or price is None or price <= 0 or atr <= 0:
        return family.stop_floor_pct
    raw = family.stop_atr_mult * (float(atr) / float(price))
    return max(family.stop_floor_pct, min(family.stop_cap_pct, raw))


def compute_atr_trailing_pct(family: FamilyParams, atr: float, price: float) -> float:
    """Compute the trailing-stop distance as a % of peak price. Same guards."""
    if atr is None or price is None or price <= 0 or atr <= 0:
        return family.trailing_floor_pct
    raw = family.trailing_atr_mult * (float(atr) / float(price))
    return max(family.trailing_floor_pct, min(family.trailing_cap_pct, raw))


def derive_origin_strategy(contributing_signals: list[dict] | None) -> str | None:
    """Pick the dominant strategy key from a RankedResult's contributing_signals.

    Returns the ``strategy_key`` of the signal with the highest
    ``signal_score × confidence_score`` product.  Returns ``None`` when the
    list is empty or malformed — callers should treat ``None`` as "unknown"
    and let :func:`resolve_family` apply the default.

    Tie-breaking: stable (first-encountered wins), matching the input order
    produced by ``_aggregate_for_security`` which preserves the caller's order.
    """
    if not contributing_signals:
        return None
    best_key: str | None = None
    best_score = -1.0
    for sig in contributing_signals:
        try:
            ss = float(sig.get("signal_score") or 0.0)
            cs = float(sig.get("confidence_score") or 0.0)
            sk = sig.get("strategy_key") or ""
        except (AttributeError, TypeError, ValueError):
            continue
        if not sk:
            continue
        score = ss * cs
        if score > best_score:
            best_score = score
            best_key = str(sk)
    return best_key
