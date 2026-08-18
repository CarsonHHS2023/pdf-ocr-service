from __future__ import annotations

import asyncio
import hashlib
import threading
from datetime import datetime, timezone

from app.processing.integration import (
    EndToEndProcessingIntegrationService,
    IntegrationErrorCategory,
    ProcessingIntegrationRequest,
    RetainedSourceDescriptor,
)
from app.processing.models import ProviderLifecycleStatus
from app.processing.orchestration import OrchestrationOutcome, OrchestrationPhase
from app.processing.pdf_canonicalization import (
    PdfCanonicalizationError,
    PdfCanonicalizationOutcome,
    PdfSelectionDisposition,
)
from app.processing.raw_result import (
    RawProcessingResultEnvelope,
    RawResultEvidenceSource,
    RawResultIdentity,
    RawResultIngestionMetadata,
    RawResultProviderProvenance,
    RawResultSourceProvenance,
)
from app.processing.transport.service import InMemoryTransportGrantService
from app.storage.models import StorageReference


SOURCE_SHA = "a" * 64


def _request() -> ProcessingIntegrationRequest:
    return ProcessingIntegrationRequest(
        processing_attempt_id="attempt-1",
        correlation_id="corr-1",
        retained_source=RetainedSourceDescriptor(
            document_id="doc-1",
            source_file_id="sf-1",
            storage_reference=StorageReference.parse("src_" + "1" * 32),
            retained=True,
            sha256=SOURCE_SHA,
            byte_size=12,
            media_type="application/pdf",
        ),
        provider_job_id="job-1",
        provider_request_id="request-1",
    )


def _raw() -> RawProcessingResultEnvelope:
    body = b"{}"
    digest = hashlib.sha256(body).hexdigest()
    return RawProcessingResultEnvelope(
        RawResultIdentity(
            "attempt-1", "corr-1", "doc-1", "sf-1", "paddle-vl", "job-1", "request-1", "standard", "completed"
        ),
        RawResultSourceProvenance(SOURCE_SHA, source_media_type="application/pdf"),
        RawResultProviderProvenance(),
        RawResultIngestionMetadata(
            datetime.now(timezone.utc),
            "application/json",
            "utf-8",
            None,
            len(body),
            digest,
            StorageReference.parse("src_" + "2" * 32),
            RawResultEvidenceSource.INLINE_JSON,
        ),
    )


def _outcome(*, completed=True, retained=True) -> OrchestrationOutcome:
    status = ProviderLifecycleStatus.PROVIDER_COMPLETED if completed else ProviderLifecycleStatus.PROVIDER_PARTIAL_FAILED
    phase = OrchestrationPhase.RAW_RESULT_RETAINED if completed else OrchestrationPhase.PROVIDER_PARTIAL_FAILED
    return OrchestrationOutcome(
        "attempt-1",
        "corr-1",
        "doc-1",
        "sf-1",
        "paddle-vl",
        "job-1",
        "request-1",
        phase,
        status,
        1.0,
        1,
        None,
        _raw() if retained else None,
    )


class _Orchestrator:
    def __init__(self, out):
        self.out = out

    async def run_once(self, request, policy=None):
        return self.out


class _Canonicalizer:
    def __init__(self, *, fail=False):
        self.calls = []
        self.fail = fail
        self.thread_ids: list[int] = []

    def canonicalize(self, envelope):
        self.calls.append(envelope)
        self.thread_ids.append(threading.get_ident())
        if self.fail:
            raise PdfCanonicalizationError("private implementation detail")
        return _canonicalization_outcome()


def _canonicalization_outcome() -> PdfCanonicalizationOutcome:
    return PdfCanonicalizationOutcome(
        document_ref="doc-1",
        source_file_ref="sf-1",
        processing_run_ref="attempt-1",
        raw_result_ref="src_" + "2" * 32,
        structured_processing_result_ref="src_" + "3" * 32,
        candidate_id="candidate-1",
        selected_candidate_id="candidate-1",
        selection_version=1,
        selection_disposition=PdfSelectionDisposition.CREATED,
        initial_selection_created=True,
    )


