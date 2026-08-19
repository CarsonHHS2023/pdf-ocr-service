from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.processing.orchestration import ProviderJobRequest, ProviderSourceDocumentRequest
from app.processing.pdf_geometry_integration import (
    ProviderInputChecksumProvider,
    ProviderInputGrantService,
    provider_delivery_descriptor,
)
from app.storage.models import StorageReference


RENDER_SHA = "a" * 64
PROVIDER_SHA = "b" * 64


def _dual_field_input():
    return SimpleNamespace(
        storage_reference=StorageReference.parse("src_" + "1" * 32),
        checksum_sha256=RENDER_SHA,
        byte_size=9000,
        media_type="application/pdf",
        filename="book.presentation-render.pdf",
        provider_storage_reference=StorageReference.parse("src_" + "2" * 32),
        provider_checksum_sha256=PROVIDER_SHA,
        provider_byte_size=4000,
        provider_filename="book.ordinary-pages.pdf",
    )


class _GrantDelegate:
    def __init__(self) -> None:
        self.kwargs = None

    def create_grant(self, **kwargs):
        self.kwargs = dict(kwargs)
        return "grant-result"

    def inspect(self, grant_id):  # pragma: no cover - shape only
        return None

    def revoke(self, grant_id):  # pragma: no cover - shape only
        return None


class _ProviderDelegate:
    def __init__(self) -> None:
        self.request = None

    async def submit_job(self, request):
        self.request = request
        return "submission-result"


def test_delivery_descriptor_prefers_provider_subset_identity() -> None:
    provider_input = _dual_field_input()

    delivery = provider_delivery_descriptor(provider_input)

    assert delivery.storage_reference == provider_input.provider_storage_reference
    assert delivery.checksum_sha256 == PROVIDER_SHA
    assert delivery.byte_size == 4000
    assert delivery.media_type == "application/pdf"
    assert delivery.filename == "book.ordinary-pages.pdf"


def test_delivery_descriptor_preserves_legacy_single_pdf_identity() -> None:
    provider_input = SimpleNamespace(
        storage_reference=StorageReference.parse("src_" + "3" * 32),
        checksum_sha256=RENDER_SHA,
        byte_size=7000,
        media_type="application/pdf",
        filename="book.opencv.pdf",
    )

    delivery = provider_delivery_descriptor(provider_input)

    assert delivery.storage_reference == provider_input.storage_reference
    assert delivery.checksum_sha256 == RENDER_SHA
    assert delivery.byte_size == 7000
    assert delivery.filename == "book.opencv.pdf"


@pytest.mark.parametrize(
    "partial_fields",
    [
        {"provider_storage_reference": StorageReference.parse("src_" + "4" * 32)},
        {
            "provider_storage_reference": StorageReference.parse("src_" + "4" * 32),
            "provider_checksum_sha256": PROVIDER_SHA,
        },
        {
            "provider_storage_reference": StorageReference.parse("src_" + "4" * 32),
            "provider_checksum_sha256": PROVIDER_SHA,
            "provider_byte_size": 4000,
        },
    ],
)
def test_delivery_descriptor_rejects_partial_provider_subset_identity(partial_fields) -> None:
    provider_input = SimpleNamespace(
        storage_reference=StorageReference.parse("src_" + "3" * 32),
        checksum_sha256=RENDER_SHA,
        byte_size=7000,
        media_type="application/pdf",
        filename="book.opencv.pdf",
        **partial_fields,
    )

    with pytest.raises(ValueError, match="subset identity is incomplete"):
        provider_delivery_descriptor(provider_input)


def test_grant_and_modal_checksum_use_the_same_provider_subset_identity() -> None:
    provider_input = _dual_field_input()
    grant_delegate = _GrantDelegate()
    grant_service = ProviderInputGrantService(grant_delegate, provider_input)

    result = grant_service.create_grant(
        storage_reference=provider_input.storage_reference,
        source_sha256=provider_input.checksum_sha256,
        source_byte_size=provider_input.byte_size,
        media_type="application/pdf",
        filename=provider_input.filename,
    )

    assert result == "grant-result"
    assert grant_delegate.kwargs is not None
    assert grant_delegate.kwargs["storage_reference"] == provider_input.provider_storage_reference
    assert grant_delegate.kwargs["source_sha256"] == PROVIDER_SHA
    assert grant_delegate.kwargs["source_byte_size"] == 4000
    assert grant_delegate.kwargs["filename"] == "book.ordinary-pages.pdf"

    provider_delegate = _ProviderDelegate()
    provider = ProviderInputChecksumProvider(provider_delegate, provider_input)
    request = ProviderJobRequest(
        job_id="job-1",
        request_id="request-1",
        documents=[
            ProviderSourceDocumentRequest(
                document_id="doc-1",
                pdf_source_url="https://atlas.example/source",
                pdf_source_sha256=RENDER_SHA,
            )
        ],
        options={},
    )

    submission = asyncio.run(provider.submit_job(request))

    assert submission == "submission-result"
    assert provider_delegate.request is not None
    assert provider_delegate.request.documents[0].pdf_source_sha256 == PROVIDER_SHA
