"""
Phase 10 — Step 2: Service Stub Tests

Verifies that news_intelligence, macro_policy_engine, theme_engine, and
rumor_scoring stubs are importable, initialise correctly, and return
properly-shaped output objects.  No external calls or DB required.
"""
from __future__ import annotations

import datetime as dt

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


# ===========================================================================
# TestNewsIntelligence
# ===========================================================================

class TestNewsIntelligence:
    def _item(
        self,
        ticker: str = "AAPL",
        tier: str = "secondary_verified",
        age_hours: float = 0.0,
    ):
        from services.news_intelligence.models import CredibilityTier, NewsItem
        published = _utcnow() - dt.timedelta(hours=age_hours)
        return NewsItem(
            source_id="test-001",
            headline=f"Test headline for {ticker}",
            published_at=published,
            credibility_tier=CredibilityTier(tier),
            tickers_mentioned=[ticker],
        )

    def test_service_initialises_with_defaults(self):
        from services.news_intelligence.service import NewsIntelligenceService
        svc = NewsIntelligenceService()
        assert svc._config is not None

    def test_process_item_returns_insight(self):
        from services.news_intelligence.service import NewsIntelligenceService
        svc = NewsIntelligenceService()
        item = self._item()
        insight = svc.process_item(item)
        assert insight.news_item is item
        assert insight.processed_at is not None
        assert 0.0 <= insight.credibility_weight <= 1.0

    def test_process_item_credibility_weight_applied(self):
        from services.news_intelligence.service import NewsIntelligenceService
        svc = NewsIntelligenceService()
        primary_item = self._item(tier="primary_verified")
        rumor_item = self._item(tier="rumor")
        assert svc.process_item(primary_item).credibility_weight > svc.process_item(rumor_item).credibility_weight

    def test_process_item_rumor_tier_sets_contains_rumor(self):
        from services.news_intelligence.service import NewsIntelligenceService
        svc = NewsIntelligenceService()
        insight = svc.process_item(self._item(tier="rumor"))
        assert insight.contains_rumor is True

    def test_process_item_non_rumor_tier_not_contains_rumor(self):
        from services.news_intelligence.service import NewsIntelligenceService
        svc = NewsIntelligenceService()
        insight = svc.process_item(self._item(tier="secondary_verified"))
        assert insight.contains_rumor is False

    def test_process_batch_filters_stale_items(self):
        from services.news_intelligence.config import NewsIntelligenceConfig
        from services.news_intelligence.service import NewsIntelligenceService
        config = NewsIntelligenceConfig(max_item_age_hours=24)
        svc = NewsIntelligenceService(config=config)
        fresh = self._item(age_hours=1)
        stale = self._item(ticker="MSFT", age_hours=48)
        results = svc.process_batch([fresh, stale])
        tickers = [ins.news_item.tickers_mentioned[0] for ins in results]
        assert "AAPL" in tickers
        assert "MSFT" not in tickers

    def test_process_batch_returns_list(self):
        from services.news_intelligence.service import NewsIntelligenceService
        svc = NewsIntelligenceService()
        assert isinstance(svc.process_batch([]), list)

    def test_get_ticker_insights_filters_correctly(self):
        from services.news_intelligence.service import NewsIntelligenceService
        svc = NewsIntelligenceService()
        aapl_item = self._item(ticker="AAPL")
        nvda_item = self._item(ticker="NVDA")
        insights = [svc.process_item(aapl_item), svc.process_item(nvda_item)]
        aapl_only = svc.get_ticker_insights("AAPL", insights)
        assert all("AAPL" in i.affected_tickers for i in aapl_only)

    def test_weighted_sentiment_property(self):
        from services.news_intelligence.service import NewsIntelligenceService
        svc = NewsIntelligenceService()
        insight = svc.process_item(self._item())
        # stub returns 0.0 sentiment_score, so weighted_sentiment == 0.0
        assert insight.weighted_sentiment == 0.0

    def test_module_exports(self):
        from services.news_intelligence import (
            NewsIntelligenceService,
        )
        assert NewsIntelligenceService is not None


# ===========================================================================
# TestMacroPolicyEngine
# ===========================================================================

