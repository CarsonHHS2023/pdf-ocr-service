from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.processing.integration import ProcessingIntegrationRequest, RetainedSourceDescriptor
from app.processing.pdf_geometry_integration import GeometryProviderInput
from app.processing.pdf_ingestion import PRODUCTION_PROVIDER_OPTIONS
from app.processing.pdf_provider_sharding import ProviderTransportShardRunResult
from app.processing import pdf_provider_sharding_compat as compat
from app.storage.models import StorageReference


class _RawClient:
    async def submit_job(self, request):  # pragma: no cover - intercepted by stubbed sharding runner
        raise AssertionError("stubbed sharding runner should intercept")

    async def get_job_status(self, job_id):  # pragma: no cover
        raise AssertionError("stubbed sharding runner should intercept")

    async def get_job_result(self, job_id, profile=None):  # pragma: no cover
        raise AssertionError("stubbed sharding runner should intercept")

    async def get_job_artifact(self, job_id, metadata=None):  # pragma: no cover
        raise AssertionError("stubbed sharding runner should intercept")


class _ProviderWrapper:
    def __init__(self) -> None:
        self._delegate = _RawClient()


class _Orchestrator:
    def __init__(self, provider_input) -> None:
        self.provider_input = provider_input
        self.provider = _ProviderWrapper()
        self.storage = object()


class _GrantService:
    pass


class _Canonicalizer:
    pass


def _geometry_provider_input(*, byte_size: int, page_count: int) -> GeometryProviderInput:
    return GeometryProviderInput(
        processing_attempt_id="attempt-geometry-runtime",
        storage_reference=StorageReference.parse("src_" + "4" * 32),
        checksum_sha256="c" * 64,
        byte_size=byte_size,
        media_type="application/pdf",
        filename="geometry-runtime.pdf",
        preprocessing=SimpleNamespace(page_count=page_count),
    )


def _request() -> ProcessingIntegrationRequest:
    return ProcessingIntegrationRequest(
        processing_attempt_id="attempt-geometry-runtime",
        correlation_id="correlation-geometry-runtime",
        retained_source=RetainedSourceDescriptor(
            document_id="document-geometry-runtime",
            source_file_id="source-geometry-runtime",
            storage_reference=StorageReference.parse("src_" + "5" * 32),
            retained=True,
            sha256="d" * 64,
            byte_size=12 * 1024 * 1024,
            media_type="application/pdf",
            filename="book.pdf",
        ),
        provider_name="paddle-vl",
        provider_job_id="job-geometry-runtime",
        provider_request_id="request-geometry-runtime",
        result_profile="full",
        provider_job_options=PRODUCTION_PROVIDER_OPTIONS,
    )


def test_real_geometry_provider_input_above_target_enters_sharding(monkeypatch) -> None:
    geometry_input = _geometry_provider_input(
        byte_size=81 * 1024 * 1024,
        page_count=100,
    )
    captured = {}
    diagnostics = []
    canonical = SimpleNamespace(candidate_id="candidate-geometry-runtime")

    async def fake_run_provider_transport_shards(**kwargs):
        captured.update(kwargs)
        return ProviderTransportShardRunResult(
            canonicalization=canonical,
            raw_result=None,
            error=None,
            cleanup_safe=True,
            submission_started=True,
            shard_count=2,
        )

    monkeypatch.setattr(compat, "run_provider_transport_shards", fake_run_provider_transport_shards)
    monkeypatch.setattr(
        compat,
        "_diagnostic",
        lambda event, **fields: diagnostics.append((event, fields)),
    )

    service = compat.ShardingAwareEndToEndProcessingIntegrationService(
        grant_service=_GrantService(),
        orchestrator=_Orchestrator(geometry_input),
        canonicalizer=_Canonicalizer(),
        public_origin="https://reader.example",
    )

    outcome = asyncio.run(service.process(_request()))

    normalized = captured["provider_input"]
    assert normalized.provider_byte_size == geometry_input.byte_size
    assert normalized.provider_page_count == 100
    assert normalized.provider_storage_reference == geometry_input.storage_reference
    assert normalized.provider_checksum_sha256 == geometry_input.checksum_sha256
    assert len(normalized.provider_page_map) == 100
    assert normalized.provider_page_map[0]["provider_page_index"] == 0
    assert normalized.provider_page_map[0]["original_page_number"] == 1
    assert normalized.provider_page_map[-1]["provider_page_index"] == 99
    assert normalized.provider_page_map[-1]["original_page_number"] == 100
    assert len(normalized.presentation_manifest["pages"]) == 100
    assert all(
        page["ocr_route"] == "modal_paddle_ocr"
        for page in normalized.presentation_manifest["pages"]
    )

    decision = next(
        fields
        for event, fields in diagnostics
        if event == "PDF_PROVIDER_TRANSPORT_SHARDING_DECISION"
    )
    assert decision["recognized_provider_input"] is True
    assert decision["provider_input_size_bytes"] == 81 * 1024 * 1024
    assert decision["provider_input_page_count"] == 100
    assert decision["sharding_required"] is True
    assert outcome.error is None
    assert outcome.canonicalization is canonical


def test_real_geometry_provider_input_at_target_uses_base_path(monkeypatch) -> None:
    geometry_input = _geometry_provider_input(
        byte_size=80 * 1024 * 1024,
        page_count=100,
    )
    service = compat.ShardingAwareEndToEndProcessingIntegrationService(
        grant_service=_GrantService(),
        orchestrator=_Orchestrator(geometry_input),
        canonicalizer=_Canonicalizer(),
        public_origin="https://reader.example",
    )
    called = False

    async def fake_base_process(self, request):
        nonlocal called
        called = True
        return "base-path"

    monkeypatch.setattr(compat._BaseIntegrationService, "process", fake_base_process)

    assert asyncio.run(service.process(_request())) == "base-path"
    assert called is True
