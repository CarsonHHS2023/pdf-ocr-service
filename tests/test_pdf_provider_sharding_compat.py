from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.processing.integration import ProcessingIntegrationRequest, RetainedSourceDescriptor
from app.processing.pdf_geometry_integration import GeometryProviderInput
from app.processing.pdf_geometry_preprocessing import GeometryPreprocessedPdf
from app.processing.pdf_ingestion import PRODUCTION_PROVIDER_OPTIONS
from app.processing.pdf_page_presentation_bridge import PresentationProviderInput
from app.processing.pdf_provider_sharding import (
    ProviderTransportShardError,
    ProviderTransportShardRunResult,
)
from app.processing import pdf_provider_sharding_compat as compat
from app.storage.models import StorageReference
from scripts.apply_provider_transport_sharding import (
    patch_provider_transport_sharding_installation,
)


_MIB = 1024 * 1024


class _RawClient:
    async def submit_job(self, request):  # pragma: no cover - compatibility shape only
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
    def canonicalize(self, envelope):  # pragma: no cover - stubbed runner returns outcome
        raise AssertionError("stubbed sharding runner should intercept")


def _preprocessing(page_count: int) -> GeometryPreprocessedPdf:
    pdf_bytes = b"%PDF-1.4\n% production-type sharding test\n%%EOF\n"
    checksum = hashlib.sha256(pdf_bytes).hexdigest()
    return GeometryPreprocessedPdf(
        pdf_bytes=pdf_bytes,
        checksum_sha256=checksum,
        byte_size=len(pdf_bytes),
        page_count=page_count,
        changed_page_count=0,
        pages=(),
        version="test-production-presentation-input",
    )


def _presentation_provider_input(
    *,
    full_size: int = 81 * _MIB,
    provider_size: int = 81 * _MIB,
    full_page_count: int = 101,
    provider_page_count: int = 101,
    delivery_is_full_render: bool = True,
) -> PresentationProviderInput:
    if not 0 <= provider_page_count <= full_page_count:
        raise ValueError("provider page count must fit within the full document")

    full_reference = StorageReference.parse("src_" + "2" * 32)
    provider_reference = (
        full_reference
        if delivery_is_full_render
        else StorageReference.parse("src_" + "3" * 32)
    )
    full_checksum = "a" * 64
    provider_checksum = full_checksum if delivery_is_full_render else "b" * 64
    if delivery_is_full_render:
        provider_size = full_size
        provider_page_count = full_page_count

    page_map = tuple(
        {
            "provider_page_index": index,
            "original_page_index": index,
            "original_page_number": index + 1,
            "source_unit_id": f"pdf-page:{index + 1:06d}",
        }
        for index in range(provider_page_count)
    )
    presentation_page_count = full_page_count - provider_page_count
    return PresentationProviderInput(
        processing_attempt_id="attempt-sharding-compat",
        storage_reference=full_reference,
        checksum_sha256=full_checksum,
        byte_size=full_size,
        media_type="application/pdf",
        filename="render.presentation-render.pdf",
        preprocessing=_preprocessing(full_page_count),
        provider_storage_reference=provider_reference,
        provider_checksum_sha256=provider_checksum,
        provider_byte_size=provider_size,
        provider_filename="render.ordinary-pages.pdf",
        provider_page_count=provider_page_count,
        provider_page_map=page_map,
        presentation_manifest={
            "page_count": full_page_count,
            "provider_page_count": provider_page_count,
            "presentation_page_count": presentation_page_count,
            "provider_page_map": list(page_map),
        },
    )


def _large_provider_input() -> PresentationProviderInput:
    return _presentation_provider_input(
        full_size=81 * _MIB,
        provider_size=81 * _MIB,
        full_page_count=101,
        provider_page_count=101,
        delivery_is_full_render=True,
    )


def _geometry_provider_input(*, byte_size: int, page_count: int) -> GeometryProviderInput:
    return GeometryProviderInput(
        processing_attempt_id="attempt-sharding-compat",
        storage_reference=StorageReference.parse("src_" + "4" * 32),
        checksum_sha256="c" * 64,
        byte_size=byte_size,
        media_type="application/pdf",
        filename="geometry-runtime.pdf",
        preprocessing=SimpleNamespace(page_count=page_count),
    )


