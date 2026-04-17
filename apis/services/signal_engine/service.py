"""
SignalEngineService — owns raw signal generation per strategy family.

Responsibilities (per 07_API_AND_SERVICE_BOUNDARIES_SPEC §3.8):
  - Accept a signal run context (tickers, signal_run_id)
  - Load feature sets from the feature store
  - Delegate to strategy implementations to produce SignalOutput objects
  - Persist SecuritySignal ORM rows (one row per security × strategy)
  - Return a list of SignalOutput for the ranking engine

Does NOT own: ranking, portfolio decisions, or order generation.
"""
from __future__ import annotations

import datetime as dt
import logging
import uuid

import sqlalchemy as sa
from sqlalchemy.orm import Session

from infra.db.models import SecuritySignal, SignalRun, Strategy
from services.feature_store.enrichment import FeatureEnrichmentService
from services.feature_store.models import FeatureSet
from services.feature_store.service import FeatureStoreService
from services.signal_engine.models import SignalOutput
from services.signal_engine.strategies.macro_tailwind import MacroTailwindStrategy
from services.signal_engine.strategies.momentum import MomentumStrategy
from services.signal_engine.strategies.sentiment import SentimentStrategy
from services.signal_engine.strategies.theme_alignment import ThemeAlignmentStrategy
from services.signal_engine.strategies.valuation import ValuationStrategy

logger = logging.getLogger(__name__)


def _build_default_strategies() -> list:
    """Build the default strategy list, respecting feature gates."""
    from config.settings import get_settings  # noqa: PLC0415

    strategies: list = [
        MomentumStrategy(),
        ThemeAlignmentStrategy(),
        MacroTailwindStrategy(),
        SentimentStrategy(),
        ValuationStrategy(),
    ]
    cfg = get_settings()
    if getattr(cfg, "enable_insider_flow_strategy", False):
        from services.signal_engine.strategies.insider_flow import (
            InsiderFlowStrategy,
        )
        strategies.append(InsiderFlowStrategy())
    return strategies


