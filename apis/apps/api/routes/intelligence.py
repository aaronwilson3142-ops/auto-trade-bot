"""Route handlers for /api/v1/intelligence/*.

Surfaces the current state of the intelligence pipeline for operator
monitoring and debugging:

  GET  /intelligence/regime          — active macro regime from app_state
  GET  /intelligence/signals         — active policy signals summary
  GET  /intelligence/insights        — active news insights (ticker-filterable)
  GET  /intelligence/themes/{ticker} — thematic exposure from static registry

Authenticated operator-push endpoints (require Bearer token via
APIS_OPERATOR_API_KEY):

  POST /intelligence/events  — push a processed policy event into app_state
  POST /intelligence/news    — push a processed news insight into app_state
"""
from __future__ import annotations

import datetime as dt
import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Query, status

from apps.api.deps import AppStateDep, SettingsDep
from apps.api.schemas.intelligence import (
    AlternativeDataRecordSchema,
    AlternativeDataResponse,
    MacroRegimeResponse,
    NewsInsightsResponse,
    NewsInsightSummary,
    PolicySignalsResponse,
    PolicySignalSummary,
    PushEventRequest,
    PushItemResponse,
    PushNewsItemRequest,
    ThematicExposureResponse,
    ThemeMappingSummary,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/intelligence", tags=["Intelligence"])


# ---------------------------------------------------------------------------
# Auth helpers (operator bearer token)
# ---------------------------------------------------------------------------

def _extract_bearer(authorization: str | None) -> str:
    """Parse ``Authorization: Bearer <token>`` header value."""
    if not authorization:
        return ""
    parts = authorization.strip().split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return ""
    return parts[1].strip()


def _token_matches(expected: str, provided: str) -> bool:
    """Constant-time comparison to prevent timing side-channel attacks."""
    return hmac.compare_digest(
        expected.encode("utf-8"),
        provided.encode("utf-8"),
    )


def _require_operator_auth(settings, authorization: str | None) -> None:
    """Raise HTTP 503/401 if the operator_api_key is not configured or wrong."""
    key = getattr(settings, "operator_api_key", "")
    if not key:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Operator push endpoint is disabled (APIS_OPERATOR_API_KEY not set).",
        )
    provided = _extract_bearer(authorization)
    if not _token_matches(key, provided):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing operator bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# Read-only GET endpoints
# ---------------------------------------------------------------------------

@router.get("/regime", response_model=MacroRegimeResponse)
async def get_macro_regime(state: AppStateDep) -> MacroRegimeResponse:
    """Return the current assessed macro regime and active signal count."""
    return MacroRegimeResponse(
        regime=getattr(state, "current_macro_regime", "NEUTRAL"),
        signal_count=len(getattr(state, "latest_policy_signals", [])),
        as_of=dt.datetime.now(dt.UTC),
    )


@router.get("/signals", response_model=PolicySignalsResponse)
async def get_policy_signals(
    state: AppStateDep,
    limit: int = Query(20, ge=1, le=100),
) -> PolicySignalsResponse:
    """Return the currently active policy signals (most recent first).

    Args:
        limit: Maximum number of signals to return (1–100, default 20).
    """
    signals = getattr(state, "latest_policy_signals", [])
    summaries = [
        PolicySignalSummary(
            event_id=s.event.event_id,
            headline=s.event.headline,
            event_type=s.event.event_type.value,
            directional_bias=round(s.directional_bias, 4),
            confidence=round(s.confidence, 4),
            affected_sectors=s.affected_sectors,
            affected_themes=s.affected_themes,
            implication_summary=s.implication_summary,
            generated_at=s.generated_at,
        )
        for s in signals[:limit]
    ]
    return PolicySignalsResponse(
        count=len(summaries),
        signals=summaries,
        as_of=dt.datetime.now(dt.UTC),
    )


