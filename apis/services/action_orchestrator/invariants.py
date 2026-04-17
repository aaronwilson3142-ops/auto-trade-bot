"""Action-conflict detector (Deep-Dive Plan Step 2, Rec 3).

Guards against Phase-65-class bugs where two independent action sources
emit opposing actions for the same ticker in the same cycle:

* Portfolio engine emits ``CLOSE`` for a ticker dropped from the buy set
* Rebalancer independently emits ``OPEN`` for the same ticker because
  its target weight drifted

Before this detector existed the two lists were concatenated and both
orders submitted, producing an open→close→open churn loop visible as
"alternating position flap" in the paper cycle log.  Phase 65 landed a
bandaid (CLOSE-suppression when ``rebalance_targets`` is populated) but
did not catch the general case of conflict between any two sources.

Strategy
--------
Rather than hard-raising on conflict (which would stall the whole cycle),
the orchestrator *resolves* each conflict pair and logs it.  Resolution
rule: keep the action with higher ``ranked_result.composite_score`` when
available, else keep OPEN over CLOSE (bias toward trading), else keep
the first.  A webhook-level alert is emitted so operator can audit.

Feature flag
------------
``APIS_ACTION_CONFLICT_DETECTOR_ENABLED`` (default ON).  Disable only to
reproduce pre-Step-2 behavior for debugging.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config.logging_config import get_logger

logger = get_logger(__name__)

# Action types considered opposing.  Uses .value for robustness with the
# ActionType Enum in services.portfolio_engine.models.
_OPPOSING_PAIRS = {
    frozenset({"open", "close"}),
}


def _action_type_str(action: Any) -> str:
    """Return lowercase string form of an action's action_type."""
    at = getattr(action, "action_type", None)
    if at is None:
        return ""
    # Enum .value preferred; fall back to str(at)
    val = getattr(at, "value", None)
    return str(val if val is not None else at).lower()


def _composite_score(action: Any) -> float:
    """Extract composite_score from action.ranked_result, default 0.0."""
    rr = getattr(action, "ranked_result", None)
    if rr is None:
        return 0.0
    cs = getattr(rr, "composite_score", None)
    try:
        return float(cs) if cs is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


@dataclass
class ActionConflict:
    """A single pair of opposing actions for the same ticker."""

    ticker: str
    kept_action_type: str
    dropped_action_type: str
    kept_score: float
    dropped_score: float
    resolution_reason: str


@dataclass
class ActionConflictReport:
    """Result of running the conflict detector across an action list."""

    conflicts: list[ActionConflict] = field(default_factory=list)
    resolved_actions: list[Any] = field(default_factory=list)

    @property
    def had_conflicts(self) -> bool:
        return bool(self.conflicts)


def _find_conflict_pairs(
    actions: list[Any],
) -> list[tuple[int, int]]:
    """Return list of (lo_idx, hi_idx) pairs of opposing actions.

    Within one ticker, if multiple opposing pairs exist we collapse them
    into a series of pairwise comparisons (rare in practice: a single
    cycle usually produces at most one OPEN and one CLOSE per ticker).
    """
    by_ticker: dict[str, list[int]] = {}
    for i, a in enumerate(actions):
        by_ticker.setdefault(getattr(a, "ticker", ""), []).append(i)

    pairs: list[tuple[int, int]] = []
    for ticker, idxs in by_ticker.items():
        if len(idxs) < 2 or not ticker:
            continue
        # Compare every pair within this ticker for an opposing type
        for i_a in range(len(idxs)):
            for i_b in range(i_a + 1, len(idxs)):
                ia, ib = idxs[i_a], idxs[i_b]
                ta = _action_type_str(actions[ia])
                tb = _action_type_str(actions[ib])
                if frozenset({ta, tb}) in _OPPOSING_PAIRS:
                    pairs.append((ia, ib))
    return pairs


def resolve_action_conflicts(
    actions: list[Any],
    *,
    settings: Any | None = None,
    alert_fn: Any | None = None,
) -> ActionConflictReport:
    """Detect opposing actions per-ticker and drop the lower-score one.

    Returns a report summarising what was dropped and the surviving
    action list (safe to hand to the risk engine).  If the detector is
    disabled via ``settings.action_conflict_detector_enabled=False``,
    returns the input unchanged with an empty conflicts list.

    Parameters
    ----------
    actions:
        Merged list of PortfolioActions from all upstream sources.
    settings:
        Optional settings instance.  When provided and the flag is False,
        the call is a no-op.
    alert_fn:
        Optional callable invoked once per detected conflict with the
        ActionConflict record.  Suitable for webhook dispatch.
    """
    if settings is not None and not getattr(
        settings, "action_conflict_detector_enabled", True
    ):
        return ActionConflictReport(conflicts=[], resolved_actions=list(actions))

    if not actions:
        return ActionConflictReport(conflicts=[], resolved_actions=[])

    to_drop: set[int] = set()
    conflicts: list[ActionConflict] = []

    for ia, ib in _find_conflict_pairs(actions):
        if ia in to_drop or ib in to_drop:
            continue  # already resolved via earlier pair
        action_a = actions[ia]
        action_b = actions[ib]
        score_a = _composite_score(action_a)
        score_b = _composite_score(action_b)
        type_a = _action_type_str(action_a)
        type_b = _action_type_str(action_b)

        if score_a > score_b:
            keep_idx, drop_idx = ia, ib
            reason = "higher_composite_score"
        elif score_b > score_a:
            keep_idx, drop_idx = ib, ia
            reason = "higher_composite_score"
        else:
            # Tie-break: prefer OPEN over CLOSE (bias toward trading)
            if type_a == "open":
                keep_idx, drop_idx = ia, ib
            elif type_b == "open":
                keep_idx, drop_idx = ib, ia
            else:
                keep_idx, drop_idx = ia, ib
            reason = "tie_break_prefer_open"

        to_drop.add(drop_idx)
        kept = actions[keep_idx]
        dropped = actions[drop_idx]
        conflict = ActionConflict(
            ticker=getattr(kept, "ticker", ""),
            kept_action_type=_action_type_str(kept),
            dropped_action_type=_action_type_str(dropped),
            kept_score=_composite_score(kept),
            dropped_score=_composite_score(dropped),
            resolution_reason=reason,
        )
        conflicts.append(conflict)
        logger.warning(
            "action_conflict_detected",
            ticker=conflict.ticker,
            kept=conflict.kept_action_type,
            dropped=conflict.dropped_action_type,
            kept_score=conflict.kept_score,
            dropped_score=conflict.dropped_score,
            reason=conflict.resolution_reason,
        )
        if alert_fn is not None:
            try:
                alert_fn(conflict)
            except Exception as exc:  # noqa: BLE001
                logger.warning("action_conflict_alert_failed", error=str(exc))

    resolved = [a for i, a in enumerate(actions) if i not in to_drop]
    return ActionConflictReport(conflicts=conflicts, resolved_actions=resolved)


def assert_no_action_conflicts(
    actions: list[Any],
    *,
    settings: Any | None = None,
) -> list[Any]:
    """Convenience wrapper: resolve conflicts and return cleaned list.

    Callers that want the report object should use
    :func:`resolve_action_conflicts` directly.
    """
    report = resolve_action_conflicts(actions, settings=settings)
    return report.resolved_actions
