"""
Point-in-time universe source — Phase A.2.

Produces a survivorship-safe ``base_tickers`` list (for the existing
UniverseManagementService) that reflects the actual membership of an
index on a historical date.

Why this module exists
----------------------
The static ``config/universe.py`` hand-curated 62-stock list is
survivorship-biased by construction — it lists only companies the operator
thought were interesting *today*.  Any backtest that iterates across
history using that list automatically drops delisted / merged / renamed
names, inflating measured edge.

This service instead sources the base universe from the Norgate
``S&P 500 Current & Past`` watchlist, combined with per-ticker
``index_constituent_timeseries`` lookups so it can answer
"what was in the S&P 500 on YYYY-MM-DD?" for any date in Norgate's history.

Trial-window caveat
-------------------
The 21-day Norgate free trial exposes the watchlist *name* but caps the
historical membership data at the Gold tier — meaning only current
constituents are returned (~541 names vs the 700+ needed for true
survivorship safety).  Running this service against the trial gives
you a universe that is larger and cleaner than the hand-curated 62 but
still not fully survivorship-safe.  Full accuracy requires Platinum.

Interaction with existing services
----------------------------------
``UniverseManagementService.get_active_universe`` already accepts
``base_tickers`` as a parameter.  This module simply provides a different
source for that parameter:

    from services.universe_management.pointintime_source import (
        PointInTimeUniverseService,
    )
    source = PointInTimeUniverseService()
    base = source.get_universe_as_of(dt.date(2022, 1, 3))
    active = UniverseManagementService.get_active_universe(base, overrides)

Operator overrides, quality removals, and the existing active-universe
logic all continue to work unchanged.
"""
from __future__ import annotations

import datetime as dt
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from services.data_ingestion.adapters.pointintime_adapter import (
        PointInTimeAdapter,
    )

logger = logging.getLogger(__name__)

DEFAULT_WATCHLIST = "S&P 500 Current & Past"
DEFAULT_INDEX = "S&P 500"


class PointInTimeUniverseService:
    """Survivorship-safe base-universe source backed by Norgate NDU.

    Instance-level cache keyed by (index_name, as_of) — keeps walk-forward
    runs fast when they query consecutive days.
    """

    def __init__(
        self,
        adapter: PointInTimeAdapter | None = None,
        watchlist_name: str = DEFAULT_WATCHLIST,
        default_index_name: str = DEFAULT_INDEX,
    ) -> None:
        if adapter is None:
            # Lazy import to keep this module import-safe when norgatedata
            # is not installed (unit tests inject a stub adapter).
            from services.data_ingestion.adapters.pointintime_adapter import (
                PointInTimeAdapter,
            )
            adapter = PointInTimeAdapter()
        self._adapter = adapter
        self._watchlist_name = watchlist_name
        self._default_index_name = default_index_name
        self._universe_cache: dict[tuple[str, dt.date], list[str]] = {}
        self._candidate_pool_cache: list[str] | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_candidate_pool(self) -> list[str]:
        """All tickers ever in the watchlist (current + past, if available).

        Cached for the lifetime of the service instance — the underlying
        watchlist rarely changes intraday.
        """
        if self._candidate_pool_cache is not None:
            return list(self._candidate_pool_cache)

        pool = self._adapter.watchlist_symbols(self._watchlist_name)
        if not pool:
            logger.warning(
                "point-in-time candidate pool is empty for watchlist '%s' — "
                "Norgate subscription tier may not expose this watchlist",
                self._watchlist_name,
            )
        self._candidate_pool_cache = list(pool)
        return list(self._candidate_pool_cache)

    def get_universe_as_of(
        self,
        as_of: dt.date,
        index_name: str | None = None,
    ) -> list[str]:
        """Tickers that were members of ``index_name`` on ``as_of``.

        Args:
            as_of: historical date.  If ``as_of`` is today, returns the
                current index membership.
            index_name: Norgate index name (default: "S&P 500").

        Returns:
            Sorted unique ticker list.  Empty list on any error or when
            the trial tier doesn't expose constituent history.
        """
        index_name = index_name or self._default_index_name
        cache_key = (index_name, as_of)
        if cache_key in self._universe_cache:
            return list(self._universe_cache[cache_key])

        candidates = self.get_candidate_pool()
        if not candidates:
            self._universe_cache[cache_key] = []
            return []

        try:
            import norgatedata as nd
        except ImportError:
            logger.error("norgatedata not installed — returning empty universe")
            self._universe_cache[cache_key] = []
            return []

        members: set[str] = set()
        for ticker in candidates:
            try:
                was_member = _was_index_member(
                    nd=nd,
                    ticker=ticker,
                    index_name=index_name,
                    as_of=as_of,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "constituent lookup failed for %s: %s", ticker, exc
                )
                continue
            if was_member:
                members.add(ticker)

        result = sorted(members)
        self._universe_cache[cache_key] = result

        logger.info(
            "point_in_time_universe_built index=%s as_of=%s candidates=%d members=%d",
            index_name, as_of, len(candidates), len(result),
        )
        return list(result)

    def get_current_universe(self, index_name: str | None = None) -> list[str]:
        """Shortcut for today's membership."""
        return self.get_universe_as_of(dt.date.today(), index_name=index_name)

    def iter_universe_over_range(
        self,
        start: dt.date,
        end: dt.date,
        index_name: str | None = None,
        step_days: int = 1,
    ):
        """Yield ``(date, tickers)`` pairs across a date range.

        Used by walk-forward / rolling backtests.  ``step_days=21`` ≈ monthly
        rebalance; ``step_days=1`` = daily snapshots.
        """
        current = start
        while current <= end:
            yield current, self.get_universe_as_of(current, index_name=index_name)
            current += dt.timedelta(days=step_days)

    # ------------------------------------------------------------------
    # Cache management
    # ------------------------------------------------------------------

    def clear_cache(self) -> None:
        """Reset all cached universes and the candidate pool."""
        self._universe_cache.clear()
        self._candidate_pool_cache = None


# ----------------------------------------------------------------------
# Private helpers (module-level so tests can patch nd.* uniformly)
# ----------------------------------------------------------------------


def _was_index_member(
    *,
    nd,  # the live norgatedata module  # noqa: ANN001
    ticker: str,
    index_name: str,
    as_of: dt.date,
) -> bool:
    """Return True if ``ticker`` was a member of ``index_name`` on ``as_of``.

    Uses ``nd.index_constituent_timeseries`` which returns a DataFrame whose
    index is a date and whose value (``Index Constituent``) is 1 on days when
    the ticker was a member of the index.
    """
    df = nd.index_constituent_timeseries(
        ticker,
        indexname=index_name,
        # Return raw flag series (no forward-fill) so we can read an exact day
        padding_setting=getattr(nd.PaddingType, "NONE", 0) if hasattr(nd, "PaddingType") else 0,
        start_date=as_of.isoformat(),
        end_date=as_of.isoformat(),
        timeseriesformat="pandas-dataframe",
    )
    if df is None or df.empty:
        return False

    # Norgate returns a single column named "Index Constituent" with 0/1.
    # Be defensive about the column name across library versions.
    for candidate in ("Index Constituent", "index_constituent", "IndexConstituent"):
        if candidate in df.columns:
            try:
                return bool(int(df[candidate].iloc[-1]) == 1)
            except Exception:  # noqa: BLE001
                return False

    # Fallback: take the first column whatever it's named
    try:
        return bool(int(df.iloc[-1, 0]) == 1)
    except Exception:  # noqa: BLE001
        return False
