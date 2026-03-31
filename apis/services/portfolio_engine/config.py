"""
Portfolio engine service configuration.

Service-specific configuration for the portfolio engine is delegated to the
central ``config.settings.Settings`` object (loaded from environment variables
via pydantic-settings).  Position sizing, max_positions, and concentration
limits are read directly from ``Settings``.

This module is a placeholder for any future portfolio-engine-local config
dataclasses (e.g. per-strategy sizing overrides) that are too granular for
top-level Settings.
"""
