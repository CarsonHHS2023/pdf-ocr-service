"""Bounded provider diagnostics that bypass mutable logging configuration."""
from __future__ import annotations

import logging
import sys
from typing import Mapping

_logger = logging.getLogger("uvicorn.error")


def emit_refinement_provider_event(event: str, fields: Mapping[str, object]) -> None:
    """Emit one bounded provider event through logger and flushed stderr."""

    payload = " ".join(f"{name}={value}" for name, value in sorted(fields.items()))
    message = f"{event} {payload}".rstrip()
    _logger.info(message)
    print(message, file=sys.stderr, flush=True)


__all__ = ["emit_refinement_provider_event"]
