"""
QuiverQuant insider-flow adapter (Phase 57 Part 2 — DEC-024 / 2026-04-18).

Pulls congressional trading disclosures from QuiverQuant's REST API and
normalises them into ``InsiderFlowEvent`` objects the enrichment pipeline
can aggregate.

Provider choice rationale (DEC-023):
    QuiverQuant is a paid provider with a documented REST contract, explicit
    ToS that permits programmatic access, and first-party ingestion of STOCK
    Act filings (raw Form 4 / PTR data).  It is the *primary* source for this
    adapter family; SEC EDGAR Form 4 parsing is the *supplementary* source
    (see sec_edgar_form4_adapter.py).

Safety rules (from InsiderFlowAdapter contract):
    - NEVER raise on empty result sets → return []
    - NEVER raise on individual row parse failures → log WARNING + skip
    - Apply rate-limiting / backoff internally
    - Return events with filing_date <= as_of (default: today UTC)

Default-OFF: the factory only wires this adapter when BOTH
``insider_flow_provider`` names it AND ``quiverquant_api_key`` is set.  A
missing key falls back to ``NullInsiderFlowAdapter`` with a WARNING — never a
crash.
"""
from __future__ import annotations

import datetime as dt
import logging
import random
import time
from decimal import Decimal, InvalidOperation
from typing import Any

from services.data_ingestion.adapters.insider_flow_adapter import (
    InsiderFlowAdapter,
    InsiderFlowEvent,
)

logger = logging.getLogger(__name__)

SOURCE_KEY = "quiverquant"
BASE_URL = "https://api.quiverquant.com/beta"
# Congressional Trading (STOCK Act) — per-ticker endpoint.
# Docs: https://api.quiverquant.com/docs/
CONGRESS_ENDPOINT = "/historical/congresstrading/{ticker}"

# Default HTTP timeout in seconds — generous enough for multi-ticker pulls
# but short enough that worker cycles never block on a slow provider.
DEFAULT_TIMEOUT_S = 10.0

# Rate limiting — QuiverQuant's free/basic tiers document ~60 req/min.
# We conservatively target ≤30 req/min here (one request every 2s).
DEFAULT_MIN_INTERVAL_S = 2.0

# Retry / backoff on transient 429 or 5xx responses.
DEFAULT_MAX_RETRIES = 3
DEFAULT_BACKOFF_BASE_S = 1.0

# Map QuiverQuant transaction strings to our canonical BUY/SELL.  Anything
# unrecognised is skipped with a WARNING so we never guess.
_BUY_TOKENS = {"purchase", "buy", "acquire", "acquired"}
_SELL_TOKENS = {"sale", "sell", "sold", "dispose", "disposed", "sale_full", "sale_partial"}


def _to_decimal(value: Any) -> Decimal | None:
    """Safely convert a scalar to Decimal (None-safe, NaN-safe)."""
    if value is None:
        return None
    try:
        import math
        if isinstance(value, float) and math.isnan(value):
            return None
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _parse_iso_date(value: Any) -> dt.date | None:
    """Parse YYYY-MM-DD into a date; return None on failure."""
    if value is None:
        return None
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _classify_side(raw_transaction: str | None) -> str | None:
    """Return 'BUY' / 'SELL' / None for an unrecognised QuiverQuant token."""
    if not raw_transaction:
        return None
    tok = raw_transaction.strip().lower()
    if any(t in tok for t in _BUY_TOKENS):
        return "BUY"
    if any(t in tok for t in _SELL_TOKENS):
        return "SELL"
    return None


def _midpoint_of_range(raw: dict[str, Any]) -> Decimal | None:
    """QuiverQuant reports amounts as bracket ranges (``$1,001 - $15,000``) or
    numeric ``Amount``.  Take the midpoint of the bracket, else the numeric
    field, else None.
    """
    # Prefer explicit numeric if present (paid tier).
    amt = _to_decimal(raw.get("Amount"))
    if amt is not None and amt > 0:
        return amt

    # Fall back to the bracket.
    low = _to_decimal(raw.get("Range_Lower") or raw.get("AmountLower"))
    high = _to_decimal(raw.get("Range_Upper") or raw.get("AmountUpper"))
    if low is not None and high is not None and high >= low:
        return (low + high) / Decimal("2")
    if low is not None:
        return low
    if high is not None:
        return high
    return None


