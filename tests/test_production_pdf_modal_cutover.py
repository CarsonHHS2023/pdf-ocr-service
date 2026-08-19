from __future__ import annotations

import asyncio
import gzip
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from app.processing.integration import (
    EndToEndProcessingIntegrationService,
    ProcessingIntegrationRequest,
    RetainedSourceDescriptor,
)
from app.processing.models import ProviderLifecycleStatus
from app.processing.orchestration import OrchestrationOutcome, OrchestrationPhase, PollingPolicy
from app.processing.paddle_vl.normalization import PaddlePdfNormalizationError
from app.processing.pdf_canonicalization import PdfCanonicalizationError, _decode_json_payload, _matching_document
from app.processing.pdf_ingestion import (
    PRODUCTION_BATCH_SIZE,
    PRODUCTION_MAX_CONCURRENT_WORKERS,
    PRODUCTION_PROVIDER_OPTIONS,
    PRODUCTION_RESULT_PROFILE,
    _canonicalization_failure_message,
    _canonicalization_safe_reason,
)
from app.processing.raw_result import (
    RawProcessingResultEnvelope,
    RawResultArtifactMetadata,
    RawResultEvidenceSource,
    RawResultIdentity,
    RawResultIngestionMetadata,
    RawResultProviderProvenance,
    RawResultSourceProvenance,
)
from app.processing.transport.service import InMemoryTransportGrantService
from app.storage.models import StorageReference


SOURCE_SHA = "a" * 64


class _CapturingOrchestrator:
    def __init__(self) -> None:
        self.request = None
        self.policy = None

    async def run_once(self, request, policy=None):
        self.request = request
        self.policy = policy
        return OrchestrationOutcome(
            request.processing_attempt_id,
            request.correlation_id,
            request.document_id,
            request.source_file_id,
            request.provider_name,
            request.provider_job_id,
            request.provider_request_id,
            OrchestrationPhase.PROVIDER_PARTIAL_FAILED,
            ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED,
            0.1,
            1,
            None,
            None,
        )


def test_production_modal_options_are_not_single_page_spike_settings() -> None:
    assert PRODUCTION_RESULT_PROFILE == "full"
    assert PRODUCTION_BATCH_SIZE == 50
    assert PRODUCTION_MAX_CONCURRENT_WORKERS == 5
    assert PRODUCTION_PROVIDER_OPTIONS == {
        "batch_size": 50,
        "max_concurrent_workers": 5,
        "fail_fast": False,
        "ttl_seconds": 3600,
    }
    assert PRODUCTION_PROVIDER_OPTIONS["batch_size"] != 1


def test_integration_forwards_provider_options_and_custom_polling_policy() -> None:
    orchestrator = _CapturingOrchestrator()
    policy = PollingPolicy(
        timeout_seconds=1800,
        initial_interval_seconds=2,
        max_interval_seconds=10,
        backoff_factor=1.5,
    )
    service = EndToEndProcessingIntegrationService(
        grant_service=InMemoryTransportGrantService(),
        orchestrator=orchestrator,
        public_origin="https://reader.example",
        polling_policy=policy,
    )
    request = ProcessingIntegrationRequest(
        processing_attempt_id="attempt-production-1",
        correlation_id="corr-production-1",
        retained_source=RetainedSourceDescriptor(
            document_id="doc-production-1",
            source_file_id="source-production-1",
            storage_reference=StorageReference.parse("src_" + "1" * 32),
            retained=True,
            sha256=SOURCE_SHA,
            byte_size=123,
            media_type="application/pdf",
        ),
        provider_job_id="job-production-1",
        result_profile="full",
        provider_job_options=PRODUCTION_PROVIDER_OPTIONS,
    )

    asyncio.run(service.process(request))

    assert orchestrator.request is not None
    assert dict(orchestrator.request.provider_job_options) == PRODUCTION_PROVIDER_OPTIONS
    assert orchestrator.request.result_profile == "full"
    assert orchestrator.policy is policy
    assert orchestrator.policy.timeout_seconds == 1800


def test_canonicalizer_accepts_modal_full_result_gzip_artifact_document_list() -> None:
    payload = [
        {
            "document_id": "doc-production-1",
            "raw_result": [
                {
                    "page_number": 1,
                    "page_index": 0,
                    "local_page_index": 0,
                    "source_page_range": {"page_start": 1, "page_end": 1},
                    "width": 1000,
                    "height": 1400,
                    "parsing_res_list": [],
                }
            ],
        }
    ]
    retained = gzip.compress(json.dumps(payload).encode("utf-8"))
    envelope = RawProcessingResultEnvelope(
        identity=RawResultIdentity(
            "attempt-production-1",
            "corr-production-1",
            "doc-production-1",
            "source-production-1",
            "paddle-vl",
            "job-production-1",
            "request-production-1",
            "full",
            "completed",
        ),
        source=RawResultSourceProvenance(SOURCE_SHA, source_media_type="application/pdf"),
        provider=RawResultProviderProvenance(),
        ingestion=RawResultIngestionMetadata(
            ingested_at=datetime.now(timezone.utc),
            payload_media_type="json.gz",
            payload_encoding=None,
            payload_compression="gzip",
            payload_size_bytes=len(retained),
            payload_sha256=hashlib.sha256(retained).hexdigest(),
            storage_reference=StorageReference.parse("src_" + "2" * 32),
            evidence_source=RawResultEvidenceSource.ARTIFACT_BYTES,
            artifact_metadata=RawResultArtifactMetadata(
                artifact_id="artifact-production-1",
                media_type="json.gz",
                compression="gzip",
                size_bytes=len(retained),
                checksum_sha256=hashlib.sha256(retained).hexdigest(),
            ),
        ),
    )

    decoded = _decode_json_payload(envelope, retained)
    document = _matching_document(decoded, "doc-production-1")
    assert document["document_id"] == "doc-production-1"
    assert len(document["raw_result"]) == 1


