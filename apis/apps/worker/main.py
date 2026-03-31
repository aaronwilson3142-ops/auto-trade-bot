"""
APIS Worker application — APScheduler entry point.

Schedule
--------
All times are Eastern Time (US/Eastern).  Jobs only fire on weekdays.

  05:30  run_broker_token_refresh      — refresh OAuth token before market open
  06:00  run_market_data_ingestion     — fetch OHLCV bars for the universe
  06:05  run_alternative_data_ingestion — social mention + alt data ingest
  06:10  run_intel_feed_ingestion      — seed + process policy events & news items
  06:15  run_feature_refresh           — compute / persist baseline features
  06:16  run_correlation_refresh       — pairwise Pearson correlation matrix (Phase 39)
  06:17  run_liquidity_refresh         — dollar_volume_20d per ticker from feature store (Phase 41)
  06:18  run_fundamentals_refresh      — fetch P/E, PEG, EPS growth from yfinance
  06:19  run_var_refresh               — portfolio VaR & CVaR from bar history (Phase 43)
  06:20  run_regime_detection          — classify market regime + set adaptive weights
  06:21  run_stress_test               — historical-scenario stress test (Phase 44)
  06:22  run_feature_enrichment        — assess macro regime from policy signals
  06:23  run_earnings_refresh          — earnings calendar + proximity gate (Phase 45)
  06:25  run_universe_refresh          — compute active universe from overrides + quality (Phase 48)
  06:30  run_signal_generation         — generate signals per strategy
  17:20  run_signal_quality_update     — match closed trades to signals, compute per-strategy quality (Phase 46)
  06:45  run_ranking_generation        — composite score + write to ApiAppState
  06:52  run_weight_optimization       — Sharpe-proportional strategy weights
  09:35  run_paper_trading_cycle       — morning execution: rank → risk → execute
  12:00  run_paper_trading_cycle       — midday execution: re-rank → risk → execute
  17:00  run_daily_evaluation          — DailyScorecard → app_state
  17:15  run_attribution_analysis      — attribution log
  17:20  run_signal_quality_update     — per-strategy signal quality (Phase 46)
  17:30  run_generate_daily_report     — DailyOperationalReport → app_state
  17:45  run_publish_operator_summary  — structured operator log entry
  18:00  run_generate_improvement_proposals — proposals → app_state
  18:15  run_auto_execute_proposals    — auto-execute PROMOTED proposals → app_state

All jobs are fire-and-forget: exceptions are caught inside each function
so the scheduler thread never dies.

The worker imports ApiAppState from the API module so that a co-process
deployment (API + worker in one process) shares a single state object.
For multi-process deployments, replace with a Redis-backed state bridge.
"""
from __future__ import annotations

import signal
import sys

import pytz
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from apps.api.state import get_app_state
from apps.worker.jobs import (
    run_alternative_data_ingestion,
    run_attribution_analysis,
    run_auto_execute_proposals,
    run_broker_token_refresh,
    run_correlation_refresh,
    run_daily_evaluation,
    run_feature_enrichment,
    run_feature_refresh,
    run_fundamentals_refresh,
    run_generate_daily_report,
    run_generate_improvement_proposals,
    run_intel_feed_ingestion,
    run_liquidity_refresh,
    run_market_data_ingestion,
    run_paper_trading_cycle,
    run_publish_operator_summary,
    run_ranking_generation,
    run_regime_detection,
    run_signal_generation,
    run_var_refresh,
    run_stress_test,
    run_earnings_refresh,
    run_signal_quality_update,
    run_weight_optimization,
    run_universe_refresh,
    run_rebalance_check,
    run_fill_quality_update,
    run_fill_quality_attribution,
    run_readiness_report_update,
)
from config.logging_config import configure_logging, get_logger
from config.settings import get_settings

settings = get_settings()
configure_logging(log_level=settings.log_level)
logger = get_logger(__name__)

_ET = pytz.timezone("US/Eastern")


# ---------------------------------------------------------------------------
# Session factory (real DB path — None-safe for environments without a DB)
# ---------------------------------------------------------------------------

def _make_session_factory():
    """Return a SQLAlchemy session factory, or None if DB is unavailable."""
    try:
        from infra.db.session import SessionLocal
        return SessionLocal
    except Exception as exc:  # noqa: BLE001
        logger.warning("db_unavailable_jobs_will_skip_db_steps", error=str(exc))
        return None


