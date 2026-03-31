"""
Earnings Calendar Integration + Pre-Earnings Risk Management — Phase 45.

EarningsCalendarService tracks upcoming earnings dates for universe tickers
and blocks new OPEN actions when a ticker's earnings are within a configured
proximity window.  Earnings events are the largest discontinuous risk events
in equity trading — a stock can gap 15-25% overnight on a miss.  The system's
VaR model, stop-loss, and stress tests all assume continuous-price risk; they
provide no protection against earnings-gap risk.  This service closes that gap.

Design rules
------------
- Stateless: every method is a classmethod / staticmethod (no DB access).
- Data fetch: yfinance Ticker.calendar attribute (next_earnings_date field).
  Falls back to None gracefully when data is unavailable or the ticker is
  unknown.
- filter_for_earnings_proximity() applies to OPEN actions only — CLOSE and
  TRIM actions are never blocked.
- uses dataclasses.replace() pattern is not needed here; SimpleNamespace-
  compatible (actions only need .action_type and .ticker).
- structlog only — no print() calls.
- no_calendar=True when no earnings data is available; callers treat this
  as "no earnings signal" and pass all actions through.

Earnings proximity logic
------------------------
  If ticker has an earnings date within ``max_earnings_proximity_days`` from
  *reference_date*, the OPEN action is blocked.  The default window is 2
  calendar days — enough to protect against overnight gaps (announced after
  close on day 0; surprise gap at open on day 1).

  days_to_earnings is computed as (earnings_date - reference_date).days.
  Negative values mean earnings have already passed (no action taken).
  Zero means earnings today — still blocked.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

import structlog

if TYPE_CHECKING:
    from config.settings import Settings
    from services.portfolio_engine.models import PortfolioAction

log = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class EarningsEntry:
    """Earnings data for a single ticker.

    days_to_earnings is None when no earnings date is available.
    earnings_within_window is True when the position is earnings-at-risk.
    """

    ticker: str
    earnings_date: Optional[dt.date]          # next confirmed earnings date or None
    days_to_earnings: Optional[int]           # positive = future, 0 = today, negative = past
    earnings_within_window: bool              # True if days_to_earnings in [0, max_days]
    max_earnings_proximity_days: int          # window used for this computation


@dataclass
class EarningsCalendarResult:
    """Aggregated earnings calendar for the current universe.

    ``entries`` maps ticker → EarningsEntry.
    ``at_risk_tickers`` is the set of tickers with earnings within the window.
    ``no_calendar`` is True when no earnings data could be fetched at all.
    """

    computed_at: dt.datetime
    reference_date: dt.date
    max_earnings_proximity_days: int
    entries: dict = field(default_factory=dict)          # ticker → EarningsEntry
    at_risk_tickers: list = field(default_factory=list)  # tickers within earnings window
    no_calendar: bool = False                            # True when fetch completely failed


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class EarningsCalendarService:
    """Fetch and evaluate upcoming earnings dates for the universe.

    All methods are classmethods / staticmethods — no instance state.

    The yfinance calendar attribute returns a DataFrame with columns including
    'Earnings Date'.  We extract the next (most immediate future) date.
    """

    # ── Data fetch ─────────────────────────────────────────────────────────

    @staticmethod
    def _fetch_next_earnings_date(ticker: str) -> Optional[dt.date]:
        """Return the next earnings date for *ticker* from yfinance.

        Returns None when:
        - yfinance is not installed
        - the ticker is unknown or delisted
        - no upcoming earnings date is reported
        - any other exception occurs

        All exceptions are caught — data unavailability is normal for some
        tickers and must never crash the refresh job.
        """
        try:
            import yfinance as yf  # noqa: PLC0415

            info = yf.Ticker(ticker).calendar
            if info is None:
                return None

            # yfinance returns either a DataFrame or a dict depending on version
            if hasattr(info, "columns"):
                # DataFrame form — look for 'Earnings Date' column
                if "Earnings Date" in info.columns:
                    dates = info["Earnings Date"].dropna()
                    if dates.empty:
                        return None
                    # Take the first (earliest) date
                    raw = dates.iloc[0]
                    if hasattr(raw, "date"):
                        return raw.date()
                    return dt.date.fromisoformat(str(raw)[:10])
                return None
            elif isinstance(info, dict):
                raw = info.get("Earnings Date") or info.get("earningsDate")
                if raw is None:
                    return None
                if isinstance(raw, (list, tuple)) and raw:
                    raw = raw[0]
                if hasattr(raw, "date"):
                    return raw.date()
                if isinstance(raw, dt.date):
                    return raw
                return dt.date.fromisoformat(str(raw)[:10])
            return None
        except Exception as exc:  # noqa: BLE001
            log.debug(
                "earnings_date_fetch_failed",
                ticker=ticker,
                error=str(exc),
            )
            return None

    # ── Calendar build ─────────────────────────────────────────────────────

    @classmethod
    def build_calendar(
        cls,
        tickers: list[str],
        max_earnings_proximity_days: int,
        reference_date: Optional[dt.date] = None,
    ) -> EarningsCalendarResult:
        """Fetch earnings dates for all *tickers* and build a calendar result.

        Args:
            tickers: List of ticker symbols to check.
            max_earnings_proximity_days: Window (calendar days) within which
                a ticker is considered earnings-at-risk.
            reference_date: Date from which proximity is measured; defaults
                to today (UTC).

        Returns:
            EarningsCalendarResult with per-ticker entries and at-risk set.
        """
        now = dt.datetime.now(dt.timezone.utc)
        ref = reference_date or now.date()

        entries: dict[str, EarningsEntry] = {}
        at_risk: list[str] = []

        for ticker in tickers:
            earnings_date = cls._fetch_next_earnings_date(ticker)
            if earnings_date is None:
                days_to = None
                within_window = False
            else:
                days_to = (earnings_date - ref).days
                within_window = 0 <= days_to <= max_earnings_proximity_days

            entry = EarningsEntry(
                ticker=ticker,
                earnings_date=earnings_date,
                days_to_earnings=days_to,
                earnings_within_window=within_window,
                max_earnings_proximity_days=max_earnings_proximity_days,
            )
            entries[ticker] = entry

            if within_window:
                at_risk.append(ticker)
                log.info(
                    "ticker_earnings_at_risk",
                    ticker=ticker,
                    earnings_date=str(earnings_date),
                    days_to_earnings=days_to,
                )

        log.info(
            "earnings_calendar_built",
            tickers_checked=len(tickers),
            at_risk_count=len(at_risk),
        )

        return EarningsCalendarResult(
            computed_at=now,
            reference_date=ref,
            max_earnings_proximity_days=max_earnings_proximity_days,
            entries=entries,
            at_risk_tickers=at_risk,
            no_calendar=(len(tickers) > 0 and len(entries) == 0),
        )

    # ── Paper cycle gate ───────────────────────────────────────────────────

    @staticmethod
    def filter_for_earnings_proximity(
        actions: list,                          # list[PortfolioAction]
        calendar_result: "EarningsCalendarResult",
        settings: "Settings",
    ) -> tuple[list, int]:
        """Block OPEN actions for tickers with earnings within the proximity window.

        CLOSE and TRIM actions always pass through — exits must never be
        blocked by an earnings gate.  When no calendar data is available
        (no_calendar=True) or the gate is disabled (max_earnings_proximity_days=0),
        all actions pass through unchanged.

        Args:
            actions:         Proposed list of PortfolioAction objects.
            calendar_result: Latest EarningsCalendarResult from build_calendar.
            settings:        Settings instance carrying max_earnings_proximity_days.

        Returns:
            Tuple of (filtered_actions, blocked_count).
        """
        from services.portfolio_engine.models import ActionType  # noqa: PLC0415

        max_days: int = int(getattr(settings, "max_earnings_proximity_days", 2))

        # Gate disabled or no calendar data → pass through all
        if max_days <= 0 or calendar_result.no_calendar:
            return actions, 0

        at_risk_set = set(calendar_result.at_risk_tickers)
        if not at_risk_set:
            return actions, 0

        filtered: list = []
        blocked = 0

        for action in actions:
            if action.action_type == ActionType.OPEN and action.ticker in at_risk_set:
                blocked += 1
                entry = calendar_result.entries.get(action.ticker)
                log.info(
                    "earnings_gate_open_blocked",
                    ticker=action.ticker,
                    earnings_date=str(entry.earnings_date) if entry else "unknown",
                    days_to_earnings=entry.days_to_earnings if entry else None,
                )
            else:
                filtered.append(action)

        if blocked:
            log.warning(
                "earnings_gate_applied",
                blocked_count=blocked,
                at_risk_tickers=sorted(at_risk_set),
                max_earnings_proximity_days=max_days,
            )

        return filtered, blocked
