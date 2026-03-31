"""
Data ingestion service configuration.

Service-specific configuration for data ingestion is delegated to the central
``config.settings.Settings`` object (loaded from environment variables via
pydantic-settings).  Data source URLs, API keys (Alpaca, yfinance), and fetch
intervals are managed there.

This module is a placeholder for any future ingestion-specific config dataclasses
(e.g. per-source retry policies) that are too granular for top-level Settings.
"""
