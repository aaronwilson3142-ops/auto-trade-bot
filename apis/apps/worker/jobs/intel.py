"""Worker job: intelligence feed ingestion.

Populates app_state.latest_policy_signals and app_state.latest_news_insights
by running the built-in seed services through the full intel NLP pipelines:

  PolicyEventSeedService  →  MacroPolicyEngineService.process_batch()
                          →  app_state.latest_policy_signals

  NewsSeedService         →  NewsIntelligenceService.process_batch()
                          →  app_state.latest_news_insights

After this job runs, the feature_enrichment job (06:22) reads
app_state.latest_policy_signals to derive the macro regime, and
run_signal_generation (06:30) passes both lists to SignalEngineService so
the enrichment pipeline can produce non-neutral theme/macro/sentiment overlays.

In production, replace the seed services with adapters that call real
news and policy data APIs.  The injectable *_seed_service parameters make
that swap transparent to this job function.

Design rules
------------
- Writes directly to ApiAppState (this job owns latest_policy_signals and
  latest_news_insights).
- Exceptions in either sub-pipeline are caught individually; a failure in
  one does not prevent the other from running.
- The job never raises.  Caller observes status "ok", "partial", or "error".
- Services are injectable for testing.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

from config.logging_config import get_logger
from config.settings import Settings, get_settings

logger = get_logger(__name__)


def run_intel_feed_ingestion(
    app_state: Any,
    settings: Settings | None = None,
    policy_engine: Any | None = None,
    news_service: Any | None = None,
    policy_seed_service: Any | None = None,
    news_seed_service: Any | None = None,
) -> dict[str, Any]:
    """Ingest daily macro policy events and news items into app_state.

    Steps
    -----
    1. Generate PolicyEvent objects from PolicyEventSeedService.
    2. Run them through MacroPolicyEngineService.process_batch().
    3. Store resulting PolicySignal list in app_state.latest_policy_signals.
    4. Generate NewsItem objects from NewsSeedService.
    5. Run them through NewsIntelligenceService.process_batch().
    6. Store resulting NewsInsight list in app_state.latest_news_insights.

    Args:
        app_state:           Shared ApiAppState.
        settings:            Settings instance.  Defaults to get_settings().
        policy_engine:       MacroPolicyEngineService instance for injection.
        news_service:        NewsIntelligenceService instance for injection.
        policy_seed_service: PolicyEventSeedService instance for injection.
        news_seed_service:   NewsSeedService instance for injection.

    Returns:
        dict with keys: status, policy_signals_count, news_insights_count,
        errors, run_at.
    """
    _settings = settings or get_settings()
    run_at = dt.datetime.now(dt.UTC)
    errors: list[str] = []

    logger.info("intel_feed_ingestion_starting", run_at=run_at.isoformat())

    policy_signals: list[Any] = []
    news_insights: list[Any] = []

    # ── Policy signal ingestion ───────────────────────────────────────────────
    try:
        from services.macro_policy_engine.seed import PolicyEventSeedService
        from services.macro_policy_engine.service import MacroPolicyEngineService

        p_engine = policy_engine or MacroPolicyEngineService()
        p_seed = policy_seed_service or PolicyEventSeedService()

        events = p_seed.get_daily_events()
        policy_signals = p_engine.process_batch(events)

        logger.info(
            "intel_feed_policy_done",
            events_generated=len(events),
            signals_retained=len(policy_signals),
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"policy_ingestion: {exc}")
        logger.error("intel_feed_policy_failed", error=str(exc))

    # ── News insight ingestion ────────────────────────────────────────────────
    try:
        from services.news_intelligence.seed import NewsSeedService
        from services.news_intelligence.service import NewsIntelligenceService

        n_svc = news_service or NewsIntelligenceService()
        n_seed = news_seed_service or NewsSeedService()

        items = n_seed.get_daily_items()
        news_insights = n_svc.process_batch(items)

        logger.info(
            "intel_feed_news_done",
            items_generated=len(items),
            insights_retained=len(news_insights),
        )
    except Exception as exc:  # noqa: BLE001
        errors.append(f"news_ingestion: {exc}")
        logger.error("intel_feed_news_failed", error=str(exc))

    # ── Persist to app_state ──────────────────────────────────────────────────
    if hasattr(app_state, "latest_policy_signals"):
        app_state.latest_policy_signals = policy_signals
    if hasattr(app_state, "latest_news_insights"):
        app_state.latest_news_insights = news_insights

    # "error" only when BOTH pipelines failed; otherwise "partial" or "ok"
    if len(errors) == 2:
        overall_status = "error"
    elif errors:
        overall_status = "partial"
    else:
        overall_status = "ok"

    logger.info(
        "intel_feed_ingestion_complete",
        policy_signals=len(policy_signals),
        news_insights=len(news_insights),
        status=overall_status,
    )
    return {
        "status": overall_status,
        "policy_signals_count": len(policy_signals),
        "news_insights_count": len(news_insights),
        "errors": errors,
        "run_at": run_at.isoformat(),
    }
