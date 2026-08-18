from __future__ import annotations

import hashlib

import pytest

from app.processing import pdf_geometry_integration as integration
from app.processing import pdf_page_presentation_bridge as presentation
from app.processing.pdf_page_presentation_lifecycle_compat import (
    DeferredPresentationProviderInput,
    _DeferredProviderStorage,
    _pre_reviewed_source_units_confident,
    _presentation_provenance_configuration,
    install_presentation_lifecycle_compat,
)
from app.storage.models import PutResult, StorageReference


class RecordingStorage:
    def __init__(self) -> None:
        self.puts = []
        self.deletes = []

    def put(
        self,
        content,
        reference,
        *,
        expected_size,
        expected_sha256,
    ):
        self.puts.append((content, reference, expected_size, expected_sha256))
        return PutResult(
            reference=reference,
            byte_size=len(content),
            checksum_sha256=hashlib.sha256(content).hexdigest(),
        )

    def delete(self, reference):
        self.deletes.append(reference)


class GrantDelegate:
    def __init__(self, *, fail_create: bool = False) -> None:
        self.fail_create = fail_create
        self.create_kwargs = None
        self.revoked = []

    def create_grant(self, **kwargs):
        self.create_kwargs = dict(kwargs)
        if self.fail_create:
            raise RuntimeError("grant creation failed")
        return "grant-1"

    def inspect(self, grant_id):
        return grant_id

    def revoke(self, grant_id):
        self.revoked.append(grant_id)
        return {"grant_id": grant_id, "state": "revoked"}


def _provider_input(subset: bytes) -> DeferredPresentationProviderInput:
    render = b"%PDF-render"
    render_checksum = hashlib.sha256(render).hexdigest()
    subset_checksum = hashlib.sha256(subset).hexdigest()
    return DeferredPresentationProviderInput(
        processing_attempt_id="attempt-lifecycle",
        storage_reference=presentation._render_reference(
            "attempt-lifecycle",
            render_checksum,
        ),
        checksum_sha256=render_checksum,
        byte_size=len(render),
        media_type="application/pdf",
        filename="render.pdf",
        preprocessing=None,
        provider_storage_reference=presentation._provider_reference(
            "attempt-lifecycle",
            subset_checksum,
        ),
        provider_checksum_sha256=subset_checksum,
        provider_byte_size=len(subset),
        provider_filename="ordinary.pdf",
        provider_page_count=1,
        provider_page_map=(),
        presentation_manifest={
            "page_count": 2,
            "provider_page_count": 1,
            "presentation_page_count": 1,
        },
        provider_pdf_bytes=subset,
    )


def _presentation_only_input() -> DeferredPresentationProviderInput:
    render = b"%PDF-presentation-only-render"
    render_checksum = hashlib.sha256(render).hexdigest()
    reference = presentation._render_reference(
        "attempt-presentation-only",
        render_checksum,
    )
    return DeferredPresentationProviderInput(
        processing_attempt_id="attempt-presentation-only",
        storage_reference=reference,
        checksum_sha256=render_checksum,
        byte_size=len(render),
        media_type="application/pdf",
        filename="presentation-only.render.pdf",
        preprocessing=None,
        provider_storage_reference=reference,
        provider_checksum_sha256=render_checksum,
        provider_byte_size=len(render),
        provider_filename="presentation-only.ordinary-pages.pdf",
        provider_page_count=0,
        provider_page_map=(),
        presentation_manifest={
            "page_count": 3,
            "provider_page_count": 0,
            "presentation_page_count": 3,
        },
        provider_pdf_bytes=None,
    )


