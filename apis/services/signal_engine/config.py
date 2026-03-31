"""
Signal engine service configuration.

Service-specific configuration for the signal engine is delegated to the
central ``config.settings.Settings`` object (loaded from environment variables
via pydantic-settings).  Signal thresholds, strategy activation flags, and
scoring parameters are managed there.

This module is a placeholder for any future signal-engine-local config
dataclasses (e.g. per-strategy confidence thresholds) that are too granular
for top-level Settings.
"""