def test_completed_retained_result_invokes_canonicalizer_once() -> None:
    canonicalizer = _Canonicalizer()
    result = asyncio.run(
        EndToEndProcessingIntegrationService(
            grant_service=InMemoryTransportGrantService(),
            orchestrator=_Orchestrator(_outcome()),
            canonicalizer=canonicalizer,
            public_origin="https://public.example",
        ).process(_request())
    )

    assert len(canonicalizer.calls) == 1
    assert result.error is None
    assert result.canonicalization is not None
    assert result.canonicalization.candidate_id == "candidate-1"
    assert result.canonicalization.initial_selection_created is True


def test_sync_canonicalizer_runs_off_event_loop_thread() -> None:
    canonicalizer = _Canonicalizer()
    event_loop_thread_id: int | None = None

    async def run():
        nonlocal event_loop_thread_id
        event_loop_thread_id = threading.get_ident()
        return await EndToEndProcessingIntegrationService(
            grant_service=InMemoryTransportGrantService(),
            orchestrator=_Orchestrator(_outcome()),
            canonicalizer=canonicalizer,
            public_origin="https://public.example",
        ).process(_request())

    result = asyncio.run(run())

    assert result.error is None
    assert canonicalizer.thread_ids
    assert canonicalizer.thread_ids[0] != event_loop_thread_id


def test_async_canonicalizer_is_awaited_directly() -> None:
    calls: list[RawProcessingResultEnvelope] = []
    thread_ids: list[int] = []

    class AsyncCanonicalizer:
        def canonicalize(self, _envelope):
            raise AssertionError("sync canonicalize must not be called")

        async def canonicalize_async(self, envelope):
            calls.append(envelope)
            thread_ids.append(threading.get_ident())
            await asyncio.sleep(0)
            return _canonicalization_outcome()

    event_loop_thread_id: int | None = None

    async def run():
        nonlocal event_loop_thread_id
        event_loop_thread_id = threading.get_ident()
        return await EndToEndProcessingIntegrationService(
            grant_service=InMemoryTransportGrantService(),
            orchestrator=_Orchestrator(_outcome()),
            canonicalizer=AsyncCanonicalizer(),
            public_origin="https://public.example",
        ).process(_request())

    result = asyncio.run(run())

    assert result.error is None
    assert len(calls) == 1
    assert thread_ids == [event_loop_thread_id]


def test_partial_failed_result_does_not_canonicalize() -> None:
    canonicalizer = _Canonicalizer()
    result = asyncio.run(
        EndToEndProcessingIntegrationService(
            grant_service=InMemoryTransportGrantService(),
            orchestrator=_Orchestrator(_outcome(completed=False)),
            canonicalizer=canonicalizer,
            public_origin="https://public.example",
        ).process(_request())
    )

    assert canonicalizer.calls == []
    assert result.canonicalization is None


def test_canonicalization_failure_keeps_retained_raw_result_in_outcome() -> None:
    canonicalizer = _Canonicalizer(fail=True)
    result = asyncio.run(
        EndToEndProcessingIntegrationService(
            grant_service=InMemoryTransportGrantService(),
            orchestrator=_Orchestrator(_outcome()),
            canonicalizer=canonicalizer,
            public_origin="https://public.example",
        ).process(_request())
    )

    assert len(canonicalizer.calls) == 1
    assert result.raw_result is not None
    assert result.raw_result_storage_reference == StorageReference.parse("src_" + "2" * 32)
    assert result.canonicalization is None
    assert result.error is not None
    assert result.error.category is IntegrationErrorCategory.CANONICALIZATION_FAILURE
    assert "private implementation detail" not in result.error.safe_message
