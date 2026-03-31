"""news_intelligence service — rule-based NLP pipeline.

Implements keyword-based sentiment scoring, ticker extraction, theme
detection, and market implication generation.  No external NLP dependencies.
"""
from __future__ import annotations

import datetime as dt

import structlog

from services.news_intelligence.config import NewsIntelligenceConfig
from services.news_intelligence.models import (
    CredibilityTier,
    NewsInsight,
    NewsItem,
    SentimentLabel,
)
from services.news_intelligence.utils import (
    detect_themes,
    extract_tickers_from_text,
    generate_market_implication,
    score_sentiment,
)

log = structlog.get_logger(__name__)


def _label_from_score(score: float) -> SentimentLabel:
    if score > 0.15:
        return SentimentLabel.POSITIVE
    if score < -0.15:
        return SentimentLabel.NEGATIVE
    if score != 0.0:
        return SentimentLabel.MIXED
    return SentimentLabel.NEUTRAL


class NewsIntelligenceService:
    """Parses, scores, and enriches news items into structured insights.

    Uses keyword-based NLP: sentiment lexicon scoring, ticker extraction
    from headline/body, and theme tagging.  The credibility weight is
    determined by source tier and applied as a discount to the raw score.
    """

    def __init__(self, config: NewsIntelligenceConfig | None = None) -> None:
        self._config = config or NewsIntelligenceConfig()
        self._log = log.bind(service="news_intelligence")

    def process_item(self, item: NewsItem) -> NewsInsight:
        """Run NLP pipeline on a single NewsItem and return a NewsInsight.\n\n        Pipeline steps:\n        1. Compute credibility weight from tier\n        2. Score raw sentiment from headline + body_snippet\n        3. Extract mentioned tickers (headline + body)\n        4. Detect affected themes from full text\n        5. Generate a market implication summary\n        """
        weight = self._config.credibility_weights.get(
            item.credibility_tier.value, 0.4
        )
        full_text = f"{item.headline} {item.body_snippet}"
        raw_score = score_sentiment(full_text)
        label = _label_from_score(raw_score)

        # Merge explicitly tagged tickers with those extracted from text
        extracted = extract_tickers_from_text(full_text)
        merged_tickers = list(
            dict.fromkeys(list(item.tickers_mentioned) + extracted)
        )

        themes = detect_themes(full_text)
        implication = generate_market_implication(raw_score, merged_tickers, themes)

        return NewsInsight(
            news_item=item,
            sentiment=label,
            sentiment_score=round(raw_score, 4),
            credibility_weight=weight,
            affected_tickers=merged_tickers,
            affected_themes=themes,
            market_implication=implication,
            contains_rumor=(item.credibility_tier == CredibilityTier.RUMOR),
            processed_at=dt.datetime.now(dt.UTC),
        )

    def process_batch(self, items: list[NewsItem]) -> list[NewsInsight]:
        """Process a batch of NewsItems, filtering by age and credibility."""
        cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(
            hours=self._config.max_item_age_hours
        )
        results: list[NewsInsight] = []
        for item in items:
            ts = item.published_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=dt.UTC)
            if ts < cutoff:
                continue
            insight = self.process_item(item)
            if insight.credibility_weight >= self._config.min_credibility_weight:
                results.append(insight)
        self._log.info("batch_processed", total=len(items), retained=len(results))
        return results

    def get_ticker_insights(
        self, ticker: str, insights: list[NewsInsight]
    ) -> list[NewsInsight]:
        """Filter a list of insights to those affecting a specific ticker."""
        return [
            ins for ins in insights
            if ticker.upper() in [t.upper() for t in ins.affected_tickers]
        ][: self._config.max_insights_per_ticker]
