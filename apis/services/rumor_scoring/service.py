"""rumor_scoring service — low-confidence chatter scoring stub.

The score() method is fully implemented using configurable penalties and
exponential time decay.  The classification/NLP layer (determining what the
rumor says and which tickers it affects) is a future phase stub.
"""
from __future__ import annotations

import datetime as dt
import math
from typing import Optional

import structlog

from services.rumor_scoring.config import RumorScoringConfig
from services.rumor_scoring.models import RumorEvent, RumorScore

log = structlog.get_logger(__name__)


class RumorScoringService:
    """Scores rumor events using credibility penalties and time decay."""

    def __init__(self, config: Optional[RumorScoringConfig] = None) -> None:
        self._config = config or RumorScoringConfig()
        self._log = log.bind(service="rumor_scoring")

    def score(self, rumor: RumorEvent, raw_confidence: float = 0.5) -> RumorScore:
        """Score a single RumorEvent.

        influence_score = raw_confidence * (1 - credibility_penalty) * decay_factor
        """
        now = dt.datetime.now(dt.timezone.utc)
        penalty = self._config.source_penalties.get(rumor.source.value, 0.7)

        received = rumor.received_at
        if received.tzinfo is None:
            received = received.replace(tzinfo=dt.timezone.utc)
        age_hours = (now - received).total_seconds() / 3600.0
        decay = math.exp(-math.log(2) * age_hours / self._config.decay_half_life_hours)

        influence = raw_confidence * (1.0 - penalty) * decay

        return RumorScore(
            rumor=rumor,
            raw_confidence=raw_confidence,
            credibility_penalty=penalty,
            decay_factor=decay,
            influence_score=round(influence, 6),
            scored_at=now,
        )

    def score_batch(
        self, rumors: list[RumorEvent], raw_confidence: float = 0.5
    ) -> list[RumorScore]:
        """Score a batch of rumors, returning only actionable results."""
        results = [self.score(r, raw_confidence) for r in rumors]
        actionable = [s for s in results if s.is_actionable]
        self._log.info(
            "batch_scored",
            total=len(rumors),
            actionable=len(actionable),
        )
        return actionable

    def get_ticker_scores(
        self, ticker: str, scores: list[RumorScore]
    ) -> list[RumorScore]:
        """Filter scored rumors to those affecting a specific ticker."""
        return [
            s for s in scores
            if s.rumor.ticker.upper() == ticker.upper()
        ][: self._config.max_rumors_per_ticker]
