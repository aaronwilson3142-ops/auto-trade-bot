"""Universe Management Service — Phase 48.

Manages the active trading universe: applies operator add/remove overrides
and optional signal-quality-driven auto-removals to produce the
``active_universe`` list that the paper trading pipeline uses in place of
the static UNIVERSE_TICKERS constant.

Design
------
- Stateless: all methods are @staticmethod; no instance state.
- Reads from DB overrides passed in as plain dicts (caller queries DB).
- Gracefully degrades to the full base universe when no overrides exist.
- Quality-based removal is disabled by default (min_quality_score=0.0).
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Optional

import structlog

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class OverrideRecord:
    """Lightweight DTO built from a UniverseOverride ORM row."""
    ticker: str
    action: str          # "ADD" or "REMOVE"
    reason: Optional[str]
    operator_id: Optional[str]
    active: bool
    expires_at: Optional[dt.datetime]


@dataclass(frozen=True)
class UniverseTickerStatus:
    """Per-ticker universe status snapshot."""
    ticker: str
    in_base_universe: bool
    in_active_universe: bool
    override_action: Optional[str]     # "ADD", "REMOVE", or None
    override_reason: Optional[str]
    quality_removed: bool              # True if removed due to low signal quality
    signal_quality_score: Optional[float]


@dataclass(frozen=True)
class UniverseSummary:
    """Summary of the active universe computation."""
    computed_at: dt.datetime
    base_count: int
    active_count: int
    added_tickers: list[str]
    removed_tickers: list[str]
    quality_removed_tickers: list[str]
    override_count: int
    ticker_statuses: list[UniverseTickerStatus]


class UniverseManagementService:
    """Stateless service: produces and reports on the active trading universe."""

    # ------------------------------------------------------------------
    # Core: compute active universe
    # ------------------------------------------------------------------

    @staticmethod
    def get_active_universe(
        base_tickers: list[str],
        overrides: list[OverrideRecord],
        signal_quality_scores: dict[str, float] | None = None,
        min_quality_score: float = 0.0,
        reference_dt: dt.datetime | None = None,
    ) -> list[str]:
        """Compute the active universe by applying overrides and quality filter.

        Priority order (highest wins):
        1. Active ADD override  → ticker is always included (even if not in base)
        2. Active REMOVE override → ticker is always excluded
        3. Signal quality removal → excluded when quality < min_quality_score
           (only applies when min_quality_score > 0.0 and score is known)
        4. Default: include if in base_tickers

        Args:
            base_tickers: canonical static universe (UNIVERSE_TICKERS).
            overrides: active override records (caller pre-filters to active=True).
            signal_quality_scores: dict of strategy-level quality per ticker
                (from SignalQualityReport.strategy_quality[strategy].win_rate or
                a pre-aggregated per-ticker score dict).  None = no quality data.
            min_quality_score: minimum average quality score to stay in universe.
                0.0 = quality removal disabled (safe default).
            reference_dt: UTC datetime for evaluating expires_at; defaults to now().

        Returns:
            Sorted list of tickers in the active universe.
        """
        now = reference_dt or dt.datetime.now(dt.timezone.utc)

        # Separate active-and-unexpired overrides by action
        add_tickers: set[str] = set()
        remove_tickers: set[str] = set()

        for ovr in overrides:
            if not ovr.active:
                continue
            if ovr.expires_at is not None:
                exp = ovr.expires_at
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=dt.timezone.utc)
                if exp <= now:
                    continue  # expired
            if ovr.action == "ADD":
                add_tickers.add(ovr.ticker.upper())
            elif ovr.action == "REMOVE":
                remove_tickers.add(ovr.ticker.upper())

        # Quality-based removals (only when min_quality_score > 0.0)
        quality_removed: set[str] = set()
        if min_quality_score > 0.0 and signal_quality_scores:
            for ticker, score in signal_quality_scores.items():
                if score < min_quality_score:
                    quality_removed.add(ticker.upper())

        # Build active universe
        result: set[str] = set()

        # Start from base universe
        for t in base_tickers:
            t_up = t.upper()
            if t_up in remove_tickers:
                continue  # explicit operator removal
            if t_up in quality_removed and t_up not in add_tickers:
                continue  # quality removal (unless ADD override)
            result.add(t_up)

        # Operator ADD overrides (may include non-base tickers)
        for t in add_tickers:
            result.add(t)

        log.debug(
            "active_universe_computed",
            base_count=len(base_tickers),
            active_count=len(result),
            add_overrides=len(add_tickers),
            remove_overrides=len(remove_tickers),
            quality_removed=len(quality_removed),
        )

        return sorted(result)

    # ------------------------------------------------------------------
    # Reporting helpers
    # ------------------------------------------------------------------

    @staticmethod
    def compute_universe_summary(
        base_tickers: list[str],
        active_tickers: list[str],
        overrides: list[OverrideRecord],
        signal_quality_scores: dict[str, float] | None = None,
        min_quality_score: float = 0.0,
        reference_dt: dt.datetime | None = None,
    ) -> UniverseSummary:
        """Build a full summary of active universe state for API/dashboard."""
        now = reference_dt or dt.datetime.now(dt.timezone.utc)

        base_set = {t.upper() for t in base_tickers}
        active_set = {t.upper() for t in active_tickers}

        # Determine which tickers were added vs removed vs unchanged
        added = sorted(active_set - base_set)
        removed = sorted(base_set - active_set)

        # Quality removed (in base, not in active, no REMOVE override)
        # Overrides
        override_map: dict[str, OverrideRecord] = {}
        for ovr in overrides:
            if ovr.active:
                if ovr.expires_at is not None:
                    exp = ovr.expires_at
                    if exp.tzinfo is None:
                        exp = exp.replace(tzinfo=dt.timezone.utc)
                    if exp <= now:
                        continue
                override_map[ovr.ticker.upper()] = ovr

        quality_removed_set: set[str] = set()
        if min_quality_score > 0.0 and signal_quality_scores:
            for ticker, score in signal_quality_scores.items():
                t_up = ticker.upper()
                if score < min_quality_score and t_up not in active_set and t_up in base_set:
                    quality_removed_set.add(t_up)

        # Build per-ticker statuses for all base + added tickers
        all_tickers = sorted(base_set | active_set)
        statuses: list[UniverseTickerStatus] = []
        for t in all_tickers:
            ovr = override_map.get(t)
            quality_score = (signal_quality_scores or {}).get(t)
            statuses.append(UniverseTickerStatus(
                ticker=t,
                in_base_universe=t in base_set,
                in_active_universe=t in active_set,
                override_action=ovr.action if ovr else None,
                override_reason=ovr.reason if ovr else None,
                quality_removed=t in quality_removed_set,
                signal_quality_score=quality_score,
            ))

        return UniverseSummary(
            computed_at=now,
            base_count=len(base_set),
            active_count=len(active_set),
            added_tickers=added,
            removed_tickers=removed,
            quality_removed_tickers=sorted(quality_removed_set),
            override_count=len(override_map),
            ticker_statuses=statuses,
        )

    # ------------------------------------------------------------------
    # DB helper: load active overrides
    # ------------------------------------------------------------------

    @staticmethod
    def load_active_overrides(
        session_factory: Any,
        reference_dt: dt.datetime | None = None,
    ) -> list[OverrideRecord]:
        """Query the universe_overrides table and return active, unexpired records.

        Returns [] when session_factory is None or DB is unreachable.
        """
        if session_factory is None:
            return []
        now = reference_dt or dt.datetime.now(dt.timezone.utc)
        try:
            from infra.db.models.universe_override import UniverseOverride
            import sqlalchemy as sa

            with session_factory() as db:
                rows = (
                    db.query(UniverseOverride)
                    .filter(UniverseOverride.active == True)  # noqa: E712
                    .filter(
                        sa.or_(
                            UniverseOverride.expires_at == None,  # noqa: E711
                            UniverseOverride.expires_at > now,
                        )
                    )
                    .all()
                )
                return [
                    OverrideRecord(
                        ticker=r.ticker,
                        action=r.action,
                        reason=r.reason,
                        operator_id=r.operator_id,
                        active=r.active,
                        expires_at=r.expires_at,
                    )
                    for r in rows
                ]
        except Exception as exc:  # noqa: BLE001
            log.warning("load_active_overrides_failed", error=str(exc))
            return []
