"""
Structured logging configuration for APIS using structlog.

Call configure_logging() once at application startup.
All modules should import and use get_logger() to obtain a logger.

Usage:
    from config.logging_config import configure_logging, get_logger

    configure_logging()
    logger = get_logger(__name__)
    logger.info("event_name", key="value", other_key=123)
"""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog


def configure_logging(log_level: str = "INFO", *, as_json: bool | None = None) -> None:
    """
    Configure structlog for the entire application.

    Args:
        log_level: Logging level string ("DEBUG", "INFO", "WARNING", "ERROR").
        as_json: Force JSON output. Defaults to True in non-development environments.
                 When None, auto-detects based on whether stdout is a TTY.
    """
    # Determine output format
    if as_json is None:
        as_json = not sys.stdout.isatty()

    level = getattr(logging, log_level.upper(), logging.INFO)

    # Configure stdlib logging to feed into structlog
    logging.basicConfig(
        format="%(message)s",
        level=level,
        stream=sys.stdout,
    )

    # Processors applied before the final renderer.
    # add_logger_name requires a stdlib logger (has .name), so we use LoggerFactory below.
    pre_chain: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if as_json:
        formatter: logging.Formatter = structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.processors.JSONRenderer(),
            ],
            foreign_pre_chain=pre_chain,
        )
    else:
        formatter = structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                structlog.dev.ConsoleRenderer(colors=True),
            ],
            foreign_pre_chain=pre_chain,
        )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.stdlib.add_logger_name,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Return a structlog bound logger.

    Args:
        name: Logger name, typically __name__.

    Returns:
        A structlog BoundLogger.
    """
    return structlog.get_logger(name)
