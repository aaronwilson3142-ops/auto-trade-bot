"""
Reporting service configuration.

Service-specific configuration for the reporting service is delegated to the
central ``config.settings.Settings`` object (loaded from environment variables
via pydantic-settings).

This module is a placeholder for any future reporting-specific config
dataclasses (e.g. report output paths, email delivery settings) that are too
granular for top-level Settings.
"""
