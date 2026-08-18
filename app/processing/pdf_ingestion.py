"""Production PDF ingestion through retained source -> Modal -> Reader v2 canonical content."""
from __future__ import annotations

import asyncio
from concurrent.futures import Future as ConcurrentFuture
from concurrent.futures import ThreadPoolExecutor
from functools import partial
import hashlib
import logging
import sys
import threading
import uuid
from dataclasses import dataclass

from app.config import settings
from app.database import SessionLocal
from app.models import Document, SourceFile
from app.processing.integration import (
    EndToEndProcessingIntegrationService,
    IntegrationError,
    ProcessingIntegrationRequest,
    RetainedSourceDescriptor,
)
from app.processing.orchestration import PollingPolicy
from app.processing.paddle_vl.client import PaddleVLClient, PaddleVLClientConfig
from app.processing.paddle_vl.normalization import PaddlePdfNormalizationError
from app.processing.pdf_canonicalization import (
    PdfCanonicalizationError,
    PdfCanonicalizationService,
    PdfSelectionDisposition,
)
from app.processing.pdf_geometry_integration import (
    GeometryProviderInput,
    ProviderInputAwareProcessingOrchestrator,
    ProviderInputChecksumProvider,
    ProviderInputGrantService,
    prepare_geometry_provider_input,
)
from app.processing.transport.dependencies import get_transport_grant_service
from app.processing.transport.models import TransportGrantState
from app.storage.dependencies import get_storage_provider
from app.storage.models import StorageReference

logger = logging.getLogger("uvicorn.error")

PRODUCTION_RESULT_PROFILE = "full"
PRODUCTION_BATCH_SIZE = 50
PRODUCTION_MAX_CONCURRENT_WORKERS = 5
PDF_PREPROCESSING_MAX_CONCURRENCY = 1
PDF_PREPROCESSING_MAX_INFLIGHT = 2
_PDF_PREPROCESSING_EXECUTOR = ThreadPoolExecutor(
    max_workers=PDF_PREPROCESSING_MAX_CONCURRENCY,
    thread_name_prefix="pdf-preprocess",
)
_PDF_PREPROCESSING_CAPACITY = threading.BoundedSemaphore(
    PDF_PREPROCESSING_MAX_INFLIGHT
)
PRODUCTION_PROVIDER_OPTIONS = {
    "batch_size": PRODUCTION_BATCH_SIZE,
    "max_concurrent_workers": PRODUCTION_MAX_CONCURRENT_WORKERS,
    "fail_fast": False,
    "ttl_seconds": 3600,
}


@dataclass(frozen=True, slots=True)
class PdfIngestionIds:
    processing_attempt_id: str
    provider_job_id: str
    provider_request_id: str


class PdfPreprocessingCapacityError(RuntimeError):
    """The bounded OCRmyPDF submission capacity is currently full."""


