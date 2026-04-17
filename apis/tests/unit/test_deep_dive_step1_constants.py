"""Deep-Dive Plan Step 1 - Un-buried constants regression tests.

Validates that the six magic numbers moved from code into
``config/settings.py`` preserve their pre-refactor defaults byte-for-byte
and are correctly consumed by the downstream services.
"""
from __future__ import annotations

import datetime as dt
import sys

import pytest

from config.settings import (
    _DEFAULT_AI_RANKING_BONUS_MAP,
    _DEFAULT_AI_THEME_BONUS_MAP,
    Settings,
)


class TestStep1Defaults:
    """Default values must match the pre-refactor literals byte-for-byte."""

    def test_buy_threshold_default(self):
        s = Settings()
        assert s.buy_threshold == 0.65

    def test_watch_threshold_default(self):
        s = Settings()
        assert s.watch_threshold == 0.45

    def test_source_weight_hit_rate_floor_default(self):
        s = Settings()
        assert s.source_weight_hit_rate_floor == 0.50

    def test_ranking_threshold_avg_loss_floor_default(self):
        s = Settings()
        assert s.ranking_threshold_avg_loss_floor == -0.02

    def test_rebalance_target_ttl_seconds_default(self):
        s = Settings()
        assert s.rebalance_target_ttl_seconds == 3600

    def test_ai_ranking_bonus_map_default(self):
        s = Settings()
        expected = {
            "ai_infrastructure":   0.08,
            "ai_applications":     0.07,
            "semiconductors":      0.06,
            "cybersecurity":       0.06,
            "power_infrastructure": 0.06,
            "networking":          0.06,
            "data_centres":        0.05,
            "cloud_software":      0.04,
            "mega_cap_tech":       0.03,
        }
        assert s.ai_ranking_bonus_map == expected
        assert _DEFAULT_AI_RANKING_BONUS_MAP == expected

    def test_ai_theme_bonus_map_default(self):
        s = Settings()
        expected = {
            "ai_infrastructure":   1.35,
            "ai_applications":     1.30,
            "semiconductors":      1.25,
            "cybersecurity":       1.25,
            "power_infrastructure": 1.25,
            "networking":          1.25,
            "data_centres":        1.20,
            "cloud_software":      1.15,
        }
        assert s.ai_theme_bonus_map == expected
        assert _DEFAULT_AI_THEME_BONUS_MAP == expected


class TestStep1EnvOverrides:
    def test_buy_threshold_env_override(self, monkeypatch):
        monkeypatch.setenv("APIS_BUY_THRESHOLD", "0.55")
        s = Settings()
        assert s.buy_threshold == 0.55

    def test_watch_threshold_env_override(self, monkeypatch):
        monkeypatch.setenv("APIS_WATCH_THRESHOLD", "0.30")
        s = Settings()
        assert s.watch_threshold == 0.30

    def test_source_weight_hit_rate_floor_env_override(self, monkeypatch):
        monkeypatch.setenv("APIS_SOURCE_WEIGHT_HIT_RATE_FLOOR", "0.60")
        s = Settings()
        assert s.source_weight_hit_rate_floor == 0.60

    def test_ranking_threshold_avg_loss_floor_env_override(self, monkeypatch):
        monkeypatch.setenv("APIS_RANKING_THRESHOLD_AVG_LOSS_FLOOR", "-0.05")
        s = Settings()
        assert s.ranking_threshold_avg_loss_floor == -0.05

    def test_rebalance_target_ttl_env_override(self, monkeypatch):
        monkeypatch.setenv("APIS_REBALANCE_TARGET_TTL_SECONDS", "1800")
        s = Settings()
        assert s.rebalance_target_ttl_seconds == 1800


class TestStep1RangeValidation:
    def test_buy_threshold_rejects_above_one(self, monkeypatch):
        monkeypatch.setenv("APIS_BUY_THRESHOLD", "1.5")
        with pytest.raises(Exception):
            Settings()

    def test_ranking_threshold_avg_loss_floor_rejects_positive(self, monkeypatch):
        monkeypatch.setenv("APIS_RANKING_THRESHOLD_AVG_LOSS_FLOOR", "0.05")
        with pytest.raises(Exception):
            Settings()


