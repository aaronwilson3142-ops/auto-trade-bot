"""
FeatureStoreService — owns engineered feature persistence and retrieval.

Responsibilities (per 07_API_AND_SERVICE_BOUNDARIES_SPEC §3.7):
  - Register feature definitions in the `features` table (idempotent)
  - Compute feature sets by delegating to BaselineFeaturePipeline
  - Persist SecurityFeatureValue rows (upsert by security + feature + as_of)
  - Retrieve feature values for a security as of a given timestamp

Does NOT own: raw bar fetching, signal generation, or portfolio decisions.
"""
from __future__ import annotations

import datetime as dt
import logging
from uuid import UUID

import pandas as pd
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from infra.db.models import DailyMarketBar, Feature, SecurityFeatureValue
from services.feature_store.models import FEATURE_GROUP_MAP, FEATURE_KEYS, FeatureSet
from services.feature_store.pipeline import BaselineFeaturePipeline

logger = logging.getLogger(__name__)


class FeatureStoreService:
    """Orchestrates feature computation and storage.

    Args:
        pipeline: Feature pipeline instance.  Defaults to BaselineFeaturePipeline().
    """

    def __init__(self, pipeline: BaselineFeaturePipeline | None = None) -> None:
        self._pipeline = pipeline or BaselineFeaturePipeline()

    # ------------------------------------------------------------------
    # Feature registration (idempotent)
    # ------------------------------------------------------------------

    def ensure_feature_catalog(self, session: Session) -> dict[str, UUID]:
        """Ensure all FEATURE_KEYS exist in the `features` table.

        Returns a dict of feature_key → feature UUID.
        """
        existing = {
            row.feature_key: row.id
            for row in session.execute(sa.select(Feature)).scalars()
        }

        new_keys = [k for k in FEATURE_KEYS if k not in existing]
        for key in new_keys:
            feat = Feature(
                feature_key=key,
                feature_name=key.replace("_", " ").title(),
                feature_group=FEATURE_GROUP_MAP[key],
            )
            session.add(feat)

        if new_keys:
            session.flush()
            # Re-fetch to pick up new UUIDs
            all_rows = session.execute(sa.select(Feature)).scalars().all()
            return {r.feature_key: r.id for r in all_rows}

        return existing

    # ------------------------------------------------------------------
    # Compute + persist
    # ------------------------------------------------------------------

    def compute_and_persist(
        self,
        session: Session,
        security_id: UUID,
        ticker: str,
        as_of: dt.datetime | None = None,
    ) -> FeatureSet:
        """Load bars from DB, compute features, persist them, and return the FeatureSet.

        Args:
            session:     Active SQLAlchemy session.
            security_id: UUID of the Security row.
            ticker:      Symbol (used for logging).
            as_of:       Timestamp for the feature snapshot.  Defaults to
                         utcnow() if not provided.

        Returns:
            FeatureSet with all computed features.
        """
        bars_df = self._load_bars_df(session, security_id)
        feature_set = self._pipeline.compute(
            security_id=security_id,
            ticker=ticker,
            bars_df=bars_df,
            as_of=as_of,
        )

        if feature_set.features:
            catalog = self.ensure_feature_catalog(session)
            self._persist_feature_set(session, feature_set, catalog)

        return feature_set

    def get_features(
        self,
        session: Session,
        security_id: UUID,
        as_of: dt.datetime | None = None,
    ) -> dict[str, object]:
        """Retrieve the most recent feature values for a security.

        Args:
            session:     Active session.
            security_id: UUID of the Security.
            as_of:       Upper bound for as_of_timestamp.  None ⇒ latest.

        Returns:
            dict of feature_key → Decimal (None if feature is absent).
        """
        subq = (
            sa.select(
                SecurityFeatureValue.feature_id,
                sa.func.max(SecurityFeatureValue.as_of_timestamp).label("max_ts"),
            )
            .where(SecurityFeatureValue.security_id == security_id)
            .group_by(SecurityFeatureValue.feature_id)
        )
        if as_of is not None:
            subq = subq.where(SecurityFeatureValue.as_of_timestamp <= as_of)
        subq = subq.subquery()

        rows = session.execute(
            sa.select(Feature.feature_key, SecurityFeatureValue.feature_value_numeric)
            .join(SecurityFeatureValue, SecurityFeatureValue.feature_id == Feature.id)
            .join(subq, sa.and_(
                subq.c.feature_id == SecurityFeatureValue.feature_id,
                subq.c.max_ts == SecurityFeatureValue.as_of_timestamp,
            ))
            .where(SecurityFeatureValue.security_id == security_id)
        ).all()

        return {key: val for key, val in rows}

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _load_bars_df(self, session: Session, security_id: UUID) -> pd.DataFrame:
        """Load daily bars from DB → DataFrame for the pipeline."""
        rows = session.execute(
            sa.select(
                DailyMarketBar.trade_date,
                DailyMarketBar.open,
                DailyMarketBar.high,
                DailyMarketBar.low,
                DailyMarketBar.close,
                DailyMarketBar.adjusted_close,
                DailyMarketBar.volume,
            )
            .where(DailyMarketBar.security_id == security_id)
            .order_by(DailyMarketBar.trade_date.asc())
        ).all()

        if not rows:
            return pd.DataFrame()

        return pd.DataFrame(
            rows,
            columns=["trade_date", "open", "high", "low", "close", "adjusted_close", "volume"],
        )

    def _persist_feature_set(
        self,
        session: Session,
        feature_set: FeatureSet,
        catalog: dict[str, UUID],
    ) -> None:
        """Upsert SecurityFeatureValue rows for each ComputedFeature."""
        rows = []
        for cf in feature_set.features:
            feat_id = catalog.get(cf.feature_key)
            if feat_id is None:
                continue
            rows.append({
                "security_id": feature_set.security_id,
                "feature_id": feat_id,
                "as_of_timestamp": cf.as_of_timestamp,
                "feature_value_numeric": cf.value,
                "source_version": cf.source_version,
            })

        if not rows:
            return

        stmt = (
            pg_insert(SecurityFeatureValue)
            .values(rows)
            .on_conflict_do_nothing()
        )
        session.execute(stmt)
        logger.debug(
            "Persisted %d feature values for security_id=%s as_of=%s",
            len(rows),
            feature_set.security_id,
            feature_set.as_of_timestamp,
        )

