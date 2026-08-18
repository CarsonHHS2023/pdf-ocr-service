from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.processing.orchestration import (
    ProcessingOrchestrator,
    ProviderJobRequest,
    ProviderSourceDocumentRequest,
)
from app.processing.pdf_geometry_integration import (
    GeometryProviderInput,
    ProviderInputAwareProcessingOrchestrator,
    ProviderInputChecksumProvider,
    ProviderInputGrantService,
)
from app.processing.pdf_geometry_preprocessing import GeometryPreprocessedPdf
from app.processing.raw_result import (
    RawProcessingResultEnvelope,
    RawResultEvidenceSource,
    RawResultIdentity,
    RawResultIngestionMetadata,
    RawResultProviderProvenance,
    RawResultSourceProvenance,
)
from app.storage.models import StorageReference


SOURCE_SHA = "a" * 64
PROVIDER_SHA = "b" * 64


def _provider_input() -> GeometryProviderInput:
    preprocessing = GeometryPreprocessedPdf(
        pdf_bytes=b"%PDF-preprocessed",
        checksum_sha256=PROVIDER_SHA,
        byte_size=17,
        page_count=2,
        changed_page_count=1,
        pages=(),
    )
    return GeometryProviderInput(
        processing_attempt_id="attempt-1",
        storage_reference=StorageReference.parse("src_" + "1" * 32),
        checksum_sha256=PROVIDER_SHA,
        byte_size=17,
        media_type="application/pdf",
        filename="book.geometry.pdf",
        preprocessing=preprocessing,
    )


class FakeProvider:
    def __init__(self) -> None:
        self.submitted = None

    async def submit_job(self, request):
        self.submitted = request
        return "accepted"

    async def get_job_status(self, job_id):
        raise AssertionError("not used")

    async def get_job_result(self, job_id, profile=None):
        raise AssertionError("not used")

    async def get_job_artifact(self, job_id, metadata=None):
        raise AssertionError("not used")


class FakeGrantService:
    def __init__(self) -> None:
        self.kwargs = None

    def create_grant(self, **kwargs):
        self.kwargs = kwargs
        return "grant"

    def inspect(self, grant_id):
        return grant_id

    def revoke(self, grant_id):
        return grant_id


def test_provider_submission_uses_preprocessed_checksum() -> None:
    delegate = FakeProvider()
    provider = ProviderInputChecksumProvider(delegate, _provider_input())
    request = ProviderJobRequest(
        "job-1",
        "req-1",
        [
            ProviderSourceDocumentRequest(
                "doc-1",
                "https://example.test/source.pdf",
                '"original"',
                SOURCE_SHA,
            )
        ],
    )

    assert asyncio.run(provider.submit_job(request)) == "accepted"
    submitted = delegate.submitted
    assert submitted.documents[0].pdf_source_sha256 == PROVIDER_SHA
    assert submitted.documents[0].pdf_source_etag is None
    assert request.documents[0].pdf_source_sha256 == SOURCE_SHA


def test_transport_grant_serves_preprocessed_object() -> None:
    delegate = FakeGrantService()
    service = ProviderInputGrantService(delegate, _provider_input())

    service.create_grant(
        storage_reference=StorageReference.parse("src_" + "2" * 32),
        source_sha256=SOURCE_SHA,
        source_byte_size=99,
        media_type="application/pdf",
        source_etag='"source"',
        filename="book.pdf",
    )

    assert delegate.kwargs["storage_reference"] == _provider_input().storage_reference
    assert delegate.kwargs["source_sha256"] == PROVIDER_SHA
    assert delegate.kwargs["source_byte_size"] == 17
    assert delegate.kwargs["source_etag"] is None
    assert delegate.kwargs["filename"] == "book.geometry.pdf"


def _raw_envelope() -> RawProcessingResultEnvelope:
    return RawProcessingResultEnvelope(
        identity=RawResultIdentity(
            "attempt-1",
            "corr-1",
            "doc-1",
            "source-1",
            "paddle-vl",
            "job-1",
        ),
        source=RawResultSourceProvenance(SOURCE_SHA, None, "application/pdf"),
        provider=RawResultProviderProvenance(
            build_tag="build-1",
            model_version="model-1",
            pipeline_version="pipeline-1",
            configuration={"profile": "full", "nested": {"mode": "original"}},
            capabilities={"vision": {"images": False}},
            timestamps={"provider": {"completed": "2026-07-31T00:00:00Z"}},
            warnings=({"code": "bounded-warning"},),
            errors=(),
        ),
        ingestion=RawResultIngestionMetadata(
            ingested_at=datetime.now(timezone.utc),
            payload_media_type="application/json",
            payload_encoding=None,
            payload_compression=None,
            payload_size_bytes=2,
            payload_sha256="c" * 64,
            storage_reference=StorageReference.parse("src_" + "3" * 32),
            evidence_source=RawResultEvidenceSource.INLINE_JSON,
        ),
    )


def test_orchestrator_rebuilds_frozen_provider_provenance_without_mappingproxy_failure(monkeypatch) -> None:
    async def fake_ingest(self, request, result, page_summary):
        return _raw_envelope()

    monkeypatch.setattr(ProcessingOrchestrator, "_ingest", fake_ingest)
    orchestrator = ProviderInputAwareProcessingOrchestrator(
        provider_input=_provider_input(),
        provider=FakeProvider(),
        storage=object(),
    )
    request = type("Request", (), {"source_checksum_sha256": SOURCE_SHA})()

    envelope = asyncio.run(orchestrator._ingest(request, object(), None))
    config = dict(envelope.provider.configuration)

    assert envelope.source.source_checksum_sha256 == SOURCE_SHA
    assert config["source_checksum_sha256"] == SOURCE_SHA
    assert config["provider_input_checksum_sha256"] == PROVIDER_SHA
    assert config["provider_input_kind"] == "geometry_preprocessed_pdf"
    assert config["geometry_page_count"] == 2
    assert config["geometry_changed_page_count"] == 1
    assert config["nested"]["mode"] == "original"
    assert envelope.provider.capabilities["vision"]["images"] is False
    assert envelope.provider.timestamps["provider"]["completed"] == "2026-07-31T00:00:00Z"
    assert envelope.provider.warnings[0]["code"] == "bounded-warning"
