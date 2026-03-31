"""API routes package — exports all v1 routers."""
from apps.api.routes.actions import router as actions_router
from apps.api.routes.admin import router as admin_router
from apps.api.routes.backtest import backtest_router
from apps.api.routes.config import router as config_router
from apps.api.routes.correlation import correlation_router
from apps.api.routes.earnings import earnings_router
from apps.api.routes.evaluation import router as evaluation_router
from apps.api.routes.exit_levels import exit_levels_router
from apps.api.routes.factor import factor_router
from apps.api.routes.factor_alerts import factor_tilt_router
from apps.api.routes.fill_quality import fill_quality_router
from apps.api.routes.intelligence import router as intelligence_router
from apps.api.routes.liquidity import liquidity_router
from apps.api.routes.live_gate import router as live_gate_router
from apps.api.routes.metrics import router as metrics_router
from apps.api.routes.portfolio import router as portfolio_router
from apps.api.routes.prices import router as prices_router
from apps.api.routes.readiness import readiness_router
from apps.api.routes.rebalancing import rebalance_router
from apps.api.routes.recommendations import router as recommendations_router
from apps.api.routes.regime import regime_router
from apps.api.routes.reports import router as reports_router
from apps.api.routes.sector import sector_router
from apps.api.routes.self_improvement import router as self_improvement_router
from apps.api.routes.signal_quality import signal_quality_router
from apps.api.routes.signals_rankings import rankings_router, signals_router
from apps.api.routes.stress import stress_router
from apps.api.routes.universe import universe_router
from apps.api.routes.var import var_router
from apps.api.routes.weights import weights_router

__all__ = [
    "actions_router",
    "admin_router",
    "backtest_router",
    "config_router",
    "correlation_router",
    "evaluation_router",
    "exit_levels_router",
    "intelligence_router",
    "live_gate_router",
    "metrics_router",
    "portfolio_router",
    "prices_router",
    "rankings_router",
    "recommendations_router",
    "reports_router",
    "self_improvement_router",
    "signals_router",
    "weights_router",
    "regime_router",
    "sector_router",
    "liquidity_router",
    "var_router",
    "stress_router",
    "earnings_router",
    "signal_quality_router",
    "universe_router",
    "rebalance_router",
    "factor_router",
    "fill_quality_router",
    "readiness_router",
    "factor_tilt_router",
]
