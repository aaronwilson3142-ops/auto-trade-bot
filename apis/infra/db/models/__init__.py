"""APIS ORM models package.

Importing this package registers ALL model classes with ``Base.metadata``,
which is required for Alembic autogenerate to detect all tables.
"""
from .base import Base
from .reference import Security, Theme, SecurityTheme
from .source import Source, SourceEvent, SecurityEventLink
from .market_data import DailyMarketBar, SecurityLiquidityMetric
from .analytics import Feature, SecurityFeatureValue
from .signal import Strategy, SignalRun, SecuritySignal, RankingRun, RankedOpportunity
from .portfolio import PortfolioSnapshot, Position, Order, Fill, RiskEvent, PositionHistory
from .evaluation import EvaluationRun, EvaluationMetric, PerformanceAttribution
from .self_improvement import ImprovementProposal, ImprovementEvaluation, PromotedVersion
from .audit import DecisionAudit, SessionCheckpoint, AdminEvent
from .system_state import SystemStateEntry
from .backtest import BacktestRun
from .proposal_execution import ProposalExecution
from .weight_profile import WeightProfile
from .regime_detection import RegimeSnapshot
from .signal_quality import SignalOutcome
from .readiness import ReadinessSnapshot

__all__ = [
    "Base",
    # reference
    "Security",
    "Theme",
    "SecurityTheme",
    # source ingestion
    "Source",
    "SourceEvent",
    "SecurityEventLink",
    # market data
    "DailyMarketBar",
    "SecurityLiquidityMetric",
    # analytics
    "Feature",
    "SecurityFeatureValue",
    # signal & ranking
    "Strategy",
    "SignalRun",
    "SecuritySignal",
    "RankingRun",
    "RankedOpportunity",
    # portfolio & execution
    "PortfolioSnapshot",
    "Position",
    "Order",
    "Fill",
    "RiskEvent",
    "PositionHistory",
    # evaluation
    "EvaluationRun",
    "EvaluationMetric",
    "PerformanceAttribution",
    # self-improvement
    "ImprovementProposal",
    "ImprovementEvaluation",
    "PromotedVersion",
    # audit
    "DecisionAudit",
    "SessionCheckpoint",
    "AdminEvent",
    # system state persistence
    "SystemStateEntry",
    # backtest runs
    "BacktestRun",
    # proposal execution audit
    "ProposalExecution",
    # strategy weight profiles
    "WeightProfile",
    # market regime detection snapshots
    "RegimeSnapshot",
    # signal quality outcome records
    "SignalOutcome",
    # readiness report history snapshots
    "ReadinessSnapshot",
]