# ---------------------------------------------------------------------------
# Job wrappers (bind app_state + settings + session_factory at schedule time)
# ---------------------------------------------------------------------------

def _job_market_data_ingestion() -> None:
    run_market_data_ingestion(
        settings=settings,
        session_factory=_make_session_factory(),
    )


def _job_alternative_data_ingestion() -> None:
    run_alternative_data_ingestion(
        app_state=get_app_state(),
        settings=settings,
    )


def _job_intel_feed_ingestion() -> None:
    run_intel_feed_ingestion(
        app_state=get_app_state(),
        settings=settings,
    )


def _job_feature_refresh() -> None:
    run_feature_refresh(
        settings=settings,
        session_factory=_make_session_factory(),
    )


def _job_correlation_refresh() -> None:
    run_correlation_refresh(
        app_state=get_app_state(),
        settings=settings,
        session_factory=_make_session_factory(),
    )


def _job_liquidity_refresh() -> None:
    run_liquidity_refresh(
        app_state=get_app_state(),
        settings=settings,
        session_factory=_make_session_factory(),
    )


def _job_fundamentals_refresh() -> None:
    run_fundamentals_refresh(
        app_state=get_app_state(),
        settings=settings,
    )


def _job_var_refresh() -> None:
    run_var_refresh(
        app_state=get_app_state(),
        settings=settings,
        session_factory=_make_session_factory(),
    )


def _job_stress_test() -> None:
    run_stress_test(
        app_state=get_app_state(),
        settings=settings,
    )


def _job_earnings_refresh() -> None:
    run_earnings_refresh(
        app_state=get_app_state(),
        settings=settings,
    )


def _job_regime_detection() -> None:
    run_regime_detection(
        app_state=get_app_state(),
        settings=settings,
        session_factory=_make_session_factory(),
    )


def _job_feature_enrichment() -> None:
    run_feature_enrichment(
        app_state=get_app_state(),
        settings=settings,
    )


def _job_signal_generation() -> None:
    run_signal_generation(
        app_state=get_app_state(),
        settings=settings,
        session_factory=_make_session_factory(),
    )


def _job_ranking_generation() -> None:
    run_ranking_generation(
        app_state=get_app_state(),
        settings=settings,
    )


def _job_daily_evaluation() -> None:
    run_daily_evaluation(
        app_state=get_app_state(),
        settings=settings,
    )


def _job_attribution_analysis() -> None:
    run_attribution_analysis(
        app_state=get_app_state(),
        settings=settings,
    )


def _job_generate_daily_report() -> None:
    run_generate_daily_report(
        app_state=get_app_state(),
        settings=settings,
    )


def _job_publish_operator_summary() -> None:
    run_publish_operator_summary(
        app_state=get_app_state(),
        settings=settings,
    )


def _job_generate_improvement_proposals() -> None:
    run_generate_improvement_proposals(
        app_state=get_app_state(),
        settings=settings,
    )


def _job_auto_execute_proposals() -> None:
    run_auto_execute_proposals(
        app_state=get_app_state(),
        settings=settings,
        session_factory=_make_session_factory(),
    )


def _job_weight_optimization() -> None:
    run_weight_optimization(
        app_state=get_app_state(),
        settings=settings,
        session_factory=_make_session_factory(),
    )


def _job_signal_quality_update() -> None:
    run_signal_quality_update(
        app_state=get_app_state(),
        settings=settings,
        session_factory=_make_session_factory(),
    )


def _job_universe_refresh() -> None:
    run_universe_refresh(
        app_state=get_app_state(),
        settings=settings,
        session_factory=_make_session_factory(),
    )


def _job_rebalance_check() -> None:
    run_rebalance_check(
        app_state=get_app_state(),
        settings=settings,
    )


def _job_fill_quality_update() -> None:
    run_fill_quality_update(
        app_state=get_app_state(),
        settings=settings,
    )


def _job_fill_quality_attribution() -> None:
    run_fill_quality_attribution(
        app_state=get_app_state(),
        settings=settings,
        session_factory=_make_session_factory(),
    )


def _job_readiness_report_update() -> None:
    run_readiness_report_update(
        app_state=get_app_state(),
        settings=settings,
        session_factory=_make_session_factory(),
    )


