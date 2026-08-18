from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models import ProcessingRun
from app.structured_content_v2.repository import (
    StructuredContentCandidateV2Repository,
    StructuredContentV2ProcessingRunMismatch,
)


class _AutoflushDisabledSession:
    def __init__(self, pending_run: ProcessingRun) -> None:
        self.new = {pending_run}

    def execute(self, statement):
        raise AssertionError("database lookup must not run for a matching pending ProcessingRun")


def _pending_run(*, document_id: str = "doc-1") -> ProcessingRun:
    return ProcessingRun(
        processing_run_id="run-1",
        document_id=document_id,
        source_file_id="source-1",
        status="running",
        provider_ref="paddle-vl",
    )


def test_processing_run_validation_accepts_matching_pending_run_when_autoflush_is_disabled() -> None:
    session = _AutoflushDisabledSession(_pending_run())
    candidate = SimpleNamespace(processing_run_ref="run-1", document_ref="doc-1")

    StructuredContentCandidateV2Repository()._validate_processing_run(session, candidate)


def test_processing_run_validation_rejects_pending_run_for_another_document() -> None:
    session = _AutoflushDisabledSession(_pending_run(document_id="doc-2"))
    candidate = SimpleNamespace(processing_run_ref="run-1", document_ref="doc-1")

    with pytest.raises(
        StructuredContentV2ProcessingRunMismatch,
        match="processing run belongs to a different document",
    ):
        StructuredContentCandidateV2Repository()._validate_processing_run(session, candidate)
