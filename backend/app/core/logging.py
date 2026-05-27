"""
Structured Logging Configuration
=================================
Uses structlog for structured, context-rich logging.

Why structlog over Python's built-in logging?
  - Built-in logging: outputs plain strings → hard to parse/search
  - structlog: outputs JSON in production → parseable by CloudWatch, Datadog, ELK

In development: Beautiful colored console output (human readable)
In production:  JSON output (machine parseable, sent to CloudWatch)

Example output:
  Development:
    2026-05-27 14:32:00 [info     ] Request completed  [app] method=GET path=/health status=200 duration_ms=12

  Production (JSON):
    {"timestamp": "2026-05-27T14:32:00Z", "level": "info", "event": "Request completed",
     "method": "GET", "path": "/health", "status": 200, "duration_ms": 12}

Usage:
    import structlog
    logger = structlog.get_logger(__name__)

    async def my_handler():
        logger.info("expense_created", expense_id="uuid-123", amount=50.00, user_id="uuid-456")
        logger.error("database_error", error=str(e), query="SELECT * FROM expenses")
"""

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger

from app.config import get_settings


def add_app_context(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """
    Processor: Adds application context to every log entry.

    Structlog "processors" are functions that transform the log event
    before it's written. Think of them as a pipeline:
      event → processor1 → processor2 → ... → output

    This processor adds the app name and version to every log line,
    so in CloudWatch you can filter logs by app name when multiple
    services log to the same log group.
    """
    settings = get_settings()
    event_dict["app"] = settings.app_name
    event_dict["version"] = settings.app_version
    event_dict["env"] = settings.env
    return event_dict


def drop_color_message_key(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    """
    Processor: Remove the 'color_message' key added by uvicorn.

    Uvicorn's access logger adds a 'color_message' key for terminal coloring.
    This is redundant in structured logs — we remove it for cleaner output.
    """
    event_dict.pop("color_message", None)
    return event_dict


def setup_logging() -> None:
    """
    Configure structlog for the application.

    Call this ONCE at application startup (in the lifespan function).
    After this, any module can do:
        import structlog
        logger = structlog.get_logger(__name__)
    """
    settings = get_settings()

    # -------------------------------------------------------------------------
    # Step 1: Configure Python's standard logging
    # structlog integrates with stdlib logging so third-party libraries
    # (SQLAlchemy, uvicorn) also produce structured output
    # -------------------------------------------------------------------------
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",  # structlog handles formatting
        stream=sys.stdout,  # 12-factor: log to stdout, not files
        level=log_level,
    )

    # Suppress noisy library loggers (but keep ERROR+ from them)
    for noisy_logger in ["uvicorn.access", "sqlalchemy.engine", "asyncpg"]:
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)

    # -------------------------------------------------------------------------
    # Step 2: Define the processor chain
    # Processors are applied LEFT TO RIGHT before the log is written
    # -------------------------------------------------------------------------

    # Shared processors (run for ALL log entries, dev and prod)
    shared_processors: list[Any] = [
        # Add log level to the event dict
        structlog.stdlib.add_log_level,
        # Add timestamp (ISO 8601 format for machine parsing)
        structlog.stdlib.add_logger_name,
        # Add custom app context
        add_app_context,
        # Remove uvicorn's color key
        drop_color_message_key,
        # Format exceptions as structured data (not just a string)
        structlog.processors.format_exc_info,
        # Add timestamp
        structlog.processors.TimeStamper(fmt="iso"),
    ]

    # -------------------------------------------------------------------------
    # Step 3: Choose renderer based on environment
    # -------------------------------------------------------------------------
    if settings.log_format == "json" or settings.is_production:
        # Production: JSON output → parseable by CloudWatch, Datadog, ELK
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        # Development: Beautiful colored console output
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    # -------------------------------------------------------------------------
    # Step 4: Configure structlog
    # -------------------------------------------------------------------------
    structlog.configure(
        processors=[
            # Handle log levels properly
            structlog.stdlib.filter_by_level,
            *shared_processors,
            # Render with our chosen renderer (JSON or Console)
            renderer,
        ],
        # Use stdlib logging as the backend
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        # Cache loggers for performance (create once, reuse)
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """
    Get a structured logger instance.

    Usage:
        logger = get_logger(__name__)
        logger.info("expense_created", expense_id="123", amount=50.0)
    """
    return structlog.get_logger(name)