class SignalEngineService:
    """Generates and persists signals for a list of tickers.

    Args:
        feature_store: FeatureStoreService for loading feature sets.
        strategies:    List of strategy instances.  Defaults to [MomentumStrategy()].
    """

    def __init__(
        self,
        feature_store: FeatureStoreService | None = None,
        strategies: list | None = None,
        enrichment_service: FeatureEnrichmentService | None = None,
    ) -> None:
        self._feature_store = feature_store or FeatureStoreService()
        self._strategies: list = strategies if strategies is not None else _build_default_strategies()
        self._enrichment_service = enrichment_service or FeatureEnrichmentService()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        session: Session,
        signal_run_id: uuid.UUID,
        tickers: list[str],
        security_id_map: dict[str, uuid.UUID] | None = None,
        policy_signals: list | None = None,
        news_insights: list | None = None,
        fundamentals_store: dict | None = None,
    ) -> list[SignalOutput]:
        """Generate and persist signals for all tickers in the given signal run.

        Args:
            session:           Active SQLAlchemy session.
            signal_run_id:     FK to signal_runs.id.
            tickers:           List of symbols to process.
            security_id_map:   Optional pre-built ticker → security_id mapping.
                               If None, looked up from the securities table.
            policy_signals:    PolicySignal list from the current cycle.  When
                               provided, each FeatureSet is enriched with macro
                               and theme overlays before strategy scoring.
            news_insights:     NewsInsight list from the current cycle.  When
                               provided, ticker-specific sentiment overlays are
                               applied before scoring.
            fundamentals_store: Optional dict of ticker → FundamentalsData.
                               When provided, fundamentals overlays (P/E, PEG,
                               EPS growth, earnings surprise) are applied before
                               scoring so ValuationStrategy has data.

        Returns:
            List of SignalOutput (one per ticker × strategy).
        """
        _policy_signals = policy_signals or []
        _news_insights = news_insights or []
        _fundamentals_store = fundamentals_store or {}

        # Create the SignalRun header row so SecuritySignal FK constraint is satisfied
        signal_run_row = SignalRun(
            id=signal_run_id,
            run_timestamp=dt.datetime.now(dt.UTC),
            run_mode="paper",
            universe_name="default",
            status="in_progress",
        )
        session.add(signal_run_row)
        session.flush()

        # Build security_id map if not supplied
        sid_map = security_id_map or self._load_security_ids(session, tickers)

        # Ensure strategy rows exist in the DB
        strategy_id_map = self._ensure_strategy_rows(session)

        all_outputs: list[SignalOutput] = []

        for ticker in tickers:
            security_id = sid_map.get(ticker)
            if security_id is None:
                logger.warning("No security_id found for %s; skipping.", ticker)
                continue

            # Load or compute feature set
            feature_set = self._get_feature_set(session, security_id, ticker)
            if feature_set is None:
                logger.warning("No feature set available for %s; skipping.", ticker)
                continue

            # Enrich feature set with intelligence overlays before scoring
            feature_set = self._enrichment_service.enrich(
                feature_set,
                policy_signals=_policy_signals,
                news_insights=_news_insights,
                fundamentals_store=_fundamentals_store,
            )

            for strategy in self._strategies:
                output = strategy.score(feature_set)
                strat_id = strategy_id_map.get(strategy.STRATEGY_KEY)
                if strat_id:
                    self._persist_signal(session, signal_run_id, strat_id, output)
                all_outputs.append(output)

        logger.info(
            "SignalEngineService.run: %d signals generated for %d tickers.",
            len(all_outputs),
            len(tickers),
        )

        # Mark SignalRun as completed
        signal_run_row.status = "completed"
        session.flush()

        return all_outputs

    def score_from_features(
        self,
        feature_sets: list[FeatureSet],
    ) -> list[SignalOutput]:
        """Score a list of pre-built FeatureSets without DB access.

        Useful for backtesting and unit tests that already have feature data.
        """
        outputs: list[SignalOutput] = []
        for fs in feature_sets:
            for strategy in self._strategies:
                outputs.append(strategy.score(fs))
        return outputs

    # ------------------------------------------------------------------
    # Strategy registry helpers
    # ------------------------------------------------------------------

    def _ensure_strategy_rows(self, session: Session) -> dict[str, uuid.UUID]:
        """Ensure each strategy has a row in the `strategies` table.

        Returns dict of strategy_key → strategy UUID.
        """
        existing = {
            row.strategy_key: row.id
            for row in session.execute(sa.select(Strategy)).scalars()
        }
        for strategy in self._strategies:
            key = strategy.STRATEGY_KEY
            if key not in existing:
                row = Strategy(
                    strategy_key=key,
                    strategy_name=key.replace("_", " ").title(),
                    strategy_family=strategy.STRATEGY_FAMILY,
                    is_active=True,
                    config_version=strategy.CONFIG_VERSION,
                )
                session.add(row)

        if any(s.STRATEGY_KEY not in existing for s in self._strategies):
            session.flush()
            all_rows = session.execute(sa.select(Strategy)).scalars().all()
            return {r.strategy_key: r.id for r in all_rows}

        return existing

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _persist_signal(
        self,
        session: Session,
        signal_run_id: uuid.UUID,
        strategy_id: uuid.UUID,
        output: SignalOutput,
    ) -> None:
        row = SecuritySignal(
            signal_run_id=signal_run_id,
            security_id=output.security_id,
            strategy_id=strategy_id,
            signal_type=output.signal_type,
            signal_score=output.signal_score,
            confidence_score=output.confidence_score,
            risk_score=output.risk_score,
            catalyst_score=output.catalyst_score,
            liquidity_score=output.liquidity_score,
            horizon_classification=output.horizon_classification,
            explanation_json=output.explanation_dict,
        )
        session.add(row)

    def _get_feature_set(
        self,
        session: Session,
        security_id: uuid.UUID,
        ticker: str,
    ) -> FeatureSet | None:
        """Attempt to compute a feature set from persisted bars."""
        try:
            return self._feature_store.compute_and_persist(
                session=session,
                security_id=security_id,
                ticker=ticker,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("feature_store.compute_and_persist failed for %s: %s", ticker, exc)
            return None

    @staticmethod
    def _load_security_ids(
        session: Session,
        tickers: list[str],
    ) -> dict[str, uuid.UUID]:
        from infra.db.models import Security
        rows = session.execute(
            sa.select(Security.ticker, Security.id).where(Security.ticker.in_(tickers))
        ).all()
        return {ticker: sid for ticker, sid in rows}