def _request() -> ProcessingIntegrationRequest:
    return ProcessingIntegrationRequest(
        processing_attempt_id="attempt-sharding-compat",
        correlation_id="correlation-sharding-compat",
        retained_source=RetainedSourceDescriptor(
            document_id="document-sharding-compat",
            source_file_id="source-sharding-compat",
            storage_reference=StorageReference.parse("src_" + "1" * 32),
            retained=True,
            sha256="a" * 64,
            byte_size=60 * _MIB,
            media_type="application/pdf",
            filename="book.pdf",
        ),
        provider_name="paddle-vl",
        provider_job_id="job-sharding-compat",
        provider_request_id="request-sharding-compat",
        result_profile="full",
        provider_job_options=PRODUCTION_PROVIDER_OPTIONS,
    )


def test_sharding_integration_preserves_modal_batch_and_worker_options(monkeypatch) -> None:
    captured = {}
    diagnostics = []
    canonical = SimpleNamespace(candidate_id="candidate-sharded")

    monkeypatch.setattr(
        compat,
        "_diagnostic",
        lambda event, **fields: diagnostics.append((event, fields)),
    )

    async def fake_run_provider_transport_shards(**kwargs):
        captured.update(kwargs)
        return ProviderTransportShardRunResult(
            canonicalization=canonical,
            raw_result=None,
            error=None,
            cleanup_safe=True,
            submission_started=True,
            shard_count=3,
        )

    monkeypatch.setattr(
        compat,
        "run_provider_transport_shards",
        fake_run_provider_transport_shards,
    )
    ticks = iter((10.0, 15.5))
    service = compat.ShardingAwareEndToEndProcessingIntegrationService(
        grant_service=_GrantService(),
        orchestrator=_Orchestrator(_large_provider_input()),
        canonicalizer=_Canonicalizer(),
        public_origin="https://reader.example",
        monotonic=lambda: next(ticks),
    )

    outcome = asyncio.run(service.process(_request()))

    assert captured["provider_job_options"] == {
        "batch_size": 50,
        "max_concurrent_workers": 5,
        "fail_fast": False,
        "ttl_seconds": 3600,
    }
    assert captured["public_origin"] == "https://reader.example"
    assert captured["logical_provider_job_id"] == "job-sharding-compat"
    assert outcome.canonicalization is canonical
    assert outcome.error is None
    assert outcome.revocation_succeeded is True
    assert outcome.elapsed_seconds == 5.5
    assert outcome.grant_id == "provider-transport-shards:3"

    delivery = next(
        fields
        for event, fields in diagnostics
        if event == "PDF_PROVIDER_DELIVERY_READY"
    )
    assert delivery["full_render_byte_size"] == 81 * _MIB
    assert delivery["provider_byte_size"] == 81 * _MIB
    assert delivery["provider_page_count"] == 101
    assert delivery["presentation_page_count"] == 0
    assert delivery["delivery_is_full_render"] is True
    assert delivery["sharding_required"] is True

    decision = next(
        fields
        for event, fields in diagnostics
        if event == "PDF_PROVIDER_TRANSPORT_SHARDING_DECISION"
    )
    assert decision["recognized_provider_input"] is True
    assert decision["provider_input_size_bytes"] == 81 * _MIB
    assert decision["provider_input_page_count"] == 101
    assert decision["sharding_required"] is True

    concise_decision = next(
        fields
        for event, fields in diagnostics
        if event == "PDF_PROVIDER_SHARDING_DECISION"
    )
    assert concise_decision["provider_byte_size"] == 81 * _MIB
    assert concise_decision["route"] == "sharded"


def test_production_presentation_full_render_above_target_enters_sharding(monkeypatch) -> None:
    captured = {}
    canonical = SimpleNamespace(candidate_id="candidate-full-render")

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

    monkeypatch.setattr(
        compat,
        "run_provider_transport_shards",
        fake_run_provider_transport_shards,
    )
    provider_input = _presentation_provider_input(
        full_size=81 * _MIB,
        full_page_count=100,
        delivery_is_full_render=True,
    )
    service = compat.ShardingAwareEndToEndProcessingIntegrationService(
        grant_service=_GrantService(),
        orchestrator=_Orchestrator(provider_input),
        canonicalizer=_Canonicalizer(),
        public_origin="https://reader.example",
    )

    outcome = asyncio.run(service.process(_request()))

    assert captured["provider_input"] is provider_input
    assert outcome.error is None
    assert outcome.canonicalization is canonical