@router.get("/insights", response_model=NewsInsightsResponse)
async def get_news_insights(
    state: AppStateDep,
    ticker: str | None = Query(
        None, description="Filter insights to those affecting this ticker symbol"
    ),
    limit: int = Query(20, ge=1, le=100),
) -> NewsInsightsResponse:
    """Return the currently active news insights.

    Args:
        ticker: Optional ticker symbol to filter by (case-insensitive).
        limit:  Maximum number of insights to return (1–100, default 20).
    """
    insights = getattr(state, "latest_news_insights", [])
    if ticker:
        upper = ticker.upper()
        insights = [
            ins for ins in insights
            if upper in [t.upper() for t in ins.affected_tickers]
        ]
    summaries = [
        NewsInsightSummary(
            source_id=ins.news_item.source_id,
            headline=ins.news_item.headline,
            sentiment=ins.sentiment.value,
            sentiment_score=round(ins.sentiment_score, 4),
            credibility_weight=round(ins.credibility_weight, 4),
            affected_tickers=ins.affected_tickers,
            affected_themes=ins.affected_themes,
            market_implication=ins.market_implication,
            contains_rumor=ins.contains_rumor,
            processed_at=ins.processed_at,
        )
        for ins in insights[:limit]
    ]
    return NewsInsightsResponse(
        count=len(summaries),
        insights=summaries,
        as_of=dt.datetime.now(dt.UTC),
    )


@router.get("/themes/{ticker}", response_model=ThematicExposureResponse)
async def get_thematic_exposure(ticker: str) -> ThematicExposureResponse:
    """Return thematic exposure for a single ticker from the static registry.

    Args:
        ticker: Ticker symbol (case-insensitive).  Unknown tickers return an
                empty mappings list rather than a 404.
    """
    from services.theme_engine.service import ThemeEngineService

    svc = ThemeEngineService()
    exposure = svc.get_exposure(ticker.upper())
    mappings = [
        ThemeMappingSummary(
            theme=m.theme,
            beneficiary_order=m.beneficiary_order.value,
            thematic_score=round(m.thematic_score, 4),
            rationale=m.rationale,
        )
        for m in exposure.mappings
    ]
    return ThematicExposureResponse(
        ticker=exposure.ticker,
        primary_theme=exposure.primary_theme,
        max_score=round(exposure.max_score, 4),
        mappings=mappings,
        as_of=dt.datetime.now(dt.UTC),
    )


# ---------------------------------------------------------------------------
# Authenticated operator-push POST endpoints
# ---------------------------------------------------------------------------

@router.post("/events", response_model=PushItemResponse, status_code=status.HTTP_201_CREATED)
async def push_policy_event(
    body: PushEventRequest,
    state: AppStateDep,
    settings: SettingsDep,
    authorization: str | None = Header(None),
) -> PushItemResponse:
    """Push a processed policy event into the active intelligence state.

    The event is converted into a ``PolicySignal`` and prepended to
    ``app_state.latest_policy_signals``.  It will be picked up by the next
    feature-enrichment and signal-generation jobs.

    Requires ``Authorization: Bearer <APIS_OPERATOR_API_KEY>`` header.
    Returns 503 if the key is not configured; 401 if the token is wrong.
    """
    _require_operator_auth(settings, authorization)

    from services.macro_policy_engine.models import (
        PolicyEvent,
        PolicyEventType,
        PolicySignal,
    )

    # Validate event_type — raises 422 (ValueError) if unknown
    try:
        evt_type = PolicyEventType(body.event_type)
    except ValueError:
        valid = [e.value for e in PolicyEventType]
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown event_type '{body.event_type}'. Valid: {valid}",
        )

    now = dt.datetime.now(dt.UTC)
    event = PolicyEvent(
        event_id=body.event_id,
        headline=body.headline,
        event_type=evt_type,
        published_at=now,
        source=body.source,
        body_snippet=body.body_snippet,
    )
    signal = PolicySignal(
        event=event,
        affected_sectors=body.affected_sectors,
        affected_themes=body.affected_themes,
        affected_tickers=body.affected_tickers,
        directional_bias=max(-1.0, min(1.0, body.directional_bias)),
        confidence=max(0.0, min(1.0, body.confidence)),
        implication_summary=body.implication_summary,
        generated_at=now,
    )

    existing: list = list(getattr(state, "latest_policy_signals", []))
    existing.insert(0, signal)  # most recent first
    state.latest_policy_signals = existing

    logger.info(
        "Operator pushed policy event %s (bias=%.2f, conf=%.2f); "
        "total signals in state: %d",
        body.event_id, signal.directional_bias, signal.confidence, len(existing),
    )
    return PushItemResponse(
        status="accepted",
        message=f"Policy event '{body.event_id}' accepted.",
        items_in_state=len(existing),
    )


