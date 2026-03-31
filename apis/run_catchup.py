"""
Manual pipeline catchup script.
Runs all missed morning jobs in sequence for today.
Run from the apis/ directory with the venv Python.
"""
import traceback

from apps.api.state import get_app_state
from config.logging_config import configure_logging, get_logger
from config.settings import get_settings
from infra.db.session import SessionLocal

settings = get_settings()
configure_logging(log_level="INFO")
logger = get_logger("catchup")

app_state = get_app_state()
session_factory = SessionLocal


def _run(label, fn, **kwargs):
    print(f"\n{'='*60}")
    print(f"  RUNNING: {label}")
    print(f"{'='*60}")
    try:
        fn(**kwargs)
        print(f"  OK: {label}")
    except Exception:
        print(f"  ERROR in {label}:")
        traceback.print_exc()


from apps.worker.jobs import (
    run_alternative_data_ingestion,
    run_broker_token_refresh,
    run_correlation_refresh,
    run_earnings_refresh,
    run_feature_enrichment,
    run_feature_refresh,
    run_fundamentals_refresh,
    run_intel_feed_ingestion,
    run_liquidity_refresh,
    run_market_data_ingestion,
    run_ranking_generation,
    run_regime_detection,
    run_signal_generation,
    run_stress_test,
    run_universe_refresh,
    run_var_refresh,
    run_weight_optimization,
)

_run("broker_token_refresh",     run_broker_token_refresh,     app_state=app_state, settings=settings)
_run("market_data_ingestion",    run_market_data_ingestion,    settings=settings, session_factory=session_factory)
_run("alternative_data_ingestion", run_alternative_data_ingestion, app_state=app_state, settings=settings)
_run("intel_feed_ingestion",     run_intel_feed_ingestion,     app_state=app_state, settings=settings)
_run("feature_refresh",          run_feature_refresh,          settings=settings, session_factory=session_factory)
_run("correlation_refresh",      run_correlation_refresh,      app_state=app_state, settings=settings, session_factory=session_factory)
_run("liquidity_refresh",        run_liquidity_refresh,        app_state=app_state, settings=settings, session_factory=session_factory)
_run("fundamentals_refresh",     run_fundamentals_refresh,     app_state=app_state, settings=settings)
_run("var_refresh",              run_var_refresh,              app_state=app_state, settings=settings, session_factory=session_factory)
_run("regime_detection",         run_regime_detection,         app_state=app_state, settings=settings, session_factory=session_factory)
_run("stress_test",              run_stress_test,              app_state=app_state, settings=settings)
_run("feature_enrichment",       run_feature_enrichment,       app_state=app_state, settings=settings)
_run("earnings_refresh",         run_earnings_refresh,         app_state=app_state, settings=settings)
_run("universe_refresh",         run_universe_refresh,         app_state=app_state, settings=settings)
_run("signal_generation",        run_signal_generation,        app_state=app_state, settings=settings, session_factory=session_factory)
_run("ranking_generation",       run_ranking_generation,       app_state=app_state, settings=settings, session_factory=session_factory)
_run("weight_optimization",      run_weight_optimization,      app_state=app_state, settings=settings, session_factory=session_factory)

print("\n" + "="*60)
print("  CATCHUP COMPLETE")
print("="*60)
