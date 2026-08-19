from __future__ import annotations

import asyncio
from datetime import timedelta

import pytest

from app.processing.integration import (
    EndToEndProcessingIntegrationService,
    IntegrationError,
    IntegrationErrorCategory,
    ProcessingIntegrationRequest,
    RetainedSourceDescriptor,
    TemporarySourceTransportUrl,
)
from app.processing.models import ProviderLifecycleStatus
from app.processing.orchestration import OrchestrationOutcome, OrchestrationPhase
from app.processing.provider_input_source_access import (
    build_provider_input_source_url_factory,
)
from app.processing.transport.models import TransportGrantState
from app.processing.transport.service import InMemoryTransportGrantService
from app.storage.errors import ProviderUnavailable
from app.storage.models import StorageReference


SHA = "a" * 64
PRESIGNED_URL = "https://s3.hf.co/ns/bucket/object?X-Amz-Signature=redacted"


def request() -> ProcessingIntegrationRequest:
    source = RetainedSourceDescriptor(
        document_id="doc-1",
        source_file_id="source-1",
        storage_reference=StorageReference.generate(),
        retained=True,
        sha256=SHA,
        byte_size=1024,
        media_type="application/pdf",
        filename="book.pdf",
    )
    return ProcessingIntegrationRequest(
        processing_attempt_id="attempt-1",
        correlation_id="corr-1",
        retained_source=source,
        provider_job_id="job-1",
        provider_request_id="request-1",
    )


def success_outcome() -> OrchestrationOutcome:
    return OrchestrationOutcome(
        processing_attempt_id="attempt-1",
        correlation_id="corr-1",
        document_id="doc-1",
        source_file_id="source-1",
        provider_name="paddle-vl",
        provider_job_id="job-1",
        provider_request_id="request-1",
        final_phase=OrchestrationPhase.RAW_RESULT_RETAINED,
        provider_terminal_status=ProviderLifecycleStatus.PROVIDER_COMPLETED,
        elapsed_seconds=1.0,
        poll_count=1,
        provider_status_snapshot=None,
        raw_result=None,
    )


class FakeOrchestrator:
    def __init__(self) -> None:
        self.calls = []

    async def run_once(self, orchestration_request, policy=None):
        self.calls.append((orchestration_request, policy))
        return success_outcome()


class FakeProviderInputStorage:
    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls = []

    def generate_provider_read_url(self, reference, *, expires_seconds):
        self.calls.append((reference, expires_seconds))
        if self.failure is not None:
            raise self.failure
        return PRESIGNED_URL


def test_presigned_factory_bypasses_public_origin_and_receives_exact_ttl() -> None:
    grants = InMemoryTransportGrantService()
    orchestrator = FakeOrchestrator()
    observed = []

    def factory(ttl: timedelta):
        observed.append(ttl)
        return TemporarySourceTransportUrl(PRESIGNED_URL)

    service = EndToEndProcessingIntegrationService(
        grant_service=grants,
        orchestrator=orchestrator,
        public_origin=None,
        source_transport_url_factory=factory,
        source_access_ttl=timedelta(minutes=30),
    )
    result = asyncio.run(service.process(request()))

    assert observed == [timedelta(minutes=30)]
    assert len(orchestrator.calls) == 1
    assert orchestrator.calls[0][0].source_url == PRESIGNED_URL
    assert result.grant_final_state == TransportGrantState.REVOKED
    assert PRESIGNED_URL not in repr(result)


def test_factory_none_falls_back_to_existing_atlas_transport() -> None:
    orchestrator = FakeOrchestrator()
    service = EndToEndProcessingIntegrationService(
        grant_service=InMemoryTransportGrantService(),
        orchestrator=orchestrator,
        public_origin="https://atlas.example",
        source_transport_url_factory=lambda ttl: None,
        source_access_ttl=timedelta(minutes=30),
    )

    asyncio.run(service.process(request()))

    assert len(orchestrator.calls) == 1
    assert orchestrator.calls[0][0].source_url.startswith(
        "https://atlas.example/internal/source-transport/"
    )


def test_invalid_factory_value_revokes_grant_and_never_submits() -> None:
    grants = InMemoryTransportGrantService()
    orchestrator = FakeOrchestrator()
    service = EndToEndProcessingIntegrationService(
        grant_service=grants,
        orchestrator=orchestrator,
        source_transport_url_factory=lambda ttl: PRESIGNED_URL,
    )

    with pytest.raises(IntegrationError) as exc_info:
        asyncio.run(service.process(request()))

    assert exc_info.value.category == IntegrationErrorCategory.URL_CONSTRUCTION_FAILURE
    assert exc_info.value.grant_final_state == TransportGrantState.REVOKED
    assert orchestrator.calls == []
    assert PRESIGNED_URL not in str(exc_info.value)


def test_source_access_ttl_must_be_positive() -> None:
    with pytest.raises(ValueError):
        EndToEndProcessingIntegrationService(
            grant_service=InMemoryTransportGrantService(),
            orchestrator=FakeOrchestrator(),
            public_origin="https://atlas.example",
            source_access_ttl=timedelta(0),
        )


def test_built_factory_logs_safe_route_without_presigned_query(caplog) -> None:
    reference = StorageReference.generate()
    storage = FakeProviderInputStorage()
    factory = build_provider_input_source_url_factory(
        storage=storage,
        reference=reference,
        byte_size=87_179_148,
    )

    with caplog.at_level("INFO", logger="uvicorn.error"):
        result = factory(timedelta(seconds=4200))

    assert isinstance(result, TemporarySourceTransportUrl)
    assert result.url == PRESIGNED_URL
    assert storage.calls == [(reference, 4200)]
    assert "route=presigned_object_get" in caplog.text
    assert "host=s3.hf.co" in caplog.text
    assert "byte_size=87179148" in caplog.text
    assert PRESIGNED_URL not in caplog.text
    assert "X-Amz-Signature" not in caplog.text


def test_built_factory_fallback_logs_only_safe_error_type(caplog) -> None:
    reference = StorageReference.generate()
    storage = FakeProviderInputStorage(
        failure=ProviderUnavailable("secret signed url must never be logged")
    )
    factory = build_provider_input_source_url_factory(
        storage=storage,
        reference=reference,
        byte_size=87_179_148,
    )

    with caplog.at_level("WARNING", logger="uvicorn.error"):
        result = factory(timedelta(seconds=4200))

    assert result is None
    assert "route=atlas_source_transport_fallback" in caplog.text
    assert "reason=ProviderUnavailable" in caplog.text
    assert "secret signed url" not in caplog.text
