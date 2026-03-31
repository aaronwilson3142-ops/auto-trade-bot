"""
Execution engine service configuration.

Service-specific configuration for the execution engine is delegated to the
central ``config.settings.Settings`` object (loaded from environment variables
via pydantic-settings).  Broker credentials and operating mode are accessed
from ``Settings`` and the alpaca-specific ``AlpacaSettings`` object.

This module is a placeholder for any future execution-engine-local config
dataclasses (e.g. per-order-type slippage models) that are too granular to
belong in the top-level Settings.
"""
