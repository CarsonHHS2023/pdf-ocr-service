from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.processing import pdf_page_classification_observability_compat as classification_obs
from app.processing import pdf_page_presentation_bridge as bridge
from app.processing import pdf_page_presentation_preprocess_compat as preprocess
from app.processing import pdf_provider_sharding as sharding
from app.processing import pdf_provider_sharding_compat as sharding_compat
from app.processing.pdf_provider_sharding import ProviderInputShardPlan


_MIB = 1024 * 1024


def test_provider_transport_defaults_are_20_mib_with_narrow_safety_ceiling() -> None:
    assert sharding.PROVIDER_TRANSPORT_SHARD_TARGET_BYTES == 20 * _MIB
    assert sharding.PROVIDER_TRANSPORT_SHARD_MAX_BYTES == 24 * _MIB
    assert sharding.PROVIDER_TRANSPORT_SHARD_MAX_CONCURRENCY == 5
    assert sharding.PROVIDER_TRANSPORT_SHARD_TARGET_BYTES < (
        sharding.PROVIDER_TRANSPORT_SHARD_MAX_BYTES
    )


def test_provider_delivery_route_counts_distinguish_presentation_native_and_ocr() -> None:
    provider_input = SimpleNamespace(
        provider_page_count=7,
        presentation_manifest={
            "pages": [
                {"page_number": 1, "ocr_route": "skipped_presentation_image"},
                {"page_number": 2, "ocr_route": "skipped_presentation_image"},
                {"page_number": 3, "ocr_route": "skipped_presentation_image"},
                {"page_number": 4, "ocr_route": "modal_paddle_ocr"},
                {"page_number": 5, "ocr_route": "modal_paddle_ocr"},
                {"page_number": 6, "ocr_route": "modal_paddle_ocr"},
                {"page_number": 7, "ocr_route": "modal_paddle_ocr"},
                {"page_number": 8, "ocr_route": "modal_paddle_ocr"},
                {"page_number": 9, "ocr_route": "native_pdf_text"},
                {"page_number": 10, "ocr_route": "modal_paddle_ocr"},
                {"page_number": 11, "ocr_route": "modal_paddle_ocr"},
            ]
        },
    )

    counts = sharding_compat._provider_page_route_counts(provider_input)

    assert counts == {
        "full_document_page_count": 11,
        "presentation_page_count": 3,
        "native_text_page_count": 1,
        "provider_route_page_count": 7,
        "provider_excluded_page_count": 4,
    }


def test_page_classification_observability_separates_model_fallback_and_native_text(
    monkeypatch,
) -> None:
    diagnostics: list[tuple[str, dict[str, object]]] = []
    decisions = [
        {
            "page_index": 0,
            "page_number": 1,
            "source_unit_id": "pdf-page:000001",
            "candidate": True,
            "classification": {
                "page_role": "cover",
                "confidence": 0.99,
                "provider": "openai",
                "model_id": "test-model",
                "cache_hit": False,
                "reason_codes": ["visual_cover"],
            },
            "skip_ocr": True,
            "decision_reason": "presentation_page_confirmed",
        },
        {
            "page_index": 1,
            "page_number": 2,
            "source_unit_id": "pdf-page:000002",
            "candidate": True,
            "classification": {
                "page_role": "unknown",
                "confidence": 0.0,
                "provider": "none",
                "model_id": "",
                "cache_hit": False,
                "reason_codes": ["classification_failed:ReadTimeout"],
            },
            "skip_ocr": False,
            "decision_reason": "role_not_presentation",
        },
        {
            "page_index": 2,
            "page_number": 3,
            "source_unit_id": "pdf-page:000003",
            "candidate": True,
            "classification": {
                "page_role": "body",
                "confidence": 0.98,
                "provider": "openai",
                "model_id": "test-model",
                "cache_hit": True,
                "reason_codes": ["body_prose"],
            },
            "native_text_accepted": True,
            "skip_ocr": True,
            "decision_reason": "native_pdf_text_accepted",
        },
        {
            "page_index": 3,
            "page_number": 4,
            "source_unit_id": "pdf-page:000004",
            "candidate": False,
            "classification": {
                "page_role": "unknown",
                "confidence": 0.0,
                "provider": "none",
                "model_id": "",
                "cache_hit": False,
                "reason_codes": ["not_selected_for_multimodal_review"],
            },
            "skip_ocr": False,
            "decision_reason": "not_a_local_candidate",
        },
    ]

    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_OPENAI_API_KEY", "not-logged-secret")
    monkeypatch.setenv("PDF_STRUCTURE_REFINEMENT_OPENAI_MODEL", "test-model")
    monkeypatch.setattr(
        bridge,
        "_diagnostic",
        lambda event, **fields: diagnostics.append((event, fields)),
    )
    monkeypatch.setattr(preprocess, "_classify_source_pages", lambda source: decisions)
    monkeypatch.setattr(classification_obs, "_INSTALLED", False)

    classification_obs.install_page_classification_observability_compat()
    result = preprocess._classify_source_pages(SimpleNamespace())

    assert result is decisions
    config = next(fields for event, fields in diagnostics if event == "PDF_PAGE_CLASSIFICATION_CONFIG")
    assert config["enabled"] is True
    assert config["provider"] == "openai"
    assert config["model_id"] == "test-model"
    assert "not-logged-secret" not in repr(config)

    summary = next(fields for event, fields in diagnostics if event == "PDF_PAGE_CLASSIFICATION_SUMMARY")
    assert summary["document_page_count"] == 4
    assert summary["candidate_count"] == 3
    assert summary["classifier_success_count"] == 2
    assert summary["classifier_fallback_count"] == 1
    assert summary["cache_hit_count"] == 1
    assert summary["presentation_page_count"] == 1
    assert summary["native_text_page_count"] == 1
    assert summary["provider_page_count"] == 2
    assert summary["excluded_from_provider_count"] == 2
    assert summary["fallback_to_ocr_count"] == 1

    page_two = next(
        fields
        for event, fields in diagnostics
        if event == "PDF_PAGE_CLASSIFICATION_DECISION"
        and fields["page_number"] == 2
    )
    assert page_two["provider"] == "none"
    assert page_two["skip_ocr"] is False
    assert page_two["reason_codes"] == "classification_failed:ReadTimeout"


