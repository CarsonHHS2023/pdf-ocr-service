from __future__ import annotations

from dataclasses import replace
import hashlib

import fitz
import pytest

from app.processing.ingestion import ingest_inline_result
from app.processing.pdf_canonicalization import _decode_json_payload, _matching_document
from app.processing.pdf_page_presentation_lifecycle_compat import (
    DeferredPresentationProviderInput,
)
from app.processing.pdf_provider_sharding import (
    PROVIDER_TRANSPORT_SHARD_MAX_BYTES,
    PROVIDER_TRANSPORT_SHARD_TARGET_BYTES,
    ProviderInputShardPlan,
    ProviderShardEvidence,
    ProviderTransportShardError,
    materialize_provider_input_shard,
    merge_provider_shard_results,
    plan_provider_input_shards,
)
from app.processing.raw_result import (
    RawResultIdentity,
    RawResultProviderProvenance,
    RawResultSourceProvenance,
)
from app.storage.models import PutResult, StorageReference


SOURCE_SHA = "a" * 64


class _MemoryStorage:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put(
        self,
        data,
        reference=None,
        *,
        expected_size=None,
        expected_sha256=None,
    ):
        checksum = hashlib.sha256(data).hexdigest()
        if reference is None:
            reference = StorageReference.parse(f"src_{checksum[:32]}")
        elif not isinstance(reference, StorageReference):
            reference = StorageReference.parse(reference)
        assert expected_size in (None, len(data))
        assert expected_sha256 in (None, checksum)
        self.objects[str(reference)] = data
        return PutResult(reference, len(data), checksum)

    def get(self, reference):
        return self.objects[str(reference)]

    def delete(self, reference):
        self.objects.pop(str(reference), None)


def _pdf(page_count: int) -> bytes:
    document = fitz.open()
    try:
        for index in range(page_count):
            page = document.new_page(width=612, height=792)
            page.insert_text(
                (72, 96),
                f"provider transport shard test page {index + 1} " + ("x" * 1500),
                fontsize=10,
            )
        return document.tobytes(garbage=4, deflate=True)
    finally:
        document.close()


def _provider_input(
    provider_pdf: bytes,
    *,
    original_page_numbers: tuple[int, ...] | None = None,
    total_original_pages: int | None = None,
) -> DeferredPresentationProviderInput:
    provider_document = fitz.open(stream=provider_pdf, filetype="pdf")
    try:
        provider_page_count = provider_document.page_count
    finally:
        provider_document.close()
    original_page_numbers = original_page_numbers or tuple(
        range(1, provider_page_count + 1)
    )
    assert len(original_page_numbers) == provider_page_count
    total_original_pages = total_original_pages or max(original_page_numbers)

    provider_checksum = hashlib.sha256(provider_pdf).hexdigest()
    render = _pdf(total_original_pages)
    render_checksum = hashlib.sha256(render).hexdigest()
    render_reference = StorageReference.parse(f"src_{render_checksum[:32]}")
    provider_reference = StorageReference.parse(f"src_{provider_checksum[:32]}")
    provider_map = tuple(
        {
            "provider_page_index": provider_index,
            "original_page_index": original_page_number - 1,
            "original_page_number": original_page_number,
            "source_unit_id": f"pdf-page:{original_page_number:06d}",
        }
        for provider_index, original_page_number in enumerate(original_page_numbers)
    )
    ordinary_numbers = set(original_page_numbers)
    pages = []
    for page_number in range(1, total_original_pages + 1):
        if page_number in ordinary_numbers:
            pages.append(
                {
                    "page_number": page_number,
                    "source_unit_id": f"pdf-page:{page_number:06d}",
                    "ocr_route": "modal_paddle_ocr",
                    "page_width_points": 612.0,
                    "page_height_points": 792.0,
                }
            )
        else:
            pages.append(
                {
                    "page_number": page_number,
                    "source_unit_id": f"pdf-page:{page_number:06d}",
                    "ocr_route": "skipped_presentation_image",
                    "page_kind": "full_page_figure",
                    "page_width_points": 612.0,
                    "page_height_points": 792.0,
                    "page_classification": {
                        "page_role": "full_page_figure",
                        "confidence": 0.99,
                        "provider": "test",
                        "skip_ocr": True,
                    },
                }
            )

    return DeferredPresentationProviderInput(
        processing_attempt_id="attempt-sharding",
        storage_reference=render_reference,
        checksum_sha256=render_checksum,
        byte_size=len(render),
        media_type="application/pdf",
        filename="book.presentation-render.pdf",
        preprocessing=None,
        provider_storage_reference=provider_reference,
        provider_checksum_sha256=provider_checksum,
        provider_byte_size=len(provider_pdf),
        provider_filename="book.ordinary-pages.pdf",
        provider_page_count=provider_page_count,
        provider_page_map=provider_map,
        presentation_manifest={
            "page_count": total_original_pages,
            "provider_page_count": provider_page_count,
            "presentation_page_count": total_original_pages - provider_page_count,
            "pages": pages,
            "provider_page_map": list(provider_map),
        },
        provider_pdf_bytes=provider_pdf,
    )