@router.get("/alternative", response_model=AlternativeDataResponse)
async def get_alternative_data(
    state: AppStateDep,
    ticker: str | None = Query(
        None, description="Filter records to this ticker symbol (case-insensitive)"
    ),
    limit: int = Query(50, ge=1, le=200),
) -> AlternativeDataResponse:
    """Return latest alternative data records (social sentiment, etc.).

    Args:
        ticker: Optional ticker to filter by (case-insensitive).
        limit:  Maximum number of records to return (1–200, default 50).
    """
    records = getattr(state, "latest_alternative_data", [])
    if ticker:
        upper = ticker.upper()
        records = [r for r in records if getattr(r, "ticker", "") == upper]
    records = list(reversed(records))[:limit]
    return AlternativeDataResponse(
        count=len(records),
        records=[
            AlternativeDataRecordSchema(
                id=r.id,
                ticker=r.ticker,
                source=r.source.value if hasattr(r.source, "value") else str(r.source),
                sentiment_score=r.sentiment_score,
                mention_count=r.mention_count,
                raw_snippet=r.raw_snippet,
                captured_at=r.captured_at,
            )
            for r in records
        ],
        as_of=dt.datetime.now(dt.UTC),
    )


@router.post("/news", response_model=PushItemResponse, status_code=status.HTTP_201_CREATED)
async def push_news_item(
    body: PushNewsItemRequest,
    state: AppStateDep,
    settings: SettingsDep,
    authorization: str | None = Header(None),
) -> PushItemResponse:
    """Push a processed news insight into the active intelligence state.

    The item is converted into a ``NewsInsight`` and prepended to
    ``app_state.latest_news_insights``.  It will be picked up by the next
    feature-enrichment and signal-generation jobs.

    Requires ``Authorization: Bearer <APIS_OPERATOR_API_KEY>`` header.
    Returns 503 if the key is not configured; 401 if the token is wrong.
    """
    _require_operator_auth(settings, authorization)

    from services.news_intelligence.models import (
        CredibilityTier,
        NewsInsight,
        NewsItem,
        SentimentLabel,
    )

    now = dt.datetime.now(dt.UTC)

    # Infer credibility tier from credibility_weight
    if body.credibility_weight >= 0.7:
        cred_tier = CredibilityTier.PRIMARY_VERIFIED
    elif body.credibility_weight >= 0.4:
        cred_tier = CredibilityTier.SECONDARY_VERIFIED
    else:
        cred_tier = CredibilityTier.UNVERIFIED

    # Infer SentimentLabel from sentiment_score
    score = body.sentiment_score
    if score > 0.1:
        sentiment_label = SentimentLabel.POSITIVE
    elif score < -0.1:
        sentiment_label = SentimentLabel.NEGATIVE
    else:
        sentiment_label = SentimentLabel.NEUTRAL

    item = NewsItem(
        source_id=body.source_id,
        headline=body.headline,
        published_at=now,
        body_snippet=body.body_snippet,
        credibility_tier=cred_tier,
        tickers_mentioned=body.affected_tickers,
    )
    insight = NewsInsight(
        news_item=item,
        sentiment=sentiment_label,
        sentiment_score=max(-1.0, min(1.0, body.sentiment_score)),
        credibility_weight=max(0.0, min(1.0, body.credibility_weight)),
        affected_tickers=body.affected_tickers,
        affected_themes=body.affected_themes,
        market_implication=body.market_implication,
        contains_rumor=body.contains_rumor,
        processed_at=now,
    )

    existing: list = list(getattr(state, "latest_news_insights", []))
    existing.insert(0, insight)  # most recent first
    state.latest_news_insights = existing

    logger.info(
        "Operator pushed news item %s (score=%.2f, tickers=%s); "
        "total insights in state: %d",
        body.source_id, insight.sentiment_score, body.affected_tickers, len(existing),
    )
    return PushItemResponse(
        status="accepted",
        message=f"News item '{body.source_id}' accepted.",
        items_in_state=len(existing),
    )