def test_mixed_provider_subset_is_deferred_while_render_is_retained():
    storage = RecordingStorage()
    proxy = _DeferredProviderStorage(storage, "attempt-deferred")
    render = b"%PDF-render"
    subset = b"%PDF-subset"
    render_checksum = hashlib.sha256(render).hexdigest()
    subset_checksum = hashlib.sha256(subset).hexdigest()
    render_reference = presentation._render_reference(
        "attempt-deferred",
        render_checksum,
    )
    subset_reference = presentation._provider_reference(
        "attempt-deferred",
        subset_checksum,
    )

    render_put = proxy.put(
        render,
        render_reference,
        expected_size=len(render),
        expected_sha256=render_checksum,
    )
    subset_put = proxy.put(
        subset,
        subset_reference,
        expected_size=len(subset),
        expected_sha256=subset_checksum,
    )

    assert render_put.reference == render_reference
    assert subset_put.reference == subset_reference
    assert [item[1] for item in storage.puts] == [render_reference]
    assert proxy.provider_reference == subset_reference
    assert proxy.provider_pdf_bytes == subset


def test_mixed_provider_provenance_records_subset_and_render_separately():
    provider_input = _provider_input(b"%PDF-provenance-subset")
    original = {
        "source_checksum_sha256": "source-checksum",
        "provider_input_kind": "geometry_preprocessed_pdf",
        "provider_input_checksum_sha256": provider_input.checksum_sha256,
        "provider_input_size_bytes": provider_input.byte_size,
    }

    configuration = _presentation_provenance_configuration(
        original,
        provider_input,
    )

    assert configuration["source_checksum_sha256"] == "source-checksum"
    assert configuration["provider_input_kind"] == (
        "presentation_ordinary_page_subset_pdf"
    )
    assert configuration["provider_input_checksum_sha256"] == (
        provider_input.provider_checksum_sha256
    )
    assert configuration["provider_input_size_bytes"] == (
        provider_input.provider_byte_size
    )
    assert configuration["provider_input_filename"] == "ordinary.pdf"
    assert configuration["provider_input_page_count"] == 1
    assert configuration["provider_submission_status"] == "submitted"
    assert configuration["provider_submission_skip_reason"] is None
    assert configuration["presentation_render_kind"] == (
        "presentation_full_render_pdf"
    )
    assert configuration["presentation_render_checksum_sha256"] == (
        provider_input.checksum_sha256
    )
    assert configuration["presentation_render_size_bytes"] == (
        provider_input.byte_size
    )
    assert configuration["presentation_render_filename"] == "render.pdf"
    assert original["provider_input_checksum_sha256"] == (
        provider_input.checksum_sha256
    )


def test_presentation_only_provenance_records_provider_was_skipped():
    provider_input = _presentation_only_input()
    original = {
        "source_checksum_sha256": "source-checksum",
        "provider_input_kind": "geometry_preprocessed_pdf",
        "provider_input_checksum_sha256": provider_input.checksum_sha256,
        "provider_input_size_bytes": provider_input.byte_size,
        "provider_input_media_type": "application/pdf",
        "provider_input_filename": provider_input.filename,
    }

    configuration = _presentation_provenance_configuration(
        original,
        provider_input,
    )

    assert configuration["source_checksum_sha256"] == "source-checksum"
    assert configuration["provider_input_kind"] == (
        "provider_skipped_presentation_only"
    )
    assert configuration["provider_input_checksum_sha256"] is None
    assert configuration["provider_input_size_bytes"] == 0
    assert configuration["provider_input_media_type"] is None
    assert configuration["provider_input_filename"] is None
    assert configuration["provider_input_page_count"] == 0
    assert configuration["provider_submission_status"] == "skipped"
    assert configuration["provider_submission_skip_reason"] == (
        "all_pages_classified_as_presentation"
    )
    assert configuration["presentation_render_checksum_sha256"] == (
        provider_input.checksum_sha256
    )
    assert configuration["presentation_render_size_bytes"] == (
        provider_input.byte_size
    )
    assert configuration["presentation_render_filename"] == (
        provider_input.filename
    )
    assert original["provider_input_checksum_sha256"] == (
        provider_input.checksum_sha256
    )