def test_production_presentation_full_render_large_but_provider_subset_small_uses_single_path(
    monkeypatch,
) -> None:
    diagnostics = []
    provider_input = _presentation_provider_input(
        full_size=90 * _MIB,
        provider_size=70 * _MIB,
        full_page_count=100,
        provider_page_count=90,
        delivery_is_full_render=False,
    )
    service = compat.ShardingAwareEndToEndProcessingIntegrationService(
        grant_service=_GrantService(),
        orchestrator=_Orchestrator(provider_input),
        canonicalizer=_Canonicalizer(),
        public_origin="https://reader.example",
    )

    async def fake_base_process(self, request):
        return "base-path"

    monkeypatch.setattr(compat._BaseIntegrationService, "process", fake_base_process)
    monkeypatch.setattr(
        compat,
        "_diagnostic",
        lambda event, **fields: diagnostics.append((event, fields)),
    )

    assert asyncio.run(service.process(_request())) == "base-path"
    delivery = next(
        fields
        for event, fields in diagnostics
        if event == "PDF_PROVIDER_DELIVERY_READY"
    )
    assert delivery["full_render_byte_size"] == 90 * _MIB
    assert delivery["provider_byte_size"] == 70 * _MIB
    assert delivery["provider_page_count"] == 90
    assert delivery["presentation_page_count"] == 10
    assert delivery["delivery_is_full_render"] is False
    assert delivery["sharding_required"] is False


def test_production_presentation_provider_subset_above_target_enters_sharding(monkeypatch) -> None:
    captured = {}
    canonical = SimpleNamespace(candidate_id="candidate-subset")
    provider_input = _presentation_provider_input(
        full_size=92 * _MIB,
        provider_size=81 * _MIB,
        full_page_count=100,
        provider_page_count=95,
        delivery_is_full_render=False,
    )

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

    monkeypatch.setattr(
        compat,
        "run_provider_transport_shards",
        fake_run_provider_transport_shards,
    )
    service = compat.ShardingAwareEndToEndProcessingIntegrationService(
        grant_service=_GrantService(),
        orchestrator=_Orchestrator(provider_input),
        canonicalizer=_Canonicalizer(),
        public_origin="https://reader.example",
    )

    outcome = asyncio.run(service.process(_request()))

    assert captured["provider_input"] is provider_input
    assert outcome.error is None
    assert outcome.canonicalization is canonical


def test_real_geometry_provider_input_above_target_enters_sharding(monkeypatch) -> None:
    captured = {}
    diagnostics = []
    canonical = SimpleNamespace(candidate_id="candidate-geometry")

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

    monkeypatch.setattr(
        compat,
        "run_provider_transport_shards",
        fake_run_provider_transport_shards,
    )
    monkeypatch.setattr(
        compat,
        "_diagnostic",
        lambda event, **fields: diagnostics.append((event, fields)),
    )
    geometry_input = _geometry_provider_input(
        byte_size=81 * _MIB,
        page_count=100,
    )
    service = compat.ShardingAwareEndToEndProcessingIntegrationService(
        grant_service=_GrantService(),
        orchestrator=_Orchestrator(geometry_input),
        canonicalizer=_Canonicalizer(),
        public_origin="https://reader.example",
    )

    outcome = asyncio.run(service.process(_request()))
    normalized = captured["provider_input"]

    assert normalized.provider_storage_reference == geometry_input.storage_reference
    assert normalized.provider_checksum_sha256 == geometry_input.checksum_sha256
    assert normalized.provider_byte_size == geometry_input.byte_size
    assert normalized.provider_page_count == 100
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
    assert decision["provider_input_size_bytes"] == 81 * _MIB
    assert decision["provider_input_page_count"] == 100
    assert decision["sharding_required"] is True
    assert outcome.error is None
    assert outcome.canonicalization is canonical


