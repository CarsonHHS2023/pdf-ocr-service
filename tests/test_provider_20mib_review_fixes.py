from __future__ import annotations

import asyncio
from contextlib import nullcontext
import inspect
from types import SimpleNamespace

import pytest

from app.processing import pdf_page_classification_observability_compat as classification_obs
from app.processing import pdf_page_presentation_bridge as bridge
from app.processing import pdf_page_presentation_preprocess_compat as preprocess
from app.processing import pdf_provider_sharding as sharding
from app.processing import pdf_provider_sharding_compat as sharding_compat
from app.processing.integration import IntegrationErrorCategory
from app.processing.pdf_canonicalization import PdfCanonicalizationError
from app.processing.pdf_provider_sharding import ProviderInputShardPlan


_MIB = 1024 * 1024


def test_actual_provider_transport_hard_max_is_20_mib() -> None:
    assert sharding.PROVIDER_TRANSPORT_SHARD_TARGET_BYTES == 20 * _MIB
    assert sharding.PROVIDER_TRANSPORT_SHARD_MAX_BYTES == 20 * _MIB
    assert (
        inspect.signature(sharding.materialize_provider_input_shard)
        .parameters["max_bytes"]
        .default
        == 20 * _MIB
    )


def test_materialization_over_20_mib_fails_before_provider_storage(monkeypatch) -> None:
    class FakeDocument:
        page_count = 1

        def close(self):
            pass

    monkeypatch.setattr(sharding, "_provider_pdf_bytes", lambda *args: b"%PDF-fixture")
    monkeypatch.setattr(sharding.fitz, "open", lambda *args, **kwargs: FakeDocument())
    monkeypatch.setattr(
        sharding,
        "_serialize_page_range",
        lambda *args, **kwargs: b"x" * (20 * _MIB + 1),
    )

    storage_puts: list[object] = []
    storage = SimpleNamespace(put=lambda *args, **kwargs: storage_puts.append((args, kwargs)))
    plan = ProviderInputShardPlan(0, 0, 0, 1, 20 * _MIB)

    with pytest.raises(
        sharding.ProviderTransportShardError,
        match="exceeds transport safety maximum",
    ):
        sharding.materialize_provider_input_shard(
            storage,
            SimpleNamespace(),
            plan,
            shard_count=1,
        )

    assert storage_puts == []


def test_classification_diagnostics_use_real_timeout_parse_and_attempt_identity(
    monkeypatch,
) -> None:
    diagnostics: list[tuple[str, dict[str, object]]] = []
    decisions = [
        {
            "page_number": 1,
            "source_unit_id": "pdf-page:000001",
            "candidate": True,
            "classification": {
                "page_role": "unknown",
                "confidence": 0.0,
                "provider": "none",
                "model_id": "",
                "cache_hit": False,
                "reason_codes": ["classification_failed:ValueError"],
            },
            "skip_ocr": False,
            "decision_reason": "role_not_presentation",
        }
    ]

    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY", "not-logged-secret")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL", "test-model")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_TIMEOUT_SECONDS", "not-a-number")
    monkeypatch.setattr(
        bridge,
        "_diagnostic",
        lambda event, **fields: diagnostics.append((event, fields)),
    )
    monkeypatch.setattr(preprocess, "_classify_source_pages", lambda source: decisions)
    monkeypatch.setattr(classification_obs, "_INSTALLED", False)

    classification_obs.install_page_classification_observability_compat()
    with classification_obs.page_classification_observation_context(
        "attempt-review-42"
    ):
        result = preprocess._classify_source_pages(SimpleNamespace())

    assert result is decisions
    for event_name in (
        "PDF_PAGE_CLASSIFICATION_CONFIG",
        "PDF_PAGE_CLASSIFICATION_SUMMARY",
        "PDF_PAGE_CLASSIFICATION_DECISION",
    ):
        fields = next(fields for event, fields in diagnostics if event == event_name)
        assert fields["processing_attempt_id"] == "attempt-review-42"

    config = next(
        fields
        for event, fields in diagnostics
        if event == "PDF_PAGE_CLASSIFICATION_CONFIG"
    )
    assert config["timeout_config_valid"] is False
    assert config["timeout_seconds"] is None
    assert "not-logged-secret" not in repr(config)
    assert classification_obs._PROCESSING_ATTEMPT_ID.get() is None


def test_active_pdf_ingestion_entrypoint_scopes_classification_identity(monkeypatch) -> None:
    """Exercise the actual top-level function used by pdf_ingestion, not a stale alias."""
    from app.processing import pdf_ingestion

    observed_attempts: list[str | None] = []

    monkeypatch.setattr(
        pdf_ingestion,
        "record_pdf_processing_heartbeat",
        lambda **kwargs: None,
    )
    monkeypatch.setattr(
        pdf_ingestion,
        "_read_verified_source_pdf",
        lambda storage, descriptor: b"%PDF-review-fixture",
    )
    monkeypatch.setattr(
        pdf_ingestion,
        "pdf_resource_observation_context",
        lambda **kwargs: nullcontext(),
    )

    expected = SimpleNamespace(
        byte_size=123,
        preprocessing=SimpleNamespace(changed_page_count=0),
    )

    def fake_prepare_geometry_provider_input(**kwargs):
        observed_attempts.append(classification_obs._PROCESSING_ATTEMPT_ID.get())
        return expected

    monkeypatch.setattr(
        pdf_ingestion,
        "prepare_geometry_provider_input",
        fake_prepare_geometry_provider_input,
    )

    result = pdf_ingestion._prepare_geometry_provider_input_from_storage(
        storage=SimpleNamespace(),
        descriptor=SimpleNamespace(
            document_id="document-review-42",
            filename="review.pdf",
        ),
        processing_attempt_id="attempt-active-route-42",
        expected_page_count=1,
    )

    assert result is expected
    assert observed_attempts == ["attempt-active-route-42"]
    assert classification_obs._PROCESSING_ATTEMPT_ID.get() is None


