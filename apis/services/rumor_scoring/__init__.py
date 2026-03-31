"""rumor_scoring — low-confidence chatter ingestion and decay-adjusted scoring."""
from services.rumor_scoring.config import RumorScoringConfig
from services.rumor_scoring.models import RumorEvent, RumorScore, RumorSource
from services.rumor_scoring.service import RumorScoringService

__all__ = [
    "RumorEvent",
    "RumorScore",
    "RumorScoringConfig",
    "RumorScoringService",
    "RumorSource",
]