def _job_paper_trading_cycle() -> None:
    run_paper_trading_cycle(
        app_state=get_app_state(),
        settings=settings,
    )


def _job_broker_token_refresh() -> None:
    run_broker_token_refresh(
        app_state=get_app_state(),
        settings=settings,
    )


# ---------------------------------------------------------------------------
# Scheduler factory
# ---------------------------------------------------------------------------

def build_scheduler() -> BackgroundScheduler:
    """Create and configure the APScheduler BackgroundScheduler.

    Returns a configured (but not yet started) scheduler so it can be
    inspected or started by the caller.
    """
    scheduler = BackgroundScheduler(timezone=_ET)

    _weekday = "mon-fri"

    # Pre-market token refresh — before any data ingestion or trading
    scheduler.add_job(
        _job_broker_token_refresh,
        CronTrigger(day_of_week=_weekday, hour=5, minute=30, timezone=_ET),
        id="broker_token_refresh",
        name="Broker Token Refresh",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Morning pipeline — before market open
    scheduler.add_job(
        _job_market_data_ingestion,
        CronTrigger(day_of_week=_weekday, hour=6, minute=0, timezone=_ET),
        id="market_data_ingestion",
        name="Market Data Ingestion",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_alternative_data_ingestion,
        CronTrigger(day_of_week=_weekday, hour=6, minute=5, timezone=_ET),
        id="alternative_data_ingestion",
        name="Alternative Data Ingestion",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_intel_feed_ingestion,
        CronTrigger(day_of_week=_weekday, hour=6, minute=10, timezone=_ET),
        id="intel_feed_ingestion",
        name="Intel Feed Ingestion",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_feature_refresh,
        CronTrigger(day_of_week=_weekday, hour=6, minute=15, timezone=_ET),
        id="feature_refresh",
        name="Feature Refresh",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_correlation_refresh,
        CronTrigger(day_of_week=_weekday, hour=6, minute=16, timezone=_ET),
        id="correlation_refresh",
        name="Correlation Matrix Refresh",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_liquidity_refresh,
        CronTrigger(day_of_week=_weekday, hour=6, minute=17, timezone=_ET),
        id="liquidity_refresh",
        name="Liquidity Data Refresh",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_fundamentals_refresh,
        CronTrigger(day_of_week=_weekday, hour=6, minute=18, timezone=_ET),
        id="fundamentals_refresh",
        name="Fundamentals Refresh",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_var_refresh,
        CronTrigger(day_of_week=_weekday, hour=6, minute=19, timezone=_ET),
        id="var_refresh",
        name="Portfolio VaR & CVaR Refresh",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_regime_detection,
        CronTrigger(day_of_week=_weekday, hour=6, minute=20, timezone=_ET),
        id="regime_detection",
        name="Market Regime Detection",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_stress_test,
        CronTrigger(day_of_week=_weekday, hour=6, minute=21, timezone=_ET),
        id="stress_test",
        name="Portfolio Stress Test",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_feature_enrichment,
        CronTrigger(day_of_week=_weekday, hour=6, minute=22, timezone=_ET),
        id="feature_enrichment",
        name="Feature Enrichment",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_earnings_refresh,
        CronTrigger(day_of_week=_weekday, hour=6, minute=23, timezone=_ET),
        id="earnings_refresh",
        name="Earnings Calendar Refresh",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_universe_refresh,
        CronTrigger(day_of_week=_weekday, hour=6, minute=25, timezone=_ET),
        id="universe_refresh",
        name="Universe Refresh",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_rebalance_check,
        CronTrigger(day_of_week=_weekday, hour=6, minute=26, timezone=_ET),
        id="rebalance_check",
        name="Portfolio Rebalance Check",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_signal_generation,
        CronTrigger(day_of_week=_weekday, hour=6, minute=30, timezone=_ET),
        id="signal_generation",
        name="Signal Generation",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_ranking_generation,
        CronTrigger(day_of_week=_weekday, hour=6, minute=45, timezone=_ET),
        id="ranking_generation",
        name="Ranking Generation",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_weight_optimization,
        CronTrigger(day_of_week=_weekday, hour=6, minute=52, timezone=_ET),
        id="weight_optimization",
        name="Strategy Weight Optimization",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Evening pipeline — after market close
    scheduler.add_job(
        _job_daily_evaluation,
        CronTrigger(day_of_week=_weekday, hour=17, minute=0, timezone=_ET),
        id="daily_evaluation",
        name="Daily Evaluation",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_attribution_analysis,
        CronTrigger(day_of_week=_weekday, hour=17, minute=15, timezone=_ET),
        id="attribution_analysis",
        name="Attribution Analysis",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_signal_quality_update,
        CronTrigger(day_of_week=_weekday, hour=17, minute=20, timezone=_ET),
        id="signal_quality_update",
        name="Signal Quality Update",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_generate_daily_report,
        CronTrigger(day_of_week=_weekday, hour=17, minute=30, timezone=_ET),
        id="generate_daily_report",
        name="Generate Daily Report",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_publish_operator_summary,
        CronTrigger(day_of_week=_weekday, hour=17, minute=45, timezone=_ET),
        id="publish_operator_summary",
        name="Publish Operator Summary",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_generate_improvement_proposals,
        CronTrigger(day_of_week=_weekday, hour=18, minute=0, timezone=_ET),
        id="generate_improvement_proposals",
        name="Generate Improvement Proposals",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_auto_execute_proposals,
        CronTrigger(day_of_week=_weekday, hour=18, minute=15, timezone=_ET),
        id="auto_execute_proposals",
        name="Auto-Execute Improvement Proposals",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_fill_quality_update,
        CronTrigger(day_of_week=_weekday, hour=18, minute=30, timezone=_ET),
        id="fill_quality_update",
        name="Order Fill Quality Update",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_fill_quality_attribution,
        CronTrigger(day_of_week=_weekday, hour=18, minute=32, timezone=_ET),
        id="fill_quality_attribution",
        name="Fill Quality Alpha-Decay Attribution",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_readiness_report_update,
        CronTrigger(day_of_week=_weekday, hour=18, minute=45, timezone=_ET),
        id="readiness_report_update",
        name="Live-Mode Readiness Report Update",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Paper trading cycles — market hours only; mode guard inside the job
    scheduler.add_job(
        _job_paper_trading_cycle,
        CronTrigger(day_of_week=_weekday, hour=9, minute=35, timezone=_ET),
        id="paper_trading_cycle_morning",
        name="Paper Trading Cycle (Morning)",
        replace_existing=True,
        misfire_grace_time=300,
    )
    scheduler.add_job(
        _job_paper_trading_cycle,
        CronTrigger(day_of_week=_weekday, hour=12, minute=0, timezone=_ET),
        id="paper_trading_cycle_midday",
        name="Paper Trading Cycle (Midday)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    return scheduler


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _setup_alert_service() -> None:
    """Initialize WebhookAlertService from settings and store in app_state.

    Called once at worker startup.  Silently skips when webhook_url is empty.
    """
    app_state = get_app_state()
    webhook_url = getattr(settings, "webhook_url", "")
    webhook_secret = getattr(settings, "webhook_secret", "")
    if webhook_url:
        try:
            from services.alerting.service import make_alert_service
            app_state.alert_service = make_alert_service(
                webhook_url=webhook_url,
                secret=webhook_secret,
            )
            logger.info("webhook_alert_service_initialized", url=webhook_url[:30] + "...")
        except Exception as exc:  # noqa: BLE001
            logger.warning("webhook_alert_service_init_failed", error=str(exc))


def main() -> None:
    """Start the APIS worker scheduler and block until interrupted."""
    logger.info(
        "apis_worker_starting",
        mode=settings.operating_mode.value,
        kill_switch=settings.is_kill_switch_active,
    )

    _setup_alert_service()
    scheduler = build_scheduler()
    scheduler.start()

    # Log the registered jobs for visibility
    for job in scheduler.get_jobs():
        logger.info(
            "scheduled_job_registered",
            job_id=job.id,
            name=job.name,
            next_run=str(job.next_run_time),
        )

    logger.info("apis_worker_started", job_count=len(scheduler.get_jobs()))

    # Graceful shutdown on SIGTERM / SIGINT
    def _shutdown(signum, frame):  # noqa: ANN001
        logger.info("apis_worker_shutdown_signal_received", signal=signum)
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    # Block the main thread
    try:
        import time
        while True:
            time.sleep(60)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown(wait=False)
        logger.info("apis_worker_stopped")


if __name__ == "__main__":
    main()