class _PreprocessingJobState:
    """Release capacity and clean abandoned outputs independently of task state."""

    def __init__(
        self,
        *,
        storage,
        document_id: str,
        processing_attempt_id: str,
    ) -> None:
        self._storage = storage
        self._document_id = document_id
        self._processing_attempt_id = processing_attempt_id
        self._lock = threading.Lock()
        self._completed = False
        self._abandoned = False
        self._cleanup_claimed = False
        self._capacity_released = False

    def mark_abandoned(self, future: ConcurrentFuture) -> None:
        schedule_cleanup = False
        with self._lock:
            self._abandoned = True
            if self._completed and not self._cleanup_claimed:
                self._cleanup_claimed = True
                schedule_cleanup = True
        if schedule_cleanup:
            _PDF_PREPROCESSING_EXECUTOR.submit(
                self._cleanup_abandoned_result_and_release,
                future,
            )

    def mark_consumed_or_failed(self) -> None:
        release_capacity = False
        with self._lock:
            if not self._capacity_released:
                self._capacity_released = True
                release_capacity = True
        if release_capacity:
            _PDF_PREPROCESSING_CAPACITY.release()

    def on_worker_done(self, future: ConcurrentFuture) -> None:
        cleanup_inline = False
        with self._lock:
            self._completed = True
            if self._abandoned and not self._cleanup_claimed:
                self._cleanup_claimed = True
                cleanup_inline = True
        if cleanup_inline:
            self._cleanup_abandoned_result_and_release(future)

    def _cleanup_abandoned_result_and_release(
        self,
        future: ConcurrentFuture,
    ) -> None:
        try:
            try:
                abandoned_input = future.result()
            except BaseException:
                logger.exception(
                    "PDF preprocessing failed after task cancellation document_id=%s processing_attempt_id=%s",
                    self._document_id,
                    self._processing_attempt_id,
                )
            else:
                try:
                    self._storage.delete(abandoned_input.storage_reference)
                    _diagnostic(
                        "PDF_GEOMETRY_PROVIDER_INPUT_DELETED_AFTER_CANCELLATION",
                        document_id=self._document_id,
                        processing_attempt_id=self._processing_attempt_id,
                    )
                except Exception:
                    logger.exception(
                        "Could not delete cancelled preprocessing output document_id=%s processing_attempt_id=%s",
                        self._document_id,
                        self._processing_attempt_id,
                    )
        finally:
            self.mark_consumed_or_failed()


def _diagnostic(event: str, **fields: object) -> None:
    payload = " ".join(f"{name}={value}" for name, value in fields.items())
    message = f"{event} {payload}".rstrip()
    logger.info(message)
    print(message, file=sys.stderr, flush=True)


def new_pdf_ingestion_ids() -> PdfIngestionIds:
    token = uuid.uuid4().hex
    return PdfIngestionIds(
        processing_attempt_id=f"pdf-ingest-{token}",
        provider_job_id=f"pdf-job-{token}",
        provider_request_id=f"pdf-request-{token}",
    )


def _safe_failure_message(exc: BaseException | None = None) -> str:
    if isinstance(exc, IntegrationError):
        return exc.safe_message
    if isinstance(exc, PdfPreprocessingCapacityError):
        return "PDF preprocessing capacity is temporarily full; retry later"
    return "PDF processing failed before Reader v2 content became ready"


def _canonicalization_safe_reason(exc: PdfCanonicalizationError) -> tuple[str | None, str]:
    cause = exc.__cause__
    if isinstance(cause, PaddlePdfNormalizationError):
        return type(cause).__name__, str(cause)
    return (type(cause).__name__ if cause is not None else None, str(exc))


def _canonicalization_failure_message(cause_type: str | None, safe_reason: str) -> str:
    if cause_type == "PaddlePdfNormalizationError":
        return f"canonicalization failed: {cause_type}: {safe_reason}"
    return "canonicalization failed: retained PDF canonicalization failed"


class _DiagnosticPdfCanonicalizationService:
    """Thin production wrapper that records safe canonicalization failure diagnostics."""

    def __init__(self, delegate: PdfCanonicalizationService) -> None:
        self._delegate = delegate
        self.last_failure_message: str | None = None

    def canonicalize(self, envelope):
        self.last_failure_message = None
        _diagnostic(
            "PDF_CANONICALIZATION_STARTED",
            document_id=envelope.identity.document_id,
            processing_attempt_id=envelope.identity.atlas_attempt_id,
            evidence_source=envelope.ingestion.evidence_source.value,
            payload_size_bytes=envelope.ingestion.payload_size_bytes,
        )
        try:
            outcome = self._delegate.canonicalize(envelope)
        except PdfCanonicalizationError as exc:
            cause_type, safe_reason = _canonicalization_safe_reason(exc)
            self.last_failure_message = _canonicalization_failure_message(cause_type, safe_reason)
            print(
                "PDF_CANONICALIZATION_FAILED "
                f"document_id={envelope.identity.document_id} "
                f"processing_attempt_id={envelope.identity.atlas_attempt_id} "
                f"error_type={type(exc).__name__} cause_type={cause_type} safe_reason={safe_reason}",
                file=sys.stderr,
                flush=True,
            )
            logger.exception(
                "PDF canonicalization failed document_id=%s processing_attempt_id=%s error_type=%s cause_type=%s safe_reason=%s",
                envelope.identity.document_id,
                envelope.identity.atlas_attempt_id,
                type(exc).__name__,
                cause_type,
                safe_reason,
            )
            raise
        _diagnostic(
            "PDF_CANONICALIZATION_COMPLETED",
            document_id=envelope.identity.document_id,
            processing_attempt_id=envelope.identity.atlas_attempt_id,
            produced_candidate_id=outcome.candidate_id,
            selected_candidate_id=outcome.selected_candidate_id,
            selection_version=outcome.selection_version,
            selection_disposition=outcome.selection_disposition.value,
        )
        return outcome


