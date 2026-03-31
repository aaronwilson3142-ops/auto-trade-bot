"""Worker jobs package.

Exports all APScheduler-compatible job functions.  Each function accepts
an ApiAppState and an optional Settings object so they can be wired into
the scheduler or called directly in tests.
"""
from apps.worker.jobs.broker_refresh import run_broker_token_refresh
from apps.worker.jobs.correlation import run_correlation_refresh
from apps.worker.jobs.earnings_refresh import run_earnings_refresh
from apps.worker.jobs.evaluation import (
    run_attribution_analysis,
    run_daily_evaluation,
)
from apps.worker.jobs.fill_quality import run_fill_quality_update
from apps.worker.jobs.fill_quality_attribution import run_fill_quality_attribution
from apps.worker.jobs.ingestion import (
    run_alternative_data_ingestion,
    run_feature_enrichment,
    run_feature_refresh,
    run_fundamentals_refresh,
    run_market_data_ingestion,
)
from apps.worker.jobs.intel import run_intel_feed_ingestion
from apps.worker.jobs.liquidity import run_liquidity_refresh
from apps.worker.jobs.paper_trading import run_paper_trading_cycle
from apps.worker.jobs.readiness import run_readiness_report_update
from apps.worker.jobs.rebalancing import run_rebalance_check
from apps.worker.jobs.reporting import (
    run_generate_daily_report,
    run_publish_operator_summary,
)
from apps.worker.jobs.self_improvement import (
    run_auto_execute_proposals,
    run_generate_improvement_proposals,
)
from apps.worker.jobs.signal_quality import run_signal_quality_update
from apps.worker.jobs.signal_ranking import (
    run_ranking_generation,
    run_regime_detection,
    run_signal_generation,
    run_weight_optimization,
)
from apps.worker.jobs.stress_test import run_stress_test
from apps.worker.jobs.universe import run_universe_refresh
from apps.worker.jobs.var_refresh import run_var_refresh

__all__ = [
    "run_market_data_ingestion",
    "run_alternative_data_ingestion",
    "run_intel_feed_ingestion",
    "run_feature_refresh",
    "run_feature_enrichment",
    "run_fundamentals_refresh",
    "run_correlation_refresh",
    "run_liquidity_refresh",
    "run_var_refresh",
    "run_stress_test",
    "run_earnings_refresh",
    "run_signal_quality_update",
    "run_signal_generation",
    "run_ranking_generation",
    "run_regime_detection",
    "run_daily_evaluation",
    "run_attribution_analysis",
    "run_generate_daily_report",
    "run_publish_operator_summary",
    "run_generate_improvement_proposals",
    "run_auto_execute_proposals",
    "run_paper_trading_cycle",
    "run_broker_token_refresh",
    "run_weight_optimization",
    "run_universe_refresh",
    "run_rebalance_check",
    "run_fill_quality_update",
    "run_fill_quality_attribution",
    "run_readiness_report_update",
]
