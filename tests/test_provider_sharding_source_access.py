from __future__ import annotations

import asyncio
from datetime import timedelta
import inspect
from types import SimpleNamespace

import pytest

from app.processing import pdf_geometry_integration as integration
from app.processing import pdf_provider_sharding as sharding
from app.processing.integration import RetainedSourceDescriptor
from app.processing.models import ProviderLifecycleStatus
from app.processing.orchestration import OrchestrationPhase, PollingPolicy
from app.processing.transport.models import TransportGrantState
from app.storage.models import StorageReference


RENDER_SHA = "a" * 64
SHARD_SHA = "b" * 64


def _require_staging_sharding_overlay() -> None:
    source = inspect.getsource(sharding.run_provider_transport_shards)
    if "shard_source_url_factory" not in source:
        pytest.skip("Staging provider sharding source-access overlay is not installed")


def test_each_shard_receives_exact_delivery_source_factory_and_4200s_ttl(
    monkeypatch,
) -> None:
    _require_staging_sharding_overlay()
    storage = object()
    client = object()
    render_reference = StorageReference.parse("src_" + "1" * 32)
    shard_reference = StorageReference.parse("src_" + "2" * 32)
    provider_input = SimpleNamespace(
        provider_byte_size=87_179_148,
        provider_page_count=100,
    )
    shard_input = SimpleNamespace(
        storage_reference=render_reference,
        checksum_sha256=RENDER_SHA,
        byte_size=87_179_148,
        media_type="application/pdf",
        filename="book.presentation-render.pdf",
        provider_storage_reference=shard_reference,
        provider_checksum_sha256=SHARD_SHA,
        provider_byte_size=40_000_000,
        provider_filename="book.provider-shard-001.pdf",
    )
    plan = sharding.ProviderInputShardPlan(
        shard_index=0,
        provider_page_start=0,
        provider_page_end=49,
        provider_page_count=50,
        serialized_size_bytes=40_000_000,
    )
    descriptor = RetainedSourceDescriptor(
        document_id="doc-1",
        source_file_id="source-1",
        storage_reference=StorageReference.parse("src_" + "3" * 32),
        retained=True,
        sha256="c" * 64,
        byte_size=12_486_675,
        media_type="application/pdf",
        filename="book.pdf",
    )
    polling_policy = PollingPolicy(
        timeout_seconds=1800,
        initial_interval_seconds=2,
        max_interval_seconds=10,
        backoff_factor=1.5,
    )
    factory_calls = []
    service_kwargs = []
    source_factory = object()

    monkeypatch.setattr(
        sharding,
        "plan_provider_input_shards",
        lambda *args, **kwargs: (plan,),
    )
    monkeypatch.setattr(
        sharding,
        "materialize_provider_input_shard",
        lambda *args, **kwargs: shard_input,
    )

    def build_factory(*, storage, reference, byte_size):
        factory_calls.append((storage, reference, byte_size))
        return source_factory

    monkeypatch.setattr(sharding, "build_provider_input_source_url_factory", build_factory)
    monkeypatch.setattr(
        integration,
        "ProviderInputChecksumProvider",
        lambda *args, **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        integration,
        "ProviderInputAwareProcessingOrchestrator",
        lambda **kwargs: SimpleNamespace(),
    )
    monkeypatch.setattr(
        integration,
        "ProviderInputGrantService",
        lambda *args, **kwargs: SimpleNamespace(),
    )

    class FakeService:
        def __init__(self, **kwargs):
            service_kwargs.append(dict(kwargs))

        async def process(self, request):
            return SimpleNamespace(
                revocation_succeeded=True,
                grant_final_state=TransportGrantState.REVOKED,
                integration_terminal_phase=OrchestrationPhase.RAW_RESULT_RETAINED,
                provider_terminal_status=ProviderLifecycleStatus.PROVIDER_COMPLETED,
                error=None,
                poll_count=1,
                raw_result=object(),
            )

    monkeypatch.setattr(sharding, "EndToEndProcessingIntegrationService", FakeService)
    monkeypatch.setattr(
        sharding,
        "_delete_shard_provider_input_if_safe",
        lambda *args, **kwargs: None,
    )
    merged = SimpleNamespace(
        ingestion=SimpleNamespace(payload_size_bytes=1234, page_summary=None)
    )
    monkeypatch.setattr(
        sharding,
        "merge_provider_shard_results",
        lambda *args, **kwargs: merged,
    )
    canonical = object()
    canonicalizer = SimpleNamespace(canonicalize=lambda raw: canonical)

    result = asyncio.run(
        sharding.run_provider_transport_shards(
            storage=storage,
            client=client,
            provider_input=provider_input,
            descriptor=descriptor,
            processing_attempt_id="attempt-1",
            logical_provider_job_id="job-1",
            logical_provider_request_id="request-1",
            result_profile="full",
            provider_job_options={"ttl_seconds": 3600},
            public_origin="https://atlas.example",
            polling_policy=polling_policy,
            canonicalizer=canonicalizer,
            diagnostic=lambda *args, **kwargs: None,
        )
    )

    assert result.error is None
    assert result.canonicalization is canonical
    assert result.shard_count == 1
    assert factory_calls == [(storage, shard_reference, 40_000_000)]
    assert len(service_kwargs) == 1
    assert service_kwargs[0]["source_transport_url_factory"] is source_factory
    assert service_kwargs[0]["source_access_ttl"] == timedelta(seconds=4200)
    assert service_kwargs[0]["polling_policy"] is polling_policy