def test_canonicalization_failure_preserves_merged_raw_result(monkeypatch) -> None:
    plan = ProviderInputShardPlan(0, 0, 0, 1, 1024)
    shard_reference = SimpleNamespace(value="review-shard-0")
    shard_input = SimpleNamespace(
        provider_byte_size=1024,
        provider_page_count=1,
        provider_storage_reference=shard_reference,
        provider_checksum_sha256="a" * 64,
        provider_filename="review-shard.pdf",
        media_type="application/pdf",
        preprocessing=None,
    )
    monkeypatch.setattr(sharding, "plan_provider_input_shards", lambda *a, **k: (plan,))
    monkeypatch.setattr(
        sharding,
        "materialize_provider_input_shard",
        lambda *a, **k: shard_input,
    )

    from app.processing import pdf_geometry_integration as integration

    monkeypatch.setattr(
        integration,
        "ProviderInputChecksumProvider",
        lambda client, provider_input: SimpleNamespace(),
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
    monkeypatch.setattr(
        integration,
        "provider_delivery_descriptor",
        lambda provider_input: SimpleNamespace(
            storage_reference=provider_input.provider_storage_reference,
            byte_size=provider_input.provider_byte_size,
        ),
    )
    monkeypatch.setattr(sharding, "get_transport_grant_service", lambda: SimpleNamespace())
    monkeypatch.setattr(
        sharding,
        "build_provider_input_source_url_factory",
        lambda **kwargs: object(),
    )

    raw = SimpleNamespace(name="raw-shard")

    class FakeService:
        def __init__(self, **kwargs):
            pass

        async def process(self, request):
            return SimpleNamespace(
                revocation_succeeded=True,
                grant_final_state=None,
                integration_terminal_phase=SimpleNamespace(value="raw_result_retained"),
                provider_terminal_status=SimpleNamespace(value="completed"),
                error=None,
                poll_count=1,
                raw_result=raw,
            )

    monkeypatch.setattr(sharding, "EndToEndProcessingIntegrationService", FakeService)
    merged_reference = SimpleNamespace(value="merged-raw-result")
    merged = SimpleNamespace(
        ingestion=SimpleNamespace(
            storage_reference=merged_reference,
            payload_sha256="b" * 64,
            payload_size_bytes=1234,
            page_summary=None,
        )
    )
    monkeypatch.setattr(
        sharding,
        "merge_provider_shard_results",
        lambda *args, **kwargs: merged,
    )

    class FailingCanonicalizer:
        def canonicalize(self, envelope):
            raise PdfCanonicalizationError("canonicalization failed")

    diagnostics: list[tuple[str, dict[str, object]]] = []
    result = asyncio.run(
        sharding.run_provider_transport_shards(
            storage=SimpleNamespace(delete=lambda reference: None),
            client=SimpleNamespace(),
            provider_input=SimpleNamespace(
                provider_byte_size=21 * _MIB,
                provider_page_count=1,
            ),
            descriptor=SimpleNamespace(),
            processing_attempt_id="attempt-canonicalization-failure",
            logical_provider_job_id="job-review",
            logical_provider_request_id="request-review",
            result_profile="full",
            provider_job_options={},
            public_origin=None,
            polling_policy=SimpleNamespace(),
            canonicalizer=FailingCanonicalizer(),
            diagnostic=lambda event, **fields: diagnostics.append((event, fields)),
        )
    )

    assert isinstance(result.error, PdfCanonicalizationError)
    assert result.canonicalization is None
    assert result.raw_result is merged
    assert any(event == "PDF_PROVIDER_SHARDS_MERGED" for event, _ in diagnostics)
    assert any(
        event == "PDF_PROVIDER_SHARD_CANONICALIZATION_FAILED"
        and fields["raw_result_retained"] is True
        for event, fields in diagnostics
    )
    assert not any(event == "PDF_PROVIDER_SHARD_MERGE_FAILED" for event, _ in diagnostics)

    outcome = sharding_compat._outcome_from_sharded_result(
        SimpleNamespace(
            retained_source=SimpleNamespace(
                document_id="document-review",
                source_file_id="source-review",
            ),
            provider_name="paddle-vl",
            provider_job_id="job-review",
            provider_request_id="request-review",
        ),
        result,
        elapsed_seconds=1.25,
    )
    assert outcome.error is not None
    assert outcome.error.category is IntegrationErrorCategory.CANONICALIZATION_FAILURE
    assert outcome.canonicalization is None
    assert outcome.raw_result is merged
    assert outcome.raw_result_storage_reference is merged_reference
    assert outcome.raw_result_checksum_sha256 == "b" * 64
    assert outcome.raw_result_size_bytes == 1234
