"""Shared processing-package runtime setup."""
from __future__ import annotations

import logging
import sys

_PROVIDER_EVENT_PREFIX = "PDF_STRUCTURE_REFINEMENT_PROVIDER_"
_PROVIDER_STDERR_HANDLER_MARKER = "_atlas_refinement_provider_stderr"


class _ProviderEventFilter(logging.Filter):
    """Allow only bounded provider lifecycle diagnostics onto stderr."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().startswith(_PROVIDER_EVENT_PREFIX)


def install_refinement_provider_stderr_handler() -> None:
    """Surface provider status/retry events when hosted runtimes filter INFO logs.

    The provider events contain only bounded fields such as attempt, status_code,
    retryable, and error_type. Request bodies, OCR text, images, credentials, and
    authorization headers are never included.
    """

    logger = logging.getLogger("uvicorn.error")
    if any(
        getattr(handler, _PROVIDER_STDERR_HANDLER_MARKER, False)
        for handler in logger.handlers
    ):
        return

    handler = logging.StreamHandler(sys.stderr)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(_ProviderEventFilter())
    setattr(handler, _PROVIDER_STDERR_HANDLER_MARKER, True)
    logger.addHandler(handler)


install_refinement_provider_stderr_handler()

__all__ = ["install_refinement_provider_stderr_handler"]
