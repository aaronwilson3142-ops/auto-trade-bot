"""
DataIngestionService — orchestrates raw market-data retrieval and persistence.

Responsibilities (owns per 07_API_AND_SERVICE_BOUNDARIES_SPEC §3.1):
  - Accept ingestion requests (ticker list + period/date range)
  - Delegate fetch to a configurable adapter (default: YFinanceAdapter)
  - Upsert Security records into the securities table
  - Upsert DailyMarketBar rows into daily_market_bars (ON CONFLICT DO NOTHING)
  - Return a structured IngestionResult

Does NOT own: feature computation, signal generation, or ordering.
"""
from __future__ import annotations

import datetime as dt
import logging

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from infra.db.models import DailyMarketBar, Security
from services.data_ingestion.adapters.yfinance_adapter import YFinanceAdapter
from services.data_ingestion.models import (
    BarRecord,
    IngestionRequest,
    IngestionResult,
    IngestionStatus,
    TickerResult,
)

logger = logging.getLogger(__name__)


def _build_default_adapter() -> object:
    """Pick the adapter implementation based on APIS_DATA_SOURCE.

    Defaults to YFinanceAdapter if settings cannot be loaded (e.g. in minimal
    test contexts) or if the chosen adapter fails to import — this keeps the
    service usable when Norgate/NDU is not installed on a given host.
    """
    try:
        from config.settings import DataSource, get_settings
        source = get_settings().data_source
    except Exception as exc:  # noqa: BLE001
        logger.debug("settings unavailable, falling back to yfinance: %s", exc)
        return YFinanceAdapter()

    if source == DataSource.POINTINTIME:
        try:
            from services.data_ingestion.adapters.pointintime_adapter import (
                PointInTimeAdapter,
            )
            return PointInTimeAdapter()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "PointInTimeAdapter unavailable (%s) — falling back to yfinance",
                exc,
            )
            return YFinanceAdapter()

    return YFinanceAdapter()


class DataIngestionService:
    """Orchestrates fetching and persisting daily market bars.

    Args:
        adapter: Any adapter exposing ``fetch_bulk(tickers, period=...)``
                 and ``fetch_bars(ticker, period=...)``.  Defaults to
                 ``YFinanceAdapter()``.
    """

    def __init__(self, adapter: object | None = None) -> None:
        self._adapter = adapter or _build_default_adapter()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest_universe_bars(
        self,
        session: Session,
        request: IngestionRequest,
    ) -> IngestionResult:
        """Fetch and persist bars for all tickers in *request*.

        Each ticker is processed independently so a failure on one does
        not abort the rest.
        """
        result = IngestionResult(request=request)

        bulk = self._adapter.fetch_bulk(
            request.tickers,
            period=request.period,
            start=request.start_date,
            end=request.end_date,
        )

        for ticker in request.tickers:
            bars = bulk.get(ticker, [])
            ticker_result = self._ingest_ticker(session, ticker, bars)
            result.ticker_results.append(ticker_result)

        result.finalise()
        logger.info(
            "Ingestion complete: %d tickers, %d bars persisted, status=%s",
            len(request.tickers),
            result.total_bars_persisted,
            result.status,
        )
        return result

    def ingest_single_ticker(
        self,
        session: Session,
        ticker: str,
        period: str = "1y",
        start_date: dt.date | None = None,
        end_date: dt.date | None = None,
    ) -> TickerResult:
        """Convenience method: ingest one ticker and return its TickerResult."""
        bars = self._adapter.fetch_bars(
            ticker,
            period=period,
            start=start_date,
            end=end_date,
        )
        return self._ingest_ticker(session, ticker, bars)

    # ------------------------------------------------------------------
    # Security upsert
    # ------------------------------------------------------------------

    def get_or_create_security(self, session: Session, ticker: str) -> Security:
        """Return the Security ORM row for *ticker*, creating it if absent.

        Metadata (name, sector, etc.) are populated lazily from yfinance info
        on first insert and left unchanged on subsequent calls.
        """
        obj = session.execute(
            sa.select(Security).where(Security.ticker == ticker)
        ).scalar_one_or_none()

        if obj is not None:
            return obj

        # Attempt to pull basic metadata from yfinance (best-effort)
        name = ticker
        sector: str | None = None
        industry: str | None = None
        exchange: str | None = None
        currency: str | None = "USD"

        try:
            import yfinance as yf
            info = yf.Ticker(ticker).info or {}
            name = info.get("shortName") or info.get("longName") or ticker
            sector = info.get("sector")
            industry = info.get("industry")
            exchange = info.get("exchange")
            currency = info.get("currency", "USD")
        except Exception:  # noqa: BLE001
            pass  # metadata is optional; proceed with defaults

        obj = Security(
            ticker=ticker,
            name=name,
            asset_type="equity",
            exchange=exchange,
            sector=sector,
            industry=industry,
            country="US",
            currency=currency,
            is_active=True,
        )
        session.add(obj)
        session.flush()  # get the UUID assigned without committing
        logger.debug("Created security record for %s (id=%s)", ticker, obj.id)
        return obj

    # ------------------------------------------------------------------
    # Bar persistence
    # ------------------------------------------------------------------

    def persist_bars(
        self,
        session: Session,
        security_id: object,
        bars: list[BarRecord],
    ) -> int:
        """Upsert bars into daily_market_bars; return count of rows inserted.

        Uses INSERT … ON CONFLICT DO NOTHING so re-running the same period
        is safe.
        """
        if not bars:
            return 0

        rows = [
            {
                "security_id": security_id,
                "trade_date": b.trade_date,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "adjusted_close": b.adjusted_close,
                "volume": b.volume,
                "vwap": b.vwap,
            }
            for b in bars
        ]

        stmt = (
            pg_insert(DailyMarketBar)
            .values(rows)
            .on_conflict_do_nothing(
                index_elements=["security_id", "trade_date"]
            )
        )
        # Use the postgresql dialect insert (already imported via sqlalchemy)
        result = session.execute(stmt)
        inserted = result.rowcount if result.rowcount >= 0 else len(rows)
        return inserted

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ingest_ticker(
        self,
        session: Session,
        ticker: str,
        bars: list[BarRecord],
    ) -> TickerResult:
        if not bars:
            return TickerResult(
                ticker=ticker,
                status=IngestionStatus.FAILED,
                error="No bars returned from adapter",
            )

        try:
            security = self.get_or_create_security(session, ticker)
            inserted = self.persist_bars(session, security.id, bars)
            return TickerResult(
                ticker=ticker,
                status=IngestionStatus.SUCCESS,
                bars_fetched=len(bars),
                bars_persisted=inserted,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to persist bars for %s: %s", ticker, exc)
            session.rollback()
            return TickerResult(
                ticker=ticker,
                status=IngestionStatus.FAILED,
                error=str(exc),
            )

