"""Structured logging configuration."""

from __future__ import annotations

import logging
import sys
from typing import Any, Literal

import structlog


def configure_logging(level: str = "info", format_: Literal["json", "console"] = "json") -> None:
    """Set up structlog. Call once at app startup."""
    level_int = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=level_int, stream=sys.stdout, format="%(message)s")

    processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
    ]
    if format_ == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(level_int),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name)
