"""
Feature store service configuration.

Service-specific configuration for the feature store is delegated to the
central ``config.settings.Settings`` object (loaded from environment variables
via pydantic-settings).

This module is a placeholder for any future feature-store-local config
dataclasses (e.g. feature staleness thresholds, pipeline-specific lookback
windows) that are too granular for top-level Settings.
"""
