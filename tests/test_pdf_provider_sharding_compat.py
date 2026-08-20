from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.processing.integration import ProcessingIntegrationRequest, RetainedSourceDescriptor
from app.processing.pdf_geometry_integration import GeometryProviderInput
from app.processing.pdf_ingestion import PRODUCTION_PROVIDER_OPTIONS
from app.processing.pdf_provider_sharding import ProviderTransportShardRunResult
from app.processing import pdf_provider_sharding_compat as compat
from app.processing.pdf_page_presentation_lifecycle_compat import (
    DeferredPresentationProviderInput,
)
from app.storage.models import StorageReference
from scripts.apply_provider_transport_sharding import (
    patch_provider_transport_sharding_installation,
)


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


def _large_provider_input() -> DeferredPresentationProviderInput:
    page_map = tuple(
        {
            "provider_page_index": index,
            "original_page_index": index,
            "original_page_number": index + 1,
            "source_unit_id": f"pdf-page:{index + 1:06d}",
        }
        for index in range(101)
    )
    return DeferredPresentationProviderInput(
        processing_attempt_id="attempt-sharding-compat",
        storage_reference=StorageReference.parse("src_" + "2" * 32),
        checksum_sha256="a" * 64,
        byte_size=81 * 1024 * 1024,
        media_type="application/pdf",
        filename="render.pdf",
        preprocessing=SimpleNamespace(page_count=101),
        provider_storage_reference=StorageReference.parse("src_" + "3" * 32),
        provider_checksum_sha256="b" * 64,
        provider_byte_size=81 * 1024 * 1024,
        provider_filename="ordinary-pages.pdf",
        provider_page_count=101,
        provider_page_map=page_map,
        presentation_manifest={"provider_page_map": list(page_map), "pages": [{"page_number": i + 1, "source_unit_id": f"pdf-page:{i + 1:06d}", "ocr_route": "modal_paddle_ocr"} for i in range(101)]},
        provider_pdf_bytes=None,
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
            byte_size=60 * 1024 * 1024,
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

    monkeypatch.setattr(compat, "run_provider_transport_shards", fake_run_provider_transport_shards)
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
    decision = next(fields for event, fields in diagnostics if event == "PDF_PROVIDER_TRANSPORT_SHARDING_DECISION")
    assert decision["recognized_provider_input"] is True
    assert decision["provider_input_size_bytes"] == 81 * 1024 * 1024
    assert decision["provider_input_page_count"] == 101
    assert decision["sharding_required"] is True


def test_real_geometry_provider_input_above_target_enters_sharding(monkeypatch) -> None:
    captured = {}
    diagnostics = []
    canonical = SimpleNamespace(candidate_id="candidate-geometry")

    async def fake_run_provider_transport_shards(**kwargs):
        captured.update(kwargs)
        return ProviderTransportShardRunResult(canonical, None, None, True, True, 2)

    monkeypatch.setattr(compat, "run_provider_transport_shards", fake_run_provider_transport_shards)
    monkeypatch.setattr(compat, "_diagnostic", lambda event, **fields: diagnostics.append((event, fields)))
    geometry_input = _geometry_provider_input(byte_size=81 * 1024 * 1024, page_count=100)
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
    assert normalized.provider_page_map[0]["original_page_number"] == 1
    assert normalized.provider_page_map[-1]["original_page_number"] == 100
    assert len(normalized.presentation_manifest["pages"]) == 100
    assert all(page["ocr_route"] == "modal_paddle_ocr" for page in normalized.presentation_manifest["pages"])
    decision = next(fields for event, fields in diagnostics if event == "PDF_PROVIDER_TRANSPORT_SHARDING_DECISION")
    assert decision["recognized_provider_input"] is True
    assert decision["sharding_required"] is True
    assert outcome.error is None
    assert outcome.canonicalization is canonical


def test_sharding_integration_falls_back_for_provider_input_at_target(monkeypatch) -> None:
    provider_input = replace(_large_provider_input(), provider_byte_size=80 * 1024 * 1024)
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
        orchestrator=_Orchestrator(_geometry_provider_input(byte_size=80 * 1024 * 1024, page_count=100)),
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


def test_sharding_install_replaces_only_pdf_ingestion_constructor(monkeypatch) -> None:
    from app.processing import pdf_ingestion

    monkeypatch.setattr(compat, "_INSTALLED", False)
    monkeypatch.setattr(pdf_ingestion, "EndToEndProcessingIntegrationService", compat._BaseIntegrationService)
    compat.install_provider_transport_sharding_compat()
    assert pdf_ingestion.EndToEndProcessingIntegrationService is compat.ShardingAwareEndToEndProcessingIntegrationService
    assert compat._INSTALLED is True


def test_sharding_install_rejects_unexpected_existing_constructor(monkeypatch) -> None:
    from app.processing import pdf_ingestion

    class _UnexpectedService:
        pass

    monkeypatch.setattr(compat, "_INSTALLED", False)
    monkeypatch.setattr(pdf_ingestion, "EndToEndProcessingIntegrationService", _UnexpectedService)
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
    assert "service = ShardingAwareEndToEndProcessingIntegrationService(" in source
    assert "install_provider_transport_sharding_compat()" in source
