"""APIS ORM models package.

Importing this package registers ALL model classes with ``Base.metadata``,
which is required for Alembic autogenerate to detect all tables.
"""
from .analytics import Feature, SecurityFeatureValue
from .audit import AdminEvent, DecisionAudit, SessionCheckpoint
from .backtest import BacktestRun
from .base import Base
from .evaluation import EvaluationMetric, EvaluationRun, PerformanceAttribution
from .market_data import DailyMarketBar, SecurityLiquidityMetric
from .portfolio import Fill, Order, PortfolioSnapshot, Position, PositionHistory, RiskEvent
from .proposal_execution import ProposalExecution
from .readiness import ReadinessSnapshot
from .reference import Security, SecurityTheme, Theme
from .regime_detection import RegimeSnapshot
from .self_improvement import ImprovementEvaluation, ImprovementProposal, PromotedVersion
from .signal import RankedOpportunity, RankingRun, SecuritySignal, SignalRun, Strategy
from .signal_quality import SignalOutcome
from .source import SecurityEventLink, Source, SourceEvent
from .system_state import SystemStateEntry
from .weight_profile import WeightProfile

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
