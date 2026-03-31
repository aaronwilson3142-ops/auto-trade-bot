"""
Risk engine service configuration.

Service-specific configuration for the risk engine is delegated to the
central ``config.settings.Settings`` object (loaded from environment variables
via pydantic-settings).  Risk parameters such as ``max_positions``,
``daily_loss_limit_pct``, ``weekly_drawdown_limit_pct``, and
``monthly_drawdown_limit_pct`` are accessed directly from ``Settings``.

This module is a placeholder for any future risk-engine-local config dataclasses
that are too granular to belong in the top-level Settings.
"""