def test_boundary_review_suppression_requires_usable_pre_ocr_decision(monkeypatch):
    monkeypatch.delenv("PDF_PAGE_CLASSIFICATION_MIN_CONFIDENCE", raising=False)
    manifest = {
        "pages": [
            {
                "source_unit_id": "pdf-page:000001",
                "ocr_route": "modal_paddle_ocr",
                "page_classification": {
                    "page_role": "unknown",
                    "confidence": 0.99,
                    "provider": "openai",
                },
            },
            {
                "source_unit_id": "pdf-page:000002",
                "ocr_route": "modal_paddle_ocr",
                "page_classification": {
                    "page_role": "cover",
                    "confidence": 0.89,
                    "provider": "openai",
                    "skip_ocr": False,
                },
            },
            {
                "source_unit_id": "pdf-page:000003",
                "ocr_route": "modal_paddle_ocr",
                "page_classification": {
                    "page_role": "title_page",
                    "confidence": 0.99,
                    "provider": "openai",
                    "skip_ocr": False,
                    "decision_reason": "local_continuous_prose_conflict",
                },
            },
            {
                "source_unit_id": "pdf-page:000004",
                "ocr_route": "modal_paddle_ocr",
                "page_classification": {
                    "page_role": "body",
                    "confidence": 0.95,
                    "provider": "openai",
                    "skip_ocr": False,
                },
            },
            {
                "source_unit_id": "pdf-page:000005",
                "ocr_route": "modal_paddle_ocr",
                "page_classification": {
                    "page_role": "body",
                    "confidence": 0.89,
                    "provider": "openai",
                    "skip_ocr": False,
                },
            },
            {
                "source_unit_id": "pdf-page:000006",
                "ocr_route": "skipped_presentation_image",
                "page_classification": {
                    "page_role": "back_cover",
                    "confidence": 0.96,
                    "provider": "openai",
                    "skip_ocr": True,
                },
            },
            {
                "source_unit_id": "pdf-page:000007",
                "ocr_route": "modal_paddle_ocr",
                "page_classification": {
                    "page_role": "body",
                    "confidence": 0.99,
                    "provider": "none",
                    "skip_ocr": False,
                },
            },
        ]
    }

    reviewed = _pre_reviewed_source_units_confident(manifest)

    assert reviewed == {
        "pdf-page:000004",
        "pdf-page:000006",
    }
    presentation.install_pre_ocr_presentation_bridge()
    install_presentation_lifecycle_compat()
    assert presentation._pre_reviewed_source_units(manifest) == reviewed


def test_grant_creation_retains_deferred_subset_and_revoke_deletes_it(monkeypatch):
    presentation.install_pre_ocr_presentation_bridge()
    install_presentation_lifecycle_compat()
    storage = RecordingStorage()
    monkeypatch.setattr(
        "app.storage.dependencies.get_storage_provider",
        lambda: storage,
    )
    provider_input = _provider_input(b"%PDF-mixed-subset")
    delegate = GrantDelegate()
    service = integration.ProviderInputGrantService(delegate, provider_input)

    grant_id = service.create_grant(document_id="document-1")

    assert grant_id == "grant-1"
    assert [item[1] for item in storage.puts] == [
        provider_input.provider_storage_reference
    ]
    assert delegate.create_kwargs["storage_reference"] == (
        provider_input.provider_storage_reference
    )
    service.revoke(grant_id)
    assert storage.deletes == [provider_input.provider_storage_reference]


def test_grant_creation_failure_deletes_newly_retained_subset(monkeypatch):
    presentation.install_pre_ocr_presentation_bridge()
    install_presentation_lifecycle_compat()
    storage = RecordingStorage()
    monkeypatch.setattr(
        "app.storage.dependencies.get_storage_provider",
        lambda: storage,
    )
    provider_input = _provider_input(b"%PDF-failing-subset")
    service = integration.ProviderInputGrantService(
        GrantDelegate(fail_create=True),
        provider_input,
    )

    with pytest.raises(RuntimeError, match="grant creation failed"):
        service.create_grant(document_id="document-2")

    assert [item[1] for item in storage.puts] == [
        provider_input.provider_storage_reference
    ]
    assert storage.deletes == [provider_input.provider_storage_reference]
