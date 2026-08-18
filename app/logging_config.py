"""Application logging configured for container stdout collection."""
from __future__ import annotations

import logging
import os
import sys
from typing import TextIO

_DEFAULT_FORMAT = "%(asctime)s %(levelname)s %(name)s %(message)s"
_CONFIGURED = False


class ImmediateStreamHandler(logging.StreamHandler):
    """Stream handler that flushes every record for container log visibility."""

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        self.flush()


def configure_application_logging(
    *,
    level: int | str | None = None,
    stream: TextIO | None = None,
    force: bool = False,
) -> None:
    """Configure one stdout handler before Uvicorn imports the ASGI app.

    Hugging Face Spaces collects process stdout/stderr. Uvicorn's default
    ``log_config`` can replace application handlers after import, so the entrypoint
    disables that replacement and calls this function first.
    """
    global _CONFIGURED
    if _CONFIGURED and not force:
        return

    configured_level: int | str = level or os.getenv("LOG_LEVEL", "INFO").upper()
    handler = ImmediateStreamHandler(stream or sys.stdout)
    handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT))

    logging.basicConfig(
        level=configured_level,
        handlers=[handler],
        force=True,
    )

    # Let application and Uvicorn records flow through the same stdout handler.
    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "app", "app.processing"):
        target = logging.getLogger(logger_name)
        target.handlers.clear()
        target.setLevel(configured_level)
        target.propagate = True

    _CONFIGURED = True