def _set_document_terminal_state(document_id: str, *, status: str, error_message: str | None) -> None:
    db = SessionLocal()
    try:
        document = db.get(Document, document_id)
        if document is None:
            return
        document.status = status
        document.error_message = error_message
        db.commit()
        _diagnostic(
            "PDF_DOCUMENT_STATE_UPDATED",
            document_id=document_id,
            status=status,
            has_error=bool(error_message),
        )
    except Exception:
        db.rollback()
        logger.exception("Could not update PDF ingestion terminal state document_id=%s", document_id)
    finally:
        db.close()


def _set_document_page_count_if_missing(document_id: str, page_count: int) -> None:
    if int(page_count) <= 0:
        raise RuntimeError("Preprocessed PDF page count is invalid")
    db = SessionLocal()
    try:
        document = db.get(Document, document_id)
        if document is None:
            return
        if document.pages_count is None or int(document.pages_count or 0) <= 0:
            document.pages_count = int(page_count)
            db.commit()
            _diagnostic(
                "PDF_DOCUMENT_PAGE_COUNT_DISCOVERED",
                document_id=document_id,
                page_count=page_count,
            )
    except Exception:
        db.rollback()
        logger.exception("Could not persist PDF page count document_id=%s", document_id)
        raise
    finally:
        db.close()


def _read_verified_source_pdf(storage, descriptor: RetainedSourceDescriptor) -> bytes:
    source_pdf = storage.get(descriptor.storage_reference)
    if not isinstance(source_pdf, bytes) or not source_pdf.startswith(b"%PDF-"):
        raise RuntimeError("Retained PDF source bytes are unavailable")
    if len(source_pdf) != descriptor.byte_size:
        raise RuntimeError("Retained PDF source size does not match metadata")
    if hashlib.sha256(source_pdf).hexdigest().lower() != descriptor.sha256.lower():
        raise RuntimeError("Retained PDF source checksum does not match metadata")
    return source_pdf


def _cleanup_is_safe_from_outcome(outcome) -> bool:
    return bool(
        outcome.revocation_succeeded
        or outcome.grant_final_state is TransportGrantState.REVOKED
    )


def _cleanup_is_safe_from_error(exc: BaseException, provider_submission_started: bool) -> bool:
    if isinstance(exc, IntegrationError):
        return bool(
            exc.revocation_succeeded
            or exc.grant_final_state is TransportGrantState.REVOKED
        )
    return not provider_submission_started


def _prepare_geometry_provider_input_from_storage(
    *,
    storage,
    descriptor: RetainedSourceDescriptor,
    processing_attempt_id: str,
    expected_page_count: int | None,
) -> GeometryProviderInput:
    """Read and preprocess only after bounded executor admission."""
    source_pdf = _read_verified_source_pdf(storage, descriptor)
    return prepare_geometry_provider_input(
        storage=storage,
        source_pdf_bytes=source_pdf,
        original_filename=descriptor.filename,
        processing_attempt_id=processing_attempt_id,
        expected_page_count=expected_page_count,
    )