def _local_raw_pages(count: int) -> list[dict[str, object]]:
    return [
        {
            "page_number": page_number,
            "page_index": page_number - 1,
            "local_page_index": 0,
            "source_page_range": {
                "page_start": page_number,
                "page_end": page_number,
            },
            "width": 612,
            "height": 792,
            "parsing_res_list": [],
            "metadata": {},
        }
        for page_number in range(1, count + 1)
    ]


def _evidence(
    storage: _MemoryStorage,
    plan: ProviderInputShardPlan,
    *,
    job_id: str,
    build_tag: str = "test-build",
) -> ProviderShardEvidence:
    request_id = f"{job_id}-request"
    envelope = ingest_inline_result(
        storage=storage,
        identity=RawResultIdentity(
            "attempt-sharding",
            request_id,
            "document-sharding",
            "source-sharding",
            "paddle-vl",
            job_id,
            request_id,
            "full",
            "completed",
        ),
        source=RawResultSourceProvenance(
            SOURCE_SHA,
            source_media_type="application/pdf",
        ),
        provider=RawResultProviderProvenance(
            build_tag=build_tag,
            configuration={"profile": "full"},
        ),
        inline_result=[
            {
                "document_id": "document-sharding",
                "raw_result": _local_raw_pages(plan.provider_page_count),
            }
        ],
    )
    return ProviderShardEvidence(plan, job_id, request_id, envelope)


def test_transport_shard_limits_stay_below_existing_100_mib_grant_limit() -> None:
    grant_limit = 100 * 1024 * 1024
    assert PROVIDER_TRANSPORT_SHARD_TARGET_BYTES == 80 * 1024 * 1024
    assert PROVIDER_TRANSPORT_SHARD_MAX_BYTES == 95 * 1024 * 1024
    assert PROVIDER_TRANSPORT_SHARD_TARGET_BYTES < PROVIDER_TRANSPORT_SHARD_MAX_BYTES
    assert PROVIDER_TRANSPORT_SHARD_MAX_BYTES < grant_limit