class TestMacroPolicyEngine:
    def _event(self, age_hours: float = 0.0):
        from services.macro_policy_engine.models import PolicyEvent, PolicyEventType
        published = _utcnow() - dt.timedelta(hours=age_hours)
        return PolicyEvent(
            event_id="evt-001",
            headline="Fed raises rates 25 bps",
            event_type=PolicyEventType.INTEREST_RATE,
            published_at=published,
            source="Federal Reserve",
        )

    def test_service_initialises_with_defaults(self):
        from services.macro_policy_engine.service import MacroPolicyEngineService
        svc = MacroPolicyEngineService()
        assert svc._config is not None

    def test_process_event_returns_signal(self):
        from services.macro_policy_engine.service import MacroPolicyEngineService
        svc = MacroPolicyEngineService()
        signal = svc.process_event(self._event())
        assert signal.event is not None
        assert signal.generated_at is not None

    def test_process_event_interest_rate_has_expected_values(self):
        from services.macro_policy_engine.service import MacroPolicyEngineService
        svc = MacroPolicyEngineService()
        signal = svc.process_event(self._event())
        # INTEREST_RATE: default bias is 0.0 (set by keywords); base confidence is 0.7
        assert signal.directional_bias == 0.0
        assert signal.confidence == 0.7

    def test_process_batch_filters_stale_events(self):
        from services.macro_policy_engine.config import MacroPolicyConfig
        from services.macro_policy_engine.service import MacroPolicyEngineService
        config = MacroPolicyConfig(max_event_age_hours=24, min_signal_confidence=0.0)
        svc = MacroPolicyEngineService(config=config)
        # Stub returns confidence=0.0, so need min_signal_confidence=0.0 for any to pass
        fresh_event = self._event(age_hours=1)
        stale_event = self._event(age_hours=48)
        signals = svc.process_batch([fresh_event, stale_event])
        # stale filtered by age; fresh passes age check + confidence check (0.0 >= 0.0)
        assert len(signals) == 1

    def test_process_batch_empty_input(self):
        from services.macro_policy_engine.service import MacroPolicyEngineService
        svc = MacroPolicyEngineService()
        assert svc.process_batch([]) == []

    def test_assess_regime_returns_neutral_stub(self):
        from services.macro_policy_engine.models import MacroRegime
        from services.macro_policy_engine.service import MacroPolicyEngineService
        svc = MacroPolicyEngineService()
        indicator = svc.assess_regime([])
        assert indicator.regime == MacroRegime.NEUTRAL
        assert indicator.assessed_at is not None

    def test_module_exports(self):
        from services.macro_policy_engine import (
            MacroPolicyEngineService,
        )
        assert MacroPolicyEngineService is not None


# ===========================================================================
# TestThemeEngine
# ===========================================================================

class TestThemeEngine:
    def test_service_initialises_with_defaults(self):
        from services.theme_engine.service import ThemeEngineService
        svc = ThemeEngineService()
        assert svc._config is not None

    def test_get_exposure_nvda_has_mappings(self):
        from services.theme_engine.service import ThemeEngineService
        svc = ThemeEngineService()
        exposure = svc.get_exposure("NVDA")
        assert exposure.ticker == "NVDA"
        assert len(exposure.mappings) > 0  # concrete registry has NVDA themes

    def test_get_exposure_ticker_normalised_to_upper(self):
        from services.theme_engine.service import ThemeEngineService
        svc = ThemeEngineService()
        exposure = svc.get_exposure("nvda")
        assert exposure.ticker == "NVDA"

    def test_primary_theme_returns_none_when_no_mappings(self):
        from services.theme_engine.service import ThemeEngineService
        svc = ThemeEngineService()
        # WMT has an empty mapping list in the registry
        exposure = svc.get_exposure("WMT")
        assert exposure.primary_theme is None
        assert exposure.max_score == 0.0

    def test_get_bulk_exposure_returns_dict(self):
        from services.theme_engine.service import ThemeEngineService
        svc = ThemeEngineService()
        tickers = ["AAPL", "NVDA", "MSFT"]
        result = svc.get_bulk_exposure(tickers)
        assert set(result.keys()) == {"AAPL", "NVDA", "MSFT"}

    def test_get_theme_members_unknown_theme_returns_empty(self):
        from services.theme_engine.service import ThemeEngineService
        svc = ThemeEngineService()
        members = svc.get_theme_members("nonexistent_theme")
        assert members == []

    def test_get_theme_members_known_theme_returns_empty_stub(self):
        from services.theme_engine.service import ThemeEngineService
        svc = ThemeEngineService()
        members = svc.get_theme_members("ai_infrastructure")
        assert isinstance(members, list)

    def test_default_known_themes_includes_second_order(self):
        from services.theme_engine.config import ThemeEngineConfig
        config = ThemeEngineConfig()
        assert "power_infrastructure" in config.known_themes
        assert "data_centres" in config.known_themes
        assert "networking" in config.known_themes

    def test_module_exports(self):
        from services.theme_engine import (
            ThemeEngineService,
        )
        assert ThemeEngineService is not None


