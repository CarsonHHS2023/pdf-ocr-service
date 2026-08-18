from __future__ import annotations

import asyncio
import logging

import pytest

from app.processing import pdf_geometry_integration as integration
from app.processing import pdf_page_presentation_bridge as presentation
from app.processing.models import ProviderLifecycleStatus, ProviderResult
from app.storage.models import StorageReference


def _provider_input() -> presentation.PresentationProviderInput:
    pages = [
        {
            "page_number": 1,
            "source_unit_id": "pdf-page:000001",
            "page_kind": "cover",
            "ocr_route": "skipped_presentation_image",
            "page_width_points": 612.0,
            "page_height_points": 792.0,
            "page_classification": {
                "page_role": "cover",
                "confidence": 0.99,
                "provider": "openai",
            },
        },
        {
            "page_number": 2,
            "source_unit_id": "pdf-page:000002",
            "ocr_route": "modal_paddle_ocr",
            "page_width_points": 612.0,
            "page_height_points": 792.0,
            "page_classification": {
                "page_role": "body",
                "confidence": 0.99,
                "provider": "openai",
            },
        },
        {
            "page_number": 3,
            "source_unit_id": "pdf-page:000003",
            "page_kind": "back_cover",
            "ocr_route": "skipped_presentation_image",
            "page_width_points": 612.0,
            "page_height_points": 792.0,
            "page_classification": {
                "page_role": "back_cover",
                "confidence": 0.99,
                "provider": "openai",
            },
        },
    ]
    return presentation.PresentationProviderInput(
        processing_attempt_id="attempt-diagnostics",
        storage_reference=StorageReference.parse(
            "src_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        ),
        checksum_sha256="a" * 64,
        byte_size=300,
        media_type="application/pdf",
        filename="render.pdf",
        preprocessing=None,
        provider_storage_reference=StorageReference.parse(
            "src_bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        ),
        provider_checksum_sha256="b" * 64,
        provider_byte_size=100,
        provider_filename="ordinary.pdf",
        provider_page_count=1,
        provider_page_map=(
            {
                "provider_page_index": 0,
                "original_page_index": 1,
                "original_page_number": 2,
                "source_unit_id": "pdf-page:000002",
            },
        ),
        presentation_manifest={
            "page_count": 3,
            "provider_page_count": 1,
            "presentation_page_count": 2,
            "pages": pages,
        },
    )


def _provider_page() -> dict[str, object]:
    return {
        "page_number": 1,
        "page_index": 0,
        "local_page_index": 0,
        "source_page_range": {"page_start": 1, "page_end": 1},
        "width": 1000,
        "height": 1300,
        "blocks": [{"type": "paragraph", "text": "ordinary body"}],
    }


class _ResultDelegate:
    def __init__(self, raw_pages: list[dict[str, object]]) -> None:
        self.raw_pages = raw_pages

    async def get_job_result(self, job_id: str, profile: str | None = None):
        document = {
            "document_id": "document-1",
            "raw_result": list(self.raw_pages),
        }
        return ProviderResult(
            job_id=job_id,
            request_id="request-1",
            status=ProviderLifecycleStatus.PROVIDER_COMPLETED,
            profile=profile or "full",
            result_artifact=None,
            documents=[document],
            raw_provider_payload={
                "job_id": job_id,
                "request_id": "request-1",
                "status": "completed",
                "profile": profile or "full",
                "documents": [document],
            },
        )


def _diagnostic_provider(delegate: _ResultDelegate):
    presentation.install_pre_ocr_presentation_bridge()
    provider_class = integration.ProviderInputChecksumProvider
    return provider_class(delegate, _provider_input())


def test_inline_full_result_is_remapped_and_logs_bounded_counts(caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error")
    provider = _diagnostic_provider(_ResultDelegate([_provider_page()]))

    result = asyncio.run(provider.get_job_result("pdf-job-test", "full"))

    assert [
        page["page_number"]
        for page in result.documents[0]["raw_result"]
    ] == [1, 2, 3]
    assert [
        page["page_number"]
        for page in result.raw_provider_payload["documents"][0]["raw_result"]
    ] == [1, 2, 3]
    messages = [record.getMessage() for record in caplog.records]
    assert any(
        message.startswith("PDF_PROVIDER_RESULT_RECEIVED ")
        and "documents_count=1" in message
        and "provider_page_count=1" in message
        for message in messages
    )
    assert any(
        message.startswith("PDF_PROVIDER_RESULT_REMAP_COMPLETED ")
        and "original_page_count=3" in message
        for message in messages
    )


def test_remap_failure_logs_stage_and_exception_type(caplog):
    caplog.set_level(logging.INFO, logger="uvicorn.error")
    provider = _diagnostic_provider(_ResultDelegate([]))

    with pytest.raises(ValueError, match="does not cover every original page"):
        asyncio.run(provider.get_job_result("pdf-job-test", "full"))

    messages = [record.getMessage() for record in caplog.records]
    assert any(
        message.startswith("PDF_PROVIDER_RESULT_STAGE_FAILED ")
        and "stage=documents_remap" in message
        and "error_type=ValueError" in message
        and "provider_page_map_count=1" in message
        for message in messages
    )
