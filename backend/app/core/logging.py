"""Structured logging setup (docs/ARCHITECTURE.md §28.1).

JSON in containers, key-value in local dev. A redaction processor drops values whose
key looks secret. ``request_id`` (bound by the API middleware / worker) is merged
from context vars into every event.
"""

from __future__ import annotations

import logging

import structlog

_SECRET_HINTS = ("password", "api_key", "apikey", "secret", "token", "authorization")


def _redact_secrets(
    _logger: object, _method: str, event_dict: structlog.types.EventDict
) -> structlog.types.EventDict:
    for key in list(event_dict):
        if any(hint in key.lower() for hint in _SECRET_HINTS):
            event_dict[key] = "***"
    return event_dict


def configure_logging(*, level: str = "INFO", json_output: bool = True) -> None:
    shared: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _redact_secrets,
        structlog.processors.StackInfoRenderer(),
    ]
    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=False)
    )
    structlog.configure(
        processors=[*shared, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