def test_provider_shards_execute_with_bounded_five_way_concurrency(monkeypatch) -> None:
    plans = tuple(
        ProviderInputShardPlan(index, index, index, 1, 1024)
        for index in range(6)
    )
    active = 0
    observed = 0
    lock = asyncio.Lock()

    monkeypatch.setattr(sharding, "plan_provider_input_shards", lambda *a, **k: plans)
    monkeypatch.setattr(
        sharding,
        "materialize_provider_input_shard",
        lambda storage, provider_input, plan, **kwargs: SimpleNamespace(
            provider_byte_size=1024,
            provider_page_count=1,
            provider_storage_reference=None,
            provider_checksum_sha256="a" * 64,
            provider_filename=f"shard-{plan.shard_index}.pdf",
            media_type="application/pdf",
            preprocessing=None,
        ),
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
    monkeypatch.setattr(sharding, "get_transport_grant_service", lambda: SimpleNamespace())

    raw_results = [SimpleNamespace(name=f"raw-{index}") for index in range(6)]

    class FakeService:
        def __init__(self, **kwargs):
            pass

        async def process(self, request):
            nonlocal active, observed
            shard_index = int(request.provider_job_id.rsplit("s", 1)[1]) - 1
            async with lock:
                active += 1
                observed = max(observed, active)
            await asyncio.sleep(0.02)
            async with lock:
                active -= 1
            return SimpleNamespace(
                revocation_succeeded=True,
                grant_final_state=None,
                integration_terminal_phase=SimpleNamespace(value="raw_result_retained"),
                provider_terminal_status=SimpleNamespace(value="completed"),
                error=None,
                poll_count=2,
                raw_result=raw_results[shard_index],
            )

    monkeypatch.setattr(sharding, "EndToEndProcessingIntegrationService", FakeService)

    merged = SimpleNamespace(
        ingestion=SimpleNamespace(payload_size_bytes=1234, page_summary=None)
    )

    def fake_merge(storage, provider_input, evidence, **kwargs):
        assert [item.plan.shard_index for item in evidence] == list(range(6))
        return merged

    monkeypatch.setattr(sharding, "merge_provider_shard_results", fake_merge)
    canonical = SimpleNamespace(candidate_id="candidate")
    canonicalizer = SimpleNamespace(canonicalize=lambda envelope: canonical)
    diagnostics: list[tuple[str, dict[str, object]]] = []

    result = asyncio.run(
        sharding.run_provider_transport_shards(
            storage=SimpleNamespace(delete=lambda reference: None),
            client=SimpleNamespace(),
            provider_input=SimpleNamespace(
                provider_byte_size=30 * _MIB,
                provider_page_count=6,
            ),
            descriptor=SimpleNamespace(),
            processing_attempt_id="attempt",
            logical_provider_job_id="job",
            logical_provider_request_id="request",
            result_profile="full",
            provider_job_options={},
            public_origin=None,
            polling_policy=SimpleNamespace(),
            canonicalizer=canonicalizer,
            diagnostic=lambda event, **fields: diagnostics.append((event, fields)),
        )
    )

    assert observed == 5
    assert result.error is None
    assert result.canonicalization is canonical
    assert result.shard_count == 6
    batch = next(fields for event, fields in diagnostics if event == "PDF_PROVIDER_SHARD_BATCH_TERMINAL")
    assert batch["succeeded_shards"] == 6
    assert batch["failed_shards"] == 0
    assert batch["shard_max_concurrency"] == 5
