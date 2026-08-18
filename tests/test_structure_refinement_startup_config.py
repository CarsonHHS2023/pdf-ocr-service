from __future__ import annotations

import ast
import logging
from pathlib import Path

import pytest

from app.processing.structure_refinement_config_snapshot import (
    validate_and_log_structure_refinement_config,
)


_REFINEMENT_ENV = (
    "PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY",
    "PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL",
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
    for name in _REFINEMENT_ENV:
        monkeypatch.delenv(name, raising=False)


def test_startup_config_log_is_sanitized_and_bounded(monkeypatch, caplog) -> None:
    _clear_refinement_env(monkeypatch)
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY", "super-secret-key")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL", "vision-model")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_MAX_ATTEMPTS", "4")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_MAX_PAGES_PER_BATCH", "8")

    logger = logging.getLogger("test.structure-refinement-startup")
    with caplog.at_level(logging.INFO, logger=logger.name):
        snapshot = validate_and_log_structure_refinement_config(logger)

    assert snapshot["enabled"] is True
    assert snapshot["model"] == "vision-model"
    assert snapshot["timeout_seconds"] == 45.0
    assert snapshot["max_attempts"] == 4
    assert snapshot["image_policy"]["max_pages_per_batch"] == 8

    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) == 1
    message = messages[0]
    assert message.startswith("PDF_STRUCTURE_REFINEMENT_CONFIG ")
    assert "enabled=True" in message
    assert "model=vision-model" in message
    assert "timeout_seconds=45.0" in message
    assert "max_pages_per_batch=8" in message
    assert "super-secret-key" not in message
    assert "API_KEY" not in message
    assert "Authorization" not in message
    assert "endpoint" not in message.lower()


def test_startup_config_validation_fails_before_logging(monkeypatch, caplog) -> None:
    _clear_refinement_env(monkeypatch)
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_TIMEOUT_SECONDS", "0")

    logger = logging.getLogger("test.structure-refinement-startup-invalid")
    with caplog.at_level(logging.INFO, logger=logger.name):
        with pytest.raises(ValueError, match="TIMEOUT_SECONDS must be a positive number"):
            validate_and_log_structure_refinement_config(logger)

    assert caplog.records == []


def test_application_startup_validates_before_database_initialization() -> None:
    tree = ast.parse(Path("app/main.py").read_text(encoding="utf-8"))
    startup = next(
        node
        for node in tree.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "startup_event"
    )
    calls = [
        node.value.func.id
        for node in startup.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
    ]

    assert calls.index("validate_and_log_structure_refinement_config") < calls.index("init_db")
