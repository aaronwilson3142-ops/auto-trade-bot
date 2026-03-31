"""
Signal Quality Tracking + Per-Strategy Attribution — Phase 46.

SignalQualityService computes per-strategy prediction quality metrics from
persisted SignalOutcome records.  Each SignalOutcome captures one closed
trade matched against the strategy signal that was active when the position
was opened.

Design rules
------------
- Stateless: every method is a classmethod / staticmethod (no DB access).
  All DB I/O lives in the job function (run_signal_quality_update).
- All data is passed explicitly; no singleton or global state.
- Uses structlog — no print() calls.
- Returns dataclasses; callers serialise to Pydantic schemas as needed.
- Sharpe estimate: (mean_return / std_return) × sqrt(252) when at least
  two data points are available; 0.0 otherwise.  Uses daily returns, so
  annualisation uses sqrt(252).  This is an approximation — not a formal
  Sharpe from a risk-free rate adjusted series.
- Graceful degradation: empty outcome list → zeroed result, not an error.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class StrategyQualityResult:
    """Aggregated signal-quality statistics for one strategy.

    prediction_count: number of closed trades attributed to this strategy.
    win_count:        trades with outcome_return_pct > 0.
    win_rate:         win_count / prediction_count in [0.0, 1.0]; 0.0 if no data.
    avg_return_pct:   mean of outcome_return_pct across all attributed trades.
    best_return_pct:  highest individual outcome_return_pct observed.
    worst_return_pct: lowest individual outcome_return_pct observed.
    avg_hold_days:    mean hold_duration across attributed trades.
    sharpe_estimate:  annualised Sharpe approximation (mean/std × sqrt(252));
                      0.0 when fewer than 2 observations.
    """

    strategy_name: str
    prediction_count: int = 0
    win_count: int = 0
    win_rate: float = 0.0
    avg_return_pct: float = 0.0
    best_return_pct: float = 0.0
    worst_return_pct: float = 0.0
    avg_hold_days: float = 0.0
    sharpe_estimate: float = 0.0


@dataclass
class SignalQualityReport:
    """Full signal quality report across all tracked strategies.

    computed_at:           UTC timestamp when the report was generated.
    total_outcomes_recorded: total SignalOutcome rows in DB (all strategies).
    strategies_with_data:  strategy names that have at least one outcome row.
    strategy_results:      per-strategy StrategyQualityResult list,
                           sorted descending by win_rate then avg_return_pct.
    """

    computed_at: datetime
    total_outcomes_recorded: int = 0
    strategies_with_data: list[str] = field(default_factory=list)
    strategy_results: list[StrategyQualityResult] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class SignalQualityService:
    """Compute per-strategy signal quality statistics from outcome records.

    All methods are classmethods / staticmethods — no instance state needed.

    Callers pass pre-fetched outcome dicts (or ORM row proxies) so the
    service has no knowledge of the ORM or DB layer.

    Expected outcome dict keys
    --------------------------
    strategy_name    : str
    outcome_return_pct : float | Decimal
    was_profitable   : bool
    hold_days        : int
    signal_score     : float | Decimal | None  (optional, unused in stats)
    """

    # ── Per-strategy quality ───────────────────────────────────────────────

    @staticmethod
    def compute_strategy_quality(
        strategy_name: str,
        outcomes: list[dict],
    ) -> StrategyQualityResult:
        """Compute quality statistics for a single strategy.

        Args:
            strategy_name: Name of the strategy being evaluated.
            outcomes:      List of outcome dicts for this strategy only.

        Returns:
            StrategyQualityResult with zeroed fields when outcomes is empty.
        """
        if not outcomes:
            return StrategyQualityResult(strategy_name=strategy_name)

        returns = [float(o["outcome_return_pct"]) for o in outcomes]
        hold_days = [int(o["hold_days"]) for o in outcomes]
        wins = [o for o in outcomes if o["was_profitable"]]

        count = len(returns)
        win_count = len(wins)
        win_rate = win_count / count if count > 0 else 0.0
        avg_return = sum(returns) / count
        best = max(returns)
        worst = min(returns)
        avg_hold = sum(hold_days) / count

        # Annualised Sharpe approximation
        sharpe = 0.0
        if count >= 2:
            mean_r = avg_return
            variance = sum((r - mean_r) ** 2 for r in returns) / (count - 1)
            std_r = math.sqrt(variance) if variance > 0 else 0.0
            if std_r > 0:
                sharpe = (mean_r / std_r) * math.sqrt(252)

        return StrategyQualityResult(
            strategy_name=strategy_name,
            prediction_count=count,
            win_count=win_count,
            win_rate=round(win_rate, 6),
            avg_return_pct=round(avg_return, 6),
            best_return_pct=round(best, 6),
            worst_return_pct=round(worst, 6),
            avg_hold_days=round(avg_hold, 2),
            sharpe_estimate=round(sharpe, 4),
        )

    # ── Full report ────────────────────────────────────────────────────────

    @classmethod
    def compute_quality_report(
        cls,
        outcomes: list[dict],
        computed_at: datetime | None = None,
    ) -> SignalQualityReport:
        """Compute a full quality report across all strategies.

        Args:
            outcomes:    All SignalOutcome rows as dicts (all strategies mixed).
            computed_at: Timestamp for the report; defaults to utcnow().

        Returns:
            SignalQualityReport with per-strategy StrategyQualityResult list
            sorted descending by win_rate, then avg_return_pct.
        """
        import datetime as _dt  # noqa: PLC0415

        ts = computed_at or _dt.datetime.now(_dt.UTC)

        if not outcomes:
            return SignalQualityReport(
                computed_at=ts,
                total_outcomes_recorded=0,
                strategies_with_data=[],
                strategy_results=[],
            )

        # Group by strategy_name
        by_strategy: dict[str, list[dict]] = {}
        for o in outcomes:
            name = o["strategy_name"]
            by_strategy.setdefault(name, []).append(o)

        results: list[StrategyQualityResult] = []
        for name, strat_outcomes in by_strategy.items():
            results.append(cls.compute_strategy_quality(name, strat_outcomes))

        # Sort: best win_rate first; break ties by avg_return_pct
        results.sort(key=lambda r: (r.win_rate, r.avg_return_pct), reverse=True)

        return SignalQualityReport(
            computed_at=ts,
            total_outcomes_recorded=len(outcomes),
            strategies_with_data=sorted(by_strategy.keys()),
            strategy_results=results,
        )

    # ── Trade → signal matching ────────────────────────────────────────────

    @staticmethod
    def build_outcome_dict(
        ticker: str,
        strategy_name: str,
        trade_opened_at,
        trade_closed_at,
        outcome_return_pct,
        hold_days: int,
        was_profitable: bool,
        signal_score=None,
    ) -> dict:
        """Build a normalised outcome dict from raw fields.

        This helper ensures consistent key names across callers and handles
        Decimal → float normalisation so downstream stats math uses floats.
        """
        return {
            "ticker": ticker,
            "strategy_name": strategy_name,
            "trade_opened_at": trade_opened_at,
            "trade_closed_at": trade_closed_at,
            "outcome_return_pct": float(outcome_return_pct),
            "hold_days": int(hold_days),
            "was_profitable": bool(was_profitable),
            "signal_score": float(signal_score) if signal_score is not None else None,
        }