class TestRankingEngineUsesSettings:
    def _signal(self, composite: float):
        from services.signal_engine.models import (
            HorizonClassification,
            SignalOutput,
        )

        return SignalOutput(
            security_id="test",
            ticker="TEST",
            strategy_key="momentum_v1",
            signal_type="momentum",
            signal_score=None,
            confidence_score=None,
            risk_score=None,
            catalyst_score=None,
            liquidity_score=None,
            horizon_classification=HorizonClassification.POSITIONAL.value,
            explanation_dict={"rationale": "t"},
            source_reliability_tier="secondary_verified",
            contains_rumor=False,
            as_of=dt.datetime.now(dt.timezone.utc),
        )

    def test_recommend_action_respects_custom_buy_threshold(self, monkeypatch):
        from config.settings import Settings
        from services.ranking_engine.service import RankingEngineService

        s_default = Settings()
        out = RankingEngineService._recommend_action(0.60, self._signal(0.60), s_default)
        assert out == "watch"

        monkeypatch.setenv("APIS_BUY_THRESHOLD", "0.55")
        s_low = Settings()
        out2 = RankingEngineService._recommend_action(0.60, self._signal(0.60), s_low)
        assert out2 == "buy"

    def test_recommend_action_avoid_below_watch_threshold(self):
        from services.ranking_engine.service import RankingEngineService

        s = Settings()
        out = RankingEngineService._recommend_action(0.10, self._signal(0.10), s)
        assert out == "avoid"


class TestRebalanceTargetTTL:
    def _make_state(self, computed_at, targets):
        from types import SimpleNamespace
        return SimpleNamespace(
            rebalance_targets=targets,
            rebalance_computed_at=computed_at,
        )

    def _make_settings(self, ttl):
        from types import SimpleNamespace
        return SimpleNamespace(rebalance_target_ttl_seconds=ttl)

    def test_fresh_targets_returned(self):
        from apps.worker.jobs.paper_trading import _fresh_rebalance_targets
        now = dt.datetime.now(dt.timezone.utc)
        st = self._make_state(now, {"AAPL": 0.2, "MSFT": 0.3})
        cfg = self._make_settings(3600)
        assert _fresh_rebalance_targets(st, cfg) == {"AAPL": 0.2, "MSFT": 0.3}

    def test_stale_targets_dropped(self):
        from apps.worker.jobs.paper_trading import _fresh_rebalance_targets
        old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)
        st = self._make_state(old, {"AAPL": 0.2})
        cfg = self._make_settings(3600)
        assert _fresh_rebalance_targets(st, cfg) == {}

    def test_missing_computed_at_treated_as_stale(self):
        from apps.worker.jobs.paper_trading import _fresh_rebalance_targets
        st = self._make_state(None, {"AAPL": 0.2})
        cfg = self._make_settings(3600)
        assert _fresh_rebalance_targets(st, cfg) == {}

    def test_ttl_zero_disables_freshness_check(self):
        from apps.worker.jobs.paper_trading import _fresh_rebalance_targets
        ancient = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=30)
        st = self._make_state(ancient, {"AAPL": 0.2})
        cfg = self._make_settings(0)
        assert _fresh_rebalance_targets(st, cfg) == {"AAPL": 0.2}

    def test_empty_targets_fast_path(self):
        from apps.worker.jobs.paper_trading import _fresh_rebalance_targets
        st = self._make_state(dt.datetime.now(dt.timezone.utc), {})
        cfg = self._make_settings(3600)
        assert _fresh_rebalance_targets(st, cfg) == {}

    def test_naive_computed_at_is_normalized(self):
        from apps.worker.jobs.paper_trading import _fresh_rebalance_targets
        naive = dt.datetime.utcnow() - dt.timedelta(minutes=5)
        st = self._make_state(naive, {"AAPL": 0.2})
        cfg = self._make_settings(3600)
        assert _fresh_rebalance_targets(st, cfg) == {"AAPL": 0.2}


class TestThemeAlignmentUsesSettings:
    def test_ai_infrastructure_bonus_applied(self):
        from services.feature_store.models import FeatureSet
        from services.signal_engine.strategies.theme_alignment import (
            ThemeAlignmentStrategy,
        )

        fs = FeatureSet(
            security_id=1,
            ticker="NVDA",
            as_of_timestamp=dt.datetime.now(dt.timezone.utc),
            theme_scores={"ai_infrastructure": 0.5},
        )
        out = ThemeAlignmentStrategy().score(fs)
        assert float(out.signal_score) == pytest.approx(0.675, abs=1e-3)


class TestSelfImprovementUsesSettings:
    @pytest.mark.skipif(
        sys.version_info < (3, 11),
        reason="SelfImprovementProposal uses datetime.UTC (Python 3.11+)",
    )
    def test_hit_rate_rule_reads_setting(self, monkeypatch):
        from decimal import Decimal
        from services.self_improvement.service import SelfImprovementService

        svc = SelfImprovementService()
        proposals = svc.generate_proposals(
            scorecard_grade="D",
            attribution_summary={"hit_rate": Decimal("0.45")},
        )
        assert any(p.proposal_type.value == "source_weight" for p in proposals)

        monkeypatch.setenv("APIS_SOURCE_WEIGHT_HIT_RATE_FLOOR", "0.40")
        from config.settings import get_settings
        get_settings.cache_clear()
        svc2 = SelfImprovementService()
        proposals2 = svc2.generate_proposals(
            scorecard_grade="D",
            attribution_summary={"hit_rate": Decimal("0.45")},
        )
        assert not any(p.proposal_type.value == "source_weight" for p in proposals2)
        get_settings.cache_clear()
