"""macro_policy_engine service — rule-based policy/macro interpretation.

Uses keyword-based directional bias computation, event-type sector/theme
classification, and multi-signal regime assessment.  No external deps.
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

import structlog

from services.macro_policy_engine.config import MacroPolicyConfig
from services.macro_policy_engine.models import (
    MacroRegime,
    MacroRegimeIndicator,
    PolicyEvent,
    PolicySignal,
)
from services.macro_policy_engine.utils import (
    EVENT_TYPE_BASE_CONFIDENCE,
    EVENT_TYPE_SECTORS,
    EVENT_TYPE_THEMES,
    compute_directional_bias,
    generate_implication_summary,
)

log = structlog.get_logger(__name__)


class MacroPolicyEngineService:
    """Interprets policy/macro events and emits structured signals.

    Uses rule-based keyword analysis to compute directional biases,
    classify affected sectors/themes, and assess the macro regime.
    """

    def __init__(self, config: Optional[MacroPolicyConfig] = None) -> None:
        self._config = config or MacroPolicyConfig()
        self._log = log.bind(service="macro_policy_engine")

    def process_event(self, event: PolicyEvent) -> PolicySignal:
        """Interpret a single PolicyEvent and return a PolicySignal.

        Directional bias is computed from event type defaults plus keyword
        modifiers in the headline and body snippet.
        """
        full_text = f"{event.headline} {event.body_snippet}"
        ev_val = event.event_type.value

        bias = compute_directional_bias(ev_val, full_text)
        confidence = EVENT_TYPE_BASE_CONFIDENCE.get(ev_val, 0.3)
        sectors = list(EVENT_TYPE_SECTORS.get(ev_val, []))
        themes = list(EVENT_TYPE_THEMES.get(ev_val, []))
        # Filter sectors/themes to tracked set if configured
        if self._config.tracked_sectors:
            sectors = [s for s in sectors if s in self._config.tracked_sectors]
        summary = generate_implication_summary(
            ev_val, bias, event.headline, sectors, themes
        )

        return PolicySignal(
            event=event,
            affected_sectors=sectors,
            affected_themes=themes,
            affected_tickers=[],
            directional_bias=bias,
            confidence=confidence,
            implication_summary=summary,
            generated_at=dt.datetime.now(dt.timezone.utc),
        )

    def process_batch(self, events: list[PolicyEvent]) -> list[PolicySignal]:
        """Process a batch of PolicyEvents, filtering by age and confidence."""
        cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(
            hours=self._config.max_event_age_hours
        )
        signals: list[PolicySignal] = []
        for event in events:
            ts = event.published_at
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=dt.timezone.utc)
            if ts < cutoff:
                continue
            signal = self.process_event(event)
            if signal.confidence >= self._config.min_signal_confidence:
                signals.append(signal)
        signals = signals[: self._config.max_signals_per_cycle]
        self._log.info("batch_processed", total=len(events), signals=len(signals))
        return signals

    def assess_regime(self, signals: list[PolicySignal]) -> MacroRegimeIndicator:
        """Derive a macro regime indicator from active policy signals.

        Logic:
        - Average the directional_bias × confidence across all signals
        - Map aggregate to a MacroRegime bucket:
            > +0.25  → RISK_ON / REFLATION (if fiscal-led)
            < -0.25  → RISK_OFF / STAGFLATION (if supply-side shock)
            otherwise → NEUTRAL
        """
        if not signals:
            return MacroRegimeIndicator(
                regime=MacroRegime.NEUTRAL,
                confidence=0.0,
                supporting_factors=["No active signals"],
                assessed_at=dt.datetime.now(dt.timezone.utc),
            )

        weighted_bias = sum(s.directional_bias * s.confidence for s in signals)
        avg_confidence = sum(s.confidence for s in signals) / len(signals)
        avg_bias = weighted_bias / len(signals)

        # Classify regime bucket
        if avg_bias > 0.25:
            regime = MacroRegime.REFLATION if avg_bias < 0.5 else MacroRegime.RISK_ON
        elif avg_bias < -0.25:
            # Check if supply-side shock (stagflation) or pure risk-off
            tariff_count = sum(
                1 for s in signals
                if s.event.event_type.value in ("tariff", "interest_rate")
            )
            regime = MacroRegime.STAGFLATION if tariff_count >= 2 else MacroRegime.RISK_OFF
        else:
            regime = MacroRegime.NEUTRAL

        factors = [s.implication_summary[:60] for s in signals[:3]]

        return MacroRegimeIndicator(
            regime=regime,
            confidence=round(avg_confidence, 4),
            supporting_factors=factors,
            assessed_at=dt.datetime.now(dt.timezone.utc),
        )