async def _prepare_geometry_provider_input_async(
    *,
    storage,
    descriptor: RetainedSourceDescriptor,
    processing_attempt_id: str,
    document_id: str,
    expected_page_count: int | None,
) -> GeometryProviderInput:
    """Submit bounded preprocessing and make cancellation cleanup task-independent."""
    if not _PDF_PREPROCESSING_CAPACITY.acquire(blocking=False):
        raise PdfPreprocessingCapacityError("pdf_preprocessing_capacity_full")

    job_state = _PreprocessingJobState(
        storage=storage,
        document_id=document_id,
        processing_attempt_id=processing_attempt_id,
    )
    try:
        concurrent_future = _PDF_PREPROCESSING_EXECUTOR.submit(
            partial(
                _prepare_geometry_provider_input_from_storage,
                storage=storage,
                descriptor=descriptor,
                processing_attempt_id=processing_attempt_id,
                expected_page_count=expected_page_count,
            )
        )
    except BaseException:
        job_state.mark_consumed_or_failed()
        raise

    concurrent_future.add_done_callback(job_state.on_worker_done)
    wrapped_future = asyncio.wrap_future(concurrent_future)
    try:
        result = await asyncio.shield(wrapped_future)
    except asyncio.CancelledError:
        job_state.mark_abandoned(concurrent_future)
        raise
    except BaseException:
        job_state.mark_consumed_or_failed()
        raise
    else:
        job_state.mark_consumed_or_failed()
        return result


