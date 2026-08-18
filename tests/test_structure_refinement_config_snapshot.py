from __future__ import annotations

import asyncio
import json

import pytest

from app.processing.structure_refinement_config_snapshot import (
    structure_refinement_config_snapshot,
)
from app.routers.health import health_config


_ENV_NAMES = (
    "PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY",
    "PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL",
    "PDF_STRUCTURE_REFINEMENT_OPENAI_ENDPOINT",
    "PDF_STRUCTURE_REFINEMENT_TIMEOUT_SECONDS",
    "PDF_STRUCTURE_REFINEMENT_MAX_ATTEMPTS",
    "PDF_STRUCTURE_REFINEMENT_INITIAL_BACKOFF_SECONDS",
    "PDF_STRUCTURE_REFINEMENT_MAX_BACKOFF_SECONDS",
    "PDF_STRUCTURE_REFINEMENT_MAX_CONCURRENT_BATCHES",
    "PDF_STRUCTURE_REFINEMENT_GLOBAL_MAX_CONCURRENT_BATCHES",
    "PDF_STRUCTURE_REFINEMENT_MAX_PAGES_PER_BATCH",
    "PDF_STRUCTURE_REFINEMENT_MAX_IMAGE_DIMENSION_PIXELS",
    "PDF_STRUCTURE_REFINEMENT_JPEG_QUALITY",
    "PDF_STRUCTURE_REFINEMENT_MAX_IMAGE_BYTES",
)


def _clear_refinement_env(monkeypatch) -> None:
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_snapshot_returns_disabled_defaults_without_initializing_secrets(monkeypatch) -> None:
    _clear_refinement_env(monkeypatch)

    snapshot = structure_refinement_config_snapshot()

    assert snapshot == {
        "enabled": False,
        "provider": None,
        "model": None,
        "timeout_seconds": 60.0,
        "max_attempts": 3,
        "initial_backoff_seconds": 0.5,
        "max_backoff_seconds": 8.0,
        "max_concurrent_batches_per_document": 2,
        "global_max_concurrent_batches": 4,
        "image_policy": {
            "max_pages_per_batch": 16,
            "max_dimension_pixels": 1400,
            "jpeg_quality": 72,
            "max_image_bytes": 1_500_000,
        },
    }


def test_snapshot_and_route_expose_effective_values_but_never_credentials(monkeypatch) -> None:
    _clear_refinement_env(monkeypatch)
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY", "super-secret-key")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL", "vision-model")
    monkeypatch.setenv(
        "PDF_STRUCTURE_REFINEMENT_OPENAI_ENDPOINT",
        "https://example.invalid/v1/responses?token=endpoint-secret",
    )
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_MAX_ATTEMPTS", "5")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_INITIAL_BACKOFF_SECONDS", "0.75")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_MAX_BACKOFF_SECONDS", "6")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_MAX_CONCURRENT_BATCHES", "3")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_GLOBAL_MAX_CONCURRENT_BATCHES", "7")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_MAX_PAGES_PER_BATCH", "8")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_MAX_IMAGE_DIMENSION_PIXELS", "1200")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_JPEG_QUALITY", "68")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_MAX_IMAGE_BYTES", "900000")

    snapshot = structure_refinement_config_snapshot()
    response = asyncio.run(health_config())
    serialized = response.json()

    assert snapshot["enabled"] is True
    assert snapshot["provider"] == "openai"
    assert snapshot["model"] == "vision-model"
    assert snapshot["timeout_seconds"] == 45.0
    assert snapshot["max_attempts"] == 5
    assert snapshot["max_concurrent_batches_per_document"] == 3
    assert snapshot["global_max_concurrent_batches"] == 7
    assert snapshot["image_policy"] == {
        "max_pages_per_batch": 8,
        "max_dimension_pixels": 1200,
        "jpeg_quality": 68,
        "max_image_bytes": 900000,
    }
    assert json.loads(serialized)["model"] == "vision-model"
    assert "super-secret-key" not in serialized
    assert "endpoint-secret" not in serialized
    assert "example.invalid" not in serialized
    assert "api_key" not in serialized.lower()
    assert "endpoint" not in serialized.lower()


@pytest.mark.parametrize(
    ("name", "value", "match"),
    (
        ("PDF_STRUCTURE_REFINEMENT_TIMEOUT_SECONDS", "0", "positive number"),
        ("PDF_STRUCTURE_REFINEMENT_MAX_ATTEMPTS", "0", "positive integer"),
        ("PDF_STRUCTURE_REFINEMENT_MAX_CONCURRENT_BATCHES", "many", "positive integer"),
        ("PDF_STRUCTURE_REFINEMENT_GLOBAL_MAX_CONCURRENT_BATCHES", "-1", "positive integer"),
    ),
)
def test_snapshot_rejects_invalid_runtime_limits(monkeypatch, name, value, match) -> None:
    _clear_refinement_env(monkeypatch)
    monkeypatch.setenv(name, value)

    with pytest.raises(ValueError, match=match):
        structure_refinement_config_snapshot()


def test_snapshot_rejects_backoff_inversion(monkeypatch) -> None:
    _clear_refinement_env(monkeypatch)
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_INITIAL_BACKOFF_SECONDS", "5")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_MAX_BACKOFF_SECONDS", "4")

    with pytest.raises(ValueError, match="must be at least"):
        structure_refinement_config_snapshot()


def test_snapshot_rejects_partial_provider_configuration(monkeypatch) -> None:
    _clear_refinement_env(monkeypatch)
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY", "secret")

    with pytest.raises(ValueError, match="both PDF_STRUCTURE_REFINEMENT"):
        structure_refinement_config_snapshot()
