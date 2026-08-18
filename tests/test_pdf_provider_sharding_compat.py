from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.processing.integration import ProcessingIntegrationRequest, RetainedSourceDescriptor
from app.processing.pdf_ingestion import PRODUCTION_PROVIDER_OPTIONS
from app.processing.pdf_provider_sharding import ProviderTransportShardRunResult
from app.processing import pdf_provider_sharding_compat as compat
from app.storage.models import StorageReference


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


def _large_provider_input():
    return SimpleNamespace(
        provider_byte_size=81 * 1024 * 1024,
        provider_page_count=101,
        provider_page_map=tuple(range(101)),
        provider_checksum_sha256="b" * 64,
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
    canonical = SimpleNamespace(candidate_id="candidate-sharded")

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


def test_sharding_integration_falls_back_for_provider_input_at_target(monkeypatch) -> None:
    provider_input = _large_provider_input()
    provider_input.provider_byte_size = 80 * 1024 * 1024
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