def test_sharding_integration_falls_back_for_production_input_at_target(monkeypatch) -> None:
    provider_input = _presentation_provider_input(
        full_size=80 * _MIB,
        full_page_count=100,
        delivery_is_full_render=True,
    )
    service = compat.ShardingAwareEndToEndProcessingIntegrationService(
        grant_service=_GrantService(),
        orchestrator=_Orchestrator(provider_input),
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


def test_real_geometry_provider_input_at_target_uses_base_path(monkeypatch) -> None:
    service = compat.ShardingAwareEndToEndProcessingIntegrationService(
        grant_service=_GrantService(),
        orchestrator=_Orchestrator(
            _geometry_provider_input(
                byte_size=80 * _MIB,
                page_count=100,
            )
        ),
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


def test_production_presentation_input_with_partial_delivery_identity_fails_closed() -> None:
    provider_input = replace(
        _presentation_provider_input(
            full_size=90 * _MIB,
            provider_size=81 * _MIB,
            full_page_count=100,
            provider_page_count=95,
            delivery_is_full_render=False,
        ),
        provider_checksum_sha256=None,
    )
    service = SimpleNamespace(orchestrator=_Orchestrator(provider_input))

    with pytest.raises(
        ProviderTransportShardError,
        match="invalid delivery identity",
    ):
        compat._provider_input_for(service)


def test_sharding_input_with_partial_page_mapping_fails_closed() -> None:
    provider_input = SimpleNamespace(
        processing_attempt_id="attempt-partial-mapping",
        storage_reference=StorageReference.parse("src_" + "6" * 32),
        checksum_sha256="e" * 64,
        byte_size=81 * _MIB,
        media_type="application/pdf",
        filename="partial-mapping.pdf",
        preprocessing=SimpleNamespace(page_count=100),
        provider_page_count=100,
    )
    service = SimpleNamespace(orchestrator=_Orchestrator(provider_input))

    with pytest.raises(
        ProviderTransportShardError,
        match="partial page mapping identity",
    ):
        compat._provider_input_for(service)


def test_sharding_input_without_processing_attempt_id_fails_closed() -> None:
    provider_input = SimpleNamespace(
        storage_reference=StorageReference.parse("src_" + "7" * 32),
        checksum_sha256="f" * 64,
        byte_size=81 * _MIB,
        media_type="application/pdf",
        filename="missing-attempt.pdf",
        preprocessing=SimpleNamespace(page_count=100),
    )
    service = SimpleNamespace(orchestrator=_Orchestrator(provider_input))

    with pytest.raises(
        ProviderTransportShardError,
        match="processing attempt id is invalid",
    ):
        compat._provider_input_for(service)


def test_sharding_install_replaces_only_pdf_ingestion_constructor(monkeypatch) -> None:
    from app.processing import pdf_ingestion

    monkeypatch.setattr(compat, "_INSTALLED", False)
    monkeypatch.setattr(
        pdf_ingestion,
        "EndToEndProcessingIntegrationService",
        compat._BaseIntegrationService,
    )

    compat.install_provider_transport_sharding_compat()

    assert pdf_ingestion.EndToEndProcessingIntegrationService is (
        compat.ShardingAwareEndToEndProcessingIntegrationService
    )
    assert compat._INSTALLED is True


def test_sharding_install_rejects_unexpected_existing_constructor(monkeypatch) -> None:
    from app.processing import pdf_ingestion

    class _UnexpectedService:
        pass

    monkeypatch.setattr(compat, "_INSTALLED", False)
    monkeypatch.setattr(
        pdf_ingestion,
        "EndToEndProcessingIntegrationService",
        _UnexpectedService,
    )

    with pytest.raises(RuntimeError, match="unexpected base"):
        compat.install_provider_transport_sharding_compat()


def test_sharding_overlay_makes_production_service_explicit(tmp_path) -> None:
    from app.processing import pdf_ingestion

    source_path = Path(pdf_ingestion.__file__)
    target = tmp_path / "pdf_ingestion.py"
    target.write_text(source_path.read_text(encoding="utf-8"), encoding="utf-8")

    patch_provider_transport_sharding_installation(target)
    source = target.read_text(encoding="utf-8")

    assert "ShardingAwareEndToEndProcessingIntegrationService" in source
    assert (
        "service = ShardingAwareEndToEndProcessingIntegrationService("
        in source
    )
    assert "install_provider_transport_sharding_compat()" in source