def test_canonicalization_diagnostics_expose_only_bounded_normalization_reason() -> None:
    normalization_error = PaddlePdfNormalizationError("page 1 width must be a finite positive number")
    try:
        raise PdfCanonicalizationError("retained PDF canonicalization failed") from normalization_error
    except PdfCanonicalizationError as exc:
        cause_type, safe_reason = _canonicalization_safe_reason(exc)

    assert cause_type == "PaddlePdfNormalizationError"
    assert safe_reason == "page 1 width must be a finite positive number"
    assert _canonicalization_failure_message(cause_type, safe_reason) == (
        "canonicalization failed: PaddlePdfNormalizationError: page 1 width must be a finite positive number"
    )


def test_canonicalization_diagnostics_keep_non_normalization_causes_generic() -> None:
    try:
        raise PdfCanonicalizationError("retained PDF canonicalization failed") from RuntimeError("provider payload secret")
    except PdfCanonicalizationError as exc:
        cause_type, safe_reason = _canonicalization_safe_reason(exc)

    assert cause_type == "RuntimeError"
    assert safe_reason == "retained PDF canonicalization failed"
    persisted = _canonicalization_failure_message(cause_type, safe_reason)
    assert persisted == "canonicalization failed: retained PDF canonicalization failed"
    assert "provider payload secret" not in persisted


def test_production_upload_source_contains_no_full_page_raster_or_local_page_ocr_path() -> None:
    source = Path("app/routers/ocr.py").read_text(encoding="utf-8")
    production_block = source[source.index("# ── PDF: retain original source"):source.index('@router.post("/ocr/{task_id}"')]

    assert "_render_page_as_png" not in source
    assert "PdfPage(" not in production_block
    assert "page_image_data" not in production_block
    assert "process_book_background" not in source
    if "legacy_acceptance_key" in source:
        assert "commit_retained_ingestion" in production_block
        assert "run_ingestion_dispatch" in production_block
        assert "process_pdf_document_background" not in production_block
    else:
        assert "process_pdf_document_background" in production_block
    assert 'fitz.open(stream=content, filetype="pdf")' in production_block
    assert "get_pixmap" not in production_block


def test_production_runner_has_no_legacy_pdf_page_or_mineru_dependency() -> None:
    source = Path("app/processing/pdf_ingestion.py").read_text(encoding="utf-8")
    for forbidden in ("PdfPage", "PageOCRService", "process_book_background", "MineruResult", "page_image_data"):
        assert forbidden not in source
    assert "PdfCanonicalizationService" in source
    assert "PRODUCTION_BATCH_SIZE = 50" in source
    assert "PRODUCTION_MAX_CONCURRENT_WORKERS = 5" in source


def test_production_upload_logs_acceptance_retention_commit_and_queue_boundaries() -> None:
    source = Path("app/routers/ocr.py").read_text(encoding="utf-8")

    assert 'logging.getLogger("uvicorn.error")' in source
    assert "PDF_UPLOAD_ACCEPTED" in source
    assert "PDF_SOURCE_RETAINED" in source
    assert "PDF_DATABASE_COMMITTED" in source
    assert "PDF_BACKGROUND_TASK_QUEUED" in source
    assert "file=sys.stderr" in source
    assert "flush=True" in source


def test_production_runner_logs_flushed_diagnostic_boundaries() -> None:
    source = Path("app/processing/pdf_ingestion.py").read_text(encoding="utf-8")

    for event in (
        "PDF_BACKGROUND_TASK_STARTED",
        "PDF_SOURCE_VALIDATED",
        "PDF_PROVIDER_CONFIGURATION",
        "PDF_PROVIDER_REQUEST_STARTED",
        "PDF_PROVIDER_TERMINAL",
        "PDF_CANONICALIZATION_STARTED",
        "PDF_CANONICALIZATION_FAILED",
        "PDF_CANONICALIZATION_COMPLETED",
        "PDF_CANONICAL_SELECTION_PRESERVED",
        "PDF_DOCUMENT_STATE_UPDATED",
        "PDF_INGESTION_COMPLETED",
        "PDF_INGESTION_UNHANDLED_FAILURE",
    ):
        assert event in source
    assert "logger.exception(" in source
    assert "file=sys.stderr" in source
    assert "flush=True" in source
    assert "bearer_token_configured=bool(settings.paddle_vl_api_bearer_token)" in source
    assert "settings.paddle_vl_api_bearer_token," not in source


def test_production_runner_persists_bounded_canonicalization_failure() -> None:
    source = Path("app/processing/pdf_ingestion.py").read_text(encoding="utf-8")

    assert "self.last_failure_message" in source
    assert "error_message = canonicalizer.last_failure_message" in source
    assert "canonicalization failed: {cause_type}: {safe_reason}" in source
    assert "provider payload secret" not in source


def test_production_completion_accepts_current_or_preserved_explicit_selection() -> None:
    source = Path("app/processing/pdf_ingestion.py").read_text(encoding="utf-8")
    current_invariant = "if canonical.selection_disposition in {"
    preserved_branch = "elif canonical.selection_disposition is PdfSelectionDisposition.PRESERVED:"
    completed = '_set_document_terminal_state(document_id, status="completed", error_message=None)'

    assert current_invariant in source
    assert preserved_branch in source
    assert "PDF_CANONICAL_SELECTION_PRESERVED" in source
    assert "Reader v2 canonical selection is inconsistent with processing result" in source
    assert completed in source
    assert source.index(current_invariant) < source.index(completed)
    assert source.index(preserved_branch) < source.index(completed)
