"""
Gate A — Config tests.

Validates that the settings module loads correctly, env variables are
validated, and operating mode constraints are enforced.
"""
from __future__ import annotations

import pytest


class TestSettingsLoad:
    """Settings must load cleanly from environment variables."""

    def test_settings_load_defaults(self, settings: object) -> None:
        """Settings object loads without errors in test environment."""
        from config.settings import Settings

        s = Settings()
        assert s is not None

    def test_operating_mode_is_research_by_default(self) -> None:
        from config.settings import OperatingMode, Settings

        s = Settings()
        assert s.operating_mode == OperatingMode.RESEARCH

    def test_is_research_mode_property(self) -> None:
        from config.settings import Settings

        s = Settings()
        assert s.is_research_mode is True
        assert s.is_live_capable is False

    def test_kill_switch_off_by_default(self) -> None:
        from config.settings import Settings

        s = Settings()
        assert s.is_kill_switch_active is False

    def test_max_positions_default_is_10(self) -> None:
        from config.settings import Settings

        s = Settings()
        assert s.max_positions == 10

    def test_max_positions_cannot_exceed_spec_limit(self) -> None:
        """Spec hard cap: MVP max_positions <= 10."""
        from pydantic import ValidationError

        from config.settings import Settings

        with pytest.raises(ValidationError, match="10"):
            Settings(max_positions=11)  # type: ignore[call-arg]

    def test_restricted_live_mode_blocked_via_env(self) -> None:
        """RESTRICTED_LIVE cannot be set via config — requires explicit gate passage."""
        from pydantic import ValidationError

        from config.settings import Settings

        with pytest.raises(ValidationError, match="RESTRICTED_LIVE"):
            Settings(operating_mode="restricted_live")  # type: ignore[call-arg]

    def test_daily_loss_limit_is_sensible(self) -> None:
        from config.settings import Settings

        s = Settings()
        assert 0 < s.daily_loss_limit_pct <= 0.10

    def test_get_settings_returns_singleton(self) -> None:
        """get_settings() must return the same instance (lru_cache)."""
        from config.settings import get_settings

        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2


class TestLoggingConfig:
    """Logging module must configure without errors."""

    def test_configure_logging_runs_without_error(self) -> None:
        from config.logging_config import configure_logging

        configure_logging(log_level="DEBUG", as_json=False)

    def test_get_logger_returns_logger(self) -> None:
        from config.logging_config import configure_logging, get_logger

        configure_logging(log_level="INFO", as_json=False)
        logger = get_logger("test.config")
        assert logger is not None

    def test_logger_info_does_not_raise(self) -> None:
        from config.logging_config import configure_logging, get_logger

        configure_logging(log_level="INFO", as_json=False)
        logger = get_logger("test.config.info")
        logger.info("test_event", key="value", count=1)  # must not raise