async def process_pdf_document_background(
    document_id: str,
    source_file_id: str,
    ids: PdfIngestionIds,
) -> None:
    """Process one retained PDF and mark completed only after canonical selection exists."""
    _diagnostic(
        "PDF_BACKGROUND_TASK_STARTED",
        document_id=document_id,
        source_file_id=source_file_id,
        processing_attempt_id=ids.processing_attempt_id,
        provider_job_id=ids.provider_job_id,
    )
    db = SessionLocal()
    try:
        document = db.get(Document, document_id)
        source = db.get(SourceFile, source_file_id)
        if document is None or source is None or source.document_id != document_id:
            logger.error("PDF ingestion retained source unavailable document_id=%s", document_id)
            _set_document_terminal_state(
                document_id,
                status="failed",
                error_message="Retained PDF source metadata is unavailable",
            )
            return
        if not source.retained or not source.storage_reference or not source.checksum_sha256 or not source.byte_size:
            logger.error("PDF ingestion retained source incomplete document_id=%s", document_id)
            _set_document_terminal_state(
                document_id,
                status="failed",
                error_message="Retained PDF source metadata is incomplete",
            )
            return
        expected_page_count = int(document.pages_count) if document.pages_count and int(document.pages_count) > 0 else None
        descriptor = RetainedSourceDescriptor(
            document_id=document.id,
            source_file_id=source.id,
            storage_reference=StorageReference.parse(source.storage_reference),
            retained=True,
            sha256=source.checksum_sha256,
            byte_size=int(source.byte_size),
            media_type="application/pdf",
            filename=source.original_filename,
        )
        _diagnostic(
            "PDF_SOURCE_VALIDATED",
            document_id=document_id,
            source_file_id=source_file_id,
            processing_attempt_id=ids.processing_attempt_id,
            byte_size=descriptor.byte_size,
            page_count=(expected_page_count if expected_page_count is not None else "deferred"),
        )
    finally:
        db.close()

    storage = get_storage_provider()
    client: PaddleVLClient | None = None
    geometry_input: GeometryProviderInput | None = None
    geometry_cleanup_allowed = False
    provider_submission_started = False
    try:
        geometry_input = await _prepare_geometry_provider_input_async(
            storage=storage,
            descriptor=descriptor,
            processing_attempt_id=ids.processing_attempt_id,
            document_id=document_id,
            expected_page_count=expected_page_count,
        )
        if expected_page_count is None:
            _set_document_page_count_if_missing(
                document_id,
                geometry_input.preprocessing.page_count,
            )
        _diagnostic(
            "PDF_GEOMETRY_PREPROCESSING_COMPLETED",
            document_id=document_id,
            processing_attempt_id=ids.processing_attempt_id,
            page_count=geometry_input.preprocessing.page_count,
            changed_page_count=geometry_input.preprocessing.changed_page_count,
            provider_input_size_bytes=geometry_input.byte_size,
            preprocessing_version=geometry_input.preprocessing.version,
        )

        _diagnostic(
            "PDF_PROVIDER_CONFIGURATION",
            document_id=document_id,
            processing_attempt_id=ids.processing_attempt_id,
            base_url_configured=bool(settings.paddle_vl_api_base_url),
            bearer_token_configured=bool(settings.paddle_vl_api_bearer_token),
            public_origin_configured=bool(settings.public_source_transport_origin),
        )
        client = PaddleVLClient(
            PaddleVLClientConfig(
                base_url=settings.paddle_vl_api_base_url or "",
                bearer_token=settings.paddle_vl_api_bearer_token or "",
                timeout_seconds=settings.paddle_vl_api_timeout_seconds,
                default_result_profile=PRODUCTION_RESULT_PROFILE,
            )
        )
        provider = ProviderInputChecksumProvider(client, geometry_input)
        orchestrator = ProviderInputAwareProcessingOrchestrator(
            provider=provider,
            storage=storage,
            provider_input=geometry_input,
        )
        canonicalizer = _DiagnosticPdfCanonicalizationService(
            PdfCanonicalizationService(
                storage=storage,
                session_factory=SessionLocal,
                render_pdf_storage_reference=geometry_input.storage_reference,
                render_pdf_checksum_sha256=geometry_input.checksum_sha256,
                render_pdf_source_kind="geometry_preprocessed_provider_input",
            )
        )
        grant_service = ProviderInputGrantService(
            get_transport_grant_service(),
            geometry_input,
        )
        service = EndToEndProcessingIntegrationService(
            grant_service=grant_service,
            orchestrator=orchestrator,
            canonicalizer=canonicalizer,
            public_origin=settings.public_source_transport_origin,
            polling_policy=PollingPolicy(
                timeout_seconds=1800,
                initial_interval_seconds=2,
                max_interval_seconds=10,
                backoff_factor=1.5,
            ),
        )
        request = ProcessingIntegrationRequest(
            processing_attempt_id=ids.processing_attempt_id,
            correlation_id=ids.provider_request_id,
            retained_source=descriptor,
            provider_name="paddle-vl",
            provider_job_id=ids.provider_job_id,
            provider_request_id=ids.provider_request_id,
            result_profile=PRODUCTION_RESULT_PROFILE,
            provider_job_options=PRODUCTION_PROVIDER_OPTIONS,
        )
        _diagnostic(
            "PDF_PROVIDER_REQUEST_STARTED",
            document_id=document_id,
            processing_attempt_id=ids.processing_attempt_id,
            provider_job_id=ids.provider_job_id,
            result_profile=PRODUCTION_RESULT_PROFILE,
            batch_size=PRODUCTION_BATCH_SIZE,
            max_concurrent_workers=PRODUCTION_MAX_CONCURRENT_WORKERS,
            provider_input_kind="geometry_preprocessed_pdf",
        )
        provider_submission_started = True
        outcome = await service.process(request)
        geometry_cleanup_allowed = _cleanup_is_safe_from_outcome(outcome)
        _diagnostic(
            "PDF_PROVIDER_TERMINAL",
            document_id=document_id,
            processing_attempt_id=ids.processing_attempt_id,
            provider_job_id=ids.provider_job_id,
            phase=outcome.integration_terminal_phase.value,
            provider_status=(
                outcome.provider_terminal_status.value if outcome.provider_terminal_status is not None else None
            ),
            error_category=outcome.error.category.value if outcome.error is not None else None,
            raw_result_retained=outcome.raw_result is not None,
            canonicalization_ready=outcome.canonicalization is not None,
        )
        if outcome.error is not None or outcome.canonicalization is None:
            error_message = canonicalizer.last_failure_message
            if error_message is None:
                error_message = outcome.error.safe_message if outcome.error else "Reader v2 canonicalization did not complete"
            _set_document_terminal_state(
                document_id,
                status="failed",
                error_message=error_message,
            )
            return

        canonical = outcome.canonicalization
        selection_tracks_produced_candidate = canonical.selected_candidate_id == canonical.candidate_id
        if canonical.selection_disposition in {
            PdfSelectionDisposition.CREATED,
            PdfSelectionDisposition.UNCHANGED,
            PdfSelectionDisposition.PROMOTED,
        } and not selection_tracks_produced_candidate:
            logger.error(
                "PDF ingestion canonical selection invariant failed document_id=%s selected_candidate_id=%s produced_candidate_id=%s selection_disposition=%s",
                document_id,
                canonical.selected_candidate_id,
                canonical.candidate_id,
                canonical.selection_disposition.value,
            )
            _set_document_terminal_state(
                document_id,
                status="failed",
                error_message="Reader v2 canonical selection is inconsistent with processing result",
            )
            return
        elif canonical.selection_disposition is PdfSelectionDisposition.PRESERVED:
            _diagnostic(
                "PDF_CANONICAL_SELECTION_PRESERVED",
                document_id=document_id,
                processing_attempt_id=ids.processing_attempt_id,
                produced_candidate_id=canonical.candidate_id,
                selected_candidate_id=canonical.selected_candidate_id,
                selection_version=canonical.selection_version,
            )

        _set_document_terminal_state(document_id, status="completed", error_message=None)
        _diagnostic(
            "PDF_INGESTION_COMPLETED",
            document_id=document_id,
            processing_attempt_id=ids.processing_attempt_id,
            produced_candidate_id=canonical.candidate_id,
            selected_candidate_id=canonical.selected_candidate_id,
            selection_disposition=canonical.selection_disposition.value,
        )
    except Exception as exc:
        geometry_cleanup_allowed = _cleanup_is_safe_from_error(
            exc,
            provider_submission_started,
        )
        print(
            "PDF_INGESTION_UNHANDLED_FAILURE "
            f"document_id={document_id} processing_attempt_id={ids.processing_attempt_id} "
            f"error_type={type(exc).__name__}",
            file=sys.stderr,
            flush=True,
        )
        logger.exception(
            "Production PDF ingestion failed document_id=%s processing_attempt_id=%s",
            document_id,
            ids.processing_attempt_id,
        )
        _set_document_terminal_state(
            document_id,
            status="failed",
            error_message=_safe_failure_message(exc),
        )
    finally:
        if geometry_input is not None:
            if geometry_cleanup_allowed:
                try:
                    storage.delete(geometry_input.storage_reference)
                    _diagnostic(
                        "PDF_GEOMETRY_PROVIDER_INPUT_DELETED",
                        document_id=document_id,
                        processing_attempt_id=ids.processing_attempt_id,
                    )
                except Exception:
                    logger.exception(
                        "Could not delete temporary geometry PDF document_id=%s processing_attempt_id=%s",
                        document_id,
                        ids.processing_attempt_id,
                    )
            else:
                _diagnostic(
                    "PDF_GEOMETRY_PROVIDER_INPUT_RETAINED",
                    document_id=document_id,
                    processing_attempt_id=ids.processing_attempt_id,
                    reason="provider_submission_may_still_be_active",
                )
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                logger.exception("Failed to close PaddleVL client document_id=%s", document_id)