class QuiverQuantAdapter(InsiderFlowAdapter):
    """Pulls congressional trading events from QuiverQuant.

    Args:
        api_key: QuiverQuant API token.  Required — the factory should never
            construct this adapter without a key.
        timeout_s: per-request HTTP timeout in seconds.
        min_interval_s: minimum seconds between outbound requests.
        max_retries: maximum retries on 429 / 5xx / network errors.
        base_url: override (for tests).
        http_client: inject a pre-built ``httpx.Client`` (for tests).
    """

    SOURCE_KEY: str = SOURCE_KEY

    def __init__(
        self,
        *,
        api_key: str,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        min_interval_s: float = DEFAULT_MIN_INTERVAL_S,
        max_retries: int = DEFAULT_MAX_RETRIES,
        base_url: str = BASE_URL,
        http_client: Any = None,
    ) -> None:
        if not api_key:
            raise ValueError(
                "QuiverQuantAdapter requires a non-empty api_key; the "
                "factory should have fallen back to NullInsiderFlowAdapter."
            )
        self._api_key = api_key
        self._timeout_s = timeout_s
        self._min_interval_s = min_interval_s
        self._max_retries = max_retries
        self._base_url = base_url.rstrip("/")
        self._http_client = http_client
        self._last_request_at: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def fetch_events(
        self,
        tickers: list[str],
        lookback_days: int = 90,
        as_of: dt.date | None = None,
    ) -> list[InsiderFlowEvent]:
        """Pull congressional-trading events for the given tickers.

        Failures on individual tickers are logged and skipped — the method
        always returns a (possibly empty) list, never raises.
        """
        if not tickers:
            return []

        as_of = as_of or dt.datetime.utcnow().date()
        cutoff = as_of - dt.timedelta(days=max(1, lookback_days))

        events: list[InsiderFlowEvent] = []
        for ticker in tickers:
            try:
                raw_rows = self._fetch_congress_for_ticker(ticker)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "quiverquant_fetch_failed ticker=%s error=%s",
                    ticker, exc,
                )
                continue

            for row in raw_rows or []:
                ev = self._parse_row(ticker, row, cutoff=cutoff, as_of=as_of)
                if ev is not None:
                    events.append(ev)

        logger.info(
            "quiverquant_fetch_ok tickers=%d events=%d lookback_days=%d",
            len(tickers), len(events), lookback_days,
        )
        return events

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _fetch_congress_for_ticker(self, ticker: str) -> list[dict[str, Any]]:
        """One HTTP GET with rate-limiting + backoff.  Returns raw JSON rows."""
        path = CONGRESS_ENDPOINT.format(ticker=ticker.upper())
        url = f"{self._base_url}{path}"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }

        # Lazy httpx import so the rest of the import graph doesn't require
        # httpx at collection time (matches yfinance pattern).
        import httpx  # type: ignore

        client = self._http_client
        owns_client = False
        if client is None:
            client = httpx.Client(timeout=self._timeout_s)
            owns_client = True

        try:
            for attempt in range(self._max_retries + 1):
                self._respect_rate_limit()
                try:
                    resp = client.get(url, headers=headers)
                except Exception as exc:  # noqa: BLE001
                    if attempt >= self._max_retries:
                        logger.warning(
                            "quiverquant_network_error ticker=%s attempts=%d error=%s",
                            ticker, attempt + 1, exc,
                        )
                        return []
                    self._backoff(attempt)
                    continue

                status = getattr(resp, "status_code", 0)
                if status == 200:
                    try:
                        data = resp.json()
                    except Exception as exc:  # noqa: BLE001
                        logger.warning(
                            "quiverquant_bad_json ticker=%s error=%s", ticker, exc,
                        )
                        return []
                    return data if isinstance(data, list) else []

                if status == 404:
                    # Unknown ticker — empty result, not a failure.
                    return []

                if status in (429,) or 500 <= status < 600:
                    if attempt >= self._max_retries:
                        logger.warning(
                            "quiverquant_retry_exhausted ticker=%s status=%d",
                            ticker, status,
                        )
                        return []
                    self._backoff(attempt)
                    continue

                # 401/403/etc — permanent; log and bail for this ticker.
                logger.warning(
                    "quiverquant_bad_status ticker=%s status=%d", ticker, status,
                )
                return []

            return []
        finally:
            if owns_client:
                try:
                    client.close()
                except Exception:  # noqa: BLE001
                    pass

    def _respect_rate_limit(self) -> None:
        now = time.monotonic()
        wait = self._min_interval_s - (now - self._last_request_at)
        if wait > 0:
            time.sleep(wait)
        self._last_request_at = time.monotonic()

    @staticmethod
    def _backoff(attempt: int) -> None:
        delay = DEFAULT_BACKOFF_BASE_S * (2 ** attempt)
        # Full jitter (Exponential Backoff And Jitter — AWS Arch Blog).
        delay = random.uniform(0, delay)
        time.sleep(delay)

    def _parse_row(
        self,
        ticker: str,
        row: dict[str, Any],
        *,
        cutoff: dt.date,
        as_of: dt.date,
    ) -> InsiderFlowEvent | None:
        """Map one QuiverQuant row → InsiderFlowEvent, or None on failure."""
        try:
            side = _classify_side(row.get("Transaction"))
            if side is None:
                return None

            trade_date = _parse_iso_date(row.get("TransactionDate") or row.get("Date"))
            filing_date = _parse_iso_date(row.get("ReportDate") or row.get("FilingDate"))
            # If one of the dates is missing, fall back to the other so we
            # never silently drop an otherwise-valid row.
            if filing_date is None:
                filing_date = trade_date
            if trade_date is None:
                trade_date = filing_date
            if filing_date is None or trade_date is None:
                return None

            if filing_date > as_of:
                return None  # future-dated — provider glitch; skip.
            if filing_date < cutoff:
                return None  # outside lookback window.

            notional = _midpoint_of_range(row)
            if notional is None or notional <= 0:
                return None

            actor = str(row.get("Representative") or row.get("Senator") or "unknown")
            return InsiderFlowEvent(
                ticker=ticker.upper(),
                actor_type="congress",
                actor_name=actor,
                side=side,
                notional_usd=notional,
                trade_date=trade_date,
                filing_date=filing_date,
                source_key=SOURCE_KEY,
                confidence=0.9,  # STOCK Act filings are authoritative
                raw=row,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "quiverquant_parse_failed ticker=%s error=%s raw_keys=%s",
                ticker, exc, list(row.keys()) if isinstance(row, dict) else "n/a",
            )
            return None