# ===========================================================================
# TestRumorScoring
# ===========================================================================

class TestRumorScoring:
    def _rumor(
        self,
        ticker: str = "GME",
        source: str = "social_media",
        age_hours: float = 0.0,
    ):
        from services.rumor_scoring.models import RumorEvent, RumorSource
        received = _utcnow() - dt.timedelta(hours=age_hours)
        return RumorEvent(
            rumor_id="r-001",
            ticker=ticker,
            headline=f"Rumor about {ticker}",
            source=RumorSource(source),
            received_at=received,
        )

    def test_service_initialises_with_defaults(self):
        from services.rumor_scoring.service import RumorScoringService
        svc = RumorScoringService()
        assert svc._config is not None

    def test_score_returns_rumor_score(self):
        from services.rumor_scoring.service import RumorScoringService
        svc = RumorScoringService()
        rumor = self._rumor()
        result = svc.score(rumor, raw_confidence=0.8)
        assert result.rumor is rumor
        assert result.scored_at is not None

    def test_score_applies_credibility_penalty(self):
        from services.rumor_scoring.service import RumorScoringService
        svc = RumorScoringService()
        rumor = self._rumor(source="social_media")  # penalty=0.7
        result = svc.score(rumor, raw_confidence=1.0)
        # fresh rumor: decay ~ 1.0, so influence ≈ 1.0 * (1-0.7) * 1.0 = 0.3
        assert abs(result.influence_score - 0.3) < 0.01

    def test_score_applies_time_decay(self):
        from services.rumor_scoring.config import RumorScoringConfig
        from services.rumor_scoring.service import RumorScoringService
        config = RumorScoringConfig(decay_half_life_hours=24.0)
        svc = RumorScoringService(config=config)
        fresh = self._rumor(age_hours=0)
        old = self._rumor(age_hours=24)  # exactly one half-life
        fresh_score = svc.score(fresh, raw_confidence=1.0)
        old_score = svc.score(old, raw_confidence=1.0)
        assert fresh_score.influence_score > old_score.influence_score
        # one half-life: old_score ≈ fresh_score * 0.5
        assert abs(old_score.decay_factor - 0.5) < 0.01

    def test_is_actionable_above_threshold(self):
        from services.rumor_scoring.service import RumorScoringService
        svc = RumorScoringService()
        rumor = self._rumor(source="social_media")
        result = svc.score(rumor, raw_confidence=0.8)
        # influence ≈ 0.8 * 0.3 * ~1.0 = 0.24 → actionable
        assert result.is_actionable is True

    def test_is_actionable_below_threshold(self):
        from services.rumor_scoring.models import RumorEvent, RumorSource
        rumor = RumorEvent(
            rumor_id="r-low",
            ticker="GME",
            headline="barely any signal",
            source=RumorSource.ANONYMOUS_TIP,
            received_at=_utcnow() - dt.timedelta(hours=72),
        )
        from services.rumor_scoring.service import RumorScoringService
        svc = RumorScoringService()
        result = svc.score(rumor, raw_confidence=0.05)
        assert result.is_actionable is False

    def test_score_batch_returns_only_actionable(self):
        from services.rumor_scoring.service import RumorScoringService
        svc = RumorScoringService()
        # One fresh high-confidence, one very stale low-confidence
        fresh = self._rumor(source="social_media", age_hours=0)
        very_old = self._rumor(ticker="OLD", source="anonymous_tip", age_hours=200)
        results = svc.score_batch([fresh, very_old], raw_confidence=0.8)
        tickers = [r.rumor.ticker for r in results]
        assert "GME" in tickers
        # very old + high penalty + low confidence = not actionable
        assert "OLD" not in tickers

    def test_get_ticker_scores_filters_correctly(self):
        from services.rumor_scoring.service import RumorScoringService
        svc = RumorScoringService()
        gme = self._rumor(ticker="GME")
        amc = self._rumor(ticker="AMC")
        scores = [svc.score(gme, 0.8), svc.score(amc, 0.8)]
        gme_only = svc.get_ticker_scores("GME", scores)
        assert all(s.rumor.ticker == "GME" for s in gme_only)

    def test_module_exports(self):
        from services.rumor_scoring import (
            RumorScoringService,
        )
        assert RumorScoringService is not None
