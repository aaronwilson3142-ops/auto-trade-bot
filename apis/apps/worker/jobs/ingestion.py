"""
Worker job: market-data ingestion and feature refresh.

Functions
---------
run_market_data_ingestion  — fetch OHLCV bars for the full universe
run_feature_refresh        — compute and persist baseline features

Both functions require a database session factory.  When session_factory is
None (e.g. in unit tests that only test the no-DB fallback path) the job
logs a warning and returns immediately with status "skipped_no_session".

Design rules
------------
- Does NOT write to ApiAppState directly (ingestion has no state field to
  populate).  The result dict is returned for observability.
- Exceptions are caught; jobs must never crash the APScheduler thread.
- Services are injectable for testing.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Optional

from config.logging_config import get_logger
from config.settings import Settings, get_settings
from config.universe import get_universe_tickers

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# run_market_data_ingestion
# ---------------------------------------------------------------------------

def run_market_data_ingestion(
    settings: Optional[Settings] = None,
    session_factory: Optional[Callable] = None,
    ingestion_service: Optional[Any] = None,
) -> dict[str, Any]:
    """Fetch and persist OHLCV bars for the full universe.

    Args:
        settings:          Settings instance.  Defaults to get_settings().
        session_factory:   Callable that returns a SQLAlchemy Session.  If
                           None, the job is skipped (no-DB path for tests).
        ingestion_service: DataIngestionService instance.  Defaults to a
                           freshly constructed DataIngestionService().

    Returns:
        dict with keys: status, tickers_attempted, bars_persisted, errors,
        run_at.
    """
    cfg = settings or get_settings()
    run_at = dt.datetime.now(dt.timezone.utc)

    logger.info("ingestion_job_starting", run_at=run_at.isoformat())

    if session_factory is None:
        logger.warning("ingestion_job_skipped_no_session_factory")
        return {
            "status": "skipped_no_session",
            "tickers_attempted": 0,
            "bars_persisted": 0,
            "errors": [],
            "run_at": run_at.isoformat(),
        }

    try:
        from services.data_ingestion.models import IngestionRequest
        from services.data_ingestion.service import DataIngestionService

        svc = ingestion_service or DataIngestionService()
        tickers = get_universe_tickers()

        request = IngestionRequest(
            tickers=tickers,
            period="1y",
        )

        with session_factory() as session:
            result = svc.ingest_universe_bars(session, request)
            session.commit()

        logger.info(
            "ingestion_job_complete",
            tickers=len(tickers),
            bars_persisted=result.total_bars_persisted,
            status=result.status.value,
        )
        return {
            "status": result.status.value,
            "tickers_attempted": len(tickers),
            "bars_persisted": result.total_bars_persisted,
            "errors": [r.error_message for r in result.ticker_results if r.error_message],
            "run_at": run_at.isoformat(),
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("ingestion_job_failed", error=str(exc))
        return {
            "status": "error",
            "tickers_attempted": 0,
            "bars_persisted": 0,
            "errors": [str(exc)],
            "run_at": run_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# run_feature_refresh
# ---------------------------------------------------------------------------

def run_feature_refresh(
    settings: Optional[Settings] = None,
    session_factory: Optional[Callable] = None,
    feature_store_service: Optional[Any] = None,
) -> dict[str, Any]:
    """Compute and persist baseline features for all universe securities.

    Args:
        settings:             Settings instance.  Defaults to get_settings().
        session_factory:      Callable that returns a SQLAlchemy Session.  If
                              None, the job is skipped.
        feature_store_service: FeatureStoreService instance.  Defaults to a
                              freshly constructed FeatureStoreService().

    Returns:
        dict with keys: status, securities_processed, errors, run_at.
    """
    cfg = settings or get_settings()
    run_at = dt.datetime.now(dt.timezone.utc)

    logger.info("feature_refresh_job_starting", run_at=run_at.isoformat())

    if session_factory is None:
        logger.warning("feature_refresh_job_skipped_no_session_factory")
        return {
            "status": "skipped_no_session",
            "securities_processed": 0,
            "errors": [],
            "run_at": run_at.isoformat(),
        }

    try:
        import sqlalchemy as sa

        from infra.db.models import Security
        from services.feature_store.service import FeatureStoreService

        svc = feature_store_service or FeatureStoreService()
        errors: list[str] = []
        processed = 0

        with session_factory() as session:
            securities = session.execute(sa.select(Security)).scalars().all()
            svc.ensure_feature_catalog(session)

            for sec in securities:
                try:
                    svc.compute_and_persist(session, sec.id, sec.ticker)
                    processed += 1
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{sec.ticker}: {exc}")
                    logger.warning(
                        "feature_refresh_ticker_error",
                        ticker=sec.ticker,
                        error=str(exc),
                    )

            session.commit()

        logger.info(
            "feature_refresh_job_complete",
            securities_processed=processed,
            errors=len(errors),
        )
        return {
            "status": "ok" if not errors else "partial",
            "securities_processed": processed,
            "errors": errors,
            "run_at": run_at.isoformat(),
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("feature_refresh_job_failed", error=str(exc))
        return {
            "status": "error",
            "securities_processed": 0,
            "errors": [str(exc)],
            "run_at": run_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# run_feature_enrichment
# ---------------------------------------------------------------------------

def run_feature_enrichment(
    app_state: Any,
    settings: Optional[Settings] = None,
    enrichment_service: Optional[Any] = None,
) -> dict[str, Any]:
    """Assess the current macro regime from active policy signals.

    Reads app_state.latest_policy_signals to derive the macro regime and
    stores the result in app_state.current_macro_regime.  When no policy
    signals are available the regime is set to NEUTRAL.

    Per-ticker enrichment (theme scores, news sentiment) occurs inside
    run_signal_generation where the SignalEngineService injects
    FeatureEnrichmentService before strategy scoring.

    Args:
        app_state:          Shared ApiAppState.
        settings:           Settings instance.
        enrichment_service: FeatureEnrichmentService instance for injection.

    Returns:
        dict with keys: status, macro_regime, signal_count, run_at.
    """
    _settings = settings or get_settings()
    run_at = dt.datetime.now(dt.timezone.utc)

    logger.info("feature_enrichment_job_starting", run_at=run_at.isoformat())

    try:
        from services.feature_store.enrichment import FeatureEnrichmentService

        svc = enrichment_service or FeatureEnrichmentService()
        policy_signals = getattr(app_state, "latest_policy_signals", [])
        macro_regime = svc.assess_macro_regime(policy_signals)

        if hasattr(app_state, "current_macro_regime"):
            app_state.current_macro_regime = macro_regime

        logger.info(
            "feature_enrichment_job_complete",
            macro_regime=macro_regime,
            signal_count=len(policy_signals),
        )
        return {
            "status": "ok",
            "macro_regime": macro_regime,
            "signal_count": len(policy_signals),
            "run_at": run_at.isoformat(),
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("feature_enrichment_job_failed", error=str(exc))
        return {
            "status": "error",
            "macro_regime": "NEUTRAL",
            "signal_count": 0,
            "run_at": run_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# run_fundamentals_refresh
# ---------------------------------------------------------------------------

def run_fundamentals_refresh(
    app_state: Any,
    settings: Optional[Settings] = None,
    fundamentals_service: Optional[Any] = None,
    tickers: Optional[list] = None,
) -> dict[str, Any]:
    """Fetch fundamental metrics for all universe tickers and store in app_state.

    Fetches P/E, forward P/E, PEG ratio, EPS growth, revenue growth, and
    earnings surprise from yfinance (consensus data) for every ticker in the
    universe.  Results are stored as ``app_state.latest_fundamentals`` so
    ``FeatureEnrichmentService.enrich()`` can apply valuation overlays during
    signal generation.

    Scheduled at 06:18 ET, between feature_refresh (06:15) and
    feature_enrichment (06:22), so fundamentals are available before
    signal scoring begins.

    Args:
        app_state:            Shared ApiAppState.
        settings:             Settings instance.  Defaults to get_settings().
        fundamentals_service: FundamentalsService instance. Defaults to a
                              freshly constructed FundamentalsService().
        tickers:              List of ticker symbols.  Defaults to the
                              full universe from get_universe_tickers().

    Returns:
        dict with keys: status, tickers_fetched, errors, run_at.
    """
    _settings = settings or get_settings()
    run_at = dt.datetime.now(dt.timezone.utc)

    logger.info("fundamentals_refresh_job_starting", run_at=run_at.isoformat())

    try:
        from services.market_data.fundamentals import FundamentalsService

        svc = fundamentals_service or FundamentalsService()
        _tickers = tickers or get_universe_tickers()
        data = svc.fetch_batch(_tickers)

        if hasattr(app_state, "latest_fundamentals"):
            app_state.latest_fundamentals = data

        logger.info(
            "fundamentals_refresh_job_complete",
            tickers_fetched=len(data),
        )
        return {
            "status": "ok",
            "tickers_fetched": len(data),
            "errors": [],
            "run_at": run_at.isoformat(),
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("fundamentals_refresh_job_failed", error=str(exc))
        return {
            "status": "error",
            "tickers_fetched": 0,
            "errors": [str(exc)],
            "run_at": run_at.isoformat(),
        }


# ---------------------------------------------------------------------------
# run_alternative_data_ingestion  (Phase 36)
# ---------------------------------------------------------------------------

def run_alternative_data_ingestion(
    app_state: Any,
    settings: Optional[Settings] = None,
    alt_data_service: Optional[Any] = None,
    adapter: Optional[Any] = None,
    tickers: Optional[list] = None,
) -> dict[str, Any]:
    """Fetch alternative data (social sentiment) for the universe and store in app_state.

    Runs the SocialMentionAdapter (or an injected adapter) for all universe
    tickers and stores the resulting AlternativeDataRecord list in
    ``app_state.latest_alternative_data`` (newest first, capped at 500 records).

    Scheduled at 06:05 ET — between market_data_ingestion (06:00) and
    intel_feed_ingestion (06:10) so alternative signals are available before
    the signal-generation pipeline starts.

    Args:
        app_state:        Shared ApiAppState.
        settings:         Settings instance.  Defaults to get_settings().
        alt_data_service: AlternativeDataService instance (injectable for tests).
        adapter:          BaseAlternativeAdapter instance (injectable for tests).
        tickers:          List of ticker symbols.  Defaults to universe tickers.

    Returns:
        dict with keys: status, records_ingested, tickers_processed, run_at.
    """
    _settings = settings or get_settings()
    run_at = dt.datetime.now(dt.timezone.utc)

    logger.info("alternative_data_ingestion_job_starting", run_at=run_at.isoformat())

    try:
        from services.alternative_data.adapters import SocialMentionAdapter
        from services.alternative_data.service import AlternativeDataService

        svc = alt_data_service or AlternativeDataService()
        _adapter = adapter or SocialMentionAdapter()
        _tickers = tickers or get_universe_tickers()

        count = svc.ingest(_adapter, _tickers)

        # Merge into app_state (newest-first, cap at 500)
        if hasattr(app_state, "latest_alternative_data"):
            new_records = svc.get_records(limit=500)
            app_state.latest_alternative_data = new_records

        logger.info(
            "alternative_data_ingestion_job_complete",
            records_ingested=count,
            tickers_processed=len(_tickers),
        )
        return {
            "status": "ok",
            "records_ingested": count,
            "tickers_processed": len(_tickers),
            "run_at": run_at.isoformat(),
        }

    except Exception as exc:  # noqa: BLE001
        logger.error("alternative_data_ingestion_job_failed", error=str(exc))
        return {
            "status": "error",
            "records_ingested": 0,
            "tickers_processed": 0,
            "run_at": run_at.isoformat(),
        }
