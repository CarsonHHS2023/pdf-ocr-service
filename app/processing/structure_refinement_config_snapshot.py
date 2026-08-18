"""Sanitized read-only configuration snapshot for PDF structure refinement."""
from __future__ import annotations

import logging
import os
from typing import Any

from app.processing.pdf_structure_refinement_images import (
    openai_pdf_structure_refinement_is_configured,
    pdf_page_image_policy_from_env,
)


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _non_negative_float(name: str, default: float) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a non-negative number") from exc
    if value < 0:
        raise ValueError(f"{name} must be a non-negative number")
    return value


def _positive_float(name: str, default: float) -> float:
    value = _non_negative_float(name, default)
    if value <= 0:
        raise ValueError(f"{name} must be a positive number")
    return value


def structure_refinement_config_snapshot() -> dict[str, Any]:
    """Return effective non-secret refinement settings without runtime side effects.

    The snapshot intentionally omits API keys, authorization headers, endpoint URLs,
    PDF data, image data URLs, provider responses, and initialized client/limiter state.
    """

    enabled = openai_pdf_structure_refinement_is_configured()
    image_policy = pdf_page_image_policy_from_env()

    timeout_seconds = _positive_float("PDF_STRUCTURE_REFINEMENT_TIMEOUT_SECONDS", 60.0)
    max_attempts = _positive_int("PDF_STRUCTURE_REFINEMENT_MAX_ATTEMPTS", 3)
    initial_backoff_seconds = _non_negative_float(
        "PDF_STRUCTURE_REFINEMENT_INITIAL_BACKOFF_SECONDS", 0.5
    )
    max_backoff_seconds = _non_negative_float(
        "PDF_STRUCTURE_REFINEMENT_MAX_BACKOFF_SECONDS", 8.0
    )
    if max_backoff_seconds < initial_backoff_seconds:
        raise ValueError(
            "PDF_STRUCTURE_REFINEMENT_MAX_BACKOFF_SECONDS must be at least "
            "PDF_STRUCTURE_REFINEMENT_INITIAL_BACKOFF_SECONDS"
        )

    model = os.getenv("PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL", "").strip() or None
    return {
        "enabled": enabled,
        "provider": "openai" if enabled else None,
        "model": model if enabled else None,
        "timeout_seconds": timeout_seconds,
        "max_attempts": max_attempts,
        "initial_backoff_seconds": initial_backoff_seconds,
        "max_backoff_seconds": max_backoff_seconds,
        "max_concurrent_batches_per_document": _positive_int(
            "PDF_STRUCTURE_REFINEMENT_MAX_CONCURRENT_BATCHES", 2
        ),
        "global_max_concurrent_batches": _positive_int(
            "PDF_STRUCTURE_REFINEMENT_GLOBAL_MAX_CONCURRENT_BATCHES", 4
        ),
        "image_policy": {
            "max_pages_per_batch": image_policy.max_pages,
            "max_dimension_pixels": image_policy.max_dimension_pixels,
            "jpeg_quality": image_policy.jpeg_quality,
            "max_image_bytes": image_policy.max_image_bytes,
        },
    }


def validate_and_log_structure_refinement_config(
    logger: logging.Logger,
) -> dict[str, Any]:
    """Validate effective settings and emit one bounded, sanitized startup event."""

    snapshot = structure_refinement_config_snapshot()
    image_policy = snapshot["image_policy"]
    logger.info(
        "PDF_STRUCTURE_REFINEMENT_CONFIG "
        "enabled=%s provider=%s model=%s timeout_seconds=%s max_attempts=%s "
        "initial_backoff_seconds=%s max_backoff_seconds=%s "
        "max_concurrent_batches_per_document=%s global_max_concurrent_batches=%s "
        "max_pages_per_batch=%s max_dimension_pixels=%s jpeg_quality=%s "
        "max_image_bytes=%s",
        snapshot["enabled"],
        snapshot["provider"],
        snapshot["model"],
        snapshot["timeout_seconds"],
        snapshot["max_attempts"],
        snapshot["initial_backoff_seconds"],
        snapshot["max_backoff_seconds"],
        snapshot["max_concurrent_batches_per_document"],
        snapshot["global_max_concurrent_batches"],
        image_policy["max_pages_per_batch"],
        image_policy["max_dimension_pixels"],
        image_policy["jpeg_quality"],
        image_policy["max_image_bytes"],
    )
    return snapshot


__all__ = [
    "structure_refinement_config_snapshot",
    "validate_and_log_structure_refinement_config",
]
