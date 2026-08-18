from __future__ import annotations

import io
import logging
from pathlib import Path

from app.logging_config import configure_application_logging


def test_application_logging_writes_and_flushes_to_supplied_stream() -> None:
    stream = io.StringIO()
    configure_application_logging(stream=stream, force=True)

    logger = logging.getLogger("app.processing.pdf_ingestion")
    logger.info("PDF ingestion stage=waiting_for_modal document_id=doc-1")

    output = stream.getvalue()
    assert "app.processing.pdf_ingestion" in output
    assert "stage=waiting_for_modal" in output
    assert "document_id=doc-1" in output


def test_hf_entrypoint_preserves_application_logging_configuration() -> None:
    source = Path("app.py").read_text(encoding="utf-8")
    assert "configure_application_logging()" in source
    assert "log_config=None" in source


def test_fastapi_module_does_not_use_noop_basic_config() -> None:
    source = Path("app/main.py").read_text(encoding="utf-8")
    assert "logging.basicConfig" not in source
    assert "configure_application_logging()" in source


def test_container_disables_python_output_buffering() -> None:
    dockerfile = Path("Dockerfile").read_text(encoding="utf-8")
    assert "PYTHONUNBUFFERED=1" in dockerfile