def test_plan_provider_input_shards_uses_contiguous_page_boundaries_and_byte_budget() -> None:
    storage = _MemoryStorage()
    provider_pdf = _pdf(8)
    provider_input = _provider_input(provider_pdf)
    target = max(1, len(provider_pdf) // 3)
    maximum = len(provider_pdf)

    plans = plan_provider_input_shards(
        storage,
        provider_input,
        target_bytes=target,
        max_bytes=maximum,
    )

    assert len(plans) >= 2
    assert plans[0].provider_page_start == 0
    assert plans[-1].provider_page_end == 7
    assert sum(plan.provider_page_count for plan in plans) == 8
    for index, plan in enumerate(plans):
        assert plan.shard_index == index
        assert plan.serialized_size_bytes <= maximum
        if index:
            assert plan.provider_page_start == plans[index - 1].provider_page_end + 1


def test_materialized_shard_localizes_map_and_rechecks_actual_serialized_bytes() -> None:
    storage = _MemoryStorage()
    provider_pdf = _pdf(4)
    provider_input = _provider_input(
        provider_pdf,
        original_page_numbers=(1, 3, 4, 6),
        total_original_pages=6,
    )
    plan = ProviderInputShardPlan(
        shard_index=1,
        provider_page_start=2,
        provider_page_end=3,
        provider_page_count=2,
        # Deliberately use planning evidence from a separate serialization. Its
        # exact bytes/length are not required to match materialization.
        serialized_size_bytes=1,
    )

    shard = materialize_provider_input_shard(
        storage,
        provider_input,
        plan,
        shard_count=2,
        max_bytes=len(provider_pdf) * 2,
    )

    assert [item["provider_page_index"] for item in shard.provider_page_map] == [0, 1]
    assert [item["original_page_number"] for item in shard.provider_page_map] == [1, 2]
    assert [item["source_unit_id"] for item in shard.provider_page_map] == [
        "pdf-page:000004",
        "pdf-page:000006",
    ]
    assert [item["original_page_number"] for item in provider_input.provider_page_map] == [
        1,
        3,
        4,
        6,
    ]
    assert shard.presentation_manifest["presentation_page_count"] == 0
    assert [item["page_number"] for item in shard.presentation_manifest["pages"]] == [1, 2]
    assert isinstance(shard.provider_pdf_bytes, bytes)
    assert shard.provider_byte_size == len(shard.provider_pdf_bytes)
    assert shard.provider_checksum_sha256 == hashlib.sha256(
        shard.provider_pdf_bytes
    ).hexdigest()
    shard_document = fitz.open(stream=shard.provider_pdf_bytes, filetype="pdf")
    try:
        assert shard_document.page_count == 2
    finally:
        shard_document.close()


def test_materialized_single_shard_is_valid_for_compacted_oversized_input() -> None:
    storage = _MemoryStorage()
    provider_pdf = _pdf(3)
    provider_input = _provider_input(provider_pdf)
    plan = ProviderInputShardPlan(
        shard_index=0,
        provider_page_start=0,
        provider_page_end=2,
        provider_page_count=3,
        serialized_size_bytes=len(provider_pdf),
    )

    shard = materialize_provider_input_shard(
        storage,
        provider_input,
        plan,
        shard_count=1,
        max_bytes=len(provider_pdf) * 2,
    )

    assert shard.provider_page_count == 3
    assert len(shard.provider_page_map) == 3
    assert shard.presentation_manifest["provider_transport_shard"]["shard_count"] == 1
    assert shard.provider_filename.endswith(".transport-001-of-001.pdf")
    shard_document = fitz.open(stream=shard.provider_pdf_bytes, filetype="pdf")
    try:
        assert shard_document.page_count == 3
    finally:
        shard_document.close()

    with pytest.raises(ProviderTransportShardError, match="index/count"):
        materialize_provider_input_shard(
            storage,
            provider_input,
            plan,
            shard_count=0,
            max_bytes=len(provider_pdf) * 2,
        )


def test_merge_provider_shards_restores_original_pages_and_presentation_pages() -> None:
    storage = _MemoryStorage()
    provider_input = _provider_input(
        _pdf(4),
        original_page_numbers=(1, 3, 4, 6),
        total_original_pages=6,
    )
    plans = (
        ProviderInputShardPlan(0, 0, 1, 2, 1000),
        ProviderInputShardPlan(1, 2, 3, 2, 1000),
    )
    evidence = (
        _evidence(storage, plans[0], job_id="job-s001"),
        _evidence(storage, plans[1], job_id="job-s002"),
    )

    merged = merge_provider_shard_results(
        storage,
        provider_input,
        evidence,
        logical_provider_job_id="job-logical",
        logical_provider_request_id="request-logical",
        target_bytes=80,
        max_bytes=95,
    )

    retained = storage.get(merged.ingestion.storage_reference)
    document = _matching_document(
        _decode_json_payload(merged, retained),
        "document-sharding",
    )
    pages = document["raw_result"]
    assert [page["page_number"] for page in pages] == [1, 2, 3, 4, 5, 6]
    assert [page["page_index"] for page in pages] == [0, 1, 2, 3, 4, 5]
    assert pages[1]["metadata"]["pre_ocr_page_classification"]["skip_ocr"] is True
    assert pages[4]["metadata"]["pre_ocr_page_classification"]["skip_ocr"] is True
    assert pages[0]["metadata"]["original_page_number"] == 1
    assert pages[2]["metadata"]["original_page_number"] == 3
    assert pages[3]["metadata"]["original_page_number"] == 4
    assert pages[5]["metadata"]["original_page_number"] == 6
    assert merged.provider.configuration["provider_transport_sharded"] is True
    assert merged.provider.configuration["provider_transport_shard_count"] == 2
    assert merged.ingestion.page_summary is not None
    assert merged.ingestion.page_summary.page_count_observed == 6
    assert merged.ingestion.page_summary.mapping_valid is True


def test_merge_provider_shards_fails_closed_when_provider_build_changes() -> None:
    storage = _MemoryStorage()
    provider_input = _provider_input(_pdf(2))
    plans = (
        ProviderInputShardPlan(0, 0, 0, 1, 1000),
        ProviderInputShardPlan(1, 1, 1, 1, 1000),
    )
    evidence = (
        _evidence(storage, plans[0], job_id="job-s001", build_tag="build-a"),
        _evidence(storage, plans[1], job_id="job-s002", build_tag="build-b"),
    )

    with pytest.raises(
        ProviderTransportShardError,
        match="build_tag changed",
    ):
        merge_provider_shard_results(
            storage,
            provider_input,
            evidence,
            logical_provider_job_id="job-logical",
            logical_provider_request_id="request-logical",
        )
