"""
Ranking engine service configuration.

Service-specific configuration for the ranking engine is delegated to the
central ``config.settings.Settings`` object (loaded from environment variables
via pydantic-settings).  Strategy weights, composite scoring parameters, and
universe settings are managed there.

This module is a placeholder for any future ranking-engine-local config
dataclasses (e.g. per-factor weight overrides) that are too granular for
top-level Settings.
"""
